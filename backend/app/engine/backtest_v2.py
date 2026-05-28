"""
A股增强回测引擎 V2
支持A股特有规则：T+1交易、涨跌停限制、手续费、印花税、滑点
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Trade:
    """交易记录"""
    trade_id: str
    date: str
    ts_code: str
    side: OrderSide
    price: float
    quantity: int
    amount: float
    commission: float
    stamp_duty: float
    slippage: float
    total_cost: float


@dataclass
class Position:
    """持仓信息"""
    ts_code: str
    quantity: int
    available_quantity: int
    avg_cost: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float


@dataclass
class DailyEquity:
    """每日权益数据"""
    date: str
    cash: float
    total_value: float
    position_value: float
    total_pnl: float
    daily_return: float


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 100000.0
    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.001
    slippage_rate: float = 0.0001
    min_commission: float = 5.0
    max_position: int = 10
    price_limit_check: bool = True


@dataclass
class BacktestResultV2:
    """回测结果V2"""
    config: BacktestConfig
    trades: List[Trade] = field(default_factory=list)
    daily_equity: List[DailyEquity] = field(default_factory=list)
    positions: Dict[str, Position] = field(default_factory=dict)
    metrics: Dict = field(default_factory=dict)
    benchmark_metrics: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'config': {
                'initial_capital': self.config.initial_capital,
                'commission_rate': self.config.commission_rate,
                'stamp_duty_rate': self.config.stamp_duty_rate,
                'slippage_rate': self.config.slippage_rate,
                'max_position': self.config.max_position
            },
            'metrics': self.metrics,
            'benchmark_metrics': self.benchmark_metrics,
            'trade_count': len(self.trades),
            'trades': [
                {
                    'trade_id': t.trade_id,
                    'date': t.date,
                    'ts_code': t.ts_code,
                    'side': t.side.value,
                    'price': t.price,
                    'quantity': t.quantity,
                    'amount': t.amount,
                    'commission': t.commission,
                    'stamp_duty': t.stamp_duty,
                    'slippage': t.slippage,
                    'total_cost': t.total_cost
                } for t in self.trades
            ],
            'daily_equity': [
                {
                    'date': e.date,
                    'cash': e.cash,
                    'total_value': e.total_value,
                    'position_value': e.position_value,
                    'total_pnl': e.total_pnl,
                    'daily_return': e.daily_return
                } for e in self.daily_equity
            ]
        }


class AShareBacktestEngine:
    """
    A股增强回测引擎
    
    支持的A股特有规则：
    1. T+1交易：当日买入的股票，当日不能卖出
    2. 涨跌停限制：涨停不能买，跌停不能卖
    3. 手续费：默认万分之三，最低5元
    4. 印花税：卖出时收取千分之一
    5. 滑点：默认万分之一
    """
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.reset()
    
    def reset(self):
        """重置回测状态"""
        self.cash = self.config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.pending_sell: Dict[str, int] = {}
        self.trades: List[Trade] = {}
        self.daily_equity: List[DailyEquity] = []
        self.trade_counter = 0
        
        self.total_commission = 0.0
        self.total_stamp_duty = 0.0
        self.total_slippage = 0.0
        self.realized_pnl = 0.0
    
    def calculate_order_cost(self, price: float, quantity: int, 
                            is_buy: bool = True) -> Tuple[float, float, float, float]:
        """
        计算订单成本
        
        Returns:
            (成交金额, 手续费, 印花税, 滑点成本)
        """
        amount = price * quantity
        
        commission = max(amount * self.config.commission_rate, 
                        self.config.min_commission if is_buy else 0)
        
        stamp_duty = 0.0
        if not is_buy:
            stamp_duty = amount * self.config.stamp_duty_rate
        
        slippage = amount * self.config.slippage_rate
        
        return amount, commission, stamp_duty, slippage
    
    def can_buy(self, ts_code: str, price: float, 
                limit_up_price: float, limit_down_price: float) -> bool:
        """
        检查是否能买入
        - 检查涨跌停限制
        """
        if not self.config.price_limit_check:
            return True
        
        if price >= limit_up_price:
            return False
        return True
    
    def can_sell(self, ts_code: str, price: float,
                limit_up_price: float, limit_down_price: float) -> bool:
        """
        检查是否能卖出
        - 检查涨跌停限制
        - 检查T+1限制
        """
        if not self.config.price_limit_check:
            return True
        
        if price <= limit_down_price:
            return False
        
        if ts_code in self.pending_sell and self.pending_sell[ts_code] > 0:
            return False
        
        return True
    
    def execute_buy(self, ts_code: str, date: str, price: float,
                   quantity: int, limit_up: float = None, limit_down: float = None) -> bool:
        """
        执行买入
        
        Args:
            ts_code: 股票代码
            date: 交易日期
            price: 买入价格
            quantity: 买入数量
            limit_up: 涨停价
            limit_down: 跌停价
        
        Returns:
            是否成功
        """
        if limit_up is not None and not self.can_buy(ts_code, price, limit_up, limit_down or 0):
            return False
        
        amount, commission, stamp_duty, slippage = self.calculate_order_cost(price, quantity, True)
        total_cost = amount + commission + slippage
        
        if total_cost > self.cash:
            quantity = int(self.cash / (price * (1 + self.config.commission_rate + self.config.slippage_rate)))
            quantity = (quantity // 100) * 100
            if quantity < 100:
                return False
            amount, commission, stamp_duty, slippage = self.calculate_order_cost(price, quantity, True)
            total_cost = amount + commission + slippage
        
        self.cash -= total_cost
        self.total_commission += commission
        self.total_slippage += slippage
        
        self.trade_counter += 1
        trade = Trade(
            trade_id=f"B{self.trade_counter:06d}",
            date=date,
            ts_code=ts_code,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            stamp_duty=0,
            slippage=slippage,
            total_cost=total_cost
        )
        self.trades[trade.trade_id] = trade
        
        if ts_code in self.positions:
            pos = self.positions[ts_code]
            total_quantity = pos.quantity + quantity
            pos.avg_cost = (pos.avg_cost * pos.quantity + price * quantity) / total_quantity
            pos.quantity = total_quantity
            pos.available_quantity = pos.quantity
        else:
            self.positions[ts_code] = Position(
                ts_code=ts_code,
                quantity=quantity,
                available_quantity=quantity,
                avg_cost=price,
                last_price=price,
                market_value=0,
                unrealized_pnl=0,
                realized_pnl=0
            )
        
        return True
    
    def execute_sell(self, ts_code: str, date: str, price: float,
                   quantity: int, limit_up: float = None, limit_down: float = None) -> bool:
        """
        执行卖出
        
        Args:
            ts_code: 股票代码
            date: 交易日期
            price: 卖出价格
            quantity: 卖出数量
            limit_up: 涨停价
            limit_down: 跌停价
        
        Returns:
            是否成功
        """
        if ts_code not in self.positions:
            return False
        
        pos = self.positions[ts_code]
        sell_quantity = min(quantity, pos.available_quantity)
        
        if sell_quantity <= 0:
            return False
        
        if limit_down is not None and not self.can_sell(ts_code, price, limit_up or float('inf'), limit_down):
            return False
        
        amount, commission, stamp_duty, slippage = self.calculate_order_cost(price, sell_quantity, False)
        total_proceeds = amount - commission - stamp_duty - slippage
        
        self.cash += total_proceeds
        self.total_commission += commission
        self.total_stamp_duty += stamp_duty
        self.total_slippage += slippage
        
        realized = (price - pos.avg_cost) * sell_quantity - commission - stamp_duty - slippage
        self.realized_pnl += realized
        
        pos.quantity -= sell_quantity
        pos.available_quantity -= sell_quantity
        
        self.trade_counter += 1
        trade = Trade(
            trade_id=f"S{self.trade_counter:06d}",
            date=date,
            ts_code=ts_code,
            side=OrderSide.SELL,
            price=price,
            quantity=sell_quantity,
            amount=amount,
            commission=commission,
            stamp_duty=stamp_duty,
            slippage=slippage,
            total_cost=total_proceeds
        )
        self.trades[trade.trade_id] = trade
        
        if ts_code in self.pending_sell:
            self.pending_sell[ts_code] -= sell_quantity
        
        if pos.quantity == 0:
            del self.positions[ts_code]
        
        return True
    
    def update_pending_sell(self, ts_code: str, quantity: int):
        """更新T+1待卖出数量"""
        if ts_code in self.positions:
            if ts_code in self.pending_sell:
                self.pending_sell[ts_code] += quantity
            else:
                self.pending_sell[ts_code] = quantity
    
    def update_positions(self, price_data: pd.DataFrame, date: str):
        """更新持仓的当前价格和盈亏"""
        for ts_code, pos in self.positions.items():
            if ts_code in price_data.index:
                current_price = price_data.loc[ts_code, 'close']
                pos.last_price = current_price
                pos.market_value = pos.quantity * current_price
                pos.unrealized_pnl = (current_price - pos.avg_cost) * pos.quantity
    
    def calculate_total_value(self) -> Tuple[float, float]:
        """计算总市值"""
        position_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash, position_value
    
    def record_daily_equity(self, date: str, prev_total_value: Optional[float] = None):
        """记录每日权益"""
        cash, position_value = self.calculate_total_value()
        total_value = cash + position_value
        
        daily_return = 0.0
        if prev_total_value is not None and prev_total_value > 0:
            daily_return = (total_value - prev_total_value) / prev_total_value
        
        total_pnl = total_value - self.config.initial_capital
        
        equity = DailyEquity(
            date=date,
            cash=cash,
            total_value=total_value,
            position_value=position_value,
            total_pnl=total_pnl,
            daily_return=daily_return
        )
        self.daily_equity.append(equity)
        
        return total_value
    
    def run_backtest(self,
                    price_data: pd.DataFrame,
                    signals: pd.DataFrame,
                    benchmark_data: Optional[pd.DataFrame] = None,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None) -> BacktestResultV2:
        """
        运行回测
        
        Args:
            price_data: 价格数据，包含ts_code, date, open, high, low, close, pct_chg
            signals: 交易信号，包含ts_code, date, signal (1=买, -1=卖, 0=不操作)
            benchmark_data: 基准数据，用于对比
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            回测结果
        """
        self.reset()
        
        if 'trade_date' in price_data.columns:
            price_data = price_data.set_index('trade_date').sort_index()
        if 'trade_date' in signals.columns:
            signals = signals.set_index('trade_date').sort_index()
        
        dates = sorted(price_data.index.unique())
        if start_date:
            dates = [d for d in dates if d >= start_date]
        if end_date:
            dates = [d for d in dates if d <= end_date]
        
        prev_total_value = None
        
        for date in dates:
            if date not in signals.index:
                for ts_code in self.positions:
                    self.update_pending_sell(ts_code, self.positions[ts_code].quantity)
                continue
            
            day_signals = signals.loc[date]
            if isinstance(day_signals, pd.Series):
                day_signals = day_signals.to_frame().T
            
            for _, row in day_signals.iterrows():
                ts_code = row.get('ts_code', row.name)
                signal = row.get('signal', 0)
                
                if pd.isna(signal) or signal == 0:
                    continue
                
                if ts_code not in price_data.index.get_level_values(1) if isinstance(price_data.index, pd.MultiIndex) else ts_code not in price_data.index:
                    continue
                
                try:
                    if isinstance(price_data.index, pd.MultiIndex):
                        stock_data = price_data.xs(ts_code, level='ts_code')
                        if date not in stock_data.index:
                            continue
                        stock_day = stock_data.loc[date]
                    else:
                        stock_day = price_data.loc[date]
                        if isinstance(stock_day, pd.DataFrame):
                            stock_day = stock_day.iloc[0]
                    
                    close_price = stock_day['close']
                    limit_up = close_price * 1.1
                    limit_down = close_price * 0.9
                    
                    if signal > 0:
                        available_slots = self.config.max_position - len(self.positions)
                        if available_slots > 0 and ts_code not in self.positions:
                            buy_amount = self.cash / available_slots
                            buy_quantity = int(buy_amount / close_price / 100) * 100
                            if buy_quantity >= 100:
                                self.execute_buy(ts_code, str(date), close_price, 
                                               buy_quantity, limit_up, limit_down)
                    
                    elif signal < 0 and ts_code in self.positions:
                        pos = self.positions[ts_code]
                        self.execute_sell(ts_code, str(date), close_price,
                                        pos.available_quantity, limit_up, limit_down)
                
                except Exception:
                    continue
            
            for ts_code in self.positions:
                self.update_pending_sell(ts_code, self.positions[ts_code].quantity)
            
            self.update_positions(price_data, str(date))
            prev_total_value = self.calculate_total_value()[0] + self.calculate_total_value()[1]
            self.record_daily_equity(str(date), prev_total_value)
        
        result = BacktestResultV2(
            config=self.config,
            trades=list(self.trades.values()),
            daily_equity=self.daily_equity,
            positions=self.positions.copy(),
            metrics=self._calculate_metrics(),
            benchmark_metrics={}
        )
        
        if benchmark_data is not None and len(self.daily_equity) > 0:
            result.benchmark_metrics = self._calculate_benchmark_metrics(benchmark_data, dates)
        
        return result
    
    def _calculate_metrics(self) -> Dict:
        """计算回测指标"""
        if not self.daily_equity:
            return {}
        
        equity_df = pd.DataFrame([
            {
                'date': e.date,
                'total_value': e.total_value,
                'daily_return': e.daily_return,
                'total_pnl': e.total_pnl
            } for e in self.daily_equity
        ])
        
        if len(equity_df) < 2:
            return {}
        
        equity_df['cummax'] = equity_df['total_value'].cummax()
        equity_df['drawdown'] = (equity_df['cummax'] - equity_df['total_value']) / equity_df['cummax']
        
        total_value = self.config.initial_capital
        final_value = equity_df['total_value'].iloc[-1]
        total_return = (final_value - total_value) / total_value
        trading_days = len(equity_df)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 0 else 0
        
        daily_returns = equity_df['daily_return'].dropna()
        volatility = daily_returns.std() * np.sqrt(252)
        max_drawdown = equity_df['drawdown'].max()
        
        risk_free_rate = 0.03
        excess_returns = daily_returns - risk_free_rate / 252
        sharpe_ratio = np.sqrt(252) * excess_returns.mean() / (daily_returns.std() + 1e-10)
        
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-10
        sortino_ratio = np.sqrt(252) * excess_returns.mean() / downside_std
        
        win_days = (daily_returns > 0).sum()
        total_days = len(daily_returns)
        win_rate = win_days / total_days if total_days > 0 else 0
        
        wins = daily_returns[daily_returns > 0]
        losses = daily_returns[daily_returns < 0]
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-10
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        
        for ret in daily_returns:
            if ret > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            elif ret < 0:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
        
        return {
            'initial_capital': self.config.initial_capital,
            'final_value': final_value,
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'volatility': float(volatility),
            'max_drawdown': float(max_drawdown),
            'sharpe_ratio': float(sharpe_ratio),
            'sortino_ratio': float(sortino_ratio),
            'win_rate': float(win_rate),
            'profit_loss_ratio': float(profit_loss_ratio),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'max_consecutive_wins': int(max_consecutive_wins),
            'max_consecutive_losses': int(max_consecutive_losses),
            'total_trades': len(self.trades),
            'buy_trades': sum(1 for t in self.trades.values() if t.side == OrderSide.BUY),
            'sell_trades': sum(1 for t in self.trades.values() if t.side == OrderSide.SELL),
            'total_commission': self.total_commission,
            'total_stamp_duty': self.total_stamp_duty,
            'total_slippage': self.total_slippage,
            'realized_pnl': self.realized_pnl,
            'trading_days': trading_days
        }
    
    def _calculate_benchmark_metrics(self, benchmark_data: pd.DataFrame, 
                                    dates: List[str]) -> Dict:
        """计算基准对比指标"""
        if benchmark_data is None or len(benchmark_data) < 2:
            return {}
        
        if 'trade_date' in benchmark_data.columns:
            benchmark_data = benchmark_data.set_index('trade_date')
        
        aligned_dates = [d for d in dates if d in benchmark_data.index]
        if len(aligned_dates) < 2:
            return {}
        
        bm_values = benchmark_data.loc[aligned_dates, 'close']
        bm_initial = bm_values.iloc[0]
        bm_final = bm_values.iloc[-1]
        bm_return = (bm_final - bm_initial) / bm_initial
        
        my_return = 0.0
        if self.daily_equity:
            my_return = self.daily_equity[-1].total_value / self.config.initial_capital - 1
        
        excess_return = my_return - bm_return
        
        bm_returns = bm_values.pct_change().dropna()
        
        my_returns = pd.Series([e.daily_return for e in self.daily_equity], index=aligned_dates[:len(self.daily_equity)])
        aligned_returns = my_returns.reindex(bm_returns.index).dropna()
        aligned_bm_returns = bm_returns.reindex(my_returns.index).dropna()
        
        if len(aligned_returns) > 1 and len(aligned_bm_returns) > 1:
            combined = pd.concat([aligned_returns, aligned_bm_returns], axis=1).dropna()
            if len(combined) > 1:
                cov = combined.cov()
                if cov.shape[0] == 2:
                    beta = cov.iloc[0, 1] / (cov.iloc[1, 1] + 1e-10)
                else:
                    beta = 1.0
            else:
                beta = 1.0
            
            tracking_error = (aligned_returns - aligned_bm_returns).std() * np.sqrt(252)
            information_ratio = excess_return / (tracking_error + 1e-10) if tracking_error > 0 else 0
        else:
            beta = 1.0
            tracking_error = 0.0
            information_ratio = 0.0
        
        return {
            'benchmark_return': float(bm_return),
            'excess_return': float(excess_return),
            'beta': float(beta),
            'tracking_error': float(tracking_error),
            'information_ratio': float(information_ratio)
        }


def create_default_engine() -> AShareBacktestEngine:
    """创建默认配置的引擎"""
    config = BacktestConfig(
        initial_capital=100000.0,
        commission_rate=0.0003,
        stamp_duty_rate=0.001,
        slippage_rate=0.0001,
        min_commission=5.0,
        max_position=10,
        price_limit_check=True
    )
    return AShareBacktestEngine(config)
