"""
PatternEngine — 形态评分引擎主入口
==================================
统一调度 50 种形态 + 8 种状态检测器，实现 Wiki 10 分制聚合算法。
"""
from typing import List, Tuple, Dict, Optional
import pandas as pd

from app.engine.patterns import PatternResult
from app.engine.patterns.registry import PatternRegistry
from app.engine.patterns.detectors import (
    BullishPatternDetector,
    BearishPatternDetector,
    BlackHorsePatternDetector,
    StateDetector,
)


# 形态权重映射（基于 Wiki 星级）
WEIGHT_MAP = {
    # 预涨型 ⭐⭐⭐
    'P-1-1': 3.0, 'P-1-2': 3.0, 'P-1-3': 2.0, 'P-1-4': 3.0,
    'P-1-5': 3.0, 'P-1-6': 3.0, 'P-1-7': 3.0, 'P-1-8': 2.0,
    'P-1-9': 2.0, 'P-1-10': 3.0, 'P-1-11': 3.0, 'P-1-12': 2.0,
    'P-1-13': 2.0, 'P-1-14': 2.0, 'P-1-15': 3.0, 'P-1-16': 2.0,
    'P-1-17': 3.0, 'P-1-18': 3.0, 'P-1-19': 2.0, 'P-1-20': 3.0,

    # 预跌型 ⭐⭐⭐
    'P-2-1': 3.0, 'P-2-2': 3.0, 'P-2-3': 2.0, 'P-2-4': 3.0,
    'P-2-5': 3.0, 'P-2-6': 3.0, 'P-2-7': 2.0, 'P-2-8': 3.0,
    'P-2-9': 3.0, 'P-2-10': 2.0, 'P-2-11': 3.0, 'P-2-12': 3.0,
    'P-2-13': 2.0, 'P-2-14': 3.0, 'P-2-15': 2.0, 'P-2-16': 3.0,
    'P-2-17': 3.0, 'P-2-18': 2.0, 'P-2-19': 3.0, 'P-2-20': 3.0,

    # 黑马型 ⭐⭐⭐⭐⭐
    'P-3-1': 5.0, 'P-3-2': 4.0, 'P-3-3': 5.0, 'P-3-4': 4.0,
    'P-3-5': 5.0, 'P-3-6': 4.0, 'P-3-7': 4.0, 'P-3-8': 5.0,
    'P-3-9': 4.0, 'P-3-10': 4.0,

    # 四类八种状态
    'S-1': 2.0, 'S-2': 2.0, 'S-3': 2.5, 'S-4': 2.5,
    'S-5': 3.0, 'S-6': 3.0, 'S-7': 2.0, 'S-8': 2.0,
}


class PatternEngine:
    """
    形态评分引擎

    实现 Wiki 10 分制评分：
    - 基础分 5 分
    - 预涨形态：+权重×strength
    - 预跌形态：-权重×strength
    - 黑马形态：+权重×strength×1.5（高权重）
    - 多形态共振：≥3 个同向形态，额外 ±1 分
    """

    def __init__(self):
        self.registry = PatternRegistry()
        self.bullish_detector = BullishPatternDetector()
        self.bearish_detector = BearishPatternDetector()
        self.blackhorse_detector = BlackHorsePatternDetector()
        self.state_detector = StateDetector()

    def detect_all(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有形态和状态"""
        results = []
        results.extend(self.bullish_detector.detect(df, context))
        results.extend(self.bearish_detector.detect(df, context))
        results.extend(self.blackhorse_detector.detect(df, context))
        results.extend(self.state_detector.detect(df, context))
        return results

    def aggregate(self, patterns: List[PatternResult]) -> Tuple[float, Dict]:
        """聚合形态为 0-10 分"""
        score = 5.0
        bull_count = 0
        bear_count = 0
        bull_strength_sum = 0.0
        bear_strength_sum = 0.0

        for p in patterns:
            weight = WEIGHT_MAP.get(p.name, 1.0)

            if p.direction == 'bullish':
                # 黑马型额外加权 1.5 倍
                if p.name.startswith('P-3-'):
                    score += p.strength * weight * 1.5
                else:
                    score += p.strength * weight
                bull_count += 1
                bull_strength_sum += p.strength
            elif p.direction == 'bearish':
                score -= p.strength * weight
                bear_count += 1
                bear_strength_sum += p.strength

        # 多形态共振加分
        if bull_count >= 3:
            score += 1.0
        if bear_count >= 3:
            score -= 1.0

        final_score = max(0.0, min(10.0, score))

        details = {
            'bull_count': bull_count,
            'bear_count': bear_count,
            'bull_strength_avg': bull_strength_sum / max(bull_count, 1),
            'bear_strength_avg': bear_strength_sum / max(bear_count, 1),
            'pattern_count': len(patterns),
            'patterns': [{'name': p.name, 'direction': p.direction, 'strength': p.strength} for p in patterns],
        }

        return final_score, details

    def evaluate(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Tuple[float, Dict]:
        """一站式评估：检测 + 聚合"""
        patterns = self.detect_all(df, context)
        return self.aggregate(patterns)
