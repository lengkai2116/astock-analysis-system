"""
观潮对标 Phase 0 — 统一模式分类体系
====================================
核心数据模型：PatternResult / PatternCategory / PatternStage / PatternLevel

参考观潮 109 种命名模式的统一接口契约，将分散在各策略中的模式检测
映射为可查询、可组合、可追踪的统一 PatternResult。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict


class PatternCategory(Enum):
    """模式分类（参考观潮 PatternRouter）"""
    REVERSAL = 'reversal'
    CONTINUATION = 'continuation'
    BREAKOUT = 'breakout'
    CANDLESTICK = 'candlestick'
    GAP = 'gap'
    DIVERGENCE = 'divergence'
    COMBO = 'combo'
    TREND = 'trend'
    VOLUME = 'volume'
    CHANLUN = 'chanlun'
    VOLUME_PRICE = 'volume_price'


class PatternStage(Enum):
    """模式生命周期阶段（参考观潮 evolving 机制）"""
    FORMING = 'forming'
    CONFIRMING = 'confirming'
    COMPLETED = 'completed'
    INVALIDATED = 'invalidated'


@dataclass
class PatternLevel:
    """价格层级"""
    support: Optional[float] = None
    resistance: Optional[float] = None
    target: Optional[float] = None
    invalidation: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            'support': self.support,
            'resistance': self.resistance,
            'target': self.target,
            'invalidation': self.invalidation,
        }


@dataclass
class PatternResult:
    """
    统一模式检测结果 — 每个模式返回此结构
    对应观潮 109 种模式的统一接口契约
    """
    name: str
    category: PatternCategory
    direction: str
    strength: float
    stage: PatternStage
    completion: float
    eta: Optional[int] = None
    conditions: List[str] = field(default_factory=list)
    levels: PatternLevel = field(default_factory=PatternLevel)
    invalidation: List[str] = field(default_factory=list)
    interpretation: str = ""
    detail: Dict = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'category': self.category.value,
            'direction': self.direction,
            'strength': self.strength,
            'stage': self.stage.value,
            'completion': self.completion,
            'eta': self.eta,
            'conditions': self.conditions,
            'levels': self.levels.to_dict(),
            'invalidation': self.invalidation,
            'interpretation': self.interpretation,
            'detail': self.detail,
            'source': self.source,
        }
