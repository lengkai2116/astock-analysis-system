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
from app.models.trade import Trade, AccountSnapshot
from app.models.verification import VirtualPosition
from app.models import DailyData

logger = logging.getLogger(__name__)


class AccountService:
    """账户管理服务"""

    # ── 交易记录 CRUD ──

    def create_trade(self, ts_code: str, stock_name: str, direction: str,
                     trade_date: date, price: float, quantity: int,
                     commission: float = 0.0, notes: str = "") -> Optional[Trade]:
        """新增交易记录"""
        try:
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
        """修改交易记录"""
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
                t = self.create_trade(
                    ts_code=item['ts_code'],
                    stock_name=item.get('stock_name', ''),
                    direction=item['direction'],
                    trade_date=item['trade_date'] if isinstance(item['trade_date'], date)
                               else datetime.strptime(item['trade_date'][:10], '%Y-%m-%d').date(),
                    price=float(item['price']),
                    quantity=int(item['quantity']),
                    commission=float(item.get('commission', 0)),
                    notes=item.get('notes', ''),
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
        从交易记录计算当前持仓

        按 ts_code 汇总：买入总量/金额 vs 卖出总量/金额
        余量 > 0 即为持仓。
        """
        trades = Trade.query.order_by(Trade.trade_date.asc()).all()
        if not trades:
            return []

        holdings = {}  # ts_code -> {qty, cost, total_buy, total_sell, ...}
        for t in trades:
            code = t.ts_code
            if code not in holdings:
                holdings[code] = {
                    'ts_code': code,
                    'stock_name': t.stock_name or '',
                    'buy_qty': 0, 'buy_amount': 0.0,
                    'sell_qty': 0, 'sell_amount': 0.0,
                    'realized_pnl': 0.0,
                }
            h = holdings[code]
            if t.stock_name:
                h['stock_name'] = t.stock_name
            if t.direction == '买入':
                h['buy_qty'] += t.quantity
                h['buy_amount'] += float(t.amount)
            elif t.direction == '卖出':
                h['sell_qty'] += t.quantity
                h['sell_amount'] += float(t.amount)

        positions = []
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

            positions.append({
                'ts_code': code,
                'stock_name': h['stock_name'],
                'hold_qty': hold_qty,
                'avg_cost': round(avg_cost, 2),
                'current_price': current_price,
                'total_cost': round(avg_cost * hold_qty, 2),
                'market_value': market_value,
                'unrealized_pnl': unrealized_pnl,
                'realized_pnl': round(realized_pnl, 2),
            })

        return positions

    # ── 账户总览 ──

    def get_account_summary(self) -> Dict:
        """账户总览指标"""
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
        win_sells = [t for t in sell_trades if float(t.amount) > float(t.price) * t.quantity * 0.99]

        total_return_pct = (total_profit / initial_capital * 100) if initial_capital else 0

        return {
            'total_asset': round(total_asset, 2),
            'cash_balance': round(max(cash_balance, 0), 2),
            'position_value': round(position_value, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 4),
            'initial_capital': round(initial_capital, 2),
            'total_trades': len(trades),
            'buy_count': len(buy_trades),
            'sell_count': len(sell_trades),
            'positions_count': len(positions),
            'win_rate': round(len(win_sells) / max(len(sell_trades), 1), 4),
        }

    def _empty_summary(self) -> Dict:
        return {
            'total_asset': 0.0, 'cash_balance': 0.0, 'position_value': 0.0,
            'total_profit': 0.0, 'total_return_pct': 0.0, 'initial_capital': 0.0,
            'total_trades': 0, 'buy_count': 0, 'sell_count': 0,
            'positions_count': 0, 'win_rate': 0.0,
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

        summary = self.get_account_summary()
        initial = summary.get('initial_capital', 100000)
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
