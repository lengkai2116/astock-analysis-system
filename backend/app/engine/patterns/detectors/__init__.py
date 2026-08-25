"""
形态检测器模块
包含预涨型、预跌型、黑马型、四类八种状态检测器
"""
from .base import PatternDetector
from .bullish_patterns import BullishPatternDetector
from .bearish_patterns import BearishPatternDetector
from .blackhorse_patterns import BlackHorsePatternDetector

__all__ = [
    'PatternDetector',
    'BullishPatternDetector',
    'BearishPatternDetector',
    'BlackHorsePatternDetector',
]
