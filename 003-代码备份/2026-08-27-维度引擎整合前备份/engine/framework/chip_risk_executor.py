"""
止损止盈执行层 - Phase 3 模块8
对应书本第7章§7.2-7.3

功能：
  止损：
    8.1 硬止损(8%) — 书本§7.2.1
    8.2 跟踪止损(回撤15%) — 书本§7.2.2
    8.3 时间止损(20交易日) — 书本§7.2.4

  止盈：
    8.4 筹码止盈(低位峰<10%) — 书本§7.3.1
    8.5 RSI止盈(>=85持续3日) — 书本§7.3.2
    8.6 放量滞涨止盈 — 书本§7.3.3
    8.7 移动止盈(回撤10%) — 书本§7.3.4
"""
from typing import Dict, List, Optional
import numpy as np


class ChipRiskExecutor:
    """止损止盈执行引擎"""

    def __init__(self):
        # 持仓状态跟踪
        self.entry_prices: Dict[str, float] = {}
        self.entry_dates: Dict[str, int] = {}
        self.peak_prices: Dict[str, float] = {}
        self.rsi_high_count: Dict[str, int] = {}
        self.holding_days: Dict[str, int] = {}

    def reset(self, symbol: str):
        """清空单只股票的跟踪状态"""
        self.entry_prices.pop(symbol, None)
        self.entry_dates.pop(symbol, None)
        self.peak_prices.pop(symbol, None)
        self.rsi_high_count.pop(symbol, None)
        self.holding_days.pop(symbol, None)

    def set_entry(self, symbol: str, price: float, date_idx: int = 0):
        """记录入场信息"""
        self.entry_prices[symbol] = price
        self.entry_dates[symbol] = date_idx
        self.peak_prices[symbol] = price
        self.rsi_high_count[symbol] = 0
        self.holding_days[symbol] = 0

    # ==================== 风险检查入口 ====================

    def execute_stop_loss(
        self,
        symbol: str,
        current_price: float,
        date_idx: int = 0,
    ) -> List[Dict]:
        """
        对所有持仓执行止损检查

        Args:
            symbol: 股票代码
            current_price: 当前价格
            date_idx: 当前交易日索引（用于计算持仓天数）

        Returns:
            止损动作列表，每个元素 {'action': str, 'reason': str}
        """
        actions = []
        entry_price = self.entry_prices.get(symbol)
        if entry_price is None or entry_price <= 0:
            return actions

        # 更新持仓天数
        if date_idx > 0 and symbol in self.entry_dates:
            self.holding_days[symbol] = date_idx - self.entry_dates[symbol]

        # 更新最高价
        peak = self.peak_prices.get(symbol, entry_price)
        if current_price > peak:
            self.peak_prices[symbol] = current_price
            peak = current_price

        # --- 8.1 硬止损（书本第7章§7.2.1）---
        if current_price < entry_price * 0.92:
            actions.append({
                'action': 'SELL_ALL',
                'reason': "硬止损(8%): 入场价{:.2f} 当前{:.2f}".format(entry_price, current_price)
            })
            self.reset(symbol)
            return actions  # 硬止损优先，不再检查其他

        # --- 8.2 跟踪止损（书本第7章§7.2.2）---
        if peak > entry_price:
            drawdown = (peak - current_price) / peak
            if drawdown > 0.15:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "跟踪止损(回撤{:.1f}%>15%): 最高{:.2f} 当前{:.2f}".format(
                        drawdown * 100, peak, current_price)
                })

        # --- 8.3 时间止损（书本第7章§7.2.4）---
        holding = self.holding_days.get(symbol, 0)
        if holding >= 20 and current_price <= entry_price * 1.01:
            actions.append({
                'action': 'SELL_50',
                'reason': "时间止损({}日未盈利): 入场价{:.2f} 当前{:.2f}".format(
                    holding, entry_price, current_price)
            })

        return actions

    def check_take_profit(
        self,
        symbol: str,
        current_price: float,
        indicators: Dict,
        chip_bins: Optional[List[Dict]] = None,
        rsi: Optional[float] = None,
    ) -> List[Dict]:
        """
        止盈检查

        Args:
            symbol: 股票代码
            current_price: 当前价格
            indicators: 筹码指标字典
            chip_bins: 筹码分布数据（用于筹码止盈）
            rsi: RSI值

        Returns:
            止盈动作列表
        """
        actions = []
        entry_price = self.entry_prices.get(symbol)
        if entry_price is None:
            return actions

        peak = self.peak_prices.get(symbol, current_price)

        # --- 8.4 筹码止盈（书本第7章§7.3.1）---
        if chip_bins is not None:
            chip_action = self._chip_take_profit(symbol, chip_bins, entry_price)
            if chip_action:
                actions.append(chip_action)

        # --- 8.5 RSI止盈（书本第7章§7.3.2）---
        rsi_val = rsi or indicators.get('rsi', 50)
        if rsi_val >= 85:
            count = self.rsi_high_count.get(symbol, 0) + 1
            self.rsi_high_count[symbol] = count
            if count >= 3:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "RSI止盈(>=85持续{}日)".format(count)
                })
        else:
            self.rsi_high_count[symbol] = 0

        # --- 8.6 放量滞涨止盈（书本第7章§7.3.3）---
        vol_ratio = indicators.get('vol_ratio', 0)
        recent_return = indicators.get('recent_return', 0)
        # 如果indicators中没有recent_return，从价格位置推算
        if recent_return == 0:
            recent_return = abs(indicators.get('pct_chg', 0)) if 'pct_chg' in indicators else 0

        if vol_ratio >= 2.0 and recent_return < 0.005:
            actions.append({
                'action': 'SELL_30',
                'reason': "放量滞涨止盈: 量比{:.2f} 涨幅{:.3f}".format(vol_ratio, recent_return)
            })

        # --- 8.7 移动止盈（书本第7章§7.3.4）---
        if peak > entry_price * 1.05:
            drawdown = (peak - current_price) / peak
            if drawdown > 0.10:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "移动止盈(回撤{:.1f}%>10%): 最高{:.2f} 当前{:.2f}".format(
                        drawdown * 100, peak, current_price)
                })

        return actions

    # ==================== 子方法 ====================

    def _chip_take_profit(self, symbol: str, chip_bins: List[Dict],
                          entry_price: float) -> Optional[Dict]:
        """
        筹码止盈检查（书本第7章§7.3.1）

        条件：低位筹码峰消失（底部30%价格区间筹码比例<10%）
        -> 说明主力已完成出货，减仓70%
        """
        if not chip_bins:
            return None

        prices = [b['price_bin'] for b in chip_bins]
        if not prices:
            return None

        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        if price_range <= 0:
            return None

        # 底部30%区间
        low_threshold = min_price + price_range * 0.3
        low_chips = sum(
            b['chip_ratio'] for b in chip_bins
            if b['price_bin'] <= low_threshold
        )

        if low_chips < 0.10:
            return {
                'action': 'SELL_70',
                'reason': "筹码止盈: 低位筹码仅{:.1f}%<10%(主力出货)".format(low_chips * 100)
            }

        return None

    # ==================== 批量检查 ====================

    def execute_batch(
        self,
        portfolio: Dict[str, Dict],
        current_prices: Dict[str, float],
        indicators_map: Dict[str, Dict],
        date_idx: int = 0,
    ) -> Dict[str, List[Dict]]:
        """
        对全部持仓批量执行止损止盈检查

        Args:
            portfolio: 持仓字典 {symbol: {'entry_price': float, 'position': float, ...}}
            current_prices: 当前价格 {symbol: price}
            indicators_map: 筹码指标 {symbol: indicators_dict}
            date_idx: 当前交易日索引

        Returns:
            {symbol: [action, ...]}
        """
        results = {}

        for symbol, pos_info in portfolio.items():
            entry_price = pos_info.get('entry_price', 0)
            current_price = current_prices.get(symbol, 0)
            indicators = indicators_map.get(symbol, {})

            if entry_price <= 0 or current_price <= 0:
                continue

            # 如果还未记录入场，则记录
            if symbol not in self.entry_prices:
                self.set_entry(symbol, entry_price, date_idx)
            else:
                self.entry_prices[symbol] = entry_price

            actions = []

            # 止损
            stop_actions = self.execute_stop_loss(symbol, current_price, date_idx)
            actions.extend(stop_actions)

            # 止盈（如果没有触发止损）
            if not stop_actions or all(a.get('action') != 'SELL_ALL' for a in stop_actions):
                profit_actions = self.check_take_profit(
                    symbol, current_price, indicators,
                    chip_bins=pos_info.get('chip_bins')
                )
                actions.extend(profit_actions)

            if actions:
                results[symbol] = actions

        return results
