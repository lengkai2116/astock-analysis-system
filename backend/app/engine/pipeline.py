import logging
"""
策略流水线
为Darwin选择、筹码分布、缠论策略预留完整框架
借鉴Qlib和Vibe-Trading的策略组合理念
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """策略基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述"""
        pass

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成交易信号
        返回值: 1=买入, -1=卖出, 0=持仓/观望
        """
        pass

    def get_info(self) -> Dict:
        """获取策略信息"""
        return {
            'name': self.name,
            'description': self.description
        }


class DarwinSelectionStrategy(BaseStrategy):
    """
    Darwin选择策略（预留框架）
    基于进化算法的因子选择和组合优化
    """

    @property
    def name(self) -> str:
        return "DarwinSelection"

    @property
    def description(self) -> str:
        return "基于进化算法的达尔文选择策略，自动筛选和组合最优因子"

    def __init__(self, population_size: int = 50, generations: int = 100):
        self.population_size = population_size
        self.generations = generations
        self.best_factors: List[str] = []
        self.best_weights: List[float] = []

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成信号（预留实现）
        """
        # 预留：实际实现时需要完整的进化算法逻辑
        return pd.Series(0, index=data.index)

    def select_factors(self, factor_data: pd.DataFrame,
                      returns: pd.Series) -> List[str]:
        """
        选择最优因子组合（预留实现）
        """
        # 预留：进化算法因子选择
        return list(factor_data.columns[:5])  # 临时返回前5个因子


class ChipDistributionStrategy(BaseStrategy):
    """
    筹码分布策略 - 完整实现版
    基于《筹码分布量化策略技术说明书》
    集成完整的主力阶段识别和信号生成体系
    """

    def __init__(self, lookback_period: int = 120, data_manager=None, config: dict = None):
        self.lookback_period = lookback_period
        self.data_manager = data_manager
        # 加载外部配置（覆盖默认值）
        from ...config import get_strategy_config
        self.strategy_config = config or get_strategy_config().get('chip_distribution', {})
        if config is None:
            self.lookback_period = self.strategy_config.get('lookback_period', lookback_period)
        
        from ..data.chip_distribution_service import ChipDistributionService
        from ..data.chip_indicators import ChipIndicators
        self.chip_service = ChipDistributionService()
        self.chip_indicators = ChipIndicators(self.chip_service)

    @property
    def name(self) -> str:
        return "ChipDistribution"

    @property
    def description(self) -> str:
        return "基于筹码分布分析的完整策略，包含主力阶段识别（建仓/洗盘/拉升/出货/下跌）和多信号体系"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成筹码分布交易信号

        Args:
            data: OHLCV数据（包含ts_code, trade_date, open, high, low, close, vol等）

        Returns:
            信号序列: 1=买入(BULLISH), -1=卖出(BEARISH), 0=观望(NEUTRAL)
        """
        if data.empty or len(data) < 60:
            return pd.Series(0, index=data.index)

        try:
            # 计算完整分析
            analysis = self.analyze(data)

            # 生成信号序列
            signals = []
            recommendation = analysis.get('recommendation', {})
            action = recommendation.get('action', 'HOLD')

            for idx in range(len(data)):
                if idx == len(data) - 1:
                    # 最后一个时点使用建议操作
                    if action == 'BUY':
                        signals.append(1)
                    elif action == 'SELL':
                        signals.append(-1)
                    else:
                        signals.append(0)
                else:
                    # 历史时点先返回观望（可以扩展为回测模式）
                    signals.append(0)

            return pd.Series(signals, index=data.index)

        except Exception as e:
            logger.error(f"筹码分布策略信号生成失败: {e}")
            return pd.Series(0, index=data.index)

    def analyze(self, data: pd.DataFrame) -> Dict:
        """
        完整分析：筹码分布 + 指标 + 阶段 + 信号

        Args:
            data: OHLCV数据

        Returns:
            完整分析报告字典
        """
        result = {}

        if data.empty or len(data) < 60:
            return result

        ts_code = data['ts_code'].iloc[0] if 'ts_code' in data.columns else 'unknown'

        # ===== Phase 1: ChipPreFilter 前置过滤 =====
        try:
            from app.engine.framework.chip_pre_filter import ChipPreFilter
            if not hasattr(self, '_pre_filter'):
                self._pre_filter = ChipPreFilter()
            
            # 大盘环境过滤（含熔断）
            market_result = self._pre_filter.filter_market()
            result['market_environment'] = market_result
            
            # 熔断检查：LIQUIDATE_ALL 时阻断所有信号
            if market_result['circuit_breaker']['action'] == 'LIQUIDATE_ALL':
                result['pre_filter_passed'] = False
                result['pre_filter_reason'] = '熔断: ' + market_result['circuit_breaker']['reason']
                return result
            
            # 个股过滤
            stock_result = self._pre_filter.filter_stock(ts_code)
            result['stock_filter'] = stock_result
            
            if not stock_result['passed']:
                result['pre_filter_passed'] = False
                result['pre_filter_reason'] = '个股过滤未通过: ' + '; '.join(stock_result['reasons'])
                return result
            
            result['pre_filter_passed'] = True
            
            # 仓位乘数（环境差时整体减仓）
            position_multiplier = market_result['overall_position_multiplier']
            result['position_multiplier'] = position_multiplier
            
        except Exception as e:
            logger.warning(f"PreFilter 执行异常，跳过: {e}")
            result['pre_filter_passed'] = True
            result['position_multiplier'] = 1.0

        # ===== Phase 2: 筹码分布计算 =====
        chip_result = self.chip_service.calculate_chip_distribution(
            ts_code=ts_code,
            df_ohlcv=data,
            lookback_days=self.lookback_period
        )
        result['chip_distribution'] = chip_result

        if not chip_result or not chip_result.get('chip_bins'):
            return result

        chip_bins = chip_result['chip_bins']
        current_price = float(data['close'].iloc[-1])

        # ===== Phase 3: 指标计算 =====
        indicators = self.chip_indicators.calculate_all_indicators(
            chip_bins, current_price, data
        )
        result['indicators'] = indicators

        # ===== Phase 4: 操盘阶段检测（含V2资金流向） =====
        # 获取资金流向数据（V2方向5）
        moneyflow_data = None
        try:
            if self.data_manager:
                moneyflow_data = self.data_manager.get_cached_moneyflow(
                    ts_code=ts_code,
                    start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
                )
        except Exception as e:
            logger.debug(f"{ts_code} 资金流向数据获取失败: {e}")

        phase_info = self._detect_phase(data, chip_bins, indicators, moneyflow_data=moneyflow_data)
        result['phase_info'] = phase_info

        # ===== Phase 5: 信号生成（含V2主力测试+筹码形态+洗盘结束增强） =====
        signals = self._generate_complete_signals(data, chip_bins, indicators, phase_info, moneyflow_data=moneyflow_data)
        
        # 仓位乘数调节（大盘环境差时整体降低仓位）
        recom = signals.get('recommendation', {})
        if result.get('position_multiplier', 1.0) < 1.0 and recom.get('target_position'):
            recom['original_position'] = recom['target_position']
            recom['target_position'] = round(recom['target_position'] * result['position_multiplier'], 2)
            recom['position_note'] = f"仓位已按大盘环境调节(x{result['position_multiplier']})"
        
        result['signals'] = signals
        result['recommendation'] = recom

        return result

    def _detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None,
                    moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """委托 chip_strategy_impl.TradingPhaseDetector"""
        if not hasattr(self, '_phase_detector'):
            from app.engine.chip_strategy_impl import TradingPhaseDetector
            self._phase_detector = TradingPhaseDetector(self.chip_indicators)
        return self._phase_detector.detect_phase(
            kline_data, chip_bins, indicators, chip_bins_history, moneyflow_data
        )

    def _generate_complete_signals(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                                    indicators: Dict, phase_info: Dict,
                                    moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """委托 chip_strategy_impl.ChipDistributionSignalGenerator"""
        if not hasattr(self, '_signal_generator'):
            from app.engine.chip_strategy_impl import ChipDistributionSignalGenerator
            self._signal_generator = ChipDistributionSignalGenerator(self._phase_detector)
        return self._signal_generator.generate_signals(
            kline_data, chip_bins, indicators, phase_info, moneyflow_data
        )

    def _check_s_buy(self, *args, **kwargs):
        return self._generate_complete_signals.__wrapped__ or {}

    def _check_false_breakout(self, *args, **kwargs):
        return {}

    def _check_s_wash_end(self, *args, **kwargs):
        return {}

    def _check_s_bounce(self, *args, **kwargs):
        return {}

    def _check_s_sell(self, *args, **kwargs):
        return {}

    def _check_s_wash_stop(self, *args, **kwargs):
        return {}

    def _check_s_diverg_sell(self, *args, **kwargs):
        return {}

    def _combine_signals(self, *args, **kwargs):
        return {}

    def identify_main_phase(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        识别主力阶段（对外接口）
        """
        if data.empty or len(data) < 60:
            return {'phase': 'UNKNOWN', 'confidence': 0}

        analysis = self.analyze(data)
        return analysis.get('phase_info', {'phase': 'UNKNOWN', 'confidence': 0})

    def calculate_chip_distribution(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        计算并返回筹码分布数据
        """
        if data.empty:
            return pd.DataFrame()

        ts_code = data['ts_code'].iloc[0] if 'ts_code' in data.columns else 'unknown'

        try:
            chip_result = self.chip_service.calculate_chip_distribution(
                ts_code=ts_code,
                df_ohlcv=data,
                lookback_days=self.lookback_period
            )

            if not chip_result or not chip_result.get('chip_bins'):
                return pd.DataFrame()

            return pd.DataFrame(chip_result['chip_bins'])

        except Exception as e:
            logger.error(f"筹码分布计算失败: {e}")
            return pd.DataFrame()


class ChanLunStrategy(BaseStrategy):
    """
    缠论策略（预留框架）
    基于分型、笔、线段、中枢的技术分析策略
    """

    @property
    def name(self) -> str:
        return "ChanLun"

    @property
    def description(self) -> str:
        return "基于缠论的分型、笔、线段、中枢分析策略"

    def __init__(self, min_kline: int = 5):
        self.min_kline = min_kline

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成信号（预留实现）
        """
        # 预留：缠论信号生成逻辑
        return pd.Series(0, index=data.index)

    def identify_fractals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        识别分型（预留实现）
        """
        # 预留：顶分型、底分型识别
        return pd.DataFrame()

    def identify_pens(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        识别笔（预留实现）
        """
        # 预留：笔识别
        return pd.DataFrame()


class StrategyPipeline:
    """
    策略流水线
    支持多个策略的组合和信号融合
    """

    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.strategy_weights: Dict[str, float] = {}

    def add_strategy(self, strategy: BaseStrategy, weight: float = 1.0):
        """
        添加策略
        """
        self.strategies[strategy.name] = strategy
        self.strategy_weights[strategy.name] = weight

    def remove_strategy(self, strategy_name: str):
        """
        移除策略
        """
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            del self.strategy_weights[strategy_name]

    def generate_combined_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成组合信号
        """
        if not self.strategies:
            return pd.Series(0, index=data.index)

        # 收集各策略信号
        signals = pd.DataFrame(index=data.index)
        total_weight = sum(self.strategy_weights.values())

        for name, strategy in self.strategies.items():
            try:
                strategy_signals = strategy.generate_signals(data)
                weight = self.strategy_weights[name] / total_weight
                signals[name] = strategy_signals * weight
            except Exception as e:
                logger.warning(f"策略 {name} 生成信号失败: {e}")

        # 加权求和
        if not signals.empty:
            combined = signals.sum(axis=1)
            # 离散化：>0.3买入, <-0.3卖出
            return pd.Series(np.where(combined > 0.3, 1,
                                      np.where(combined < -0.3, -1, 0)),
                             index=data.index)

        return pd.Series(0, index=data.index)

    def list_strategies(self) -> List[Dict]:
        """
        列出所有策略
        """
        return [
            {
                'name': name,
                'description': strategy.description,
                'weight': self.strategy_weights.get(name, 1.0)
            }
            for name, strategy in self.strategies.items()
        ]

    def get_available_strategies(self) -> List[Dict]:
        """
        获取可用策略列表
        """
        return [
            {
                'name': 'DarwinSelection',
                'description': '基于进化算法的达尔文选择策略',
                'implemented': False
            },
            {
                'name': 'ChipDistribution',
                'description': '基于筹码分布分析的完整策略，包含主力阶段识别（建仓/洗盘/拉升/出货/下跌）和多信号体系',
                'implemented': True
            },
            {
                'name': 'ChanLun',
                'description': '基于缠论的分型、笔、线段、中枢分析策略',
                'implemented': False
            }
        ]


# 全局策略注册表
_strategy_pipeline: Optional[StrategyPipeline] = None


def get_strategy_pipeline() -> StrategyPipeline:
    """
    获取全局策略流水线
    """
    global _strategy_pipeline
    if _strategy_pipeline is None:
        _strategy_pipeline = StrategyPipeline()
    return _strategy_pipeline


def create_strategy(strategy_name: str, **kwargs) -> Optional[BaseStrategy]:
    """
    创建策略实例
    """
    strategy_classes = {
        'DarwinSelection': DarwinSelectionStrategy,
        'ChipDistribution': ChipDistributionStrategy,
        'ChanLun': ChanLunStrategy
    }

    if strategy_name in strategy_classes:
        return strategy_classes[strategy_name](**kwargs)

    return None
