"""
因子评估模块
借鉴Qlib和Vibe-Trading的因子分析理念
核心指标：IC、IR、换手率
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional


class FactorEvaluator:
    """
    因子评估器
    用于科学评估因子质量
    """
    
    def __init__(self):
        pass
    
    def calculate_ic(self, factor_values: pd.Series, 
                    forward_returns: pd.Series) -> float:
        """
        计算IC (Information Coefficient)
        因子与未来收益的相关性
        IC范围：-1到1，越接近1或-1表示相关性越强
        """
        aligned = pd.concat([factor_values, forward_returns], 
                           axis=1, join='inner').dropna()
        if len(aligned) < 10:
            return 0.0
        
        corr = aligned.corr()
        if isinstance(corr, pd.DataFrame):
            return float(corr.iloc[0, 1])
        return float(corr)
    
    def calculate_ir(self, ic_series: pd.Series) -> float:
        """
        计算IR (Information Ratio)
        IC均值 / IC标准差
        IR越高表示因子越稳定
        """
        if len(ic_series) < 2:
            return 0.0
        std = ic_series.std()
        if std < 1e-10:
            return 0.0
        return float(ic_series.mean() / std)
    
    def calculate_turnover(self, factor_data: pd.DataFrame) -> pd.Series:
        """
        计算因子换手率
        衡量因子权重变化的频率
        """
        if factor_data.empty or len(factor_data.columns) < 2:
            return pd.Series()
        
        factor_ranks = factor_data.rank(axis=1, pct=True)
        rank_changes = factor_ranks.diff().abs()
        turnover = rank_changes.mean(axis=1)
        
        return turnover
    
    def evaluate_factor(self, factor_data: pd.DataFrame,
                       price_data: pd.DataFrame,
                       periods: List[int] = [1, 5, 10]) -> Dict:
        """
        全面评估因子
        返回多个周期的IC、IR等指标
        """
        results = {}
        
        for period in periods:
            forward_returns = price_data['close'].pct_change(period).shift(-period)
            
            ic_values = []
            
            if len(factor_data.columns) > 0:
                factor_series = factor_data.iloc[:, 0]
                
                window_size = min(60, len(factor_series) - period)
                if window_size > 10:
                    for i in range(len(factor_series) - window_size):
                        window_factor = factor_series.iloc[i:i+window_size]
                        window_returns = forward_returns.iloc[i:i+window_size]
                        ic = self.calculate_ic(window_factor, window_returns)
                        ic_values.append(ic)
            
            ic_series = pd.Series(ic_values)
            
            results[f'period_{period}'] = {
                'ic_mean': float(ic_series.mean()) if len(ic_series) > 0 else 0.0,
                'ic_std': float(ic_series.std()) if len(ic_series) > 1 else 0.0,
                'ic_ir': float(self.calculate_ir(ic_series)),
                'ic_positive_rate': float((ic_series > 0).mean()) if len(ic_series) > 0 else 0.0,
                'ic_count': len(ic_series)
            }
        
        return results
    
    def evaluate_multiple_factors(self, factors_data: pd.DataFrame,
                                price_data: pd.DataFrame,
                                periods: List[int] = [1, 5, 10]) -> Dict:
        """
        评估多个因子
        返回每个因子的评估结果
        """
        results = {}
        
        for factor_name in factors_data.columns:
            factor_series = factors_data[factor_name]
            results[factor_name] = self.evaluate_factor(
                pd.DataFrame({factor_name: factor_series}),
                price_data,
                periods
            )
        
        return results


__all__ = ['FactorEvaluator']
