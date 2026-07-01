"""
系统配置持久化模型

存储运行时动态配置（LLM/数据源/通知/定时调度等），
支持 JSON 格式的 value 字段，适用于 SQLite。

设计约束：
- 使用通用 SQLAlchemy 数据类型（禁止 ARRAY/TSVECTOR/SERIAL）
- JSON 列使用 db.Column(JSON) → SQLAlchemy 自动适配 SQLite TEXT 存储
"""
from app import db
from datetime import datetime
from sqlalchemy import JSON


class SystemConfig(db.Model):
    """系统运行时配置表"""
    __tablename__ = 'system_config'

    key = db.Column(db.String(128), primary_key=True)   # 配置键，如 'llm', 'scheduling'
    value = db.Column(JSON, nullable=False, default=dict)  # 配置值（JSON对象）
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class SyncLog(db.Model):
    """数据同步执行日志表"""
    __tablename__ = 'sync_log'

    id = db.Column(db.Integer, primary_key=True)
    sync_type = db.Column(db.String(32), nullable=False)   # daily / incremental / full / manual
    status = db.Column(db.String(16), nullable=False)       # running / success / failed
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)      # 耗时（毫秒）
    records_added = db.Column(db.Integer, default=0)        # 新增记录数
    error_message = db.Column(db.Text, nullable=True)       # 错误信息
    details = db.Column(JSON, default=dict)                 # 额外详情（各表同步数等）

    def to_dict(self):
        return {
            'id': self.id,
            'sync_type': self.sync_type,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_ms': self.duration_ms,
            'records_added': self.records_added,
            'error_message': self.error_message,
            'details': self.details
        }
