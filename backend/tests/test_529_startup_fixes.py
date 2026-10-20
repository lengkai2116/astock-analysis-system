"""529号 批次2 定向测试：wait_db_unlock 等待期进度日志 + 上限 60s（B1）。

- **进度日志**：锁持有时等待期每 10s 打一条「仍等待数据库写锁释放（已等 Xs）」，
  避免 API 冷启动等锁时用户无反馈（原仅首尾各一条日志、中间每 5s 静默重试）。
- **上限**：默认 `max_wait` 300s→60s（原 5 分钟上限过长，实测等锁 ≤30s；
  超时继续启动有「后续重试机制兜底」）。
- **防回归**：无锁立即返回、锁释放后返回（对齐 test_428_gap_fixes 既有用例）。
"""
import sqlite3
import threading
import time

import data_daemon as dd  # 复用 _wait_db_unlock 薄包装（同 wait_db_unlock 公共函数）


# ──────────────────────────────────────────────
# 默认 max_wait 60s（B1）
# ──────────────────────────────────────────────
def test_wait_db_unlock_default_max_wait_60():
    """B1：wait_db_unlock 默认上限 60s（原 300s）。"""
    import inspect

    from app.utils.db_lock import wait_db_unlock

    sig = inspect.signature(wait_db_unlock)
    assert sig.parameters['max_wait'].default == 60.0, \
        f'默认 max_wait 应为 60.0，实际 {sig.parameters["max_wait"].default}'


# ──────────────────────────────────────────────
# 等待期进度日志（B1）
# ──────────────────────────────────────────────
def _hold_lock(path, release_after):
    """独立线程持写锁 release_after 秒后释放。"""
    conn = sqlite3.connect(path, timeout=0.1, check_same_thread=False)
    conn.execute('BEGIN IMMEDIATE')

    def _release():
        time.sleep(release_after)
        conn.execute('ROLLBACK')
        conn.close()

    t = threading.Thread(target=_release)
    t.start()
    return t


def test_wait_db_unlock_progress_log(tmp_path, caplog):
    """B1：锁持有时等待期出现进度日志（每 10s 一条）。"""
    db_dir = tmp_path / 'duckdb'
    db_dir.mkdir()
    path = str(db_dir / 'stock_cache.db')
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.close()

    # 持锁 ~17s：wait_db_unlock 每次探测在锁下阻塞 timeout=2s，到 _waited=10
    # 探测点（实际约 14s）时锁仍在 → 触发「已等 10s」进度日志
    t = _hold_lock(path, release_after=17.0)
    try:
        with caplog.at_level('WARNING', logger='app.utils.db_lock'):
            dd._wait_db_unlock(str(tmp_path), max_wait=30.0)
    finally:
        t.join(timeout=25)

    progress = [r for r in caplog.records
                if '仍等待数据库写锁释放' in r.getMessage()]
    assert progress, '等待期应出现进度日志（每 10s 一条）'
    assert any('已等 10s' in r.getMessage() for r in progress), \
        '进度日志应含已等时长（首个 10s 点）'


def test_wait_db_unlock_timeout_returns(tmp_path, caplog):
    """B1：超时（max_wait 到）仍返回不抛异常（后续重试机制兜底）。"""
    db_dir = tmp_path / 'duckdb'
    db_dir.mkdir()
    path = str(db_dir / 'stock_cache.db')
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.close()

    t = _hold_lock(path, release_after=15.0)  # 持锁 > max_wait=5
    try:
        with caplog.at_level('WARNING', logger='app.utils.db_lock'):
            dd._wait_db_unlock(str(tmp_path), max_wait=5.0)  # 5s 即超时返回
    finally:
        # 释放锁，避免线程悬挂
        import inspect as _inspect
        import os as _os
        # 通过持锁线程的 conn 释放：无法直接访问，改为等其自然释放后清理
        t.join(timeout=20)
    assert any('等待数据库写锁超时' in r.getMessage() for r in caplog.records), \
        '超时路径应打「等待数据库写锁超时」日志'


# ──────────────────────────────────────────────
# 防回归：无锁立即返回 / 锁释放后返回
# ──────────────────────────────────────────────
def test_wait_db_unlock_immediate_no_regression(tmp_path):
    """无锁（目录无库文件）时立即返回（对齐 test_428 既有行为）。"""
    t0 = time.time()
    dd._wait_db_unlock(str(tmp_path), max_wait=5.0)
    assert time.time() - t0 < 3.0, '无锁应立即返回'


def test_wait_db_unlock_release_returns(tmp_path):
    """锁在等待期内释放 → 正常返回（对齐 test_428 既有行为）。"""
    db_dir = tmp_path / 'duckdb'
    db_dir.mkdir()
    path = str(db_dir / 'stock_cache.db')
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    lock_conn = sqlite3.connect(path, timeout=0.1, check_same_thread=False)
    lock_conn.execute('BEGIN IMMEDIATE')

    def _release():
        time.sleep(1.5)
        lock_conn.execute('ROLLBACK')
        lock_conn.close()

    t = threading.Thread(target=_release)
    t.start()
    t0 = time.time()
    dd._wait_db_unlock(str(tmp_path), max_wait=15.0)
    elapsed = time.time() - t0
    assert 1.0 <= elapsed < 12.0, f'应等待锁释放后返回，实际 {elapsed:.1f}s'
    t.join()
    conn.close()
