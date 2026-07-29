"""
机会标的库数据模型

标的库（Opportunity Library）是系统维护的股票观察清单，
支持分层评分、管线分类、生命周期管理。
"""
from datetime import datetime

from app import db


class OpportunityLibrary(db.Model):
    """标的库主表"""
    __tablename__ = 'opportunity_library'

    ts_code = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(50))
    category = db.Column(db.String(20))             # 行业分类
    pipeline = db.Column(db.String(20))              # 管线
    lib_level = db.Column(db.String(10), default='scan')  # core/watch/scan/park/done
    added_date = db.Column(db.String(10))
    added_reason = db.Column(db.Text)
    last_update = db.Column(db.String(20))
    status = db.Column(db.String(20))
    days_in_status = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Integer, default=0)
    manual_keep = db.Column(db.Integer, default=0)   # bool
    is_active = db.Column(db.Integer, default=1)     # bool
    park_trigger_count = db.Column(db.Integer, default=0)
    park_last_signal = db.Column(db.Text)
    park_entered_signal = db.Column(db.Float)
    # 分层评分
    base_value_score = db.Column(db.Float)
    base_trend_score = db.Column(db.Float)
    base_event_score = db.Column(db.Float)
    base_technical_score = db.Column(db.Float)
    factor_bonus_score = db.Column(db.Float)
    vibe_bonus_score = db.Column(db.Float)
    total_score = db.Column(db.Float)
    # 操作建议
    operation_advice = db.Column(db.Text)            # JSON
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self):
        return f'<OpportunityLibrary {self.ts_code} {self.name}>'
