"""
回测赢率评估模块 - Phase 4
对应书本附录：策略回测评估体系

核心定位：不模拟实盘交易，只统计"历史发出这类信号后，后续走势如何"
输出的赢率数据作为 evidence 的一部分附在策略信号后

功能：
  4.1 信号类型分类 — 自动按 strategy_name + signal 分组
  4.2 SignalWinRateEvaluator — 每类信号的后续N日表现统计
  4.3 条件概率分支 — 按背离/大盘/换手等条件做分支统计
  4.5 数据缓存 — 持久化到 DuckDB 供重复查询
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ==================== 信号类型分类器（4.1） ====================

class SignalClassifier:
    """信号类型分类器
    从数据库/输入数据中读取历史信号，按策略类型归类
    """

    @staticmethod
    def classify_signals(signals: List[Dict]) -> Dict[str, List[Dict]]:
        """
        将信号列表按 strategy_name + signal 分组
        Args:
            signals: 信号列表
        Returns:
            {signal_type_key: [signal_list]}
        """
        result = {}
        for sig in signals:
            strategy = sig.get('strategy_name', 'unknown')
            signal_val = sig.get('signal', 'UNKNOWN')
            key = f"{strategy}::{signal_val}"
            if key not in result:
                result[key] = []
            result[key].append(sig)
        return result

    @staticmethod
    def classify_by_signal_type(signals: List[Dict]) -> Dict[str, List[Dict]]:
        """按信号类型分组（忽略策略名称）"""
        result = {}
        for sig in signals:
            sig_type = sig.get('signal', 'UNKNOWN')
            if sig_type not in result:
                result[sig_type] = []
            result[sig_type].append(sig)
        return result


# ==================== 赢率评估数据结构（4.2） ====================

@dataclass
class SignalWinRate:
    """单类信号的赢率评估结果"""
    signal_type: str
    samples: int = 0
    win_rate_5d: float = 0.0
    win_rate_10d: float = 0.0
    win_rate_20d: float = 0.0
    avg_return_5d: float = 0.0
    avg_return_10d: float = 0.0
    avg_return_20d: float = 0.0
    max_drawdown_avg_5d: float = 0.0
    max_drawdown_avg_20d: float = 0.0
    sharpe_5d: float = 0.0
    sharpe_20d: float = 0.0
    last_updated: str = ""

    def to_dict(self) -> Dict:
        return {
            'signal_type': self.signal_type,
            'samples': self.samples,
            'win_rate_5d': round(self.win_rate_5d, 4),
            'win_rate_10d': round(self.win_rate_10d, 4),
            'win_rate_20d': round(self.win_rate_20d, 4),
            'avg_return_5d': round(self.avg_return_5d, 4),
            'avg_return_10d': round(self.avg_return_10d, 4),
            'avg_return_20d': round(self.avg_return_20d, 4),
            'max_drawdown_avg_5d': round(self.max_drawdown_avg_5d, 4),
            'max_drawdown_avg_20d': round(self.max_drawdown_avg_20d, 4),
            'sharpe_5d': round(self.sharpe_5d, 4),
            'sharpe_20d': round(self.sharpe_20d, 4),
            'last_updated': self.last_updated,
        }


# ==================== 条件概率分支（4.3） ====================

@dataclass
class ConditionalWinRate:
    """条件概率分支统计"""
    signal_type: str
    total_samples: int = 0
    with_divergence_samples: int = 0
    with_divergence_win_rate_20d: float = 0.0
    without_divergence_samples: int = 0
    without_divergence_win_rate_20d: float = 0.0
    market_good_samples: int = 0
    market_good_win_rate_20d: float = 0.0
    market_poor_samples: int = 0
    market_poor_win_rate_20d: float = 0.0
    high_turnover_samples: int = 0
    high_turnover_win_rate_20d: float = 0.0
    low_turnover_samples: int = 0
    low_turnover_win_rate_20d: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'signal_type': self.signal_type,
            'total_samples': self.total_samples,
            'with_divergence': {
                'samples': self.with_divergence_samples,
                'win_rate_20d': round(self.with_divergence_win_rate_20d, 4),
            },
            'without_divergence': {
                'samples': self.without_divergence_samples,
                'win_rate_20d': round(self.without_divergence_win_rate_20d, 4),
            },
            'market_good': {
                'samples': self.market_good_samples,
                'win_rate_20d': round(self.market_good_win_rate_20d, 4),
            },
            'market_poor': {
                'samples': self.market_poor_samples,
                'win_rate_20d': round(self.market_poor_win_rate_20d, 4),
            },
            'high_turnover': {
                'samples': self.high_turnover_samples,
                'win_rate_20d': round(self.high_turnover_win_rate_20d, 4),
            },
            'low_turnover': {
                'samples': self.low_turnover_samples,
                'win_rate_20d': round(self.low_turnover_win_rate_20d, 4),
            },
        }


# ==================== SignalWinRateEvaluator（4.2 核心） ====================

class SignalWinRateEvaluator:
    """信号类型赢率评估器
    不模拟实盘交易，只回答：历史发出这类信号后，后续走势如何？
    """
    EVAL_PERIODS = [5, 10, 20]

    def __init__(self):
        self._price_cache: Dict[str, pd.DataFrame] = {}

    def evaluate(
        self,
        signals: List[Dict],
        price_data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, Dict]:
        """
        对所有信号类型评估赢率
        Args:
            signals: 历史信号列表
            price_data_map: {ts_code: DataFrame}
        Returns:
            {signal_type: SignalWinRate.to_dict()}
        """
        grouped = SignalClassifier.classify_by_signal_type(signals)
        results = {}

        for signal_type, sig_list in grouped.items():
            if len(sig_list) < 5:
                logger.debug(f"{signal_type}: 样本数{len(sig_list)}<5，跳过")
                continue
            win_rate = self._evaluate_single_type(signal_type, sig_list, price_data_map)
            results[signal_type] = win_rate.to_dict()

        return results

    def evaluate_with_conditions(
        self,
        signals: List[Dict],
        price_data_map: Dict[str, pd.DataFrame],
        divergence_map: Optional[Dict[str, bool]] = None,
        market_condition_map: Optional[Dict[str, str]] = None,
        turnover_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, ConditionalWinRate]:
        """
        评估条件概率分支（4.3）
        Args:
            signals: 历史信号列表
            price_data_map: 价格数据
            divergence_map: {信号日期: 是否有RSI背离}
            market_condition_map: {信号日期: 'GOOD'/'POOR'}
            turnover_map: {信号日期: 换手率值}
        Returns:
            {signal_type: ConditionalWinRate}
        """
        grouped = SignalClassifier.classify_by_signal_type(signals)
        results = {}
        for signal_type, sig_list in grouped.items():
            if len(sig_list) < 5:
                continue
            cond = self._evaluate_conditions(
                signal_type, sig_list, price_data_map,
                divergence_map, market_condition_map, turnover_map
            )
            results[signal_type] = cond
        return results

    def _evaluate_single_type(
        self, signal_type: str, signals: List[Dict],
        price_data_map: Dict[str, pd.DataFrame],
    ) -> SignalWinRate:
        """对单类信号评估赢率"""
        win_rate = SignalWinRate(signal_type=signal_type)
        all_returns_5d, all_returns_10d, all_returns_20d = [], [], []
        all_drawdowns_5d, all_drawdowns_20d = [], []
        wins_5d, wins_10d, wins_20d = 0, 0, 0

        for sig in signals:
            ts_code = sig.get('ts_code', '')
            signal_date = sig.get('signal_date', '')
            if isinstance(signal_date, str):
                try:
                    signal_date = datetime.strptime(signal_date[:10], '%Y-%m-%d').date()
                except ValueError:
                    continue
            df = price_data_map.get(ts_code)
            if df is None or df.empty:
                continue
            close_series = self._get_close_series(df)
            if close_series is None:
                continue
            signal_idx = self._find_signal_index(df, signal_date)
            if signal_idx is None:
                continue
            for period in self.EVAL_PERIODS:
                end_idx = signal_idx + period
                if end_idx >= len(close_series):
                    continue
                entry_price = close_series.iloc[signal_idx]
                exit_price = close_series.iloc[end_idx]
                period_return = (exit_price - entry_price) / entry_price
                period_prices = close_series.iloc[signal_idx:end_idx + 1]
                peak = float(np.max(period_prices))
                drawdown = (period_prices.iloc[-1] - peak) / peak if peak > 0 else 0
                if period == 5:
                    all_returns_5d.append(period_return)
                    all_drawdowns_5d.append(drawdown)
                    if period_return > 0:
                        wins_5d += 1
                elif period == 10:
                    all_returns_10d.append(period_return)
                    if period_return > 0:
                        wins_10d += 1
                elif period == 20:
                    all_returns_20d.append(period_return)
                    all_drawdowns_20d.append(drawdown)
                    if period_return > 0:
                        wins_20d += 1

        total = len(signals)
        win_rate.samples = total
        if wins_5d > 0 and all_returns_5d:
            win_rate.win_rate_5d = wins_5d / total
            win_rate.avg_return_5d = float(np.mean(all_returns_5d))
            win_rate.max_drawdown_avg_5d = float(np.mean(all_drawdowns_5d))
            win_rate.sharpe_5d = self._calc_sharpe(all_returns_5d, 5)
        if wins_10d > 0 and all_returns_10d:
            win_rate.win_rate_10d = wins_10d / total
            win_rate.avg_return_10d = float(np.mean(all_returns_10d))
        if wins_20d > 0 and all_returns_20d:
            win_rate.win_rate_20d = wins_20d / total
            win_rate.avg_return_20d = float(np.mean(all_returns_20d))
            win_rate.max_drawdown_avg_20d = float(np.mean(all_drawdowns_20d))
            win_rate.sharpe_20d = self._calc_sharpe(all_returns_20d, 20)
        win_rate.last_updated = datetime.now().strftime('%Y-%m-%d %H:%M')
        return win_rate

    def _evaluate_conditions(
        self, signal_type: str, signals: List[Dict],
        price_data_map: Dict[str, pd.DataFrame],
        divergence_map: Optional[Dict] = None,
        market_condition_map: Optional[Dict] = None,
        turnover_map: Optional[Dict] = None,
    ) -> ConditionalWinRate:
        """评估条件概率分支"""
        cond = ConditionalWinRate(signal_type=signal_type)
        cond.total_samples = len(signals)
        with_div_returns, without_div_returns = [], []
        market_good_returns, market_poor_returns = [], []
        high_turn_returns, low_turn_returns = [], []

        for sig in signals:
            ts_code = sig.get('ts_code', '')
            signal_date = sig.get('signal_date', '')
            if isinstance(signal_date, str):
                try:
                    signal_date = datetime.strptime(signal_date[:10], '%Y-%m-%d').date()
                except ValueError:
                    continue
            df = price_data_map.get(ts_code)
            if df is None or df.empty:
                continue
            close_series = self._get_close_series(df)
            if close_series is None:
                continue
            signal_idx = self._find_signal_index(df, signal_date)
            if signal_idx is None:
                continue
            end_idx = signal_idx + 20
            if end_idx >= len(close_series):
                continue
            entry_price = close_series.iloc[signal_idx]
            exit_price = close_series.iloc[end_idx]
            ret_20d = (exit_price - entry_price) / entry_price
            date_key = str(signal_date)
            if divergence_map:
                has_div = divergence_map.get(date_key, False)
                if has_div:
                    with_div_returns.append(ret_20d)
                else:
                    without_div_returns.append(ret_20d)
            if market_condition_map:
                mc = market_condition_map.get(date_key, 'UNKNOWN')
                if mc == 'GOOD':
                    market_good_returns.append(ret_20d)
                elif mc == 'POOR':
                    market_poor_returns.append(ret_20d)
            if turnover_map:
                tr = turnover_map.get(date_key, 0)
                if tr > 0.05:
                    high_turn_returns.append(ret_20d)
                else:
                    low_turn_returns.append(ret_20d)

        def win_rate(arr):
            return sum(1 for r in arr if r > 0) / len(arr) if arr else 0

        cond.with_divergence_samples = len(with_div_returns)
        cond.with_divergence_win_rate_20d = win_rate(with_div_returns)
        cond.without_divergence_samples = len(without_div_returns)
        cond.without_divergence_win_rate_20d = win_rate(without_div_returns)
        cond.market_good_samples = len(market_good_returns)
        cond.market_good_win_rate_20d = win_rate(market_good_returns)
        cond.market_poor_samples = len(market_poor_returns)
        cond.market_poor_win_rate_20d = win_rate(market_poor_returns)
        cond.high_turnover_samples = len(high_turn_returns)
        cond.high_turnover_win_rate_20d = win_rate(high_turn_returns)
        cond.low_turnover_samples = len(low_turn_returns)
        cond.low_turnover_win_rate_20d = win_rate(low_turn_returns)
        return cond

    # ==================== 工具方法 ====================

    @staticmethod
    def _get_close_series(df: pd.DataFrame):
        if 'close' not in df.columns:
            return None
        if isinstance(df.index, pd.DatetimeIndex):
            return df['close']
        if 'trade_date' in df.columns:
            return df.set_index('trade_date')['close']
        return df['close']

    @staticmethod
    def _find_signal_index(df: pd.DataFrame, signal_date) -> Optional[int]:
        try:
            if isinstance(df.index, pd.DatetimeIndex):
                dates = df.index
            elif 'trade_date' in df.columns:
                dates = pd.to_datetime(df['trade_date'])
            else:
                return None
            for i, d in enumerate(dates):
                d_val = d.date() if hasattr(d, 'date') else d
                if d_val >= signal_date:
                    return max(0, i - 1)
            return None
        except Exception:
            return None

    @staticmethod
    def _calc_sharpe(returns: List[float], period_days: int) -> float:
        if len(returns) < 2:
            return 0.0
        arr = np.array(returns)
        mean_r = float(np.mean(arr))
        std_r = float(np.std(arr, ddof=1))
        if std_r == 0:
            return 0.0
        daily_sharpe = mean_r / std_r
        annual_factor = np.sqrt(252 / period_days)
        return daily_sharpe * annual_factor


# ==================== 赢率证据构建器（4.4） ====================

def build_win_rate_evidence(win_rates: Dict[str, Dict]) -> List[str]:
    """将赢率数据转换为 evidence 文本"""
    evidence = []
    for sig_type, wr in win_rates.items():
        samples = wr.get('samples', 0)
        if samples < 5:
            continue
        wr_20d = wr.get('win_rate_20d', 0)
        wr_5d = wr.get('win_rate_5d', 0)
        avg_ret_20d = wr.get('avg_return_20d', 0)
        sharpe_20d = wr.get('sharpe_20d', 0)
        parts = [f"{sig_type}: {samples}次"]
        if wr_20d > 0:
            parts.append(f"20日胜率{wr_20d:.0%}")
        if wr_5d > 0:
            parts.append(f"5日胜率{wr_5d:.0%}")
        if avg_ret_20d != 0:
            parts.append(f"20日收益{avg_ret_20d:.2%}")
        if sharpe_20d != 0:
            parts.append(f"夏普{sharpe_20d:.2f}")
        evidence.append("历史回测: " + " ".join(parts))
    return evidence


def build_conditional_evidence(cond_rates: Dict[str, ConditionalWinRate]) -> List[str]:
    """将条件概率分支数据转换为 evidence 文本"""
    evidence = []
    for sig_type, cr in cond_rates.items():
        parts = []
        if cr.with_divergence_samples > 0:
            parts.append(f"有背离: {cr.with_divergence_win_rate_20d:.0%}")
        if cr.without_divergence_samples > 0:
            parts.append(f"无背离: {cr.without_divergence_win_rate_20d:.0%}")
        if cr.market_good_samples > 0:
            parts.append(f"大盘好: {cr.market_good_win_rate_20d:.0%}")
        if cr.market_poor_samples > 0:
            parts.append(f"大盘差: {cr.market_poor_win_rate_20d:.0%}")
        if cr.high_turnover_samples > 0:
            parts.append(f"高换手: {cr.high_turnover_win_rate_20d:.0%}")
        if cr.low_turnover_samples > 0:
            parts.append(f"低换手: {cr.low_turnover_win_rate_20d:.0%}")
        if parts:
            evidence.append(f"条件概率({sig_type}): " + " | ".join(parts))
    return evidence


def attach_win_rates_to_signal(
    signal: Dict,
    win_rates: Dict[str, Dict],
    cond_rates: Optional[Dict[str, ConditionalWinRate]] = None,
) -> Dict:
    """将赢率数据附加到策略信号输出中"""
    signal = dict(signal)
    sig_type = signal.get('signal', 'UNKNOWN')
    current_win_rate = win_rates.get(sig_type, {})
    current_cond = None
    if cond_rates:
        current_cond = cond_rates.get(sig_type)
    evidence = list(signal.get('evidence', []))
    win_evidence = build_win_rate_evidence({sig_type: current_win_rate})
    evidence.extend(win_evidence)
    if current_cond:
        cond_evidence = build_conditional_evidence({sig_type: current_cond})
        evidence.extend(cond_evidence)
    signal['evidence'] = evidence
    signal['backtest_win_rates'] = current_win_rate
    return signal
