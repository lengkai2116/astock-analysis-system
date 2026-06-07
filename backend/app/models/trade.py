"""
账户交易数据模型

Trade: 用户实盘交易记录
AccountSnapshot: 每日账户净值快照（资金曲线用）
"""
from app import db
from datetime import datetime, date
from sqlalchemy import DECIMAL, Text


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
    total_return_pct = db.Column(DECIMAL(8, 4), default=0.00)    # 总收益率(%)
    initial_capital = db.Column(DECIMAL(14, 2), default=0.00)     # 初始本金
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
        }
