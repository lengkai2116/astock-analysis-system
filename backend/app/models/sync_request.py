"""
SyncRequest ORM 模型（app.db）
=============================
376号修复：sync_requests 从 stock_cache.db 迁移到 app.db，
消除 Flask 进程与 daemon 进程竞争 stock_cache.db 写锁的问题。
"""
from datetime import datetime

from app import db


class SyncRequest(db.Model):
    __tablename__ = 'sync_requests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_type = db.Column(db.Text, nullable=False)
    ts_code = db.Column(db.Text)
    status = db.Column(db.Text, default='pending')
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
