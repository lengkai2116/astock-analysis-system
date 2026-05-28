"""
框架桥接层
将新的Algorithm Framework与现有系统集成
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np

from .framework import (
    Algorithm,
    UniverseSelectionModel,
    AlphaModel,
    PortfolioConstructionModel,
    RiskManagementModel,
    ExecutionModel,
    Insight,
    EqualWeightPortfolioConstruction,
    StopLossRiskManagement
)

from .framework.chip_strategy import (
    ChipUniverseSelectionModel,
    ChipAlphaModel,
    ChipRiskManagementModel,
    ChipScorer
)

from .framework.screener import MultiLayerStockScreener, DarwinRiskFilter, SignalFusion
from .framework.optimizer import (
    GridSearchOptimizer,
    RandomSearchOptimizer,
    ParameterSensitivityAnalysis
)

from .pipeline import BaseStrategy, StrategyPipeline


class AlgorithmFrameworkStrategy(BaseStrategy):
    """
    将新的Algorithm Framework包装为旧版BaseStrategy兼容格式
    """
    
    def __init__(self, algorithm: Algorithm):
        self.algorithm = algorithm
    
    @property
    def name(self) -> str:
        return f"AlgorithmFramework_{self.algorithm.name}"
    
    @property
    def description(self) -> str:
        return f"基于Algorithm Framework的策略: {self.algorithm.name}"
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成信号（桥接方法）
        
        Args:
            data: 单只股票的OHLCV数据
        
        Returns:
            信号序列
        """
        # 将单只股票数据包装为字典格式
        ts_code = data['ts_code'].iloc[0] if 'ts_code' in data.columns else 'unknown'
        market_data = {ts_code: data}
        
        # 运行算法
        insights, orders = self.algorithm.on_data(datetime.now(), market_data)
        
        # 将洞察转换为信号
        signals = pd.Series(0, index=data.index)
        
        for insight in insights:
            if insight.symbol == ts_code:
                if insight.direction == Insight.LONG:
                    signals.iloc[-1] = 1  # 最后一个位置为买入
                elif insight.direction == Insight.SHORT:
                    signals.iloc[-1] = -1  # 最后一个位置为卖出
        
        return signals


def create_chip_strategy_algorithm() -> Algorithm:
    """
    创建一个完整的筹码策略算法实例
    
    Returns:
        Algorithm实例
    """
    # 创建算法
    algorithm = Algorithm(name="ChipStrategy_Complete")
    
    # 设置各模块
    algorithm.set_universe_selection(ChipUniverseSelectionModel(top_n=20))
    algorithm.set_alpha(ChipAlphaModel())
    algorithm.set_portfolio_construction(EqualWeightPortfolioConstruction())
    algorithm.set_risk_management(ChipRiskManagementModel())
    
    return algorithm


def create_multi_layer_screener_strategy() -> Dict:
    """
    创建三层筛选策略
    
    Returns:
        策略配置字典
    """
    return {
        'name': 'MultiLayerStockScreener',
        'description': '三层筛选策略：风险过滤 → 主力识别 → 策略验证',
        'screener': MultiLayerStockScreener(),
        'signal_fusion': SignalFusion({
            'chip': 0.4,
            'chanlun': 0.3,
            'factor': 0.3
        })
    }


class FrameworkIntegration:
    """
    框架集成管理器
    提供新旧框架互操作的便捷方法
    """
    
    def __init__(self):
        self.algorithms: Dict[str, Algorithm] = {}
        self.pipeline = StrategyPipeline()
    
    def register_algorithm(self, name: str, algorithm: Algorithm):
        """
        注册算法
        
        Args:
            name: 算法名称
            algorithm: Algorithm实例
        """
        self.algorithms[name] = algorithm
        
        # 同时包装为旧版策略并添加到流水线
        wrapped_strategy = AlgorithmFrameworkStrategy(algorithm)
        self.pipeline.add_strategy(wrapped_strategy)
    
    def create_default_chip_algorithm(self) -> Algorithm:
        """
        创建默认的筹码策略算法
        
        Returns:
            配置好的Algorithm实例
        """
        algorithm = create_chip_strategy_algorithm()
        self.register_algorithm('ChipStrategy', algorithm)
        return algorithm
    
    def run_screener(self, stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        运行多层筛选器
        
        Args:
            stock_data: 股票数据 {symbol: DataFrame}
        
        Returns:
            筛选结果列表
        """
        screener_config = create_multi_layer_screener_strategy()
        screener = screener_config['screener']
        return screener.screen(list(stock_data.keys()), stock_data)
    
    def optimize_strategy(self, param_space: Dict, objective_func, 
                          method: str = 'grid', max_iter: int = 100):
        """
        策略参数优化
        
        Args:
            param_space: 参数空间
            objective_func: 目标函数
            method: 优化方法 ('grid' or 'random')
            max_iter: 最大迭代次数
        
        Returns:
            优化结果
        """
        if method == 'grid':
            optimizer = GridSearchOptimizer(param_space)
        else:
            optimizer = RandomSearchOptimizer(param_space)
        
        return optimizer.optimize(objective_func, max_iter)


# 全局集成实例
_framework_integration: Optional[FrameworkIntegration] = None


def get_framework_integration() -> FrameworkIntegration:
    """
    获取全局框架集成实例
    """
    global _framework_integration
    if _framework_integration is None:
        _framework_integration = FrameworkIntegration()
        _framework_integration.create_default_chip_algorithm()
    return _framework_integration