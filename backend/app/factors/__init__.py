"""
因子库模块
支持: GTJA191, Qlib158, Alpha101, 学术因子
"""
from .base import BaseFactor
from .registry import FactorRegistry, get_factor_registry
from .calculator import FactorCalculator

__all__ = [
    'BaseFactor',
    'FactorRegistry',
    'get_factor_registry',
    'FactorCalculator'
]
