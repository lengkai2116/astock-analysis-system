"""426号方案阶段二：根因级结构修复测试（S1/D8 路由二义性 + S4/D2 每库 PRAGMA）

故障注入/临时库测试：不依赖真实生产数据库——未登记表告警用 monkeypatch/临时
ShardingManager（tmp_path），验证 §10 阶段二 2.1/2.3 检验标准：
- S1：is_registered 区分显式总库表/未登记表；execute_insert/_insert_from_df
      对未登记表告警且不静默写总库；list_unmapped_tables 扫描出未登记表
- S2：cache_metadata 路由改归总库（None）
- S4：get_connection 按库 PRAGMA（journal_size_limit/cache_size）；
      wal_checkpoint 支持指定库路径
"""
import os
import sqlite3
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from app.data.sharding_manager import ShardingManager, sharding_manager

# ── S1：路由登记判定（is_registered 消除 None 二义性）──────────

def test_is_registered_distinguishes_total_and_unmapped():
    assert sharding_manager.is_registered('daily_cache')          # 分库表
    assert sharding_manager.is_registered('cache_metadata')       # 显式总库表
    assert sharding_manager.is_registered('pipeline_status')      # 显式总库表
    assert sharding_manager.is_registered('adj_factor_cache_2026')  # 前缀规则
    assert sharding_manager.is_registered('market_stats_cache')   # 426号P1-2：已登记 compute
    assert sharding_manager.is_registered('pattern_score_cache')  # 426号P1-2：已登记 compute
    assert not sharding_manager.is_registered('ghost_table_426')     # 未登记


def test_cache_metadata_routed_to_total_db():
    """426号 S2：cache_metadata 路由改归总库（实际读写路径在总库）"""
    assert sharding_manager.get_db_for_table('cache_metadata') is None


# ── S1：未登记表操作告警（不再静默跳过/静默落总库）─────────────

def test_execute_insert_unmapped_warns(caplog):
    """未登记表 execute_insert → 告警（原裸 return 无日志）"""
    with caplog.at_level('WARNING'):
        sharding_manager.execute_insert('ghost_tbl_426_insert', 'INSERT INTO t VALUES (?)', [1])
    assert any('未登记分库路由' in r.message and 'execute_insert' in r.message
               for r in caplog.records)


def test_execute_batch_insert_unmapped_warns(caplog):
    with caplog.at_level('WARNING'):
        sharding_manager.execute_batch_insert('ghost_tbl_426_batch', 'INSERT INTO t VALUES (?)', [[1]])
    assert any('未登记分库路由' in r.message for r in caplog.records)


def test_insert_from_df_unmapped_skips_total(caplog):
    """未登记表 _insert_from_df → 告警且不写总库（原静默落总库空壳）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.conn = mock.Mock()
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df
    df = pd.DataFrame({'trade_date': ['2026-09-10'], 'close': [1.0]})
    with caplog.at_level('WARNING'):
        ecm._insert_from_df('ghost_tbl_426_ifdf', df)
    assert ecm.conn.executemany.call_count == 0, '未登记表不得写总库'
    assert any('未登记分库路由' in r.message for r in caplog.records)


def test_insert_from_df_registered_total_still_writes(caplog):
    """显式总库表（登记）_insert_from_df 维持写总库（行为不变）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.conn = mock.Mock()
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df
    df = pd.DataFrame({'trade_date': ['2026-09-10']})
    with caplog.at_level('WARNING'):
        ecm._insert_from_df('pipeline_status', df)
    assert ecm.conn.executemany.call_count == 1, '显式总库表仍写总库'


# ── S1：list_unmapped_tables 扫描 ─────────────────────────────

def test_list_unmapped_tables(tmp_path):
    sm = ShardingManager(str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    conn = sm.get_connection('market_cache.db')
    conn.execute('CREATE TABLE daily_cache (x TEXT)')       # 登记分库表
    conn.execute('CREATE TABLE ghost_shard_tbl (x TEXT)')   # 分库未登记表
    conn.commit()
    total = sqlite3.connect(str(tmp_path / 'duckdb' / 'stock_cache.db'))
    total.execute('CREATE TABLE pipeline_status (x TEXT)')       # 登记总库表
    total.execute('CREATE TABLE ghost_total_tbl (x TEXT)')       # 总库未登记表
    total.commit()
    try:
        res = sm.list_unmapped_tables(total_conn=total)
        assert 'ghost_shard_tbl' in res
        assert 'ghost_total_tbl' in res
        assert 'daily_cache' not in res
        assert 'pipeline_status' not in res
        # 426号 P1-2：三表已登记 compute，不再列为未登记
        assert 'market_stats_cache' not in res
        assert 'sector_heat_cache' not in res
        assert 'pattern_score_cache' not in res
    finally:
        total.close()


# ── S4：每库 PRAGMA（get_connection 按库设定）─────────────────

def test_get_connection_per_db_prgmas(tmp_path):
    sm = ShardingManager(str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    cases = {
        'market_cache.db': (268435456, -32768),   # 256MB / 32MB
        'compute_cache.db': (16777216, -16384),   # 16MB / 16MB
        'snapshot_cache.db': (8388608, -8192),    # 8MB / 8MB（默认）
    }
    for db_name, (jsl, cs) in cases.items():
        conn = sm.get_connection(db_name)
        assert conn.execute('PRAGMA journal_size_limit').fetchone()[0] == jsl, db_name
        assert conn.execute('PRAGMA cache_size').fetchone()[0] == cs, db_name


def test_wal_checkpoint_supports_db_path(tmp_path):
    """426号 S4：wal_checkpoint 支持指定库路径"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    db = tmp_path / 't.db'
    conn = sqlite3.connect(str(db))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE t (x TEXT)')
    conn.commit()
    conn.close()
    r = ecm.wal_checkpoint('PASSIVE', db_path=str(db))
    assert isinstance(r, tuple) and len(r) == 3
