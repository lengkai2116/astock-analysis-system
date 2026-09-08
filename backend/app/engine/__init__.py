"""
引擎模块
提供回测引擎和策略流水线
"""
from .backtest import BacktestEngine, BacktestResult, calculate_performance_metrics
from .backtest_v2 import (
    AShareBacktestEngine,
    BacktestConfig,
    BacktestResultV2,
    create_default_engine,
)
from .pipeline import (
    BaseStrategy,
    ChanLunStrategy,
    ChipDistributionStrategy,
    DarwinSelectionStrategy,
    StrategyPipeline,
    create_strategy,
    get_strategy_pipeline,
)

__all__ = [
    'BacktestEngine',
    'BacktestResult',
    'calculate_performance_metrics',
    'AShareBacktestEngine',
    'BacktestConfig',
    'BacktestResultV2',
    'create_default_engine',
    'StrategyPipeline',
    'BaseStrategy',
    'DarwinSelectionStrategy',
    'ChipDistributionStrategy',
    'ChanLunStrategy',
    'get_strategy_pipeline',
    'create_strategy'
]
