"""
K线形态适配器 — KLinePatternVerifier → PatternResult
====================================================
将现有 kline_pattern.py 的 6 种检测结果扩展为 12 种命名模式，
输出统一 PatternResult 结构。

对应方案152 §Phase 1: 迁移 K 线形态（6种→12种）
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from app.engine.patterns import (
    PatternResult, PatternCategory, PatternStage, PatternLevel
)
from app.engine.patterns.registry import PatternRegistry


class KLinePatternAdapter:
    """
    K 线形态检测适配器
    封装 KLinePatternVerifier 的检测逻辑，输出统一 PatternResult。

    新增形态（相较于原版 6 种）:
      big_bear, hammer, hanging_man, engulfing_bullish,
      engulfing_bearish, shooting_star
    """

    def __init__(self):
        self.registry = PatternRegistry()

    def detect(self, df: pd.DataFrame) -> List[PatternResult]:
        """检测所有匹配的 K 线形态，返回 PatternResult 列表"""
        if df.empty or len(df) < 3:
            return []

        results = []

        # ── 原有 6 种 + 扩展 ──

        # 1. 大阳线
        p = self._big_yang(df)
        if p: results.append(p)

        # 2. 大阴线（新增）
        p = self._big_bear(df)
        if p: results.append(p)

        # 3. 十字星
        p = self._doji(df)
        if p: results.append(p)

        # 4. 锤子线（新增）
        p = self._hammer(df)
        if p: results.append(p)

        # 5. 吊颈线（新增）
        p = self._hanging_man(df)
        if p: results.append(p)

        # 6. 看涨吞没（新增）
        p = self._engulfing_bullish(df)
        if p: results.append(p)

        # 7. 看跌吞没（新增）
        p = self._engulfing_bearish(df)
        if p: results.append(p)

        # 8. 射击之星（新增）
        p = self._shooting_star(df)
        if p: results.append(p)

        # 9. 跳空高开 (gap_up)
        p = self._gap_up(df)
        if p: results.append(p)

        # 10. 跳空低开 (gap_down)
        p = self._gap_down(df)
        if p: results.append(p)

        # 11. 冲高回落
        p = self._high_wave(df)
        if p: results.append(p)

        # 12. 高开低走大阴线
        p = self._big_bear_high_open(df)
        if p: results.append(p)

        # 三只乌鸦（新增）
        p = self._three_crows(df)
        if p: results.append(p)

        # 纺锤线（新增）
        p = self._spinning_top(df)
        if p: results.append(p)

        # 看涨孕线（新增）
        p = self._harami_bullish(df)
        if p: results.append(p)

        # 看跌孕线（新增）
        p = self._harami_bearish(df)
        if p: results.append(p)

        return results

    def _make_result(self, name: str, direction: str, strength: float,
                     conditions: List[str], detail: dict) -> Optional[PatternResult]:
        """从检测结果构建 PatternResult"""
        meta = self.registry.get(name)
        if meta is None:
            return None

        return PatternResult(
            name=name,
            category=PatternCategory.CANDLESTICK,
            direction=direction,
            strength=strength,
            stage=PatternStage.COMPLETED,
            completion=100.0,
            conditions=conditions,
            interpretation=meta.description,
            detail=detail,
            source="kline_pattern.py",
        )

    # ── 各形态检测方法 ──

    def _big_yang(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """大阳线: 实体>振幅0.7 且 涨幅>3%"""
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp <= 0:
            return None
        pct = (latest['close'] - prev['close']) / prev['close']
        if body > amp * 0.7 and pct > 0.03:
            return self._make_result('big_yang', 'bullish', 0.7, [
                f"实体/振幅={body/amp:.2f}", f"涨幅+{pct*100:.1f}%"
            ], {'body_ratio': round(body/amp, 2), 'pct_change': round(pct*100, 1)})
        return None

    def _big_bear(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """大阴线: 实体>振幅0.7 且 跌幅>3%"""
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp <= 0:
            return None
        pct = (latest['close'] - prev['close']) / prev['close']
        bearish = latest['close'] < latest['open']
        if bearish and body > amp * 0.7 and pct < -0.03:
            return self._make_result('big_bear', 'bearish', 0.65, [
                f"实体/振幅={body/amp:.2f}", f"跌幅{pct*100:.1f}%"
            ], {'body_ratio': round(body/amp, 2), 'pct_change': round(pct*100, 1)})
        return None

    def _doji(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """十字星: 实体<振幅0.1"""
        if df.empty:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp > 0 and body < amp * 0.1:
            return self._make_result('doji', 'neutral', 0.5, [
                f"实体/振幅={body/amp:.2f}"
            ], {'body_ratio': round(body/amp, 2)})
        return None

    def _hammer(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """锤子线: 下影线>实体2倍 且 上影线短 且 在低位"""
        if df.empty:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        upper_shadow = latest['high'] - max(latest['close'], latest['open'])
        lower_shadow = min(latest['close'], latest['open']) - latest['low']
        if lower_shadow > body * 2 and upper_shadow < body * 0.5:
            return self._make_result('hammer', 'bullish', 0.6, [
                f"下影线/实体={lower_shadow/body:.1f}"
            ], {'lower_ratio': round(lower_shadow/body, 1),
                'upper_ratio': round(upper_shadow/body, 2) if body > 0 else 0})
        return None

    def _hanging_man(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """吊颈线: 下影线>实体2倍 且 上影线短 且 在高位"""
        if len(df) < 10:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        upper_shadow = latest['high'] - max(latest['close'], latest['open'])
        lower_shadow = min(latest['close'], latest['open']) - latest['low']
        recent_high = df['high'].iloc[-10:].max()
        at_high = latest['high'] >= recent_high * 0.98
        if lower_shadow > body * 2 and upper_shadow < body * 0.5 and at_high:
            return self._make_result('hanging_man', 'bearish', 0.6, [
                f"下影线/实体={lower_shadow/body:.1f}", "高位信号"
            ], {'lower_ratio': round(lower_shadow/body, 1),
                'at_high': True})
        return None

    def _engulfing_bullish(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """看涨吞没: 阳线实体完全覆盖前日阴线实体"""
        if len(df) < 2:
            return None
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        cur_bull = cur['close'] > cur['open']
        prev_bear = prev['close'] < prev['open']
        cur_body = cur['close'] - cur['open']
        prev_body = prev['open'] - prev['close']
        if cur_bull and prev_bear and cur_body > prev_body:
            return self._make_result('engulfing_bullish', 'bullish', 0.7, [
                f"覆盖比={cur_body/prev_body:.1f}"
            ], {'cover_ratio': round(cur_body/prev_body, 1)})
        return None

    def _engulfing_bearish(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """看跌吞没: 阴线实体完全覆盖前日阳线实体"""
        if len(df) < 2:
            return None
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        cur_bear = cur['close'] < cur['open']
        prev_bull = prev['close'] > prev['open']
        cur_body = cur['open'] - cur['close']
        prev_body = prev['close'] - prev['open']
        if cur_bear and prev_bull and cur_body > prev_body:
            return self._make_result('engulfing_bearish', 'bearish', 0.7, [
                f"覆盖比={cur_body/prev_body:.1f}"
            ], {'cover_ratio': round(cur_body/prev_body, 1)})
        return None

    def _shooting_star(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """射击之星: 上影线>实体2倍 且 下影线短 且 在高位"""
        if len(df) < 10:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        upper_shadow = latest['high'] - max(latest['close'], latest['open'])
        lower_shadow = min(latest['close'], latest['open']) - latest['low']
        recent_high = df['high'].iloc[-10:].max()
        at_high = latest['high'] >= recent_high * 0.98
        if upper_shadow > body * 2 and lower_shadow < body * 0.5 and at_high:
            return self._make_result('shooting_star', 'bearish', 0.65, [
                f"上影线/实体={upper_shadow/body:.1f}", "高位信号"
            ], {'upper_ratio': round(upper_shadow/body, 1), 'at_high': True})
        return None

    def _gap_up(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """跳空高开"""
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        if latest['open'] > prev['high'] * 1.005:
            gap = (latest['open'] - prev['high']) / prev['high']
            return self._make_result('big_yang', 'bullish', 0.6, [
                f"缺口+{gap*100:.2f}%"
            ], {'gap_pct': round(gap*100, 2)})
        return None

    def _gap_down(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """跳空低开"""
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        if latest['open'] < prev['low'] * 0.995:
            gap = (prev['low'] - latest['open']) / prev['low']
            return self._make_result('gap_down', 'bearish', 0.6, [
                f"缺口-{gap*100:.2f}%"
            ], {'gap_pct': round(gap*100, 2)})
        return None

    def _high_wave(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """冲高回落"""
        if df.empty:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp <= 0:
            return None
        has_high_wave = latest['high'] > latest['close'] * 1.05
        if has_high_wave and body < amp * 0.3:
            peak = (latest['high'] - latest['close']) / latest['close']
            return self._make_result('shooting_star', 'bearish', 0.65, [
                f"上影线{peak*100:.1f}%"
            ], {'peak_pct': round(peak*100, 1)})
        return None

    def _big_bear_high_open(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """高开低走大阴线"""
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp <= 0:
            return None
        high_open = latest['open'] > prev['close']
        bearish = latest['close'] < latest['open']
        if high_open and bearish and body > amp * 0.5:
            return self._make_result('big_bear', 'bearish', 0.7, [
                f"实体/振幅={body/amp:.2f}", "高开低走"
            ], {'body_ratio': round(body/amp, 2), 'high_open': True})
        return None

    def _three_crows(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """三只乌鸦: 连续3根阴线且每日创新低"""
        if len(df) < 4:
            return None
        for i in range(-3, 0):
            candle = df.iloc[i]
            if candle['close'] >= candle['open']:
                return None
            if i > -3 and candle['close'] >= df.iloc[i-1]['close']:
                return None
        return self._make_result('three_crows', 'bearish', 0.65, [
            "连续3日阴线创新低"
        ], {'days': 3})

    def _spinning_top(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """纺锤线: 实体小、上下影线长"""
        if df.empty:
            return None
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amp = latest['high'] - latest['low']
        if amp <= 0:
            return None
        upper = latest['high'] - max(latest['close'], latest['open'])
        lower = min(latest['close'], latest['open']) - latest['low']
        if body < amp * 0.3 and upper > body and lower > body:
            return self._make_result('spinning_top', 'neutral', 0.4, [
                f"实体/振幅={body/amp:.2f}"
            ], {'body_ratio': round(body/amp, 2)})
        return None

    def _harami_bullish(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """看涨孕线: 小阳线在前日大阴线实体内"""
        if len(df) < 2:
            return None
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        prev_bear = prev['close'] < prev['open']
        cur_bull = cur['close'] > cur['open']
        if prev_bear and cur_bull:
            prev_body_start = min(prev['open'], prev['close'])
            prev_body_end = max(prev['open'], prev['close'])
            if cur['open'] > prev_body_start and cur['close'] < prev_body_end:
                return self._make_result('harami_bullish', 'bullish', 0.55, [
                    f"孕线在前日阴线实体内"
                ], {'harami': True})
        return None

    def _harami_bearish(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """看跌孕线: 小阴线在前日大阳线实体内"""
        if len(df) < 2:
            return None
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        prev_bull = prev['close'] > prev['open']
        cur_bear = cur['close'] < cur['open']
        if prev_bull and cur_bear:
            prev_body_start = min(prev['open'], prev['close'])
            prev_body_end = max(prev['open'], prev['close'])
            if cur['open'] < prev_body_end and cur['close'] > prev_body_start:
                return self._make_result('harami_bearish', 'bearish', 0.55, [
                    f"孕线在前日阳线实体内"
                ], {'harami': True})
        return None
