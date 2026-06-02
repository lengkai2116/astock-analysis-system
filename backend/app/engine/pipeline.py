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

        # 1. 计算筹码分布
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

        # 2. 计算所有指标
        indicators = self.chip_indicators.calculate_all_indicators(
            chip_bins, current_price, data
        )
        result['indicators'] = indicators

        # 3. 检测操盘阶段
        phase_info = self._detect_phase(data, chip_bins, indicators)
        result['phase_info'] = phase_info

        # 4. 生成信号
        signals = self._generate_complete_signals(data, chip_bins, indicators, phase_info)
        result['signals'] = signals
        result['recommendation'] = signals.get('recommendation', {})

        return result

    def _detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None) -> Dict:
        """
        检测操盘阶段：建仓期/洗盘期/拉升期/出货期/下跌期
        """
        # 计算筹码转移信息（如提供历史数据）
        transfer_info = None
        if chip_bins_history is not None:
            try:
                transfer_info = self.chip_indicators.detect_chip_transfer(chip_bins_history, lookback=20)
            except Exception:
                pass

        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators, transfer_info),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators, transfer_info),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators, transfer_info),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators, transfer_info),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators, transfer_info)
        }

        best_phase = max(scores.items(), key=lambda x: x[1])
        total_score = sum(scores.values())

        confidence = best_phase[1] / max(total_score, 1)

        # 阶段中文名映射
        phase_names = {
            'BUILDING': '建仓期',
            'WASHING': '洗盘期',
            'RAISING': '拉升期',
            'SHIPPING': '出货期',
            'SUPPORT': '下跌支撑期'
        }

        return {
            'phase': best_phase[0],
            'phase_name': phase_names.get(best_phase[0], best_phase[0]),
            'confidence': round(confidence, 4),
            'scores': scores
        }

    def _score_building(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        score = 0.0
        if indicators.get('profit_ratio', 0) < 0.4:
            score += 2.0
        if indicators.get('asr', 0) >= 0.7:
            score += 2.0
        conc_status = indicators.get('concentration_status', '')
        if conc_status == '高度集中' or conc_status == '较集中':
            score += 2.0
        return score

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                      transfer_info: Optional[Dict] = None) -> float:
        score = 0.0
        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status == '缩量' or vol_status == '地量':
            score += 2.0
        asr = indicators.get('asr', 0)
        if 0.3 <= asr <= 0.6:
            score += 1.5
        # 筹码稳定或向下转移（方向3）
        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            low_chg = transfer_info.get('low_chips_change', 0)
            if tr_type == '稳定' and low_chg >= -0.02:
                score += 2.0
            elif tr_type == '向下转移' and low_chg > 0:
                score += 2.0
        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                     transfer_info: Optional[Dict] = None) -> float:
        score = 0.0
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price > ssrp * 1.05:
                score += 2.0
        if indicators.get('profit_ratio', 0) >= 0.6:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ['放量', '显著放量', '天量']:
            score += 2.0
        # 筹码向上转移（方向3）
        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            if tr_type == '向上转移':
                score += 2.0
            elif tr_type == '稳定' and indicators.get('profit_ratio', 0) >= 0.5:
                score += 1.0
        return score

    def _score_shipping(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        score = 0.0
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5]:
                score += 2.5
        vol_status = indicators.get('vol_status', '')
        if vol_status in ['缩量', '地量']:
            score += 2.0
        if indicators.get('rsi', 0) >= 70:
            score += 1.5
        return score

    def _score_support(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        score = 0.0
        if indicators.get('profit_ratio', 0) < 0.35:
            score += 2.0
        if indicators.get('rsi', 0) < 30:
            score += 2.0
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                score += 2.0
        return score

    def _generate_complete_signals(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                                    indicators: Dict, phase_info: Dict) -> Dict:
        """
        生成完整信号集合（含K线形态验证 + S_DIVERG_SELL背离减仓）
        """
        result = {}

        # K线形态验证
        try:
            from app.engine.framework.kline_pattern import KLinePatternVerifier
            pattern_verifier = KLinePatternVerifier()
            patterns = pattern_verifier.verify(kline_data)
            result['patterns'] = [p.to_dict() for p in patterns]
        except Exception:
            result['patterns'] = []

        # 检测各个信号
        result['S_BUY'] = self._check_s_buy(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_END'] = self._check_s_wash_end(kline_data, chip_bins, indicators, phase_info)
        result['S_BOUNCE'] = self._check_s_bounce(kline_data, chip_bins, indicators, phase_info)
        result['S_SELL'] = self._check_s_sell(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_STOP'] = self._check_s_wash_stop(kline_data, chip_bins, indicators, phase_info)
        result['S_DIVERG_SELL'] = self._check_s_diverg_sell(kline_data, chip_bins, indicators, phase_info)

        # 确定最终操作建议（含K线形态置信度调整）
        recommendation = self._combine_signals(result)
        bullish_patterns = [p for p in result.get('patterns', []) if p.get('direction') == 'bullish']
        bearish_patterns = [p for p in result.get('patterns', []) if p.get('direction') == 'bearish']
        if bullish_patterns and recommendation.get('action') == 'BUY':
            recommendation['pattern_boost'] = [p['name'] for p in bullish_patterns]
        if bearish_patterns and recommendation.get('action') == 'SELL':
            recommendation['pattern_boost'] = [p['name'] for p in bearish_patterns]
        result['recommendation'] = recommendation

        return result

    def _check_s_buy(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                     indicators: Dict, phase_info: Dict) -> Dict:
        """主买入信号 S_BUY"""
        conditions = []
        all_met = True

        # === 假突破前置过滤 ===
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'RAISING':
            conditions.append('[OK] 处于拉升期')
        else:
            conditions.append('[NO] 非拉升期')
            all_met = False

        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            max_60 = np.max(closes[-60:])
            if closes[-1] > max_60 * 0.98:
                conditions.append('[OK] 价格高位')
            else:
                conditions.append('[NO] 未突破')
                all_met = False

        if indicators.get('vol_ratio', 0) >= 1.5:
            conditions.append('[OK] 成交量放大')
        else:
            conditions.append('[NO] 成交量不足')
            all_met = False

        if indicators.get('cyqkl', 0) >= 0.2:
            conditions.append('[OK] CYQKL达标')
        else:
            conditions.append('[NO] CYQKL不足')
            all_met = False

        # SSRP穿越确认
        ssrp = indicators.get('ssrp', 0)
        current_price = float(kline_data['close'].iloc[-1]) if len(kline_data) > 0 and ssrp > 0 else 0
        if current_price > 0 and ssrp > 0 and current_price > ssrp:
            conditions.append(f'[OK] SSRP穿越确认: 收盘价{current_price:.2f} > SSRP {ssrp:.2f}')
        else:
            conditions.append('[NO] SSRP未突破')
            all_met = False

        if indicators.get('profit_ratio', 0) >= 0.6:
            conditions.append('[OK] 获利率达标')
        else:
            conditions.append('[NO] 获利率不足')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.7,
            'conditions': conditions
        }

    def _check_s_wash_end(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                          indicators: Dict, phase_info: Dict) -> Dict:
        """洗盘结束买入信号 S_WASH_END"""
        conditions = []
        all_met = True

        if phase_info.get('phase') == 'WASHING':
            conditions.append('[OK] 处于洗盘期')
        else:
            conditions.append('[NO] 非洗盘期')
            all_met = False

        if indicators.get('vol_status', '') == '地量':
            conditions.append('[OK] 成交量地量')
        else:
            conditions.append('[NO] 非地量')
            all_met = False

        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            conditions.append('[OK] RSI回调到位')
        else:
            conditions.append('[NO] RSI未到位')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.5,
            'conditions': conditions
        }

    def _check_s_bounce(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                        indicators: Dict, phase_info: Dict) -> Dict:
        """超跌反弹买入信号 S_BOUNCE"""
        conditions = []
        all_met = True

        if phase_info.get('phase') == 'SUPPORT':
            conditions.append('[OK] 处于支撑期')
        else:
            conditions.append('[NO] 非支撑期')
            all_met = False

        if indicators.get('rsi', 50) < 30:
            conditions.append('[OK] RSI超卖')
        else:
            conditions.append('[NO] RSI未超卖')
            all_met = False

        if indicators.get('profit_ratio', 0) < 0.2:
            conditions.append('[OK] 低获利率')
        else:
            conditions.append('[NO] 获利率过高')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.3,
            'conditions': conditions
        }

    def _check_s_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                      indicators: Dict, phase_info: Dict) -> Dict:
        """主卖出信号 S_SELL"""
        conditions = []
        triggered = False

        # === 假突破前置过滤 ===
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'SHIPPING':
            conditions.append('[OK] 出货期确认')
            triggered = True

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5] * 0.95:
                conditions.append('[OK] 高位回落')
                triggered = True

        if indicators.get('rsi', 50) >= 80:
            conditions.append('[OK] RSI超买')
            triggered = True

        # SSRP穿越卖出
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) >= 3:
            closes = kline_data['close'].values
            if len(closes) >= 2 and closes[-1] < ssrp and closes[-2] < ssrp:
                conditions.append(f'[OK] 连续2日低于SSRP({ssrp:.2f})')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }

    def _check_s_wash_stop(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                           indicators: Dict, phase_info: Dict) -> Dict:
        """洗盘止损信号 S_WASH_STOP"""
        conditions = []
        triggered = False

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                conditions.append('[OK] 跌破主力成本')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }

    def _check_s_diverg_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                              indicators: Dict, phase_info: Dict) -> Dict:
        """
        高位背离减仓信号 S_DIVERG_SELL
        使用 self.chip_indicators.detect_rsi_divergence()
        初次顶背离 -> 减仓至70%  二次顶背离 -> 减仓至30%  三重顶背离 -> 减仓至10%
        """
        conditions = []
        triggered = False
        position_adjustment = 1.0

        if len(kline_data) < 40:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['数据不足']}

        try:
            divergence = self.chip_indicators.detect_rsi_divergence(kline_data, period=14, lookback=20)
        except Exception:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['背离检测异常']}

        top_div = divergence.get('top_divergence', {})

        if top_div.get('detected', False):
            count = top_div.get('count', 1)
            if count >= 3:
                triggered = True
                position_adjustment = 0.1
                conditions.append(
                    '[OK] 三重顶背离确认 -> 减仓至10% '
                    f'(最新:价格{top_div["latest_high_price"]:.2f}/RSI{top_div["latest_high_rsi"]:.1f}, '
                    f'前次:价格{top_div["prev_high_price"]:.2f}/RSI{top_div["prev_high_rsi"]:.1f})'
                )
            elif count == 2:
                triggered = True
                position_adjustment = 0.3
                conditions.append(
                    '[OK] 二次顶背离确认 -> 减仓至30% '
                    f'(最新RSI{top_div["latest_high_rsi"]:.1f} < 前次RSI{top_div["prev_high_rsi"]:.1f})'
                )
            else:
                triggered = True
                position_adjustment = 0.7
                conditions.append(
                    '[->] 初次顶背离 -> 减仓至70% '
                    f'(价格{top_div["latest_high_price"]:.2f}新高, '
                    f'RSI{top_div["latest_high_rsi"]:.1f}低于前次{top_div["prev_high_rsi"]:.1f})'
                )

        return {
            'triggered': triggered,
            'position_adjustment': position_adjustment,
            'top_divergence_count': top_div.get('count', 0),
            'conditions': conditions
        }

    def _check_false_breakout(self, kline_data: pd.DataFrame, indicators: Dict) -> Dict:
        """
        假突破前置检测 - 三维确认
        仅在突破/跌破状态时激活，非突破状态直接返回通过
        """
        if kline_data.empty or len(kline_data) < 5:
            return {'passed': True, 'reason': '数据不足，默认通过', 'is_breakout': False}

        closes = kline_data['close'].values
        latest = float(closes[-1])

        if len(closes) >= 20:
            max_20 = float(np.max(closes[-20:]))
            min_20 = float(np.min(closes[-20:]))
            price_range = max_20 - min_20
            if price_range <= 0:
                return {'passed': True, 'reason': '价格无波动', 'is_breakout': False}

            is_breakout_high = latest >= max_20 * 0.98
            is_breakout_low = latest <= min_20 * 1.02

            if not is_breakout_high and not is_breakout_low:
                return {'passed': True, 'reason': '非突破状态', 'is_breakout': False}
        else:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        if is_breakout_high:
            breakout_level = max_20 * 0.98
        else:
            breakout_level = min_20 * 1.02

        breakout_days = 0
        for i in range(len(closes) - 1, -1, -1):
            if (is_breakout_high and closes[i] >= breakout_level) or (is_breakout_low and closes[i] <= breakout_level):
                breakout_days += 1
            else:
                break

        vol_ratio = indicators.get('vol_ratio', 0)
        if vol_ratio < 1.5 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'量能不足(vol_ratio={vol_ratio:.2f}<1.5,突破{breakout_days}日)'
            }

        if breakout_days < 3 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'突破时间不足({breakout_days}<3日)'
            }

        cyqkl = indicators.get('cyqkl', 0)
        if cyqkl < 0.2 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'穿透深度不足(cyqkl={cyqkl:.2f}<0.2)'
            }

        return {'passed': True, 'reason': '三维确认通过', 'is_breakout': True}

    def _combine_signals(self, signals: Dict) -> Dict:
        """综合各信号给出最终操作建议"""
        if signals.get('S_WASH_STOP', {}).get('triggered', False):
            return {
                'action': 'SELL',
                'reason': '洗盘止损',
                'target_position': 0.0,
                'priority': 1
            }

        if signals.get('S_SELL', {}).get('triggered', False):
            return {
                'action': 'SELL',
                'reason': '主卖出信号',
                'target_position': 0.0,
                'priority': 2
            }

        if signals.get('S_DIVERG_SELL', {}).get('triggered', False):
            sd = signals['S_DIVERG_SELL']
            adj = sd.get('position_adjustment', 1.0)
            return {
                'action': 'REDUCE',
                'reason': '高位背离减仓',
                'target_position': adj,
                'position_adjustment': adj,
                'priority': 3
            }

        if signals.get('S_BUY', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '主买入信号',
                'target_position': 0.7,
                'priority': 4
            }

        if signals.get('S_WASH_END', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '洗盘结束',
                'target_position': 0.5,
                'priority': 5
            }

        if signals.get('S_BOUNCE', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '超跌反弹',
                'target_position': 0.3,
                'priority': 6
            }

        return {
            'action': 'HOLD',
            'reason': '无明确信号',
            'target_position': None,
            'priority': 99
        }




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
