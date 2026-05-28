"""
回测引擎
借鉴Qlib和Vibe-Trading的回测理念
支持因子组合回测、绩效分析、Benchmark对比
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class BacktestResult:
    """回测结果"""
    
    def __init__(self):
        self.portfolio_values: pd.Series = pd.Series()
        self.benchmark_values: Optional[pd.Series] = None
        self.trades: List[Dict] = []
        self.daily_returns: pd.Series = pd.Series()
        self.metrics: Dict = {}
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'metrics': self.metrics,
            'portfolio_values': self.portfolio_values.to_dict() if not self.portfolio_values.empty else {},
            'benchmark_values': self.benchmark_values.to_dict() if self.benchmark_values is not None and not self.benchmark_values.empty else {},
            'trades': self.trades,
            'daily_returns': self.daily_returns.to_dict() if not self.daily_returns.empty else {}
        }


class BacktestEngine:
    """
    回测引擎
    """
    
    def __init__(self, initial_capital: float = 100000.0, commission_rate: float = 0.0003):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
    
    def run_simple_backtest(self, 
                           price_data: pd.DataFrame,
                           factor_series: Optional[pd.Series] = None,
                           benchmark_data: Optional[pd.DataFrame] = None,
                           top_n: int = 1,
                           rebalance_freq: int = 20) -> BacktestResult:
        """
        简单回测：基于因子选股
        
        参数:
            price_data: 价格数据，需要包含close列和trade_date索引
            factor_series: 因子序列，用于选股
            benchmark_data: Benchmark数据
            top_n: 每次选股数量
            rebalance_freq: 调仓频率（天数）
        """
        result = BacktestResult()
        
        # 如果没有因子数据，直接用买入持有策略
        if factor_series is None or factor_series.empty:
            return self._buy_and_hold(price_data, benchmark_data)
        
        # 简单回测逻辑
        portfolio_value = self.initial_capital
        portfolio_values = [portfolio_value]
        dates = price_data.index.tolist()
        
        for i in range(1, len(dates)):
            date = dates[i]
            prev_date = dates[i-1]
            
            # 简化：假设全仓买入，每日收益率等于股票收益率
            if 'close' in price_data.columns:
                daily_return = (price_data.loc[date, 'close'] / price_data.loc[prev_date, 'close']) - 1
                portfolio_value = portfolio_value * (1 + daily_return)
            
            portfolio_values.append(portfolio_value)
        
        result.portfolio_values = pd.Series(portfolio_values, index=dates)
        
        # 处理Benchmark
        if benchmark_data is not None and 'close' in benchmark_data.columns:
            benchmark_values = []
            bm_value = self.initial_capital
            benchmark_values.append(bm_value)
            
            for i in range(1, len(dates)):
                if dates[i] in benchmark_data.index and dates[i-1] in benchmark_data.index:
                    bm_return = (benchmark_data.loc[dates[i], 'close'] / benchmark_data.loc[dates[i-1], 'close']) - 1
                    bm_value = bm_value * (1 + bm_return)
                benchmark_values.append(bm_value)
            
            result.benchmark_values = pd.Series(benchmark_values, index=dates)
        
        # 计算绩效指标
        result.metrics = self._calculate_metrics(result.portfolio_values, result.benchmark_values)
        
        return result
    
    def _buy_and_hold(self, price_data: pd.DataFrame, 
                     benchmark_data: Optional[pd.DataFrame] = None) -> BacktestResult:
        """
        买入持有策略
        """
        result = BacktestResult()
        
        if 'close' not in price_data.columns:
            return result
        
        # 计算组合净值
        initial_close = price_data['close'].iloc[0]
        result.portfolio_values = (price_data['close'] / initial_close) * self.initial_capital
        
        # Benchmark
        if benchmark_data is not None and 'close' in benchmark_data.columns:
            benchmark_close = benchmark_data['close']
            initial_bm = benchmark_close.iloc[0]
            result.benchmark_values = (benchmark_close / initial_bm) * self.initial_capital
        
        # 计算指标
        result.metrics = self._calculate_metrics(result.portfolio_values, result.benchmark_values)
        
        return result
    
    def _calculate_metrics(self, 
                          portfolio_values: pd.Series,
                          benchmark_values: Optional[pd.Series] = None,
                          risk_free_rate: float = 0.03) -> Dict:
        """
        计算完整的绩效指标
        """
        if len(portfolio_values) < 2:
            return {}
        
        # 日收益率
        daily_returns = portfolio_values.pct_change().dropna()
        
        # 基本收益率
        total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1
        annual_return = (1 + total_return) ** (252 / len(portfolio_values)) - 1 if len(portfolio_values) > 0 else 0
        
        # 回撤分析
        cummax = portfolio_values.cummax()
        drawdown = (cummax - portfolio_values) / cummax
        max_drawdown = drawdown.max()
        
        # 计算回撤持续期
        drawdown_duration = 0
        max_drawdown_duration = 0
        in_drawdown = False
        for dd in drawdown:
            if dd > 0:
                if not in_drawdown:
                    in_drawdown = True
                    drawdown_duration = 1
                else:
                    drawdown_duration += 1
                max_drawdown_duration = max(max_drawdown_duration, drawdown_duration)
            else:
                in_drawdown = False
        
        # 夏普比率
        excess_returns = daily_returns - risk_free_rate / 252
        sharpe_ratio = np.sqrt(252) * excess_returns.mean() / (daily_returns.std() + 1e-10)
        
        # 索提诺比率（仅考虑下行风险）
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-10
        sortino_ratio = np.sqrt(252) * excess_returns.mean() / (downside_std + 1e-10)
        
        # 胜率
        win_rate = (daily_returns > 0).mean() if len(daily_returns) > 0 else 0
        
        # 盈亏比
        wins = daily_returns[daily_returns > 0]
        losses = daily_returns[daily_returns < 0]
        
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-10
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 波动率
        volatility = daily_returns.std() * np.sqrt(252)
        
        result = {
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'max_drawdown': float(max_drawdown),
            'max_drawdown_duration': int(max_drawdown_duration),
            'sharpe_ratio': float(sharpe_ratio),
            'sortino_ratio': float(sortino_ratio),
            'win_rate': float(win_rate),
            'profit_loss_ratio': float(profit_loss_ratio),
            'total_trades': len(daily_returns),
            'volatility': float(volatility),
            'avg_win': float(avg_win),
            'avg_loss': float(-avg_loss)
        }
        
        # Benchmark对比
        if benchmark_values is not None and len(benchmark_values) > 1:
            benchmark_returns = benchmark_values.pct_change().dropna()
            
            benchmark_total = (benchmark_values.iloc[-1] / benchmark_values.iloc[0]) - 1
            excess_return = total_return - benchmark_total
            
            aligned_returns = daily_returns.reindex(benchmark_returns.index).dropna()
            aligned_benchmark = benchmark_returns.reindex(daily_returns.index).dropna()
            
            if len(aligned_returns) > 0 and len(aligned_benchmark) > 0:
                combined_returns = pd.concat([aligned_returns, aligned_benchmark], axis=1).dropna()
                if len(combined_returns) > 1:
                    cov_matrix = combined_returns.cov()
                    if cov_matrix.shape[0] == 2:
                        beta = cov_matrix.iloc[0, 1] / (cov_matrix.iloc[1, 1] + 1e-10)
                    else:
                        beta = 1.0
                else:
                    beta = 1.0
                
                tracking_error = (aligned_returns - aligned_benchmark).std() * np.sqrt(252)
                information_ratio = excess_return / (tracking_error + 1e-10) if tracking_error > 0 else 0
                
                result.update({
                    'benchmark_return': float(benchmark_total),
                    'excess_return': float(excess_return),
                    'beta': float(beta),
                    'tracking_error': float(tracking_error),
                    'information_ratio': float(information_ratio)
                })
        
        return result


def calculate_performance_metrics(portfolio_values: pd.Series,
                                 benchmark_values: Optional[pd.Series] = None,
                                 risk_free_rate: float = 0.03) -> Dict:
    """
    计算绩效指标（独立函数）
    """
    engine = BacktestEngine()
    return engine._calculate_metrics(portfolio_values, benchmark_values, risk_free_rate)
