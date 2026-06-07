"""
七维复盘引擎 — P3.3

七维评估模型：
  1. 大盘环境评估 (15%)
  2. 板块与题材分析 (15%)
  3. 个股操作评估 (20%)
  4. 策略执行评估 (20%)
  5. 资金管理评估 (15%)
  6. 心态与纪律复盘 (15%)
  7. 综合归因与改进
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, timedelta
from decimal import Decimal

from app import db
from app.models.trade import Trade
from app.models.strategy import StrategyOutput
from app.models.verification import SignalRecord

logger = logging.getLogger(__name__)


class ReviewEngine:
    """七维复盘引擎"""

    # 各维度权重（总和 = 1.0）
    WEIGHTS = {
        'market': 0.15,
        'sector': 0.15,
        'trade': 0.20,
        'strategy': 0.20,
        'capital': 0.15,
        'psychology': 0.15,
    }

    # ── 入口 ──

    def run_review(self, trades: List[Trade],
                   start_date: date, end_date: date) -> Dict:
        """
        执行完整七维复盘

        Args:
            trades: 复盘周期内的交易记录
            start_date/end_date: 复盘周期

        Returns:
            review report dict
        """
        if not trades:
            return {'total_score': 0, 'error': '无交易数据'}

        dimensions = {}

        dimensions['market'] = self.eval_market(start_date, end_date)
        dimensions['sector'] = self.eval_sector(trades, start_date, end_date)
        dimensions['trade'] = self.eval_trade_ops(trades)
        dimensions['strategy'] = self.eval_strategy_exec(trades)
        dimensions['capital'] = self.eval_capital_mgmt(trades)
        dimensions['psychology'] = self.eval_psychology(trades)

        # 综合评分
        total = 0.0
        for key, dim in dimensions.items():
            weight = self.WEIGHTS.get(key, 0.15)
            total += dim.get('score', 0) * weight
        total = round(min(total, 100), 1)

        # 归因分析
        attribution = self._calc_attribution(trades)

        # 改进建议
        improvements = self._generate_improvements(dimensions, trades)

        return {
            'total_score': total,
            'dimensions': dimensions,
            'attribution': attribution,
            'improvements': improvements,
            'period': {
                'start': start_date.isoformat() if hasattr(start_date, 'isoformat') else str(start_date),
                'end': end_date.isoformat() if hasattr(end_date, 'isoformat') else str(end_date),
            },
        }

    # ── 维度 1: 大盘环境评估 ──

    def eval_market(self, start_date: date, end_date: date) -> Dict:
        """
        评估复盘周期内的大盘环境
        TODO: 对接 market_service 获取真实指数数据
        """
        score = 75.0  # 默认中位数
        signals = []

        # 从 SignalRecord 中提取大盘相关信号（如果存在市场状态标记）
        recent_records = SignalRecord.query.filter(
            SignalRecord.signal_date >= start_date,
            SignalRecord.signal_date <= end_date,
        ).limit(50).all()

        buy_signals = sum(1 for r in recent_records if r.signal_type in ('BULLISH', 'WATCH'))
        bear_signals = sum(1 for r in recent_records if r.signal_type == 'BEARISH')

        if buy_signals > bear_signals * 2:
            score = 85.0
            signals.append('本周期策略信号以看多为主')
        elif bear_signals > buy_signals * 2:
            score = 55.0
            signals.append('本周期策略信号以看空为主，环境偏弱')
        else:
            signals.append('本周期信号方向均衡，震荡格局')

        return {
            'score': round(score, 1),
            'details': signals,
            'buy_signals_count': buy_signals,
            'bear_signals_count': bear_signals,
            'assessment': '震荡偏多' if score >= 75 else '震荡偏空' if score < 60 else '震荡',
        }

    # ── 维度 2: 板块与题材分析 ──

    def eval_sector(self, trades: List[Trade],
                    start_date: date, end_date: date) -> Dict:
        """评估板块匹配度（从交易股票代码推导）"""
        if not trades:
            return {'score': 50.0, 'details': ['无交易数据'], 'stock_count': 0}

        codes = set(t.ts_code for t in trades)
        # TODO: 对接行业分类数据做真实板块分析
        stock_count = len(codes)
        diversity_score = min(stock_count * 10, 70)
        trade_freq = len(trades)
        freq_score = min(trade_freq * 2, 30)

        score = diversity_score + freq_score

        details = [
            f'涉及 {stock_count} 只股票, {len(trades)} 笔交易',
        ]
        if stock_count >= 3:
            details.append('✅ 持仓分散度合理')
        elif stock_count <= 1:
            details.append('⚠ 持仓过于集中，建议分散到 3 只以上')

        return {
            'score': round(min(score, 100), 1),
            'details': details,
            'stock_count': stock_count,
            'trade_count': len(trades),
        }

    # ── 维度 3: 个股操作评估 ──

    def eval_trade_ops(self, trades: List[Trade]) -> Dict:
        """评估每笔买卖操作的合理性"""
        if not trades:
            return {'score': 50.0, 'details': ['无交易数据'], 'trade_reviews': []}

        trade_reviews = []
        total_score = 0.0

        for t in trades:
            review = self._review_single_trade(t)
            trade_reviews.append(review)
            total_score += review.get('score', 50)

        avg_score = total_score / len(trades)

        # 按股票分组统计
        stock_pnl = {}
        for t in trades:
            code = t.ts_code
            if code not in stock_pnl:
                stock_pnl[code] = {'name': t.stock_name or '', 'buys': [], 'sells': []}
            if t.direction == '买入':
                stock_pnl[code]['buys'].append(float(t.price))
            else:
                stock_pnl[code]['sells'].append(float(t.price))

        details = []
        for code, data in stock_pnl.items():
            if data['sells'] and data['buys']:
                avg_buy = sum(data['buys']) / len(data['buys'])
                avg_sell = sum(data['sells']) / len(data['sells'])
                pnl_pct = (avg_sell - avg_buy) / avg_buy * 100
                details.append(f"{data['name'] or code}: 平均买入{avg_buy:.2f}, 卖出{avg_sell:.2f} ({pnl_pct:+.2f}%)")

        summary = f'个股操作评分: {avg_score:.1f}/100, {len(trades)}笔交易'
        details.insert(0, summary)

        return {
            'score': round(avg_score, 1),
            'details': details,
            'trade_reviews': trade_reviews,
        }

    def _review_single_trade(self, trade: Trade) -> Dict:
        """单笔交易评分"""
        score = 60.0

        # 信号匹配加分
        if trade.matched_signal_id:
            score += 15
        if trade.match_score and float(trade.match_score) > 70:
            score += 10

        # 买入价合理性（参考价格范围）
        if trade.direction == '买入':
            score += 5

        return {
            'trade_id': trade.id,
            'ts_code': trade.ts_code,
            'direction': trade.direction,
            'price': float(trade.price) if trade.price else None,
            'quantity': trade.quantity,
            'date': trade.trade_date.isoformat() if trade.trade_date else '',
            'score': round(min(score, 100), 1),
            'has_signal_match': bool(trade.matched_signal_id),
        }

    # ── 维度 4: 策略执行评估 ──

    def eval_strategy_exec(self, trades: List[Trade]) -> Dict:
        """评估策略执行合规性和信号执行率"""
        if not trades:
            return {'score': 50.0, 'details': ['无交易数据'],
                    'compliance_rate': 0.0, 'signal_exec_rate': 0.0}

        matched = sum(1 for t in trades if t.matched_signal_id)
        unmatched = len(trades) - matched
        compliance_rate = matched / max(len(trades), 1)

        # 信号执行率：系统发出信号的数量 vs 被执行的信号数量
        all_signals = StrategyOutput.query.filter(
            StrategyOutput.signal_date >= (min(t.trade_date for t in trades) if trades else date.today()),
            StrategyOutput.signal_date <= (max(t.trade_date for t in trades) if trades else date.today()),
        ).count()
        signal_exec_rate = matched / max(all_signals, 1) if all_signals > 0 else 0.5

        score = compliance_rate * 50 + signal_exec_rate * 30 + 20
        if unmatched == 0:
            score = min(score + 10, 100)

        details = [
            f'策略合规率: {compliance_rate:.0%} ({matched}/{len(trades)})',
            f'信号执行率: {signal_exec_rate:.0%} ({matched}/{max(all_signals, 1)})',
            f'偏差交易: {unmatched}笔',
        ]
        if unmatched > 0:
            details.append('⚠ 存在无信号交易')
        if compliance_rate >= 0.8:
            details.append('✅ 策略遵守良好')

        return {
            'score': round(min(score, 100), 1),
            'details': details,
            'compliance_rate': round(compliance_rate, 4),
            'signal_exec_rate': round(signal_exec_rate, 4),
            'matched_count': matched,
            'unmatched_count': unmatched,
        }

    # ── 维度 5: 资金管理评估 ──

    def eval_capital_mgmt(self, trades: List[Trade]) -> Dict:
        """评估仓位控制、风险敞口"""
        if not trades:
            return {'score': 50.0, 'details': ['无交易数据']}

        # 分析单笔风险敞口
        total_amount = sum(float(t.amount) for t in trades)
        buy_trades = [t for t in trades if t.direction == '买入']
        sell_trades = [t for t in trades if t.direction == '卖出']

        max_single_risk = 0.0
        if buy_trades:
            max_amount = max(float(t.amount) for t in buy_trades)
            max_single_risk = max_amount / max(total_amount, 1) * 100 if total_amount else 0

        # 集中度（重复买入同一股票的占比）
        code_amounts = {}
        for t in buy_trades:
            code_amounts[t.ts_code] = code_amounts.get(t.ts_code, 0) + float(t.amount)
        top_concentration = 0
        if code_amounts:
            top_code = max(code_amounts, key=code_amounts.get)
            top_concentration = code_amounts[top_code] / max(sum(code_amounts.values()), 1) * 100

        # 评分
        score = 70.0
        alerts = []

        if max_single_risk > 10:
            score -= 15
            alerts.append(f'⚠ 单笔最大风险敞口 {max_single_risk:.1f}% (建议≤10%)')
        elif max_single_risk > 5:
            score -= 5
            alerts.append(f'ℹ 单笔风险敞口 {max_single_risk:.1f}%')

        if top_concentration > 40:
            score -= 10
            alerts.append(f'⚠ 持仓集中度 {top_concentration:.0f}% (建议≤30%)')
        elif top_concentration > 30:
            score -= 5

        total_buy = sum(float(t.amount) for t in buy_trades)
        total_sell = sum(float(t.amount) for t in sell_trades)
        net_investment = total_buy - total_sell
        if net_investment > 0 and len(buy_trades) > 5:
            score = max(score - 5, 20)

        details = alerts if alerts else ['✅ 资金管理合理']
        details.insert(0, f'总投入: {total_buy:.0f} | 总收回: {total_sell:.0f}')

        return {
            'score': round(max(min(score, 100), 20), 1),
            'details': details,
            'max_single_risk_pct': round(max_single_risk, 1),
            'top_concentration_pct': round(top_concentration, 1),
        }

    # ── 维度 6: 心态与纪律复盘 ──

    def eval_psychology(self, trades: List[Trade]) -> Dict:
        """识别情绪化交易、纪律性问题"""
        if len(trades) < 2:
            return {'score': 80.0, 'details': ['交易样本不足，暂无法评估心态']}

        score = 85.0  # 基准分
        issues = []

        # 1. 追涨杀跌检测
        sorted_trades = sorted(trades, key=lambda t: t.trade_date)
        for i in range(1, len(sorted_trades)):
            prev = sorted_trades[i - 1]
            curr = sorted_trades[i]
            if curr.direction == '买入' and prev.direction == '卖出':
                # 卖出后又追高买入
                sell_price = float(prev.price) if prev.price else 0
                buy_price = float(curr.price) if curr.price else 0
                if buy_price > sell_price * 1.03:  # 追高超过3%
                    issues.append(f'追涨: {curr.ts_code} 卖出后高价买回 ({sell_price:.2f}→{buy_price:.2f})')
                    score -= 8

        # 2. 频繁交易检测
        if len(trades) >= 3:
            day_counts = {}
            for t in trades:
                d = t.trade_date.isoformat() if t.trade_date else ''
                day_counts[d] = day_counts.get(d, 0) + 1
            busy_days = {d: c for d, c in day_counts.items() if c >= 3}
            if busy_days:
                issues.append(f'频繁交易: {len(busy_days)}天单日≥3笔')
                score -= 5

        # 3. 止损纪律
        sell_at_loss = []
        for t in trades:
            if t.direction == '卖出':
                buy_price = Trade.query.filter(
                    Trade.ts_code == t.ts_code,
                    Trade.direction == '买入',
                    Trade.trade_date <= t.trade_date,
                ).order_by(Trade.trade_date.desc()).first()
                if buy_price and buy_price.price:
                    sell_p = float(t.price) if t.price else 0
                    buy_p = float(buy_price.price) if buy_price.price else 1
                    if sell_p < buy_p * 0.95:  # 亏损超过5%
                        sell_at_loss.append(f'止损: {t.ts_code} 买入{buy_p:.2f}→卖出{sell_p:.2f}')
        if sell_at_loss:
            score -= 10
            issues.extend(sell_at_loss[:3])

        details = issues if issues else ['✅ 纪律执行良好，无重大违规']
        details.insert(0, f'总交易 {len(trades)} 笔')

        return {
            'score': round(max(score, 30), 1),
            'details': details,
            'issues_count': len(issues),
        }

    # ── 维度 7: 归因与改进 ──

    def _calc_attribution(self, trades: List[Trade]) -> Dict:
        """盈亏归因分析"""
        if not trades:
            return {'winners': [], 'losers': [], 'summary': '无交易数据'}

        stock_pnl = {}
        for t in trades:
            code = t.ts_code
            if code not in stock_pnl:
                stock_pnl[code] = {'buys': [], 'sells': [], 'name': t.stock_name or code}
            if t.direction == '买入':
                stock_pnl[code]['buys'].append(float(t.price) * t.quantity)
            else:
                stock_pnl[code]['sells'].append(float(t.price) * t.quantity)

        results = []
        for code, data in stock_pnl.items():
            total_buy = sum(data['buys'])
            total_sell = sum(data['sells'])
            pnl = total_sell - total_buy
            results.append({
                'ts_code': code,
                'name': data['name'],
                'pnl': round(pnl, 2),
                'total_buy': round(total_buy, 2),
                'total_sell': round(total_sell, 2),
            })

        winners = sorted([r for r in results if r['pnl'] > 0], key=lambda x: x['pnl'], reverse=True)
        losers = sorted([r for r in results if r['pnl'] <= 0], key=lambda x: x['pnl'])

        total_pnl = sum(r['pnl'] for r in results)
        winner_pnl = sum(r['pnl'] for r in winners)
        loser_pnl = sum(r['pnl'] for r in losers)

        return {
            'winners': winners,
            'losers': losers,
            'total_pnl': round(total_pnl, 2),
            'winner_pnl': round(winner_pnl, 2),
            'loser_pnl': round(loser_pnl, 2),
            'stock_count': len(results),
            'summary': f'盈利{len(winners)}只, 亏损{len(losers)}只, 净盈亏{total_pnl:.0f}',
        }

    def _generate_improvements(self, dimensions: Dict,
                               trades: List[Trade]) -> List[Dict]:
        """生成改进建议"""
        suggestions = []

        # 个股操作改进
        trade_dim = dimensions.get('trade', {})
        if trade_dim.get('score', 100) < 70:
            trade_reviews = trade_dim.get('trade_reviews', [])
            for r in trade_reviews[:3]:
                if r.get('score', 100) < 60 and not r.get('has_signal_match'):
                    suggestions.append({
                        'priority': 'HIGH',
                        'category': '个股操作',
                        'suggestion': f"{r['ts_code']} (ID:{r['trade_id']}) 无信号交易, 建议遵循策略信号",
                    })

        # 策略执行改进
        strat_dim = dimensions.get('strategy', {})
        if strat_dim.get('unmatched_count', 0) > 0:
            suggestions.append({
                'priority': 'HIGH',
                'category': '策略执行',
                'suggestion': f"存在 {strat_dim['unmatched_count']} 笔无信号交易, 建议减少「非策略」操作",
            })

        # 风控改进
        cap_dim = dimensions.get('capital', {})
        if cap_dim.get('max_single_risk_pct', 0) > 10:
            suggestions.append({
                'priority': 'MEDIUM',
                'category': '资金管理',
                'suggestion': f"单笔风险敞口 {cap_dim['max_single_risk_pct']:.1f}% 偏高, 建议压缩到 5% 以内",
            })
        if cap_dim.get('top_concentration_pct', 0) > 40:
            suggestions.append({
                'priority': 'MEDIUM',
                'category': '资金管理',
                'suggestion': f"持仓集中度 {cap_dim['top_concentration_pct']:.0f}% 偏高, 建议行业分散",
            })

        # 心态改进
        psy_dim = dimensions.get('psychology', {})
        for detail in psy_dim.get('details', []):
            if '追涨' in detail:
                suggestions.append({
                    'priority': 'LOW',
                    'category': '心态纪律',
                    'suggestion': '存在追涨行为, 建议采用分批建仓策略',
                })
                break

        if not suggestions:
            suggestions.append({
                'priority': 'INFO',
                'category': '综合',
                'suggestion': '当前周期表现良好, 继续保持',
            })

        return suggestions
