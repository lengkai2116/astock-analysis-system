from app import db
from datetime import datetime
from sqlalchemy import JSON, Enum
import enum

class StrategySignal(enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    WATCH = "watch"

class StrategyTemplateType(enum.Enum):
    INDICATOR = "indicator"
    SELECTION = "selection"
    PORTFOLIO = "portfolio"

class StrategyOutput(db.Model):
    __tablename__ = 'strategy_outputs'
    
    id = db.Column(db.Integer, primary_key=True)
    ts_code = db.Column(db.String(10), nullable=False)
    strategy_name = db.Column(db.String(100), nullable=False)
    signal = db.Column(db.Enum(StrategySignal), nullable=False)
    confidence = db.Column(db.DECIMAL(5, 2))
    entry_zone_low = db.Column(db.DECIMAL(10, 2))
    entry_zone_high = db.Column(db.DECIMAL(10, 2))
    risk_line = db.Column(db.DECIMAL(10, 2))
    target_zone_low = db.Column(db.DECIMAL(10, 2))
    target_zone_high = db.Column(db.DECIMAL(10, 2))
    position_suggestion = db.Column(db.String(50))
    holding_period = db.Column(db.String(50))
    evidence = db.Column(JSON)
    risk_notes = db.Column(JSON)
    signal_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    status_recognition = db.Column(JSON, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'ts_code': self.ts_code,
            'strategy_name': self.strategy_name,
            'signal': self.signal.value if self.signal else None,
            'confidence': float(self.confidence) if self.confidence else None,
            'entry_zone': [
                float(self.entry_zone_low) if self.entry_zone_low else None,
                float(self.entry_zone_high) if self.entry_zone_high else None
            ] if (self.entry_zone_low or self.entry_zone_high) else None,
            'risk_line': float(self.risk_line) if self.risk_line else None,
            'target_zone': [
                float(self.target_zone_low) if self.target_zone_low else None,
                float(self.target_zone_high) if self.target_zone_high else None
            ] if (self.target_zone_low or self.target_zone_high) else None,
            'position_suggestion': self.position_suggestion,
            'holding_period': self.holding_period,
            'evidence': self.evidence,
            'risk_notes': self.risk_notes,
            'signal_date': self.signal_date.strftime('%Y-%m-%d') if self.signal_date else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'status_recognition': self.status_recognition if self.status_recognition else None
        }

class StrategyTemplateV2(db.Model):
    __tablename__ = 'strategy_templates_v2'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    template_type = db.Column(db.Enum(StrategyTemplateType), nullable=False)
    code_template = db.Column(db.Text, nullable=False)
    parameters = db.Column(JSON)
    output_schema = db.Column(JSON)
    is_system = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    author = db.Column(db.String(50))
    version = db.Column(db.String(20), default="1.0.0")
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'template_type': self.template_type.value if self.template_type else None,
            'code_template': self.code_template,
            'parameters': self.parameters,
            'output_schema': self.output_schema,
            'is_system': self.is_system,
            'is_active': self.is_active,
            'author': self.author,
            'version': self.version,
            'usage_count': self.usage_count,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }
