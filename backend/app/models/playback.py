"""
复盘中心数据模型

ReviewUnit: 复盘条目（RV-xxx）
PlaybackAccount: 复盘账户状态
PlaybackReport: 诊断报告（RR-xxx）
ReviewConfig: 复盘配置
"""
from datetime import datetime
from app import db
from sqlalchemy import DECIMAL, JSON, Text


class ReviewUnit(db.Model):
    """复盘条目 — 池中每个策略信号"""
    __tablename__ = 'review_units'

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.String(16), unique=True, nullable=False, index=True)  # RV-001

    # 股票元信息（meta）
    ts_code = db.Column(db.String(16), nullable=False, index=True)
    name = db.Column(db.String(50))
    sector = db.Column(db.String(50))
    snapshot_date = db.Column(db.Date)
    base_price = db.Column(DECIMAL(10, 2))
    added_at = db.Column(db.DateTime, default=datetime.now)

    # 策略配置（strategy_config JSON）
    strategy_config = db.Column(JSON)

    # 维度输出（dimension_outputs JSON）
    dimension_outputs = db.Column(JSON)

    # 交叉验证（cross_verify JSON）
    cross_verify = db.Column(JSON)

    # 仲裁结果（arbitration JSON）
    arbitration = db.Column(JSON)

    # 交易参考（practical_ref JSON）
    practical_ref = db.Column(JSON)

    # 阶段状态
    stage = db.Column(db.String(16), default='pending', index=True)  # pending / holding / completed
    stage_progress_pct = db.Column(DECIMAL(5, 2), default=0.00)
    direction = db.Column(db.String(16), default='bullish')  # bullish / bearish / neutral
    confidence = db.Column(DECIMAL(5, 2), default=0.00)

    # 交易字段
    entry_price = db.Column(DECIMAL(10, 2))
    entry_date = db.Column(db.Date)
    current_price = db.Column(DECIMAL(10, 2))
    exit_price = db.Column(DECIMAL(10, 2))
    exit_reason = db.Column(db.String(32))
    unrealized_pnl_pct = db.Column(DECIMAL(8, 2))
    realized_pnl_pct = db.Column(DECIMAL(8, 2))
    realized_pnl_amount = db.Column(DECIMAL(14, 2))
    holding_days = db.Column(db.Integer, default=0)
    max_drawdown = db.Column(DECIMAL(8, 2))

    # 资金分配（capital_allocation JSON）
    capital_allocation = db.Column(JSON)

    # 事件时间轴（events JSON）
    events = db.Column(JSON)

    # 诊断结果
    review_analysis = db.Column(JSON)
    report_id = db.Column(db.String(20))
    has_report = db.Column(db.Boolean, default=False)

    # 系统字段
    timestamp = db.Column(db.BigInteger)
    deleted_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        """返回完整条目字典（含嵌套结构）"""
        return {
            'id': self.unit_id,
            'meta': {
                'ts_code': self.ts_code,
                'name': self.name,
                'sector': self.sector,
                'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
                'base_price': float(self.base_price) if self.base_price else None,
                'added_at': self.added_at.isoformat() if self.added_at else None,
            },
            'strategy_config': self.strategy_config,
            'dimension_outputs': self.dimension_outputs,
            'cross_verify': self.cross_verify,
            'arbitration': self.arbitration,
            'practical_ref': self.practical_ref,
            'direction': self.direction,
            'confidence': float(self.confidence) if self.confidence else None,
            'stage': self.stage,
            'stage_progress_pct': float(self.stage_progress_pct) if self.stage_progress_pct else None,
            'entry_price': float(self.entry_price) if self.entry_price else None,
            'entry_date': self.entry_date.isoformat() if self.entry_date else None,
            'current_price': float(self.current_price) if self.current_price else None,
            'exit_price': float(self.exit_price) if self.exit_price else None,
            'exit_reason': self.exit_reason,
            'unrealized_pnl_pct': float(self.unrealized_pnl_pct) if self.unrealized_pnl_pct else None,
            'realized_pnl_pct': float(self.realized_pnl_pct) if self.realized_pnl_pct else None,
            'realized_pnl_amount': float(self.realized_pnl_amount) if self.realized_pnl_amount else None,
            'holding_days': self.holding_days,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown else None,
            'capital_allocation': self.capital_allocation,
            'events': self.events or [],
            'has_report': self.has_report,
            'report_id': self.report_id,
        }

    def to_list_item(self):
        """返回池列表中的精简条目"""
        ca = self.capital_allocation or {}
        return {
            'id': self.unit_id,
            'meta': {
                'ts_code': self.ts_code,
                'name': self.name,
                'sector': self.sector,
                'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
                'base_price': float(self.base_price) if self.base_price else None,
                'added_at': self.added_at.isoformat() if self.added_at else None,
            },
            'strategy_config': self.strategy_config,
            'direction': self.direction,
            'confidence': float(self.confidence) if self.confidence else None,
            'stage': self.stage,
            'entry_price': float(self.entry_price) if self.entry_price else None,
            'entry_date': self.entry_date.isoformat() if self.entry_date else None,
            'current_price': float(self.current_price) if self.current_price else None,
            'unrealized_pnl_pct': float(self.unrealized_pnl_pct) if self.unrealized_pnl_pct else None,
            'holding_days': self.holding_days,
            'stage_progress_pct': float(self.stage_progress_pct) if self.stage_progress_pct else None,
            'events': (self.events or [])[-3:],  # 最近3条事件
            'capital_allocation': {
                'allocated_capital': ca.get('allocated_capital'),
                'shares': ca.get('shares'),
                'position_value': ca.get('position_value'),
                'stop_loss_price': ca.get('stop_loss_price'),
                'take_profit_levels': ca.get('take_profit_levels'),
                'realized_pnl_amount': ca.get('realized_pnl_amount'),
                'fee_paid': ca.get('fee_paid'),
            },
            'has_report': self.has_report,
            'report_id': self.report_id,
        }


