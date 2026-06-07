"""
虚拟验证数据模型

SignalRecord: 轨A·后台自动记录全部策略信号，跟踪 T+5/T+10/T+20 验证状态
VirtualPosition: 轨B·用户选择的单股虚拟实盘验证
"""
from app import db
from datetime import datetime
from sqlalchemy import JSON


class SignalRecord(db.Model):
    """
    策略信号记录（轨A）
    
    每当方案一或方案二生成策略信号时，自动记录到此表。
    定时任务按 T+5/T+10/T+20 回调检查，更新验证结果。
    """
    __tablename__ = 'signal_records'

    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False, index=True)
    signal_date = db.Column(db.Date, nullable=False, index=True)
    strategy_name = db.Column(db.String(50), nullable=False)
    signal_type = db.Column(db.String(20), nullable=False)  # BULLISH/BEARISH/NEUTRAL/WATCH
    confidence = db.Column(db.Float, default=0.0)
    entry_price = db.Column(db.Float, nullable=True)
    risk_line = db.Column(db.Float, nullable=True)
    target_price = db.Column(db.Float, nullable=True)
    entry_zone_low = db.Column(db.Float, nullable=True)
    entry_zone_high = db.Column(db.Float, nullable=True)

    # 验证检查点（由定时任务填充）
    price_t5 = db.Column(db.Float, nullable=True)
    price_t10 = db.Column(db.Float, nullable=True)
    price_t20 = db.Column(db.Float, nullable=True)
    return_t5 = db.Column(db.Float, nullable=True)   # 信号日到T+5的收益率
    return_t10 = db.Column(db.Float, nullable=True)
    return_t20 = db.Column(db.Float, nullable=True)
    hit_target_t5 = db.Column(db.Boolean, nullable=True)
    hit_target_t10 = db.Column(db.Boolean, nullable=True)
    hit_target_t20 = db.Column(db.Boolean, nullable=True)
    hit_stop_t5 = db.Column(db.Boolean, nullable=True)
    hit_stop_t10 = db.Column(db.Boolean, nullable=True)
    hit_stop_t20 = db.Column(db.Boolean, nullable=True)
    max_drawdown_t20 = db.Column(db.Float, nullable=True)

    # 状态跟踪
    verification_status = db.Column(
        db.String(20), default='pending', index=True
    )  # pending / t5_checked / t10_checked / completed
    is_win_5d = db.Column(db.Boolean, nullable=True)
    is_win_10d = db.Column(db.Boolean, nullable=True)
    is_win_20d = db.Column(db.Boolean, nullable=True)

    # 信号详情快照（JSON 冗余存储防数据变动）
    signal_snapshot = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        db.Index('idx_sigrecord_date_type', 'signal_date', 'signal_type'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'signal_date': self.signal_date.strftime('%Y-%m-%d') if self.signal_date else None,
            'strategy_name': self.strategy_name,
            'signal_type': self.signal_type,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'risk_line': self.risk_line,
            'target_price': self.target_price,
            'entry_zone': [self.entry_zone_low, self.entry_zone_high],
            'verification_status': self.verification_status,
            'checkpoints': {
                't5': {'price': self.price_t5, 'return': self.return_t5,
                       'hit_target': self.hit_target_t5, 'hit_stop': self.hit_stop_t5},
                't10': {'price': self.price_t10, 'return': self.return_t10,
                        'hit_target': self.hit_target_t10, 'hit_stop': self.hit_stop_t10},
                't20': {'price': self.price_t20, 'return': self.return_t20,
                        'hit_target': self.hit_target_t20, 'hit_stop': self.hit_stop_t20,
                        'max_drawdown': self.max_drawdown_t20},
            },
            'is_win': {
                '5d': self.is_win_5d,
                '10d': self.is_win_10d,
                '20d': self.is_win_20d,
            },
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class VirtualPosition(db.Model):
    """
    虚拟实盘持仓（轨B）
    
    用户在单股分析页勾选"虚拟实盘验证"后创建。
    记录策略建议快照，定时回调检查实际股价走势。
    """
    __tablename__ = 'virtual_positions'

    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False, index=True)
    stock_name = db.Column(db.String(50), nullable=True)

    # 策略建议快照
    suggestion = db.Column(db.String(20), nullable=False)  # BUY/SELL/HOLD
    entry_price = db.Column(db.Float, nullable=True)
    entry_zone_low = db.Column(db.Float, nullable=True)
    entry_zone_high = db.Column(db.Float, nullable=True)
    risk_line = db.Column(db.Float, nullable=True)
    target_price = db.Column(db.Float, nullable=True)
    position_suggestion = db.Column(db.String(20), nullable=True)
    confidence = db.Column(db.Float, nullable=True)

    # 虚拟资金
    virtual_capital = db.Column(db.Float, default=100000.0)

    # 验证状态
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='tracking')  # tracking / completed

    # 回调检查点
    price_t5 = db.Column(db.Float, nullable=True)
    price_t10 = db.Column(db.Float, nullable=True)
    price_t20 = db.Column(db.Float, nullable=True)
    return_t5 = db.Column(db.Float, nullable=True)
    return_t10 = db.Column(db.Float, nullable=True)
    return_t20 = db.Column(db.Float, nullable=True)
    hit_target = db.Column(db.Boolean, nullable=True)
    hit_stop = db.Column(db.Boolean, nullable=True)

    # 最终判定
    final_judgement = db.Column(db.String(20), nullable=True)  # CORRECT / WRONG / PARTIAL
    deviation_analysis = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'stock_name': self.stock_name,
            'suggestion': self.suggestion,
            'entry_price': self.entry_price,
            'entry_zone': [self.entry_zone_low, self.entry_zone_high],
            'risk_line': self.risk_line,
            'target_price': self.target_price,
            'position_suggestion': self.position_suggestion,
            'confidence': self.confidence,
            'status': self.status,
            'start_date': self.start_date.strftime('%Y-%m-%d') if self.start_date else None,
            'checkpoints': {
                't5': {'price': self.price_t5, 'return': self.return_t5},
                't10': {'price': self.price_t10, 'return': self.return_t10},
                't20': {'price': self.price_t20, 'return': self.return_t20},
            },
            'hit_target': self.hit_target,
            'hit_stop': self.hit_stop,
            'final_judgement': self.final_judgement,
            'deviation_analysis': self.deviation_analysis,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
