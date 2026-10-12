"""核心 SQLite 分库写锁探测/等待工具（511号：从 data_daemon 提取为公共函数）

供 data_daemon 与 Flask API（create_app）共用——启动前等待核心分库写锁释放，
避免 ECM 建表/迁移在锁下按 busy_timeout 空转拖慢启动（2026-10-12 实测 18 分钟锁风暴）。
"""
import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)

# 2026-09-29 OCR：补 sharding 注册分库
_LOCK_TARGET_DBS = ['stock_cache.db', 'market_cache.db', 'compute_cache.db',
                    'snapshot_cache.db', 'financial_cache.db', 'history_cache.db',
                    'system_cache.db', 'market_snapshot.db']


def wait_db_unlock(data_dir: str, max_wait: float = 300.0) -> None:
    """启动前置：等待核心 SQLite 分库写锁释放（2026-09-29 问题5 效率修复）

    研发期反复停 daemon/跑测试，残留进程可能短暂持有写锁。ECM 连接 busy_timeout=30s，
    锁定时每次 DDL 迁移失败要干等 30s，启动被『database is locked』风暴拖慢 10 分钟+
    （09-28 实证：18:00~18:10 循环）。此处用独立短超时连接探测核心分库写锁，
    锁定时每 5s 重试直至释放或超时，避免迁移在锁下空转。
    """
    _waited = 0.0
    while True:
        _locked = []
        for _db in _LOCK_TARGET_DBS:
            _p = os.path.join(data_dir, 'duckdb', _db)
            if not os.path.exists(_p):
                continue
            try:
                _c = sqlite3.connect(_p, timeout=2.0)
                try:
                    _c.execute('BEGIN IMMEDIATE')
                    _c.execute('ROLLBACK')
                finally:
                    _c.close()
            except sqlite3.OperationalError:
                _locked.append(_db)
        if not _locked:
            if _waited > 0:
                logger.info(f"数据库写锁已释放（等待 {_waited:.0f}s）")
            return
        if _waited >= max_wait:
            logger.warning(f"等待数据库写锁超时（{max_wait:.0f}s）: {_locked} 仍被锁，继续启动（后续重试机制兜底）")
            return
        if _waited == 0:
            logger.warning(f"检测到数据库写锁: {_locked}，等待释放（残留 daemon/测试进程？）...")
        time.sleep(5)
        _waited += 5.0
