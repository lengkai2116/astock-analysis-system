"""最小回测框架 — 支撑387号方案调优验证（P0前置依赖）

核心能力：
1. 单只股票回测：逐日运行StatusEngine.evaluate()，产出opportunity_state序列
2. 批量回测：全市场统计
3. 参数扫描：对比不同参数下的回测结果
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


class MinimalBacktester:
    """最小回测框架"""

    def __init__(self, dm=None):
        if dm is None:
            from app.data import DataManager
            dm = DataManager()
        self.dm = dm

    def run(self, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
        """单只股票回测

        Args:
            ts_code: 股票代码
            start_date: 起始日期（YYYY-MM-DD），默认1年前
            end_date: 结束日期（YYYY-MM-DD），默认今天

        Returns:
            {
                'ts_code': str,
                'total_days': int,
                'states': [{'date': str, 'state': str, 'consensus_rate': float, 'direction': str}],
                'summary': {
                    'enter_count': int, 'light_count': int, 'wait_count': int, 'avoid_count': int,
                    'win_rate': float, 'avg_consensus': float,
                }
            }
        """
        if not start_date:
            from datetime import timedelta
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')

        from app.opportunity_atlas.status_engine import StatusEngine
        engine = StatusEngine(dm=self.dm)

        # 获取日线数据
        df = self.dm.get_cached_daily_data(ts_code)
        if df is None or df.empty:
            return {'ts_code': ts_code, 'total_days': 0, 'states': [], 'summary': {}}

        # 筛选日期范围
        if 'trade_date' in df.columns:
            mask = (df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)
            df = df[mask]

        # 预计算每日收益率（用于胜率/盈亏比/最大回撤/夏普）
        close_col = 'close' if 'close' in df.columns else None
        daily_returns = {}
        if close_col:
            prices = df.set_index('trade_date')[close_col].to_dict()
            sorted_dates = sorted(prices.keys())
            for i in range(1, len(sorted_dates)):
                prev = prices[sorted_dates[i - 1]]
                if prev and prev > 0:
                    daily_returns[str(sorted_dates[i])[:10]] = (prices[sorted_dates[i]] - prev) / prev

        states = []
        for _, row in df.iterrows():
            trade_date = str(row.get('trade_date', ''))[:10]
            if not trade_date:
                continue
            try:
                result = engine.evaluate(ts_code)
                if result:
                    states.append({
                        'date': trade_date,
                        'state': result.get('opportunity_state', 'wait'),
                        'consensus_rate': result.get('consensus_rate', 0),
                        'direction': result.get('direction', 'neutral'),
                    })
            except Exception as e:
                logger.debug(f"回测{ts_code}@{trade_date}失败: {e}")

        # 统计
        state_counts = {'enter': 0, 'light': 0, 'wait': 0, 'avoid': 0}
        total_consensus = 0.0
        for s in states:
            st = s['state']
            if st in state_counts:
                state_counts[st] += 1
            total_consensus += s.get('consensus_rate', 0)

        total = len(states)
        avg_consensus = total_consensus / total if total > 0 else 0

        # 387号§P0：胜率/盈亏比/最大回撤/夏普比率
        forward_days = 5  # 未来5日收益
        trade_returns = []
        state_dates = [s['date'] for s in states]
        close_prices = df.set_index('trade_date')['close'].to_dict() if close_col else {}

        for i, s in enumerate(states):
            if s['state'] != 'enter':
                continue
            entry_date = s['date']
            # 找entry_date之后第forward_days个交易日
            future_dates = [d for d in state_dates if d > entry_date][:forward_days]
            if not future_dates:
                continue
            exit_date = future_dates[-1]
            entry_price = close_prices.get(entry_date)
            exit_price = close_prices.get(exit_date)
            if entry_price and exit_price and entry_price > 0:
                ret = (exit_price - entry_price) / entry_price
                trade_returns.append(ret)

        # 胜率
        wins = sum(1 for r in trade_returns if r > 0)
        total_trades = len(trade_returns)
        win_rate = round(wins / total_trades, 4) if total_trades > 0 else 0.0

        # 盈亏比（平均盈利/平均亏损的绝对值）
        profit_trades = [r for r in trade_returns if r > 0]
        loss_trades = [r for r in trade_returns if r <= 0]
        avg_profit = sum(profit_trades) / len(profit_trades) if profit_trades else 0
        avg_loss = abs(sum(loss_trades) / len(loss_trades)) if loss_trades else 0
        profit_factor = round(avg_profit / avg_loss, 4) if avg_loss > 0 else 0.0

        # 最大回撤（基于equity curve）
        equity = [1.0]
        for r in (daily_returns.get(s['date'], 0) for s in states):
            equity.append(equity[-1] * (1 + r))
        peak = equity[0]
        max_drawdown = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # 夏普比率（年化，假设无风险利率3%）
        ret_list = [daily_returns.get(s['date'], 0) for s in states if s['date'] in daily_returns]
        if len(ret_list) > 1:
            import statistics
            mean_ret = statistics.mean(ret_list)
            std_ret = statistics.stdev(ret_list)
            sharpe = round((mean_ret * 252 - 0.03) / (std_ret * (252 ** 0.5)), 4) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            'ts_code': ts_code,
            'total_days': total,
            'states': states,
            'summary': {
                'enter_count': state_counts['enter'],
                'light_count': state_counts['light'],
                'wait_count': state_counts['wait'],
                'avoid_count': state_counts['avoid'],
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'max_drawdown': round(max_drawdown, 4),
                'sharpe_ratio': sharpe,
                'total_trades': total_trades,
                'avg_consensus': round(avg_consensus, 3),
            },
        }

    def batch_run(self, codes: List[str], start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
        """批量回测

        Returns:
            {
                'total_stocks': int,
                'state_distribution': {'enter': %, 'light': %, 'wait': %, 'avoid': %},
                'avg_consensus': float,
                'per_stock': {ts_code: summary_dict},
            }
        """
        results = {}
        state_totals = {'enter': 0, 'light': 0, 'wait': 0, 'avoid': 0}
        total_consensus = 0.0
        total_days = 0

        for code in codes:
            try:
                r = self.run(code, start_date, end_date)
                results[code] = r['summary']
                for st in state_totals:
                    state_totals[st] += r['summary'].get(f'{st}_count', 0)
                total_consensus += r['summary'].get('avg_consensus', 0) * r['total_days']
                total_days += r['total_days']
            except Exception as e:
                logger.debug(f"批量回测{code}失败: {e}")

        total_states = sum(state_totals.values())
        distribution = {}
        for st, count in state_totals.items():
            distribution[st] = round(count / total_states * 100, 1) if total_states > 0 else 0

        return {
            'total_stocks': len(results),
            'state_distribution': distribution,
            'avg_consensus': round(total_consensus / total_days, 3) if total_days > 0 else 0,
            'per_stock': results,
        }

    def param_stability_check(self, ts_code: str, param_name: str,
                               values: list, start_date: Optional[str] = None,
                               end_date: Optional[str] = None) -> dict:
        """387号5.9：参数稳定性验证（Walk-Forward简化版）

        对比不同参数值下的回测结果，计算变异系数（CV）判断稳定性。

        Args:
            param_name: 参数名（如'bearish_strong'）
            values: 参数值列表（如[0.60, 0.67, 0.75]）

        Returns:
            {'param_name': str, 'results': {value: summary_dict},
             'cv': float, 'stable': bool}
        """
        results = {}
        for val in values:
            # 简化：用当前系统回测，参数通过环境变量传递
            import os
            os.environ[f'JUD_PARAM_{param_name.upper()}'] = str(val)
            try:
                r = self.run(ts_code, start_date, end_date)
                results[val] = {
                    'enter_count': r['summary']['enter_count'],
                    'wait_count': r['summary']['wait_count'],
                    'avoid_count': r['summary']['avoid_count'],
                    'avg_consensus': r['summary']['avg_consensus'],
                }
            except Exception as e:
                results[val] = {'error': str(e)}
            finally:
                os.environ.pop(f'JUD_PARAM_{param_name.upper()}', None)

        # 计算变异系数（enter_count的CV）
        enter_counts = [r.get('enter_count', 0) for r in results.values() if 'error' not in r]
        if len(enter_counts) >= 2:
            mean = sum(enter_counts) / len(enter_counts)
            variance = sum((x - mean) ** 2 for x in enter_counts) / len(enter_counts)
            std = variance ** 0.5
            cv = round(std / mean, 3) if mean > 0 else 0
        else:
            cv = 0

        return {
            'param_name': param_name,
            'results': results,
            'cv': cv,
            'stable': cv < 0.30,  # CV<30%视为稳定
            'interpretation': '稳定' if cv < 0.30 else ('中等波动' if cv < 0.60 else '不稳定'),
        }
