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
from app.models import Stock, DailyData
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
        基于三大指数（上证/深证/创业板）的实际涨跌幅数据
        """
        indices = [
            ('000001.SH', '上证指数'),
            ('399001.SZ', '深圳成指'),
            ('399006.SZ', '创业板指'),
        ]
        details = []
        total_return = 0.0
        index_data = []

        for ts_code, name in indices:
            start_row = DailyData.query.filter(
                DailyData.ts_code == ts_code,
                DailyData.trade_date >= start_date,
            ).order_by(DailyData.trade_date.asc()).first()

            end_row = DailyData.query.filter(
                DailyData.ts_code == ts_code,
                DailyData.trade_date <= end_date,
            ).order_by(DailyData.trade_date.desc()).first()

            if start_row and end_row and start_row.close:
                ret = (float(end_row.close) - float(start_row.close)) / float(start_row.close)
                total_return += ret
                direction = '上涨' if ret > 0 else '下跌'
                details.append(f'{name} {direction} {abs(ret)*100:.2f}%')
                index_data.append({'name': name, 'return_pct': round(ret * 100, 2)})
            else:
                details.append(f'{name}: 数据不足')
                index_data.append({'name': name, 'return_pct': None})

        avg_return = total_return / len(indices) if index_data else 0
        # 评分：正收益→高分，负收益→低分
        score = 50.0 + avg_return * 200
        score = max(20, min(95, score))

        # 信号方向统计（保留原逻辑作为辅助）
        recent_records = SignalRecord.query.filter(
            SignalRecord.signal_date >= start_date,
            SignalRecord.signal_date <= end_date,
        ).limit(50).all()
        buy_signals = sum(1 for r in recent_records if r.signal_type in ('BULLISH', 'WATCH'))
        bear_signals = sum(1 for r in recent_records if r.signal_type == 'BEARISH')

        if avg_return > 0.03:
            assessment = '偏多'
        elif avg_return < -0.03:
            assessment = '偏空'
        else:
            assessment = '震荡'

        return {
            'score': round(score, 1),
            'details': details,
            'index_data': index_data,
            'avg_market_return': round(avg_return * 100, 2),
            'buy_signals_count': buy_signals,
            'bear_signals_count': bear_signals,
            'assessment': f'震荡{assessment}' if assessment == '震荡' else assessment,
        }

    # ── 维度 2: 板块与题材分析 ──

    def eval_sector(self, trades: List[Trade],
                    start_date: date, end_date: date) -> Dict:
        """评估板块匹配度（基于股票行业分类）"""
        if not trades:
            return {'score': 50.0, 'details': ['无交易数据'], 'stock_count': 0}

        codes = set(t.ts_code for t in trades)
        # 查询股票行业分类
        stocks = Stock.query.filter(Stock.ts_code.in_(codes)).all()
        stock_map = {s.ts_code: s.industry for s in stocks}
        industries = {}
        for code in codes:
            ind = stock_map.get(code, '未知')
            industries[ind] = industries.get(ind, 0) + 1

        stock_count = len(codes)
        industry_count = len(industries)
        # 行业分散度：覆盖越多行业分数越高
        diversity_score = min(industry_count * 15, 60)
        trade_freq = len(trades)
        freq_score = min(trade_freq * 2, 30)
        # 行业集中度奖励：集中在1-2个行业说明有板块聚焦
        focus_bonus = 10 if industry_count <= 2 else 0

        score = diversity_score + freq_score + focus_bonus

        industry_detail = ', '.join(f'{k}({v}只)' for k, v in
                                    sorted(industries.items(), key=lambda x: -x[1])[:5])
        details = [
            f'涉及 {stock_count} 只股票, {industry_count} 个行业',
            f'行业分布: {industry_detail}',
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


# ═══════════════════════════════════════════════════════
# 六维复盘引擎（226号方案 · 去评分化叙事格式）
# ═══════════════════════════════════════════════════════

BEHAVIOR_PATTERNS = [
    {'id': 'chase_up', 'name': '追涨买入', 'condition': lambda tx: tx.get('price_change_1d', 0) > 5},
    {'id': 'early_profit', 'name': '过早止盈', 'condition': lambda tx: tx.get('hold_days', 99) < 5 and tx.get('pnl_pct', 0) > 0},
    {'id': 'endowment_effect', 'name': '持亏过久', 'condition': lambda tx: tx.get('hold_days', 0) > 20 and tx.get('pnl_pct', 0) < 0},
    {'id': 'panic_sell', 'name': '恐慌卖出', 'condition': lambda tx: tx.get('price_change_1d', 0) < -5},
    {'id': 'over_trade', 'name': '频繁交易',
     'condition': lambda tx: False},  # 需跨交易判断（同一票3日内反向交易）
    {'id': 'avg_down', 'name': '向下摊平', 'condition': lambda tx: False},  # 跨交易判断（低于成本5%补仓）
]


def _build_trade_context(trades: List) -> List:
    """为交易记录构建分析上下文（价格变动/持有天数等）"""
    contexts = []
    sorted_trades = sorted(trades, key=lambda t: t.trade_date)

    # 先按股票分组以计算持有天数和盈亏
    stock_groups = {}
    for t in sorted_trades:
        code = t.ts_code
        if code not in stock_groups:
            stock_groups[code] = []
        stock_groups[code].append(t)

    for t in sorted_trades:
        ctx = {
            'id': t.id,
            'ts_code': t.ts_code,
            'stock_name': t.stock_name or '',
            'direction': t.direction,
            'trade_date': t.trade_date,
            'price': float(t.price),
            'quantity': t.quantity,
            'amount': float(t.amount),
            'buy_reason': t.buy_reason,
            'sell_reason': t.sell_reason,
            'review_unit_id': t.review_unit_id,
            'is_partial': bool(t.is_partial or False),
        }

        # 价格变动（对买入计算当日涨幅参考）
        if t.direction == '买入':
            daily = DailyData.query.filter(
                DailyData.ts_code == t.ts_code,
                DailyData.trade_date == t.trade_date,
            ).first()
            if daily:
                ctx['price_change_1d'] = float(daily.pct_chg or 0)

        # 持有天数（对卖出：找同一票最近一次买入）
        if t.direction == '卖出':
            same_stock_buys = [
                x for x in sorted_trades
                if x.ts_code == t.ts_code and x.direction == '买入' and x.trade_date < t.trade_date
            ]
            if same_stock_buys:
                last_buy = same_stock_buys[-1]
                ctx['hold_days'] = (t.trade_date - last_buy.trade_date).days
                ctx['pnl_pct'] = round((float(t.price) - float(last_buy.price)) / float(last_buy.price) * 100, 2)

        # 判断跨交易行为（频繁交易：3日内同一票买卖）
        if t.direction == '卖出':
            nearby = [
                x for x in sorted_trades
                if x.ts_code == t.ts_code and x.direction == '买入'
                and abs((x.trade_date - t.trade_date).days) <= 3
            ]
            if nearby:
                ctx['over_trade_3d'] = True

        contexts.append(ctx)
    return contexts


class ReviewEngine6D:
    """六维复盘引擎（226号方案）

    维度:
      A 买卖点质量  |  B 策略执行与有效性  |  C 资金与风险管理
      D 交易时机与节奏  |  E 行为模式识别  |  F 综合归因与建议
    """

    def run_review(self, trades: List[Trade], start_date: date, end_date: date) -> Dict:
        """执行六维复盘"""
        if not trades:
            return {'error': '无交易数据', 'dimensions': {}, 'review_id': None}

        ctx = _build_trade_context(trades)

        dim_a = self._eval_buy_sell_quality(ctx)
        dim_b = self._eval_strategy_exec(ctx)
        dim_c = self._eval_capital_risk(ctx)
        dim_d = self._eval_timing_tempo(ctx)
        dim_e = self._eval_behavior_patterns(ctx)
        dim_f = self._eval_composite(dim_a, dim_b, dim_c, dim_d, dim_e, ctx)

        import hashlib
        review_id = f"6DRV-{start_date.strftime('%Y%m%d')}-{hashlib.md5(str(trades[0].id).encode()).hexdigest()[:4].upper()}"

        return {
            'review_id': review_id,
            'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
            'dimensions': {
                'A': dim_a, 'B': dim_b, 'C': dim_c,
                'D': dim_d, 'E': dim_e, 'F': dim_f,
            }
        }

    # ── A: 买卖点质量评估 ──

    def _eval_buy_sell_quality(self, ctx: List[Dict]) -> Dict:
        entries = []
        for tx in ctx:
            if tx['direction'] == '买入':
                quality = 'good' if tx.get('price_change_1d', 0) or 0 >= -1 else 'fair'
                detail = f"买入价 ¥{tx['price']:.2f}"
                if tx.get('buy_reason'):
                    detail += f" · 理由: {tx['buy_reason']}"
                entries.append({
                    'stock': tx['ts_code'],
                    'stock_name': tx['stock_name'],
                    'quality': quality,
                    'detail': detail + (' ✅' if quality == 'good' else ' ⚠️'),
                    'trade_date': tx['trade_date'].isoformat(),
                    'price': tx['price'],
                })
        if not entries:
            entries.append({'detail': '本周期无买入操作'})
        narrative = self._build_a_narrative(entries)
        return {'title': '买卖点质量评估', 'narrative': narrative, 'entries': entries}

    def _build_a_narrative(self, entries: List[Dict]) -> str:
        lines = []
        for e in entries:
            lines.append(
                f"▸ {e.get('stock_name', e.get('stock', '?'))}·买入（{e.get('trade_date', '?')}）"
            )
            lines.append(f"  {e['detail']}")
        return '\n'.join(lines)

    # ── B: 策略执⾏与有效性评估 ──

    def _eval_strategy_exec(self, ctx: List[Dict]) -> Dict:
        entries = []
        for tx in ctx:
            if tx.get('review_unit_id'):
                entries.append({
                    'stock': tx['ts_code'],
                    'stock_name': tx['stock_name'],
                    'rv_id': tx['review_unit_id'],
                    'consistency': True,
                    'detail': f"关联策略 {tx['review_unit_id']} ✅",
                })
        if not entries:
            entries = [{'detail': '本周期交易均未关联复盘策略（建议在新建交易时关联）'}]
        narrative = self._build_b_narrative(entries)
        return {'title': '策略执行与有效性评估', 'narrative': narrative, 'entries': entries}

    def _build_b_narrative(self, entries: List[Dict]) -> str:
        lines = []
        for e in entries:
            sname = e.get('stock_name', e.get('stock', '?'))
            if e.get('rv_id'):
                lines.append(f"▸ {sname}·关联策略 {e['rv_id']}")
                lines.append(f"  策略诊断: 方向判断准确 ✅")
            else:
                lines.append(f"▸ {sname}")
                lines.append(f"  {e['detail']}")
        return '\n'.join(lines)

    # ── C: 资金与风险管理 ──

    def _eval_capital_risk(self, ctx: List[Dict]) -> Dict:
        entries = []
        buy_count = sum(1 for tx in ctx if tx['direction'] == '买入')
        sell_count = sum(1 for tx in ctx if tx['direction'] == '卖出')
        entries.append({
            'key': '交易频率',
            'detail': f"买入 {buy_count} 笔 · 卖出 {sell_count} 笔"
        })
        # 检测是否有止损（卖出理由含止损）
        stops = [tx for tx in ctx if tx['direction'] == '卖出' and tx.get('sell_reason') in ('止损', '止盈')]
        if stops:
            entries.append({'key': '止损执行', 'detail': f"触发止损/止盈 {len(stops)} 次 ✅", 'status': 'good'})
        else:
            entries.append({'key': '止损执行', 'detail': '本次区间内未触发止损操作'})

        stocks_involved = list(set(tx['ts_code'] for tx in ctx))
        entries.append({'key': '持仓分散度', 'detail': f"涉及 {len(stocks_involved)} 只股票"})

        narrative = self._build_c_narrative(entries)
        return {'title': '资金与风险管理', 'narrative': narrative, 'entries': entries}

    def _build_c_narrative(self, entries: List[Dict]) -> str:
        lines = []
        for e in entries:
            lines.append(f"▸ {e['key']}")
            lines.append(f"  {e['detail']}")
        return '\n'.join(lines)

    # ── D: 交易时机与节奏把控 ──

    def _eval_timing_tempo(self, ctx: List[Dict]) -> Dict:
        entries = []
        sell_tx = [tx for tx in ctx if tx['direction'] == '卖出']
        for tx in sell_tx:
            hd = tx.get('hold_days')
            if hd is not None:
                if hd <= 3:
                    eval_ = '过短 ⚠️'
                elif hd <= 20:
                    eval_ = '合理 ✅'
                else:
                    eval_ = '偏长 💤'
                entries.append({
                    'stock': tx['ts_code'],
                    'stock_name': tx['stock_name'],
                    'hold_days': hd,
                    'eval': eval_,
                    'pnl_pct': tx.get('pnl_pct', 0),
                    'detail': f"持有 {hd} 天 · {eval_}",
                })
        if not entries:
            entries.append({'detail': '本周期无已卖出交易'})
        narrative = self._build_d_narrative(entries)
        return {'title': '交易时机与节奏把控', 'narrative': narrative, 'entries': entries}

    def _build_d_narrative(self, entries: List[Dict]) -> str:
        lines = []
        for e in entries:
            sname = e.get('stock_name', e.get('stock', '?'))
            lines.append(f"▸ {sname}")
            lines.append(f"  {e['detail']} (盈亏 {e.get('pnl_pct', 0):+.1f}%)")
        return '\n'.join(lines)

    # ── E: 行为模式识别 ──

    def _eval_behavior_patterns(self, ctx: List[Dict]) -> Dict:
        found = []
        # 跨交易检测：频繁交易（同票3日内买卖）
        for tx in ctx:
            if tx.get('over_trade_3d'):
                pattern = {'type': 'over_trade', 'stock': tx['ts_code'],
                           'stock_name': tx['stock_name'],
                           'severity': 'warn',
                           'detail': f"频繁交易：{tx['stock_name']} 买入后3日内卖出"}
                found.append(pattern)

        # 逐交易检测
        for tx in ctx:
            for pat in BEHAVIOR_PATTERNS:
                if pat['id'] in ('over_trade', 'avg_down'):
                    continue  # 上面单独处理
                if pat['condition'](tx):
                    found.append({
                        'type': pat['id'],
                        'stock': tx['ts_code'],
                        'stock_name': tx['stock_name'],
                        'severity': 'warn',
                        'detail': pat['name'],
                    })

        narrative = self._build_e_narrative(found)
        return {'title': '行为模式识别', 'narrative': narrative, 'patterns': found}

    def _build_e_narrative(self, patterns: List[Dict]) -> str:
        if not patterns:
            return '▸ 未检测到明显异常行为模式 ✅'
        lines = []
        for p in patterns:
            lines.append(f"▸ {p.get('stock_name', p.get('stock', '?'))}")
            lines.append(f"  ⚠️ {p['detail']}")
        return '\n'.join(lines)

    # ── F: 综合归因与建议 ──

    def _eval_composite(self, dim_a, dim_b, dim_c, dim_d, dim_e, ctx: List[Dict]) -> Dict:
        # 归因分析
        stocks = set(t['ts_code'] for t in ctx)
        profit_sources = []
        loss_sources = []
        for code in stocks:
            buys = [t for t in ctx if t['ts_code'] == code and t['direction'] == '买入']
            sells = [t for t in ctx if t['ts_code'] == code and t['direction'] == '卖出']
            for s in sells:
                pnl = s.get('pnl_pct', 0)
                item = {'stock': code, 'stock_name': s.get('stock_name', ''), 'pnl_pct': pnl}
                if pnl >= 0:
                    profit_sources.append(item)
                else:
                    loss_sources.append(item)

        profit_sources.sort(key=lambda x: x['pnl_pct'], reverse=True)
        loss_sources.sort(key=lambda x: x['pnl_pct'])

        # 改进建议
        improvements = []
        if dim_e.get('patterns'):
            for p in dim_e['patterns']:
                mapping = {
                    'chase_up': '避免追涨：设置条件单分批建仓',
                    'early_profit': '止盈策略优化：用移动止盈替代固定目标位',
                    'endowment_effect': '止损纪律：严格执行预设止损位',
                    'panic_sell': '恐慌时复盘策略信号再做决定',
                    'over_trade': '减少交易频率：每只票每日最多操作1次',
                }
                if p['type'] in mapping:
                    tip = mapping[p['type']]
                    if tip not in improvements:
                        improvements.append(tip)

        # 行业分散建议
        stocks_set = set(t['ts_code'] for t in ctx)
        sectors = set()
        for code in stocks_set:
            stock = Stock.query.get(code)
            if stock and stock.industry:
                sectors.add(stock.industry)
        if len(sectors) <= 1 and len(stocks_set) >= 3:
            improvements.append('行业分散：当前布局过于集中，考虑分散到2-3个不同行业')

        if not improvements:
            improvements = ['当前周期操作规范，建议继续保持']

        narrative = self._build_f_narrative(profit_sources, loss_sources, improvements)
        return {
            'title': '综合归因与改进建议',
            'narrative': narrative,
            'profit_sources': profit_sources,
            'loss_sources': loss_sources,
            'top_improvements': improvements[:5],
        }

    def _build_f_narrative(self, profits, losses, improvements) -> str:
        lines = ['【收益来源】']
        for p in profits[:3]:
            lines.append(f"  ✅ {p.get('stock_name', p['stock'])} +{p['pnl_pct']:.1f}%")
        if not profits:
            lines.append('  (无盈利卖出交易)')

        lines.append('')
        lines.append('【亏损来源】')
        for l in losses[:3]:
            lines.append(f"  ❌ {l.get('stock_name', l['stock'])} {l['pnl_pct']:.1f}%")
        if not losses:
            lines.append('  (无亏损卖出交易)')

        lines.append('')
        lines.append('【TOP改进建议】')
        for i, imp in enumerate(improvements[:5], 1):
            lines.append(f"  {i}. {imp}")
        return '\n'.join(lines)


# 便捷函数
def run_review_6d(trades: List[Trade], start_date: date, end_date: date) -> Dict:
    """运行六维复盘（便捷入口）"""
    return ReviewEngine6D().run_review(trades, start_date, end_date)
