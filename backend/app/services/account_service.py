"""
账户管理服务 — P3.1

功能：
  1. 交易记录 CRUD
  2. 持仓计算（从交易记录推导）
  3. 账户总览指标（资产/盈亏/收益率）
  4. 资金曲线数据生成
  5. 绩效指标计算
  6. 虚拟验证复盘分区数据
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, timedelta, datetime
from decimal import Decimal
import numpy as np

from app import db
from app.models.trade import Trade, AccountSnapshot, AccountCashFlow
from app.models.verification import VirtualPosition
from app.models import DailyData

logger = logging.getLogger(__name__)


class AccountService:
    """账户管理服务"""

    # ── 交易记录 CRUD ──

    def create_trade(self, ts_code: str, stock_name: str, direction: str,
                     trade_date: date, price: float, quantity: int,
                     commission: float = 0.0, notes: str = "",
                     buy_reason: str = None, sell_reason: str = None,
                     review_unit_id: str = None, is_partial: bool = False,
                     stamp_tax: float = 0.0, transfer_fee: float = 0.0,
                     realized_pnl: float = None,
                     auto_calc_fee: bool = True) -> Optional[Trade]:
        """新增交易记录（226号方案扩展字段 + D9自动核算手续费）

        当 auto_calc_fee=True 且 各项费用都为0时，自动核算
        """
        try:
            if auto_calc_fee and commission == 0 and stamp_tax == 0 and transfer_fee == 0:
                fee = self.calc_trade_fee(price, quantity, direction)
                commission = fee['commission']
                stamp_tax = fee['stamp_tax']
                transfer_fee = fee['transfer_fee']
            trade = Trade(
                ts_code=ts_code,
                stock_name=stock_name or "",
                direction=direction,
                trade_date=trade_date,
                price=round(price, 2),
                quantity=quantity,
                amount=round(price * quantity, 2),
                commission=round(commission, 2),
                notes=notes,
                buy_reason=buy_reason,
                sell_reason=sell_reason,
                review_unit_id=review_unit_id,
                is_partial=is_partial,
                stamp_tax=round(stamp_tax, 2),
                transfer_fee=round(transfer_fee, 2),
                realized_pnl=round(realized_pnl, 2) if realized_pnl else None,
            )
            db.session.add(trade)
            db.session.commit()
            logger.info(f"新增交易: {ts_code} {direction} {quantity}@{price}")
            return trade
        except Exception as e:
            db.session.rollback()
            logger.warning(f"新增交易失败: {e}")
            return None

    def update_trade(self, trade_id: int, **kwargs) -> Optional[Trade]:
        """修改交易记录（含新字段）"""
        trade = Trade.query.get(trade_id)
        if not trade:
            return None
        try:
            for k, v in kwargs.items():
                if hasattr(trade, k) and v is not None:
                    setattr(trade, k, v)
            # 如果价格或数量变了，重新计算金额
            if 'price' in kwargs or 'quantity' in kwargs:
                p = kwargs.get('price', trade.price)
                q = kwargs.get('quantity', trade.quantity)
                trade.amount = round(float(p) * int(q), 2)
            db.session.commit()
            return trade
        except Exception as e:
            db.session.rollback()
            logger.warning(f"更新交易失败: {e}")
            return None

    def delete_trade(self, trade_id: int) -> bool:
        """删除交易记录"""
        trade = Trade.query.get(trade_id)
        if not trade:
            return False
        try:
            db.session.delete(trade)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logger.warning(f"删除交易失败: {e}")
            return False

    def get_trades(self, ts_code: Optional[str] = None,
                   start_date: Optional[date] = None,
                   end_date: Optional[date] = None,
                   direction: Optional[str] = None,
                   page: int = 1, per_page: int = 50) -> Tuple[List[Trade], int]:
        """获取交易记录列表（分页）"""
        q = Trade.query.order_by(Trade.trade_date.desc(), Trade.id.desc())
        if ts_code:
            q = q.filter(Trade.ts_code == ts_code)
        if start_date:
            q = q.filter(Trade.trade_date >= start_date)
        if end_date:
            q = q.filter(Trade.trade_date <= end_date)
        if direction:
            q = q.filter(Trade.direction == direction)
        total = q.count()
        trades = q.offset((page - 1) * per_page).limit(per_page).all()
        return trades, total

    def import_trades_batch(self, trades_data: List[Dict]) -> Tuple[int, int]:
        """批量导入交易记录，返回 (成功数, 失败数)"""
        ok = fail = 0
        for item in trades_data:
            try:
                t_date = item['trade_date']
                if isinstance(t_date, str):
                    t_date = datetime.strptime(t_date[:10], '%Y-%m-%d').date()
                t = self.create_trade(
                    ts_code=item['ts_code'],
                    stock_name=item.get('stock_name', ''),
                    direction=item['direction'],
                    trade_date=t_date,
                    price=float(item['price']),
                    quantity=int(item['quantity']),
                    commission=float(item.get('commission', 0)),
                    notes=item.get('notes', ''),
                    buy_reason=item.get('buy_reason'),
                    sell_reason=item.get('sell_reason'),
                    review_unit_id=item.get('review_unit_id'),
                    is_partial=item.get('is_partial', False),
                    stamp_tax=float(item.get('stamp_tax', 0)),
                    transfer_fee=float(item.get('transfer_fee', 0)),
                    realized_pnl=float(item['realized_pnl']) if item.get('realized_pnl') else None,
                )
                if t:
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                logger.warning(f"批量导入失败: {e}")
                fail += 1
        return ok, fail

    # ── 持仓计算 ──

    def get_current_positions(self) -> List[Dict]:
        """
        从交易记录计算当前持仓（226号方案增强）
        新增字段: hold_days, first_buy, pnl_pct, ratio, market_value
        """
        trades = Trade.query.order_by(Trade.trade_date.asc()).all()
        if not trades:
            return []

        holdings = {}  # ts_code -> {qty, cost, total_buy, total_sell, first_buy_date, ...}
        for t in trades:
            code = t.ts_code
            if code not in holdings:
                holdings[code] = {
                    'ts_code': code,
                    'stock_name': t.stock_name or '',
                    'buy_qty': 0, 'buy_amount': 0.0,
                    'sell_qty': 0, 'sell_amount': 0.0,
                    'first_buy_date': None,
                    'realized_pnl': 0.0,
                }
            h = holdings[code]
            if t.stock_name:
                h['stock_name'] = t.stock_name
            if t.direction == '买入':
                if h['buy_qty'] == 0:
                    h['first_buy_date'] = t.trade_date
                h['buy_qty'] += t.quantity
                h['buy_amount'] += float(t.amount)
            elif t.direction == '卖出':
                h['sell_qty'] += t.quantity
                h['sell_amount'] += float(t.amount)

        positions = []
        today = date.today()
        total_position_value = 0
        position_cost_total = 0

        for code, h in holdings.items():
            hold_qty = h['buy_qty'] - h['sell_qty']
            if hold_qty <= 0:
                continue
            avg_cost = h['buy_amount'] / h['buy_qty'] if h['buy_qty'] > 0 else 0
            realized_pnl = h['sell_amount'] - (avg_cost * h['sell_qty'])
            # 查询最新收盘价
            latest = DailyData.query.filter(
                DailyData.ts_code == code
            ).order_by(DailyData.trade_date.desc()).first()
            current_price = float(latest.close) if latest else None
            market_value = round(current_price * hold_qty, 2) if current_price else round(avg_cost * hold_qty, 2)
            unrealized_pnl = round((current_price - avg_cost) * hold_qty, 2) if current_price else 0.0
            total_cost = round(avg_cost * hold_qty, 2)
            pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2) if avg_cost and current_price else 0
            hold_days = (today - h['first_buy_date']).days if h['first_buy_date'] else 0

            total_position_value += market_value
            position_cost_total += total_cost

            positions.append({
                'ts_code': code,
                'stock_name': h['stock_name'],
                'hold_qty': hold_qty,
                'avg_cost': round(avg_cost, 2),
                'current_price': current_price,
                'total_cost': total_cost,
                'market_value': market_value,
                'unrealized_pnl': unrealized_pnl,
                'realized_pnl': round(realized_pnl, 2),
                # 新增字段
                'hold_days': hold_days,
                'first_buy_date': h['first_buy_date'].isoformat() if h['first_buy_date'] else None,
                'pnl_pct': pnl_pct,
            })

        # 计算占比
        for p in positions:
            p['ratio'] = round(p['market_value'] / total_position_value * 100, 2) if total_position_value else 0

        return positions

    # ── 账户总览 ──

    def get_account_summary(self) -> Dict:
        """账户总览指标（226号方案增强：7项KPI芯片+持仓汇总）"""
        trades = Trade.query.all()
        if not trades:
            return self._empty_summary()

        positions = self.get_current_positions()

        # 初始本金 = 所有买入金额 + 当前现金（倒推）
        total_buy = sum(float(t.amount) for t in trades if t.direction == '买入')
        total_sell = sum(float(t.amount) for t in trades if t.direction == '卖出')
        total_commission = sum(float(t.commission or 0) for t in trades)

        position_cost = sum(p['total_cost'] for p in positions)
        # 现金余额 = 总卖出 - (总买入 - 持仓成本 - 手续费)
        cash_balance = total_sell - (total_buy - position_cost - total_commission)
        position_value = sum(p.get('market_value', p['total_cost']) for p in positions)
        total_asset = cash_balance + position_value
        initial_capital = total_buy  # 近似
        total_profit = total_sell - total_buy - total_commission

        buy_trades = [t for t in trades if t.direction == '买入']
        sell_trades = [t for t in trades if t.direction == '卖出']

        # 胜率：卖出盈利笔数 / 总卖出笔数
        win_sells = [t for t in sell_trades if (float(t.price) * t.quantity - float(t.amount)) > 0]
        win_rate = round(len(win_sells) / max(len(sell_trades), 1) * 100, 2)

        total_return_pct = (total_profit / initial_capital * 100) if initial_capital else 0

        # 最大回撤（从交易记录推算，避免与 get_equity_curve 循环引用）
        max_drawdown = 0.0
        buy_amount = 0.0
        peak_asset = initial_capital
        running_cash = 0.0
        running_positions = {}
        sorted_by_date = sorted(trades, key=lambda t: t.trade_date)
        for t in sorted_by_date:
            code = t.ts_code
            if code not in running_positions:
                running_positions[code] = 0
            if t.direction == '买入':
                running_positions[code] += t.quantity
                running_cash -= float(t.amount)
            else:
                running_positions[code] -= t.quantity
                running_cash += float(t.amount)
            pos_value = sum(
                n * float(t.price) for c, n in running_positions.items() if n > 0
            )
            total = running_cash + pos_value
            if total > peak_asset:
                peak_asset = total
            dd = (peak_asset - total) / peak_asset if peak_asset else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # 盈亏比
        pnl_list = [float(t.amount) - float(t.price) * t.quantity for t in sell_trades] if sell_trades else []
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]
        avg_win = float(np.mean(wins)) if wins else 0
        avg_loss = abs(float(np.mean(losses))) if losses else 1
        profit_ratio = round(avg_win / max(avg_loss, 1), 2)

        # 年化收益
        days_traded = (trades[-1].trade_date - trades[0].trade_date).days if len(trades) > 1 else 0
        annualized_return = round(
            ((1 + total_return_pct / 100) ** (365 / max(days_traded, 1)) - 1) * 100, 2
        ) if days_traded > 0 else 0

        return {
            'total_assets': round(total_asset, 2),
            'cash_balance': round(max(cash_balance, 0), 2),
            'position_value': round(position_value, 2),
            'total_pnl': round(total_profit, 2),
            'total_pnl_pct': round(total_return_pct, 2),
            'annualized_return': annualized_return,
            'trade_count': len(trades),
            'buy_count': len(buy_trades),
            'sell_count': len(sell_trades),
            'win_rate': win_rate,
            'max_drawdown': round(max_drawdown * 100, 2),
            'profit_ratio': f'1:{profit_ratio}',
            'positions_count': len(positions),
            'position_total': round(position_value, 2),
        }

    def _empty_summary(self) -> Dict:
        return {
            'total_assets': 0.0, 'cash_balance': 0.0, 'position_value': 0.0,
            'total_pnl': 0.0, 'total_pnl_pct': 0.0, 'annualized_return': 0.0,
            'trade_count': 0, 'buy_count': 0, 'sell_count': 0,
            'win_rate': 0.0, 'max_drawdown': 0.0, 'profit_ratio': '0:0',
            'positions_count': 0, 'position_total': 0.0,
        }

    # ── 资金曲线 ──

    def get_equity_curve(self, days: int = 365) -> List[Dict]:
        """
        生成资金曲线（每日净值）

        从 AccountSnapshot 读取已有快照，不足部分从交易记录推算。
        """
        # 优先使用已有的快照数据
        cutoff = date.today() - timedelta(days=days)
        snapshots = AccountSnapshot.query.filter(
            AccountSnapshot.snapshot_date >= cutoff
        ).order_by(AccountSnapshot.snapshot_date.asc()).all()

        if snapshots:
            return [s.to_dict() for s in snapshots]

        # 无快照时，从交易记录推算
        trades = Trade.query.order_by(Trade.trade_date.asc()).all()
        if not trades:
            return []

        # 初始本金 ≈ 所有买入金额总和
        initial = sum(float(t.amount) for t in trades if t.direction == '买入')
        if initial <= 0:
            return []
        curve = []
        daily_holdings = {}
        cash = float(initial)

        for t in trades:
            code = t.ts_code
            if code not in daily_holdings:
                daily_holdings[code] = 0
            if t.direction == '买入':
                daily_holdings[code] += t.quantity
                cash -= float(t.amount)
            else:
                daily_holdings[code] -= t.quantity
                cash += float(t.amount)
            pos_value = sum(
                daily_holdings[c] * float(t.price)
                for c in daily_holdings if daily_holdings[c] > 0
            )
            total = cash + pos_value
            ret = (total - float(initial)) / float(initial)
            curve.append({
                'snapshot_date': t.trade_date.isoformat(),
                'total_asset': round(total, 2),
                'cash_balance': round(cash, 2),
                'position_value': round(pos_value, 2),
                'total_profit': round(total - float(initial), 2),
                'total_return_pct': round(ret, 4),
                'initial_capital': round(float(initial), 2),
            })

        return curve

    def get_performance_metrics(self) -> Dict:
        """计算绩效指标"""
        curve = self.get_equity_curve(days=365)
        if len(curve) < 2:
            return {}

        returns = [c['total_return_pct'] for c in curve]
        assets = [c['total_asset'] for c in curve]

        total_return = returns[-1]
        days_traded = len(curve)
        annual_return = (1 + total_return) ** (365 / max(days_traded, 1)) - 1

        # 最大回撤
        peak = assets[0]
        max_dd = 0.0
        for a in assets:
            if a > peak:
                peak = a
            dd = (peak - a) / peak if peak else 0
            if dd > max_dd:
                max_dd = dd

        # 日收益率序列
        daily_rets = np.diff(returns) if len(returns) > 1 else [0]
        std = float(np.std(daily_rets)) if len(daily_rets) > 1 else 0.0
        sharpe = ((annual_return - 0.025) / max(std * (252 ** 0.5), 0.001)) if std > 0 else 0.0

        # 胜率 & 盈亏比
        trades = Trade.query.all()
        sell_trades = [t for t in trades if t.direction == '卖出']
        if sell_trades:
            pnl_list = [float(t.amount) - float(t.price) * t.quantity for t in sell_trades]
            wins = [p for p in pnl_list if p > 0]
            losses = [p for p in pnl_list if p <= 0]
            win_rate = len(wins) / max(len(sell_trades), 1)
            avg_win = float(np.mean(wins)) if wins else 0
            avg_loss = abs(float(np.mean(losses))) if losses else 1
            profit_loss_ratio = avg_win / max(avg_loss, 1)
        else:
            win_rate = 0.0
            profit_loss_ratio = 0.0

        return {
            'total_return': round(total_return * 100, 2),
            'annual_return': round(annual_return * 100, 2),
            'max_drawdown': round(max_dd * 100, 2),
            'sharpe_ratio': round(sharpe, 4),
            'win_rate': round(win_rate, 4),
            'profit_loss_ratio': round(profit_loss_ratio, 4),
            'total_trades': len(trades),
            'days_tracked': days_traded,
        }

    # ── 虚拟验证复盘分区 ──

    def get_virtual_review_data(self) -> List[Dict]:
        """获取虚拟验证复盘数据（轨B·已完成验证）"""
        vps = VirtualPosition.query.filter(
            VirtualPosition.status == 'completed'
        ).order_by(VirtualPosition.start_date.desc()).limit(100).all()
        return [vp.to_dict() for vp in vps]

    # ── 复盘策略候选 ──

    def get_review_candidates(self, ts_code: str) -> List[Dict]:
        """获取可关联的复盘策略候选列表（按同票检索复盘中心RV）"""
        try:
            from app.models.playback import ReviewUnit
            units = ReviewUnit.query.filter(
                ReviewUnit.ts_code == ts_code
            ).order_by(ReviewUnit.added_at.desc()).limit(20).all()
            return [
                {
                    'unit_id': u.unit_id,
                    'ts_code': u.ts_code,
                    'name': u.name,
                    'stage': u.stage,
                    'strategy_config': u.strategy_config,
                    'entry_date': u.entry_date.isoformat() if u.entry_date else None,
                }
                for u in units
            ]
        except Exception as e:
            logger.warning(f"获取复盘策略候选失败: {e}")
            return []

    # ── 手续费自动核算 ──

    @staticmethod
    def calc_trade_fee(price: float, quantity: int, direction: str,
                       commission_rate: float = 2.5) -> Dict:
        """计算交易手续费（D9: 后端统一核算）

        Args:
            commission_rate: 万分数（默认 2.5 = 万分之2.5）
        Returns:
            {commission, stamp_tax, transfer_fee, total}
        """
        amount = price * quantity
        commission = max(amount * commission_rate / 10000, 5.0)  # 最低5元
        stamp_tax = amount * 0.0005 if direction == '卖出' else 0  # 卖出收万分之5
        transfer_fee = amount * 0.00001  # 过户费万分之一
        total = commission + stamp_tax + transfer_fee
        return {
            'commission': round(commission, 2),
            'stamp_tax': round(stamp_tax, 2),
            'transfer_fee': round(transfer_fee, 2),
            'total': round(total, 2),
        }

    # ── 资金变动记录 ──

    def add_fund_change(self, change_date: date, change_type: str,
                        amount: float, note: str = '') -> Optional[AccountCashFlow]:
        """新增资金变动"""
        try:
            # 计算变动后的余额
            last_flow = AccountCashFlow.query.order_by(AccountCashFlow.id.desc()).first()
            prev_balance = float(last_flow.balance_after) if last_flow else 0
            balance_after = prev_balance + (amount if change_type == 'deposit' else -amount)
            if balance_after < 0:
                logger.warning(f"资金不足: 当前余额 {prev_balance}, 取出 {amount}")
                return None

            flow = AccountCashFlow(
                change_date=change_date, change_type=change_type,
                amount=round(amount, 2), balance_after=round(balance_after, 2),
                note=note,
            )
            db.session.add(flow)
            db.session.commit()
            return flow
        except Exception as e:
            db.session.rollback()
            logger.warning(f"新增资金变动失败: {e}")
            return None

    def get_fund_history(self, limit: int = 100) -> List[Dict]:
        """获取资金变动历史"""
        flows = AccountCashFlow.query.order_by(
            AccountCashFlow.change_date.desc(), AccountCashFlow.id.desc()
        ).limit(limit).all()
        return [f.to_dict() for f in flows]

    def get_current_balance(self) -> float:
        """获取当前资金余额"""
        last = AccountCashFlow.query.order_by(AccountCashFlow.id.desc()).first()
        return float(last.balance_after) if last else 0.0

    # ── 账户配置持久化 ──

    def save_config(self, config: Dict) -> bool:
        """保存账户配置到 RuntimeConfigManager（D8）"""
        try:
            from app.services.runtime_config import runtime_config_manager
            current = runtime_config_manager.get_all() or {}
            current.setdefault('account', {})
            current['account']['config'] = config
            runtime_config_manager.save(current)
            return True
        except Exception as e:
            logger.warning(f"保存账户配置失败: {e}")
            return False

    def load_config(self) -> Dict:
        """加载账户配置（D8）"""
        try:
            from app.services.runtime_config import runtime_config_manager
            config = runtime_config_manager.get_all() or {}
            return config.get('account', {}).get('config', {})
        except Exception as e:
            logger.warning(f"加载账户配置失败: {e}")
            return {}
