"""
K线形态识别器 - Phase 2 模块4
对应书本第3章§3.2

功能：识别6种关键K线形态，输出形态+置信度+方向
集成：在 SignalGenerator 生成信号前验证当前K线形态，调整信号置信度
"""
from typing import List, Optional
import pandas as pd
import numpy as np


class KLinePattern:
    """K线形态数据类"""

    def __init__(self, name: str, strength: float, direction: str, detail: str = ""):
        self.name = name          # 形态名称
        self.strength = strength  # 置信度 0~1
        self.direction = direction  # 'bullish' / 'bearish' / 'neutral'
        self.detail = detail      # 额外描述

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'strength': self.strength,
            'direction': self.direction,
            'detail': self.detail
        }


class KLinePatternVerifier:
    """
    K线形态识别器
    识别6种形态并返回置信度调整建议
    """

    # 形态→置信度映射表（2B.2）
    PATTERN_CONFIDENCE_MAP = {
        'big_yang': {'buy_boost': 0.15, 'sell_boost': 0.0},
        'doji': {'buy_boost': 0.0, 'sell_boost': 0.0},
        'gap_up': {'buy_boost': 0.10, 'sell_boost': 0.0},
        'gap_down': {'buy_boost': 0.0, 'sell_boost': 0.10},
        '冲高回落': {'buy_boost': 0.0, 'sell_boost': 0.15},
        '高开低走大阴线': {'buy_boost': 0.0, 'sell_boost': 0.20},
    }

    def verify(self, df: pd.DataFrame) -> List[KLinePattern]:
        """
        识别所有形态

        Args:
            df: K线数据（至少包含 open/high/low/close 列）

        Returns:
            识别的形态列表
        """
        patterns = []

        if df.empty or len(df) < 2:
            return patterns

        # 大阳线: 实体 > 振幅×0.7 AND 涨幅 > 3%
        if self._is_big_yang(df):
            patterns.append(KLinePattern(
                'big_yang', 0.7, 'bullish',
                self._calc_detail(df, '大阳线')
            ))

        # 十字星: 实体 < 振幅×0.1
        if self._is_doji(df):
            patterns.append(KLinePattern(
                'doji', 0.5, 'neutral',
                self._calc_detail(df, '十字星')
            ))

        # 跳空高开: open > prev_high × 1.005
        if self._is_gap_up(df):
            patterns.append(KLinePattern(
                'gap_up', 0.6, 'bullish',
                self._calc_detail(df, '跳空高开')
            ))

        # 跳空低开: open < prev_low × 0.995
        if self._is_gap_down(df):
            patterns.append(KLinePattern(
                'gap_down', 0.6, 'bearish',
                self._calc_detail(df, '跳空低开')
            ))

        # 冲高回落: high > close × 1.05 AND 实体 < 振幅×0.3
        if self._is_high_wave(df):
            patterns.append(KLinePattern(
                '冲高回落', 0.65, 'bearish',
                self._calc_detail(df, '冲高回落')
            ))

        # 高开低走大阴线: open > prev_close AND close < open AND 实体 > 振幅×0.5
        if self._is_big_bear_high_open(df):
            patterns.append(KLinePattern(
                '高开低走大阴线', 0.7, 'bearish',
                self._calc_detail(df, '高开低走大阴线')
            ))

        return patterns

    def get_confidence_adjustment(self, patterns: List[KLinePattern],
                                  signal_direction: str) -> dict:
        """
        根据识别到的形态计算置信度调整

        Args:
            patterns: 已识别的形态列表
            signal_direction: 信号方向 ('BUY'/'SELL')

        Returns:
            {'confidence_boost': float, 'has_bearish_pattern': bool, 'detail': str}
        """
        boost = 0.0
        has_bearish = False
        details = []

        for p in patterns:
            mapping = self.PATTERN_CONFIDENCE_MAP.get(p.name, {})
            if signal_direction == 'BUY':
                b = mapping.get('buy_boost', 0.0)
                if b > 0:
                    boost += b
                    details.append(f"形态{p.name}: +{b:.0%}置信度")
            elif signal_direction == 'SELL':
                b = mapping.get('sell_boost', 0.0)
                if b > 0:
                    boost += b
                    details.append(f"形态{p.name}: +{b:.0%}置信度")

            if p.direction == 'bearish':
                has_bearish = True

        return {
            'confidence_boost': round(boost, 2),
            'has_bearish_pattern': has_bearish,
            'detail': '; '.join(details) if details else '无显著形态'
        }

    # ────────────── 各形态检测方法 ──────────────

    def _is_big_yang(self, df: pd.DataFrame) -> bool:
        """大阳线: 实体 > 振幅×0.7 AND 涨幅 > 3%"""
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amplitude = latest['high'] - latest['low']
        pct_change = (latest['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']
        return amplitude > 0 and body > amplitude * 0.7 and pct_change > 0.03

    def _is_doji(self, df: pd.DataFrame) -> bool:
        """十字星: 实体 < 振幅×0.1"""
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amplitude = latest['high'] - latest['low']
        return amplitude > 0 and body < amplitude * 0.1

    def _is_gap_up(self, df: pd.DataFrame) -> bool:
        """跳空高开: open > prev_high × 1.005"""
        if len(df) < 2:
            return False
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        return latest['open'] > prev['high'] * 1.005

    def _is_gap_down(self, df: pd.DataFrame) -> bool:
        """跳空低开: open < prev_low × 0.995"""
        if len(df) < 2:
            return False
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        return latest['open'] < prev['low'] * 0.995

    def _is_high_wave(self, df: pd.DataFrame) -> bool:
        """冲高回落: high > close × 1.05 AND 实体 < 振幅×0.3"""
        latest = df.iloc[-1]
        body = abs(latest['close'] - latest['open'])
        amplitude = latest['high'] - latest['low']
        has_high_wave = latest['high'] > latest['close'] * 1.05
        return has_high_wave and amplitude > 0 and body < amplitude * 0.3

    def _is_big_bear_high_open(self, df: pd.DataFrame) -> bool:
        """
        高开低走大阴线:
        open > prev_close AND close < open AND 实体 > 振幅×0.5
        """
        if len(df) < 2:
            return False
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(latest['close'] - latest['open'])
        amplitude = latest['high'] - latest['low']
        high_open = latest['open'] > prev['close']
        bearish = latest['close'] < latest['open']
        return high_open and bearish and amplitude > 0 and body > amplitude * 0.5

    def _calc_detail(self, df: pd.DataFrame, name: str) -> str:
        """计算形态的数值详情"""
        latest = df.iloc[-1]
        if name == '大阳线':
            pct = (latest['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']
            return f"涨幅+{pct*100:.1f}%"
        elif name == '十字星':
            body = abs(latest['close'] - latest['open'])
            amplitude = latest['high'] - latest['low']
            return f"实体/振幅={body/amplitude:.2f}" if amplitude > 0 else ""
        elif name in ('跳空高开',):
            gap = (latest['open'] - df.iloc[-2]['high']) / df.iloc[-2]['high']
            return f"缺口+{gap*100:.2f}%"
        elif name in ('跳空低开',):
            gap = (df.iloc[-2]['low'] - latest['open']) / df.iloc[-2]['low']
            return f"缺口-{gap*100:.2f}%"
        elif name == '冲高回落':
            peak = (latest['high'] - latest['close']) / latest['close']
            return f"上影线{peak*100:.1f}%"
        elif name == '高开低走大阴线':
            body = abs(latest['close'] - latest['open'])
            amplitude = latest['high'] - latest['low']
            body_pct = body / amplitude if amplitude > 0 else 0
            return f"实体/振幅={body_pct:.2f}"
        return ""
