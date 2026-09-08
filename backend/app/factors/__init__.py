"""
因子库模块
支持: GTJA191, Qlib158, Alpha101, 学术因子
"""
from .base import BaseFactor
from .calculator import FactorCalculator
from .registry import FactorRegistry, get_factor_registry

__all__ = [
    'BaseFactor',
    'FactorRegistry',
    'get_factor_registry',
    'FactorCalculator'
]
