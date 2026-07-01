"""
监控通知数据模型

规则引擎 + 通知推送 + 休眠管理 + 周期报告的全量数据模型
"""
from app import db
from datetime import datetime
from sqlalchemy import JSON, UniqueConstraint


class NotificationRule(db.Model):
    """监控规则主表"""
    __tablename__ = 'notification_rules'

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.String(80), nullable=False, unique=True, index=True)  # R-20260701-001
    name = db.Column(db.String(100), nullable=False, index=True)
    rule_type = db.Column(db.String(20), nullable=False, index=True)  # opportunity/risk/anomaly/status/discipline
    status = db.Column(db.String(20), nullable=False, default='running', index=True)  # running/paused/dormant/expired/deleted
    scope_type = db.Column(db.String(20), nullable=False, default='multi')  # single/multi/market

    # 条件组合（JSON: [{condition_id, params, logic_group}]）
    conditions = db.Column(JSON, default=list)
    condition_logic = db.Column(db.String(5), default='AND')  # AND/OR

    # 监控范围
    scope_detail = db.Column(JSON, default=dict)  # {type:"stock"|"watchlist"|"market", stocks:[], dynamic:bool}

    # 调度
    schedule_start = db.Column(db.String(5), default='09:30')  # HH:MM
    schedule_end = db.Column(db.String(5), default='15:00')    # HH:MM
    scan_interval = db.Column(db.Integer, default=15)           # 分钟: 5/15/30/60
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)

    # 通知配置
    cooldown = db.Column(db.Integer, default=30)                # 冷却期(分钟)
    channels = db.Column(JSON, default=dict)                    # {desktop: true, wechat: false, popup: false}
    confirm_period = db.Column(db.Integer, default=0)           # 确认期(周期数)
    long_term_monitor = db.Column(db.Boolean, default=False)    # 长期监控

    # 运行统计
    trigger_total = db.Column(db.Integer, default=0)
    trigger_today = db.Column(db.Integer, default=0)
    last_trigger = db.Column(db.DateTime, nullable=True)
    hot_score = db.Column(db.Float, default=0.0)               # 热度评分
    dormant_since = db.Column(db.DateTime, nullable=True)       # 休眠起始

    # 软删除
    deleted_at = db.Column(db.DateTime, nullable=True)

    # 时间
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.rule_id,
            'name': self.name,
            'type': self.rule_type,
            'status': self.status,
            'range': self.scope_type,
            'conditions': self.conditions or [],
            'condition_logic': self.condition_logic,
            'scope_detail': self.scope_detail or {},
            'schedule': {'start': self.schedule_start, 'end': self.schedule_end},
            'scan_interval': self.scan_interval,
            'valid_from': self.valid_from.isoformat() if self.valid_from else None,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'cooldown': self.cooldown,
            'channels': self.channels or {},
            'confirm_period': self.confirm_period,
            'long_term_monitor': self.long_term_monitor,
            'trigger_total': self.trigger_total or 0,
            'trigger_today': self.trigger_today or 0,
            'trigger_latest': self.last_trigger.isoformat() if self.last_trigger else None,
            'hot_score': self.hot_score or 0.0,
            'dormant_days': (datetime.now() - self.dormant_since).days if self.dormant_since else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Notification(db.Model):
    """通知记录主表"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    notif_id = db.Column(db.String(80), nullable=False, unique=True, index=True)  # N-20260630-001
    rule_id = db.Column(db.String(80), nullable=False, index=True)
    rule_name = db.Column(db.String(100))
    notif_type = db.Column(db.String(20), nullable=False, index=True)  # opportunity/risk/anomaly/status/discipline

    # 股票信息
    stock = db.Column(JSON, default=dict)  # {ts_code, name}
    trigger_time = db.Column(db.DateTime, nullable=False, index=True)
    trigger_value = db.Column(db.String(100), default='')
    today_count = db.Column(db.Integer, default=1)

    # 判定明细
    conditions_result = db.Column(JSON, default=list)
    stock_info = db.Column(JSON, default=dict)

    # 状态
    is_unread = db.Column(db.Boolean, default=True, index=True)
    channels_sent = db.Column(JSON, default=list)
    ack_action = db.Column(db.String(50), nullable=True)
    acked_at = db.Column(db.DateTime, nullable=True)

    # 类型特有
    cooldown_remaining = db.Column(db.Integer, nullable=True)
    deadline = db.Column(db.DateTime, nullable=True)
    tooltip = db.Column(db.Text, nullable=True)
    edit_data = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.Index('idx_notif_rule_time', 'rule_id', 'trigger_time'),
        db.Index('idx_notif_unread', 'is_unread', 'trigger_time'),
    )

    def to_dict(self):
        return {
            'id': self.notif_id,
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'type': self.notif_type,
            'stock': self.stock or {},
            'trigger_time': self.trigger_time.isoformat() if self.trigger_time else None,
            'trigger_value': self.trigger_value or '',
            'today_count': self.today_count or 1,
            'is_unread': self.is_unread,
            'conditions_result': self.conditions_result or [],
            'stock_info': self.stock_info or {},
            'channels_sent': self.channels_sent or [],
            'ack_action': self.ack_action,
            'acked_at': self.acked_at.isoformat() if self.acked_at else None,
            'cooldown_remaining': self.cooldown_remaining,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'tooltip': self.tooltip,
            'edit_data': self.edit_data,
        }


class NotificationRuleStats(db.Model):
    """规则运行统计表"""
    __tablename__ = 'notification_rule_stats'

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.String(80), nullable=False, index=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    trigger_count = db.Column(db.Integer, default=0)
    pass_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('rule_id', 'stat_date'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'stat_date': self.stat_date.isoformat() if self.stat_date else None,
            'trigger_count': self.trigger_count or 0,
            'pass_count': self.pass_count or 0,
        }


class ReportArchive(db.Model):
    """周期报告归档表"""
    __tablename__ = 'report_archives'

    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(20), nullable=False, index=True)  # weekly / monthly / diagnosis
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    generated_at = db.Column(db.DateTime, nullable=False)
    file_path = db.Column(db.String(500), nullable=False, default='')

    # 来源追踪（Phase 3）
    source = db.Column(db.String(50), nullable=True, default='')  # notification / dormancy_manager
    source_id = db.Column(db.String(80), nullable=True, default='')  # rule_id 或 '__all__'

    # 摘要统计（用于列表展示，免打开文件）
    total_triggers = db.Column(db.Integer, default=0)
    active_rules = db.Column(db.Integer, default=0)
    stocks_covered = db.Column(db.Integer, default=0)
    delivery_rate = db.Column(db.Float, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'report_type': self.report_type,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'file_path': self.file_path,
            'source': self.source or '',
            'source_id': self.source_id or '',
            'total_triggers': self.total_triggers or 0,
            'active_rules': self.active_rules or 0,
            'stocks_covered': self.stocks_covered or 0,
            'delivery_rate': self.delivery_rate or 0.0,
        }
