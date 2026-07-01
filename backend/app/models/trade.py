"""
账户交易数据模型

Trade: 用户实盘交易记录（226号方案扩展）
AccountSnapshot: 每日账户净值快照（资金曲线用）
"""
from app import db
from datetime import datetime, date
from sqlalchemy import DECIMAL, Text, Boolean


class Trade(db.Model):
    """实盘交易记录"""
    __tablename__ = 'account_trades'

    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(16), nullable=False, index=True)
    stock_name = db.Column(db.String(32))
    direction = db.Column(db.String(4), nullable=False)       # 买入 / 卖出
    trade_date = db.Column(db.Date, nullable=False, index=True)
    price = db.Column(DECIMAL(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount = db.Column(DECIMAL(14, 2), nullable=False)
    commission = db.Column(DECIMAL(10, 2), default=0.00)
    notes = db.Column(Text)
    # 信号匹配结果（由 signal_match_service 填充）
    matched_signal_id = db.Column(db.Integer, nullable=True)
    matched_signal_type = db.Column(db.String(20), nullable=True)
    matched_signal_confidence = db.Column(DECIMAL(5, 2), nullable=True)
    match_score = db.Column(DECIMAL(5, 2), nullable=True)     # 0-100
    # 226号方案新增字段
    buy_reason = db.Column(db.String(32), nullable=True)       # 买入理由分类
    sell_reason = db.Column(db.String(32), nullable=True)      # 卖出理由分类
    review_unit_id = db.Column(db.String(16), nullable=True)   # 关联复盘策略ID (RV-xxx)
    is_partial = db.Column(Boolean, default=False)             # 是否部分卖出
    # 手续费明细（自动核算）
    stamp_tax = db.Column(DECIMAL(10, 2), default=0.00)       # 印花税（卖出时收取）
    transfer_fee = db.Column(DECIMAL(10, 2), default=0.00)    # 过户费
    realized_pnl = db.Column(DECIMAL(14, 2), nullable=True)   # 已实现盈亏（卖出时核算）
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'stock_name': self.stock_name,
            'direction': self.direction,
            'trade_date': self.trade_date.isoformat() if self.trade_date else None,
            'price': float(self.price) if self.price else None,
            'quantity': self.quantity,
            'amount': float(self.amount) if self.amount else None,
            'commission': float(self.commission) if self.commission else None,
            'notes': self.notes,
            'signal_match': {
                'signal_id': self.matched_signal_id,
                'signal_type': self.matched_signal_type,
                'confidence': float(self.matched_signal_confidence) if self.matched_signal_confidence else None,
                'score': float(self.match_score) if self.match_score else None,
            } if self.matched_signal_id else None,
            # 226号方案新增字段
            'buy_reason': self.buy_reason,
            'sell_reason': self.sell_reason,
            'review_unit_id': self.review_unit_id,
            'is_partial': bool(self.is_partial) if self.is_partial is not None else False,
            'fee': {
                'commission': float(self.commission) if self.commission else 0,
                'stamp_tax': float(self.stamp_tax) if self.stamp_tax else 0,
                'transfer_fee': float(self.transfer_fee) if self.transfer_fee else 0,
                'total': round(
                    (float(self.commission) if self.commission else 0) +
                    (float(self.stamp_tax) if self.stamp_tax else 0) +
                    (float(self.transfer_fee) if self.transfer_fee else 0), 2
                ),
            },
            'realized_pnl': float(self.realized_pnl) if self.realized_pnl else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AccountSnapshot(db.Model):
    """每日账户净值快照"""
    __tablename__ = 'account_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    total_asset = db.Column(DECIMAL(14, 2), nullable=False)       # 总资产
    cash_balance = db.Column(DECIMAL(14, 2), default=0.00)        # 现金余额
    position_value = db.Column(DECIMAL(14, 2), default=0.00)      # 持仓市值
    total_profit = db.Column(DECIMAL(14, 2), default=0.00)        # 总盈亏
    total_return_pct = db.Column(DECIMAL(8, 4), default=0.00)     # 总收益率(%)
    initial_capital = db.Column(DECIMAL(14, 2), default=0.00)      # 初始本金
    # 226号方案新增
    daily_pnl = db.Column(DECIMAL(14, 2), default=0.00)           # 当日盈亏
    max_drawdown = db.Column(DECIMAL(8, 4), default=0.00)         # 最大回撤(%)
    win_rate = db.Column(DECIMAL(5, 2), default=0.00)             # 胜率(%)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
            'total_asset': float(self.total_asset) if self.total_asset else None,
            'cash_balance': float(self.cash_balance) if self.cash_balance else None,
            'position_value': float(self.position_value) if self.position_value else None,
            'total_profit': float(self.total_profit) if self.total_profit else None,
            'total_return_pct': float(self.total_return_pct) if self.total_return_pct else None,
            'initial_capital': float(self.initial_capital) if self.initial_capital else None,
            'daily_pnl': float(self.daily_pnl) if self.daily_pnl else None,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown else None,
            'win_rate': float(self.win_rate) if self.win_rate else None,
        }


class AccountCashFlow(db.Model):
    """账户资金变动记录（D10: 取款/追加历史）"""
    __tablename__ = 'account_cash_flow'

    id = db.Column(db.Integer, primary_key=True)
    change_date = db.Column(db.Date, nullable=False, index=True)
    change_type = db.Column(db.String(16), nullable=False)   # deposit / withdraw
    amount = db.Column(DECIMAL(14, 2), nullable=False)
    balance_after = db.Column(DECIMAL(14, 2), nullable=False)
    note = db.Column(Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'change_date': self.change_date.isoformat() if self.change_date else None,
            'change_type': self.change_type,
            'amount': float(self.amount) if self.amount else None,
            'balance_after': float(self.balance_after) if self.balance_after else None,
            'note': self.note or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
