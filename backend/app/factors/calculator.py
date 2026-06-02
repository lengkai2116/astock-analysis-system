"""
因子计算器
用于批量计算因子
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from .base import BaseFactor
from .registry import get_factor_registry



import logging
logger = logging.getLogger(__name__)
class FactorCalculator:
    """
    因子计算器
    """
    
    def __init__(self):
        self.registry = get_factor_registry()
    
    def calculate_single_factor(self, data: pd.DataFrame, 
                                factor_name: str, 
                                **kwargs) -> Optional[pd.Series]:
        """
        计算单个因子
        """
        factor = self.registry.get_factor(factor_name, **kwargs)
        if factor is None:
            logger.error(f"未找到因子: {factor_name}")
            return None
        
        if not factor.check_data(data):
            logger.error(f"数据不满足因子 {factor_name} 的要求")
            return None
        
        try:
            result = factor.calculate(data)
            return result
        except Exception as e:
            logger.error(f"计算因子 {factor_name} 失败: {e}")
            return None
    
    def calculate_multiple_factors(self, data: pd.DataFrame,
                                   factor_configs: List[Dict]) -> pd.DataFrame:
        """
        批量计算多个因子
        factor_configs 格式: [{"name": "MA", "params": {"period": 20}}]
        """
        result_df = pd.DataFrame(index=data.index)
        
        for config in factor_configs:
            factor_name = config.get("name")
            params = config.get("params", {})
            
            factor_series = self.calculate_single_factor(data, factor_name, **params)
            if factor_series is not None:
                result_df[factor_name] = factor_series
        
        return result_df
    
    def calculate_factor_combination(self, data: pd.DataFrame,
                                     factor_configs: List[Dict]) -> pd.Series:
        """
        计算因子加权组合
        factor_configs 格式: [{"name": "MA", "params": {}, "weight": 0.3}]
        """
        factors_df = self.calculate_multiple_factors(data, factor_configs)
        
        if factors_df.empty:
            return pd.Series([], index=data.index)
        
        # 计算权重和
        total_weight = sum(c.get("weight", 1.0) for c in factor_configs)
        
        # 加权平均
        result = pd.Series(0.0, index=data.index)
        for config in factor_configs:
            name = config.get("name")
            weight = config.get("weight", 1.0)
            if name in factors_df.columns:
                result += factors_df[name] * (weight / total_weight)
        
        return result
