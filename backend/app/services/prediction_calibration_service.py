"""
PredictionCalibrationService — AI 预测校准系统
===============================================
实现 153-P1-2: AiPrediction 模型 + CalibrationService + 定时回填

核心流程:
1. 策略信号 → AiPrediction 记录（包含预测方向/置信度/目标价）
2. 实际走势结束后（T+5/T+10/T+20），回填实际结果
3. 校准服务定期评估预测准确率，调整置信度偏移
"""

import logging
import json
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ── 内存存储（后续可迁移到 DB） ──
_prediction_store: Dict[str, Dict] = {}
_calibration_store: Dict[str, List] = {}


@dataclass
class AiPrediction:
    """AI 预测记录"""
    id: str
    ts_code: str
    stock_name: str = ""
    created_at: str = ""           # 预测时间
    direction: str = "neutral"     # bullish / bearish / neutral
    confidence_raw: float = 0.0    # 原始置信度 0~100
    confidence_calibrated: float = 0.0  # 校准后置信度
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    prediction_date: str = ""      # 预测日期
    actual_return: Optional[float] = None   # T+N 实际收益率
    actual_direction: Optional[str] = None  # 实际方向
    verified: bool = False         # 是否已验证
    verify_period: int = 5         # T+N 验证周期
    source: str = ""               # 预测来源 (deepseek/strategy/combined)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items()}

    def to_short_dict(self) -> Dict:
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'direction': self.direction,
            'confidence_calibrated': self.confidence_calibrated,
            'prediction_date': self.prediction_date,
            'actual_return': self.actual_return,
            'verified': self.verified,
        }

    def is_ready_for_verification(self, current_date: date) -> bool:
        """判断是否到达验证时间"""
        try:
            pred_date = datetime.strptime(self.prediction_date[:10], '%Y-%m-%d').date()
            return (current_date - pred_date).days >= self.verify_period and not self.verified
        except Exception:
            return False


class CalibrationService:
    """
    校准服务

    功能:
    - 置信度校准: 根据历史准确率调整未来预测的置信度
    - 偏差检测: 识别 AI 是否系统性偏多或偏空
    - 分组统计: 按方向/策略源/时间区间统计准确率
    """

    def __init__(self):
        self._predictions: Dict[str, AiPrediction] = {}
        self._load_state()

    def _load_state(self):
        """从内存存储加载状态"""
        for pid, data in _prediction_store.items():
            self._predictions[pid] = AiPrediction(**data)

    def register_prediction(self, pred: AiPrediction) -> str:
        """注册新预测"""
        self._predictions[pred.id] = pred
        _prediction_store[pred.id] = pred.to_dict()
        return pred.id

    def verify_prediction(self, prediction_id: str, actual_return: float) -> Optional[AiPrediction]:
        """回填验证结果"""
        pred = self._predictions.get(prediction_id)
        if not pred:
            return None
        pred.actual_return = actual_return
        pred.actual_direction = 'bullish' if actual_return > 0 else 'bearish'
        pred.verified = True
        _prediction_store[prediction_id] = pred.to_dict()
        return pred

    def get_calibration_stats(self, source: Optional[str] = None) -> Dict:
        """获取校准统计"""
        verified = [p for p in self._predictions.values()
                    if p.verified and (source is None or p.source == source)]
        total = len(verified)
        if total == 0:
            return {'total': 0, 'accuracy': 0, 'calibration_bias': 0}

        correct = sum(1 for p in verified if p.direction == p.actual_direction)
        bull_correct = sum(1 for p in verified
                          if p.direction == 'bullish' and p.actual_direction == 'bullish')
        bull_total = sum(1 for p in verified if p.direction == 'bullish')
        bear_correct = sum(1 for p in verified
                          if p.direction == 'bearish' and p.actual_direction == 'bearish')
        bear_total = sum(1 for p in verified if p.direction == 'bearish')

        return {
            'total': total,
            'accuracy': round(correct / max(total, 1) * 100, 1),
            'bullish_accuracy': round(bull_correct / max(bull_total, 1) * 100, 1),
            'bearish_accuracy': round(bear_correct / max(bear_total, 1) * 100, 1),
            'calibration_bias': round(
                (bull_correct / max(bull_total, 1)) - (bear_correct / max(bear_total, 1)), 3
            ) if bull_total > 0 and bear_total > 0 else 0,
        }

    def calibrate_confidence(self, raw_confidence: float, source: str = 'deepseek',
                              direction: str = 'neutral') -> float:
        """
        根据历史校准数据调整置信度

        Args:
            raw_confidence: 原始置信度 0~100
            source: 预测来源
            direction: 预测方向

        Returns:
            校准后置信度 0~100
        """
        stats = self.get_calibration_stats(source)
        if stats['total'] < 10:
            return raw_confidence  # 样本不足，不校准

        accuracy = stats['accuracy'] / 100.0
        bias = stats['calibration_bias']

        # 方向偏差修正
        if direction == 'bullish':
            adjusted = raw_confidence * (1 + (accuracy - 0.5) * 0.5 + bias * 0.3)
        elif direction == 'bearish':
            adjusted = raw_confidence * (1 + (accuracy - 0.5) * 0.5 - bias * 0.3)
        else:
            adjusted = raw_confidence * (1 + (accuracy - 0.5) * 0.3)

        return max(5, min(100, round(adjusted, 1)))

    def batch_verify_due(self, current_date: date, price_provider=None) -> List[Dict]:
        """
        批量验证到期预测

        Returns:
            [{'prediction_id': str, 'ts_code': str, 'result': str}, ...]
        """
        results = []
        for pred in list(self._predictions.values()):
            if pred.is_ready_for_verification(current_date):
                if price_provider:
                    actual = self._fetch_actual_return(pred, price_provider)
                    if actual is not None:
                        self.verify_prediction(pred.id, actual)
                        results.append({
                            'prediction_id': pred.id,
                            'ts_code': pred.ts_code,
                            'result': 'verified',
                            'actual_return': actual,
                        })
        return results

    def _fetch_actual_return(self, pred: AiPrediction, price_provider) -> Optional[float]:
        """获取实际收益率"""
        try:
            from datetime import timedelta
            pred_date = datetime.strptime(pred.prediction_date[:10], '%Y-%m-%d').date()
            end_date = pred_date + timedelta(days=pred.verify_period)
            data = price_provider.get_daily_data(
                pred.ts_code,
                start_date=pred_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            if data and len(data) >= 2:
                start_price = data[0].get('close', 0)
                end_price = data[-1].get('close', 0)
                if start_price > 0:
                    return round((end_price - start_price) / start_price * 100, 2)
        except Exception as e:
            logger.warning(f"获取验证数据失败: {e}")
        return None


# 全局实例
_calibration_service = CalibrationService()


def get_calibration_service() -> CalibrationService:
    return _calibration_service
