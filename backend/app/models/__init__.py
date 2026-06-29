from app import db
from datetime import datetime
from sqlalchemy import DECIMAL, JSON, UniqueConstraint, CheckConstraint

class Stock(db.Model):
    __tablename__ = 'stocks'
    
    ts_code = db.Column(db.String(10), primary_key=True)
    symbol = db.Column(db.String(10), nullable=False, unique=True)
    name = db.Column(db.String(50), nullable=False)
    industry = db.Column(db.String(50))
    market = db.Column(db.String(20))
    list_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'ts_code': self.ts_code,
            'symbol': self.symbol,
            'name': self.name,
            'industry': self.industry,
            'market': self.market,
            'list_date': self.list_date.strftime('%Y-%m-%d') if self.list_date else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class DailyData(db.Model):
    __tablename__ = 'daily_data'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    trade_date = db.Column(db.Date, nullable=False)
    open = db.Column(DECIMAL(10, 2))
    high = db.Column(DECIMAL(10, 2))
    low = db.Column(DECIMAL(10, 2))
    close = db.Column(DECIMAL(10, 2))
    vol = db.Column(DECIMAL(20, 2))
    amount = db.Column(DECIMAL(20, 2))
    pct_chg = db.Column(DECIMAL(10, 2))
    
    __table_args__ = (
        db.UniqueConstraint('ts_code', 'trade_date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'trade_date': self.trade_date.strftime('%Y-%m-%d'),
            'open': float(self.open) if self.open else None,
            'high': float(self.high) if self.high else None,
            'low': float(self.low) if self.low else None,
            'close': float(self.close) if self.close else None,
            'vol': float(self.vol) if self.vol else None,
            'amount': float(self.amount) if self.amount else None,
            'pct_chg': float(self.pct_chg) if self.pct_chg else None
        }

class Signal(db.Model):
    __tablename__ = 'signals'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    signal_date = db.Column(db.DateTime, default=datetime.now)
    signal_type = db.Column(db.String(20), nullable=False)
    confidence = db.Column(DECIMAL(5, 2))
    entry_price = db.Column(DECIMAL(10, 2))
    stop_loss = db.Column(DECIMAL(10, 2))
    take_profit = db.Column(DECIMAL(10, 2))
    indicators = db.Column(JSON)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'signal_date': self.signal_date.strftime('%Y-%m-%d %H:%M:%S'),
            'signal_type': self.signal_type,
            'confidence': float(self.confidence) if self.confidence else None,
            'entry_price': float(self.entry_price) if self.entry_price else None,
            'stop_loss': float(self.stop_loss) if self.stop_loss else None,
            'take_profit': float(self.take_profit) if self.take_profit else None,
            'indicators': self.indicators,
            'reason': self.reason,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class Holding(db.Model):
    __tablename__ = 'holdings'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    buy_date = db.Column(db.Date)
    buy_price = db.Column(DECIMAL(10, 2))
    shares = db.Column(db.Integer)
    stop_loss = db.Column(DECIMAL(10, 2))
    take_profit = db.Column(DECIMAL(10, 2))
    status = db.Column(db.String(20), default='holding')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'buy_date': self.buy_date.strftime('%Y-%m-%d') if self.buy_date else None,
            'buy_price': float(self.buy_price) if self.buy_price else None,
            'shares': self.shares,
            'stop_loss': float(self.stop_loss) if self.stop_loss else None,
            'take_profit': float(self.take_profit) if self.take_profit else None,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

# ====================
# 阶段三新增模型
# ====================

class TechnicalIndicator(db.Model):
    __tablename__ = 'technical_indicators'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    trade_date = db.Column(db.Date, nullable=False)
    ma5 = db.Column(DECIMAL(10, 4))
    ma10 = db.Column(DECIMAL(10, 4))
    ma20 = db.Column(DECIMAL(10, 4))
    macd_dif = db.Column(DECIMAL(10, 4))
    macd_dea = db.Column(DECIMAL(10, 4))
    macd_hist = db.Column(DECIMAL(10, 4))
    rsi14 = db.Column(DECIMAL(5, 2))
    kdj_k = db.Column(DECIMAL(5, 2))
    kdj_d = db.Column(DECIMAL(5, 2))
    kdj_j = db.Column(DECIMAL(5, 2))
    boll_upper = db.Column(DECIMAL(10, 4))
    boll_mid = db.Column(DECIMAL(10, 4))
    boll_lower = db.Column(DECIMAL(10, 4))
    vol_ma5 = db.Column(DECIMAL(20, 4))
    vol_ma10 = db.Column(DECIMAL(20, 4))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    __table_args__ = (
        db.UniqueConstraint('ts_code', 'trade_date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'trade_date': self.trade_date.strftime('%Y-%m-%d'),
            'ma5': float(self.ma5) if self.ma5 else None,
            'ma10': float(self.ma10) if self.ma10 else None,
            'ma20': float(self.ma20) if self.ma20 else None,
            'macd_dif': float(self.macd_dif) if self.macd_dif else None,
            'macd_dea': float(self.macd_dea) if self.macd_dea else None,
            'macd_hist': float(self.macd_hist) if self.macd_hist else None,
            'rsi14': float(self.rsi14) if self.rsi14 else None,
            'kdj_k': float(self.kdj_k) if self.kdj_k else None,
            'kdj_d': float(self.kdj_d) if self.kdj_d else None,
            'kdj_j': float(self.kdj_j) if self.kdj_j else None,
            'boll_upper': float(self.boll_upper) if self.boll_upper else None,
            'boll_mid': float(self.boll_mid) if self.boll_mid else None,
            'boll_lower': float(self.boll_lower) if self.boll_lower else None,
            'vol_ma5': float(self.vol_ma5) if self.vol_ma5 else None,
            'vol_ma10': float(self.vol_ma10) if self.vol_ma10 else None
        }

class Watchlist(db.Model):
    __tablename__ = 'watchlist'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'ts_code'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'user_id': self.user_id,
            'notes': self.notes,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class UserMemory(db.Model):
    __tablename__ = 'user_memory'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, default=1)
    memory_type = db.Column(db.String(50))
    memory_key = db.Column(db.String(100))
    memory_value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'memory_type', 'memory_key'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'memory_type': self.memory_type,
            'memory_key': self.memory_key,
            'memory_value': self.memory_value,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class Portfolio(db.Model):
    __tablename__ = 'portfolio'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, default=1)
    initial_capital = db.Column(DECIMAL(20, 4), default=1000000.00)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'user_id': self.user_id,
            'initial_capital': float(self.initial_capital) if self.initial_capital else None,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class PortfolioHolding(db.Model):
    __tablename__ = 'portfolio_holdings'
    
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolio.id'))
    ts_code = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    avg_cost = db.Column(DECIMAL(10, 4))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    
    __table_args__ = (
        db.UniqueConstraint('portfolio_id', 'ts_code'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'portfolio_id': self.portfolio_id,
            'ts_code': self.ts_code,
            'quantity': self.quantity,
            'avg_cost': float(self.avg_cost) if self.avg_cost else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class PaperTrade(db.Model):
    __tablename__ = 'paper_trades'
    
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolio.id'))
    ts_code = db.Column(db.String(10), nullable=False)
    trade_type = db.Column(db.String(10))
    price = db.Column(DECIMAL(10, 4))
    quantity = db.Column(db.Integer)
    amount = db.Column(DECIMAL(20, 4))
    reason = db.Column(db.Text)
    trade_date = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'portfolio_id': self.portfolio_id,
            'ts_code': self.ts_code,
            'trade_type': self.trade_type,
            'price': float(self.price) if self.price else None,
            'quantity': self.quantity,
            'amount': float(self.amount) if self.amount else None,
            'reason': self.reason,
            'trade_date': self.trade_date.strftime('%Y-%m-%d %H:%M:%S')
        }


# P3: 账户交易模型
from app.models.trade import Trade, AccountSnapshot


# ============================================================
# 观潮对标新增模型（151-系统能力提升方案 §3.1 / §5.2）
# ============================================================

class Alert(db.Model):
    """条件告警"""
    __tablename__ = 'alerts'

    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False, index=True)
    alert_type = db.Column(db.String(20), default='price')  # price / volume / signal
    condition = db.Column(db.String(10), default='>')       # > / < / == / cross_above / cross_below
    threshold = db.Column(db.Float, default=0.0)
    message = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    last_triggered = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'alert_type': self.alert_type,
            'condition': self.condition,
            'threshold': self.threshold,
            'message': self.message,
            'is_active': self.is_active,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'created_at': self.created_at.isoformat(),
        }


class Drawing(db.Model):
    """画图数据持久化"""
    __tablename__ = 'drawings'

    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False, index=True)
    drawing_type = db.Column(db.String(30))  # trend_line / fibonacci / rect / text / arrow
    drawing_data = db.Column(db.Text)         # JSON string
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'drawing_type': self.drawing_type,
            'drawing_data': self.drawing_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# 股市监控通知管理 — 条件库注册表模型
# ============================================================

from app.models.condition import ConditionRegistry



