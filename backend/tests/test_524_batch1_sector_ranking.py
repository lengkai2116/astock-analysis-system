"""524号 批次1（Q4）定向测试：as_sector_ranking 建表归属修正 + 写读闭环。

修复内容（enhanced_cache_manager.py）：
1. `_init_snapshot_tables` 补建 as_sector_ranking（快照库 market_snapshot.db）——
   原建表在主库段被 426 空壳自清理 DROP → 快照库从未建表 → 写静默丢
2. `read_as_sector_ranking` 改走 `self.snapshot_conn`（原 read_conn 总库读分库表恒空，499 同型）
3. `write_as_sector_ranking` 加 sector_code→ts_code 列映射（对齐表结构列）

验证方式：临时 DATA_DIR + sharding 双切隔离（sandbox-isolation 方法论，不触真实库）。
"""
import sqlite3
import threading

import pandas as pd
import pytest
from app.data.sharding_manager import ShardingManager


def _make_ecm(tmp_path, monkeypatch):
    """构造最小 ECM：临时总库 + 临时快照库 + 双切 sharding（仿 test_426 沙箱）。"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))  # 内部 db_dir = tmp_path/duckdb（426 测试同款）
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.db_path = str(tmp_path / 'total.db')
    ecm.conn = sqlite3.connect(ecm.db_path)
    ecm.read_conn = ecm.conn
    ecm._write_lock = threading.RLock()
    ecm._snapshot_write_lock = threading.RLock()
    ecm.snapshot_db_path = str(tmp_path / 'duckdb' / 'market_snapshot.db')
    ecm.snapshot_conn = sqlite3.connect(ecm.snapshot_db_path)
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df
    ecm._init_snapshot_tables()
    return ecm, mgr


def test_snapshot_tables_creates_sector_ranking(tmp_path, monkeypatch):
    """修复①：_init_snapshot_tables 后快照库存在 as_sector_ranking（与 as_market_snapshot 并列）。"""
    ecm, _ = _make_ecm(tmp_path, monkeypatch)
    tabs = {r[0] for r in ecm.snapshot_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'as_market_snapshot' in tabs
    assert 'as_sector_ranking' in tabs


def test_sector_ranking_table_schema(tmp_path, monkeypatch):
    """as_sector_ranking 表结构含 L4 所需字段（up/down/lead）。"""
    ecm, _ = _make_ecm(tmp_path, monkeypatch)
    cols = {r[1] for r in ecm.snapshot_conn.execute(
        "PRAGMA table_info(as_sector_ranking)").fetchall()}
    assert {'sector_name', 'ts_code', 'change_pct', 'up_count', 'down_count',
            'lead_ts_code', 'lead_name', 'lead_change_pct'} <= cols


def test_write_read_sector_ranking_roundtrip(tmp_path, monkeypatch):
    """修复②③：write（sector_code→ts_code 映射）→ read（snapshot_conn）闭环。"""
    ecm, _ = _make_ecm(tmp_path, monkeypatch)
    ecm.write_as_sector_ranking([{
        'sector_code': 'BK0475',
        'sector_name': '半导体',
        'change_pct': 2.5,
        'up_count': 80,
        'down_count': 12,
        'price': 1000.0,
        'rank': 1,
    }])
    rows = ecm.read_as_sector_ranking()
    assert len(rows) == 1
    r = rows[0]
    assert r['sector_name'] == '半导体'
    assert r['ts_code'] == 'BK0475'      # sector_code → ts_code 映射生效
    assert r['change_pct'] == 2.5
    assert r['up_count'] == 80
    assert r['down_count'] == 12


def test_read_as_sector_ranking_uses_snapshot_conn(tmp_path, monkeypatch):
    """修复②：read_as_sector_ranking 源码走 snapshot_conn（不再 read_conn 总库）。"""
    import inspect

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager.read_as_sector_ranking)
    assert 'self.snapshot_conn' in src
    assert 'self.read_conn' not in src.split('"""')[-1].split('def ')[0].strip() or \
        'self.read_conn' not in src


def test_write_read_concept_ranking_still_empty(tmp_path, monkeypatch):
    """as_concept_ranking 仍恒空（424 §10 决策①：废弃表，不被本次改动复活）。"""
    ecm, _ = _make_ecm(tmp_path, monkeypatch)
    assert ecm.read_as_concept_ranking() == []
