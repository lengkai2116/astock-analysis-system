"""
统一策略核心层（UnifiedStrategyCore）
287号方案 · v2.3

作为所有策略计算的唯一入口，"一次计算，两路输出"：
- 选股 L3 适配器：提取 raw_score → z-score 归一化 → 加权评分
- 个股策略分析适配器：提取 status_desc → 五维格式组装
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class StrategySignal:
    """单个策略的标准化输出"""
    strategy_name: str = ''
    raw_score: float = 0.0
    direction: str = 'neutral'
    confidence: float = 0.0
    signal: str = 'NEUTRAL'
    signal_label: str = ''
    evidence: list = field(default_factory=list)
    status_recognition: dict = field(default_factory=dict)
    raw_detail: dict = field(default_factory=dict)


@dataclass
class StandardizedResult:
    """统一策略计算结果"""
    ts_code: str = ''
    trade_date: str = ''
    period: str = 'long'
    signals: dict[str, StrategySignal] = field(default_factory=dict)
    market_context: dict = field(default_factory=dict)
    data_availability: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'StandardizedResult':
        signals = {}
        for k, v in d.get('signals', {}).items():
            signals[k] = StrategySignal(**v)
        d['signals'] = signals
        return cls(**d)


# ──────────────────────────────────────────────
# signal_name → 内部 key 映射
# ──────────────────────────────────────────────
SIGNAL_NAME_MAP: dict[str, str] = {
    '缠论': 'chanlun',
    '量价': 'volume_price',
    '筹码': 'chip',
    'BOCIASI': 'bociasi',
    '因子': 'factor',
    'Vibe': 'vibe',
}

KEY_TO_STRATEGY_NAME: dict[str, str] = {v: k for k, v in SIGNAL_NAME_MAP.items()}


class UnifiedStrategyCore:
    """统一策略核心——所有策略计算的唯一入口"""

    def compute(self, ts_code: str, period: str = 'long') -> StandardizedResult:
        """单只股票策略计算"""
        from app.services.signal_computation_service import SignalComputationService
        scs = SignalComputationService()
        signals = scs.compute_for_stock(ts_code, period=period)
        return self._to_standardized(ts_code, signals, period, scs)

    def compute_batch(
        self,
        ts_codes: list[str],
        period: str = 'long',
        max_workers: int = 4,
    ) -> dict[str, StandardizedResult]:
        """批量策略计算（供 daemon 预计算使用）"""
        results: dict[str, StandardizedResult] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
            fut_map = {
                exe.submit(self._safe_compute, code, period): code
                for code in ts_codes
            }
            for fut in concurrent.futures.as_completed(fut_map):
                code = fut_map[fut]
                try:
                    res = fut.result()
                    if res is not None:
                        results[code] = res
                except Exception:
                    continue
        return results

    def _safe_compute(self, ts_code: str, period: str) -> Optional[StandardizedResult]:
        """单股安全计算，异常不影响整体 batch"""
        try:
            return self.compute(ts_code, period=period)
        except Exception:
            return None

    def _to_standardized(
        self,
        ts_code: str,
        signals: list,
        period: str,
        scs: object = None,
    ) -> StandardizedResult:
        """将 SignalComputationService 的 List[Dict] 输出转为 StandardizedResult"""
        today = datetime.now().strftime('%Y%m%d')
        result_signals: dict[str, StrategySignal] = {}

        for sig in signals:
            name = sig.get('strategy_name', '')
            key = SIGNAL_NAME_MAP.get(name, name)
            status = sig.get('status_recognition') or {}

            confidence = sig.get('confidence', 0)
            if not isinstance(confidence, (int, float)):
                confidence = 0.0

            direction = sig.get('signal', 'neutral') or 'neutral'
            raw_level = sig.get('signal_level') or sig.get('signal') or 'NEUTRAL'
            signal_level = raw_level if raw_level else 'NEUTRAL'

            # raw_detail 中排除已提取的顶层字段
            skip_keys = {'strategy_name', 'confidence', 'signal', 'signal_level',
                         'evidence', 'status_recognition', 'signal_label', 'signal_date'}
            raw_detail = {k: v for k, v in sig.items() if k not in skip_keys}

            result_signals[key] = StrategySignal(
                strategy_name=name,
                raw_score=confidence,
                direction=direction,
                confidence=confidence,
                signal=signal_level,
                signal_label=sig.get('signal_label', ''),
                evidence=sig.get('evidence', []),
                status_recognition=status,
                raw_detail=raw_detail,
            )

        da = getattr(scs, 'last_data_availability', {}) if scs else {}

        return StandardizedResult(
            ts_code=ts_code,
            trade_date=today,
            period=period,
            signals=result_signals,
            data_availability=da,
        )