class PlaybackAccount(db.Model):
    """复盘账户状态"""
    __tablename__ = 'playback_accounts'

    id = db.Column(db.Integer, primary_key=True)
    initial_capital = db.Column(DECIMAL(14, 2), default=1000000.00)
    current_equity = db.Column(DECIMAL(14, 2), default=1000000.00)
    cash_balance = db.Column(DECIMAL(14, 2), default=1000000.00)
    position_value = db.Column(DECIMAL(14, 2), default=0.00)
    total_realized_pnl = db.Column(DECIMAL(14, 2), default=0.00)
    today_pnl = db.Column(DECIMAL(10, 2), default=0.00)
    total_fees = db.Column(DECIMAL(10, 2), default=0.00)
    daily_pnl_log = db.Column(JSON)     # [{date, daily, cumulative, equity, positions}]
    peak_equity = db.Column(DECIMAL(14, 2), default=1000000.00)
    max_drawdown_pct = db.Column(DECIMAL(8, 2), default=0.00)
    max_drawdown_date = db.Column(db.Date)
    position_count = db.Column(db.Integer, default=0)
    completed_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        daily_log = self.daily_pnl_log or []
        return {
            'initial_capital': float(self.initial_capital) if self.initial_capital else None,
            'current_equity': float(self.current_equity) if self.current_equity else None,
            'cash_balance': float(self.cash_balance) if self.cash_balance else None,
            'position_value': float(self.position_value) if self.position_value else None,
            'total_realized_pnl': float(self.total_realized_pnl) if self.total_realized_pnl else None,
            'today_pnl': float(self.today_pnl) if self.today_pnl else None,
            'total_fees': float(self.total_fees) if self.total_fees else None,
            'daily_pnl_log': [dict(d) for d in daily_log],
            'drawdown': {
                'peak_equity': float(self.peak_equity) if self.peak_equity else None,
                'current_drawdown_pct': (
                    round((float(self.current_equity) - float(self.peak_equity)) / float(self.peak_equity) * 100, 2)
                    if self.peak_equity and float(self.peak_equity) > 0 else 0
                ),
                'max_drawdown_pct': float(self.max_drawdown_pct) if self.max_drawdown_pct else None,
                'max_drawdown_date': self.max_drawdown_date.isoformat() if self.max_drawdown_date else None,
            },
            'constraints': {
                'max_positions': 10,
                'max_single_risk_pct': 0.10,
                'max_sector_pct': 0.30,
                'base_risk_per_trade': 0.005,
                'circuit_breaker_dd_pct': 0.02,
            },
            'position_count': self.position_count or 0,
            'completed_count': self.completed_count or 0,
        }


class PlaybackReport(db.Model):
    """复盘诊断报告"""
    __tablename__ = 'playback_reports'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.String(24), unique=True, nullable=False, index=True)  # RR-20260601-001
    unit_id = db.Column(db.String(16), db.ForeignKey('review_units.unit_id'), nullable=False, index=True)
    ts_code = db.Column(db.String(16))
    name = db.Column(db.String(50))
    generated_at = db.Column(db.DateTime, default=datetime.now)
    summary = db.Column(Text)
    dimensions = db.Column(JSON)          # 9维评分数组
    total_score = db.Column(DECIMAL(5, 2))
    improvements = db.Column(JSON)        # 改进建议
    diagnostic_summary = db.Column(JSON)  # 诊断汇总
    exit_analysis = db.Column(JSON)       # 退出分析
    capital_analysis = db.Column(JSON)    # 资金分析
    scenario_match = db.Column(JSON)      # 情景匹配
    raw_data = db.Column(JSON)            # 原始数据
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'report_id': self.report_id,
            'unit_id': self.unit_id,
            'ts_code': self.ts_code,
            'name': self.name,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'summary': self.summary,
            'dimensions': self.dimensions,
            'total_score': float(self.total_score) if self.total_score else None,
            'improvements': self.improvements,
            'diagnostic_summary': self.diagnostic_summary,
            'exit_analysis': self.exit_analysis,
            'capital_analysis': self.capital_analysis,
            'scenario_match': self.scenario_match,
        }

    def to_summary(self):
        """诊断汇总统计用"""
        ds = self.diagnostic_summary or {}
        exit_an = self.exit_analysis or {}
        return {
            'report_id': self.report_id,
            'unit_id': self.unit_id,
            'ts_code': self.ts_code,
            'overall_verdict': ds.get('overall_verdict', 'unknown'),
            'root_layer': ds.get('root_layer', 'unknown'),
            'diagnosis_confidence': ds.get('diagnosis_confidence', 0),
            'total_score': float(self.total_score) if self.total_score else 0,
            'exit_reason': exit_an.get('reason', 'unknown'),
        }


class ReviewConfig(db.Model):
    """复盘配置"""
    __tablename__ = 'review_configs'

    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(64), unique=True, nullable=False)
    config_value = db.Column(JSON)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'config_key': self.config_key,
            'config_value': self.config_value,
        }
