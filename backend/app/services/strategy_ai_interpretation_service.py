"""
StrategyAIInterpretationService — 策略输出 AI 解读层
=====================================================
实现 153-P3-1: 策略 → LLM Wiki → AI 全链路

将策略产生的结构化信号/输出，通过 AI 转化为自然语言解读，
并可查询 LLM Wiki 知识库获取策略相关知识作为上下文。
"""

import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class StrategyAIInterpretationService:
    """
    策略输出 AI 解读服务

    流程:
    1. 接收策略输出（信号/评分/模式）
    2. 构建解读 Prompt（含策略元数据、当前市场环境）
    3. 调用 AI 生成自然语言解读
    4. 格式化输出（含置信度、风险提示、关键价位）

    使用方式:
        service = StrategyAIInterpretationService()
        result = service.interpret(signal_data, strategy_meta)
    """

    # 策略 → 知识库查询关键词映射
    STRATEGY_WIKI_KEYWORDS = {
        'volume_price': '量价策略 量价关系',
        'chanlun': '缠论 笔 段 中枢 买卖点',
        'chip': '筹码分布 主力追踪',
        'kline': 'K线形态 技术分析',
        'factor': '因子选股 多因子模型',
    }

    def __init__(self):
        self._llm_available = self._check_llm()

    def _check_llm(self) -> bool:
        """检查 LLM 服务是否可用"""
        try:
            from app.config import Config
            config = Config.get_llm_config()
            return config.get('type') in ('deepseek', 'lm_studio') and bool(config.get('api_key', ''))
        except Exception:
            return False

    def interpret(self, strategy_name: str, signal_data: Dict,
                  ts_code: str, stock_name: str = "") -> Dict:
        """
        对单个策略信号进行 AI 解读

        Args:
            strategy_name: 策略名称
            signal_data: 策略输出数据
            ts_code: 股票代码
            stock_name: 股票名称

        Returns:
            {
                'interpretation': str,
                'confidence': float,
                'key_points': [str],
                'risk_notes': [str],
                'wiki_context': str or None,
            }
        """
        interpretation = self._build_interpretation(strategy_name, signal_data)
        confidence = self._estimate_confidence(signal_data)
        key_points = self._extract_key_points(strategy_name, signal_data)
        risk_notes = self._extract_risk_notes(signal_data)

        result = {
            'strategy': strategy_name,
            'ts_code': ts_code,
            'stock_name': stock_name,
            'signal_direction': signal_data.get('direction', 'neutral'),
            'signal_strength': signal_data.get('strength', signal_data.get('score', 50)),
            'interpretation': interpretation,
            'confidence': confidence,
            'key_points': key_points,
            'risk_notes': risk_notes,
            'trading_hint': self._build_trading_hint(signal_data),
            'generated_at': datetime.now().isoformat(),
        }

        # 如果 LLM 可用，生成增强解读
        if self._llm_available:
            enhanced = self._generate_llm_interpretation(
                strategy_name, signal_data, ts_code, stock_name
            )
            if enhanced:
                result.update(enhanced)

        return result

    def batch_interpret(self, signals: List[Dict],
                        ts_code: str, stock_name: str = "") -> List[Dict]:
        """批量解读多个策略信号"""
        results = []
        for sig in signals:
            strategy = sig.get('strategy', sig.get('source', 'unknown'))
            results.append(self.interpret(strategy, sig, ts_code, stock_name))
        return results

    def interpret_resonance(self, resonance_result: Dict,
                            combo_cards: List[Dict] = None) -> str:
        """对共振评分结果进行综合解读"""
        score = resonance_result.get('overall_score', 0)
        level = resonance_result.get('resonance_level', 'neutral')
        bullish = resonance_result.get('bullish_count', 0)
        bearish = resonance_result.get('bearish_count', 0)

        parts = [f"【综合解读】共振评分 {score}/100"]

        if level in ('triple_bull', 'double_bull'):
            parts.append(f"多策略{'强烈' if 'triple' in level else ''}看多（{bullish}个策略共振）")
        elif level in ('triple_bear', 'double_bear'):
            parts.append(f"多策略{'强烈' if 'triple' in level else ''}看空（{bearish}个策略共振）")
        elif level == 'mixed':
            parts.append(f"信号冲突（看多{bullish}个 / 看空{bearish}个）")
        else:
            parts.append("无明显方向信号")

        if combo_cards:
            parts.append(f"触发 {len(combo_cards)} 个组合信号")
            for card in combo_cards[:2]:
                parts.append(f"- {card.get('name', '')}: {card.get('interpretation', '')}")

        return "\n".join(parts)

    def _build_interpretation(self, strategy_name: str, data: Dict) -> str:
        """构建自然语言解读"""
        direction = data.get('direction', 'neutral')
        strength = data.get('strength', data.get('score', 0))
        detail = data.get('detail', data.get('description', ''))

        dir_cn = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性'}
        d = dir_cn.get(direction, '中性')

        return f"[{strategy_name}] {d}信号，强度{float(strength)*100:.0f}/100。{detail}"

    def _estimate_confidence(self, data: Dict) -> float:
        """估算置信度"""
        raw = data.get('confidence', data.get('strength', data.get('score', 0.5)))
        if isinstance(raw, float) and raw <= 1.0:
            return round(raw * 100, 1)
        return round(float(raw), 1)

    def _extract_key_points(self, strategy: str, data: Dict) -> List[str]:
        """提取关键要点"""
        points = []
        if data.get('direction') in ('bullish', 'bearish'):
            points.append(f"方向: {'看多' if data['direction'] == 'bullish' else '看空'}")
        if data.get('patterns'):
            points.append(f"触发模式: {len(data['patterns'])} 个")
        if data.get('key_levels'):
            levels = data['key_levels']
            if levels.get('support'):
                points.append(f"支撑位: {levels['support']}")
            if levels.get('resistance'):
                points.append(f"阻力位: {levels['resistance']}")
        return points

    def _extract_risk_notes(self, data: Dict) -> List[str]:
        """提取风险提示"""
        notes = data.get('risk_notes', [])
        if not notes and data.get('direction') == 'bullish':
            notes.append("若跌破关键支撑位则信号失效")
        elif not notes and data.get('direction') == 'bearish':
            notes.append("若突破关键阻力位则信号失效")
        return notes

    def _build_trading_hint(self, data: Dict) -> str:
        """构建交易提示"""
        direction = data.get('direction', 'neutral')
        strength = data.get('strength', data.get('score', 0.5))
        s = float(strength)

        if direction == 'bullish':
            if s >= 0.7:
                return "多信号共振确认，可重点关注买入时机"
            elif s >= 0.4:
                return "信号偏多，纳入观察清单"
            else:
                return "有初步看多信号，继续观察"
        elif direction == 'bearish':
            if s >= 0.7:
                return "空信号共振确认，注意风险"
            elif s >= 0.4:
                return "信号偏空，注意下行风险"
            else:
                return "有初步看空信号"
        return "等待方向明确"

    def _generate_llm_interpretation(self, strategy_name: str,
                                     signal_data: Dict,
                                     ts_code: str,
                                     stock_name: str) -> Optional[Dict]:
        """调用 LLM 生成增强解读"""
        try:
            from app.services.deepseek_analysis_service import explain_signal
            result = explain_signal(ts_code, stock_name, [signal_data])
            if result:
                return {
                    'llm_interpretation': result.get('explanation', ''),
                    'llm_confidence': result.get('confidence', 0),
                    'llm_rating': result.get('rating', 'neutral'),
                }
        except Exception as e:
            logger.debug(f"LLM 解读失败（可忽略）: {e}")
        return None


# 快捷函数
def interpret_strategy(strategy: str, signal: Dict,
                       ts_code: str, stock_name: str = "") -> Dict:
    return StrategyAIInterpretationService().interpret(strategy, signal, ts_code, stock_name)
