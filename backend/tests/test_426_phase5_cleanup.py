
"""426号方案阶段五：清理与收口测试（S8/P2-1、S7/D5、P2-2、P2-3、P2-5）

临时库/故障注入/源码断言测试：不依赖真实生产数据库。验证 §10 阶段五：
- 5.1 S8/P2-1：init_sharding/backfill_all 死表引用（chip_distribution_cache/tag_history）已清除
- 5.2 S7/D5：write_as_market_snapshot 死方法已删（双写分裂路径消除）；
      as_market_snapshot 已登记 market_snapshot.db 路由（消除未登记告警）
- 5.3 P2-2：cache_fina_indicator_data 返回写入成功与否（虚报计数消除）；
      嵌套 Series/对象列被展平（防 sqlite 绑参失败）
- 5.4 P2-3：factor_precompute get_cache_stats 走分库（返回非零统计）、
      clear_cache 走分库 _exec_shard（原总库 DELETE 空操作）
- 5.5 P2-5：cache_pre_feat_batch 死代码已删（源码零引用）
"""
import inspect
import os
import sqlite3
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from app.data.sharding_manager import ShardingManager

DEAD_TABLES = ('chip_distribution_cache', 'tag_history')


# ── 5.1 S8/P2-1：死表引用已清除 ────────────────────────────

def test_dead_table_refs_removed_from_config():
    """init_sharding / backfill_all 无死表引用（注释除外）"""
    from app.data import init_sharding
    src = inspect.getsource(init_sharding)
    assert 'chip_distribution_cache' not in src, 'init_sharding 残留 chip_distribution_cache'
    assert 'tag_history' not in src, 'init_sharding 残留 tag_history'

    with open(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'backfill_all.py')) as f:
        src2 = f.read()
    assert 'chip_distribution_cache' not in src2, 'backfill_all 残留 chip_distribution_cache'
    assert 'tag_history' not in src2, 'backfill_all 残留 tag_history'


# ── 5.2 S7/D5：as_market_snapshot 单写路径 + 路由登记 ───────

def test_write_as_market_snapshot_removed():
    """write_as_market_snapshot 死方法已删除（双写分裂路径消除）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    assert not hasattr(EnhancedCacheManager, 'write_as_market_snapshot')


def test_as_market_snapshot_registered():
    """as_market_snapshot 已登记 market_snapshot.db 路由"""
    from app.data.sharding_manager import sharding_manager
    assert sharding_manager.get_db_for_table('as_market_snapshot') == 'market_snapshot.db'
    assert sharding_manager.is_registered('as_market_snapshot')


# ── 5.3 P2-2：fina Series 展平 + 成功计数 ──────────────────

def test_cache_fina_returns_bool_and_flattens_series(tmp_path, monkeypatch):
    """cache_fina_indicator_data 返回成功标志；嵌套 Series 列被展平（防绑参失败）"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.db_path = str(tmp_path / 'total.db')
    ecm.conn = sqlite3.connect(ecm.db_path)
    ecm._write_lock = threading.RLock()
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df
    # 总库建表（供 _insert_from_df 复制结构到分库）
    ecm.conn.execute("CREATE TABLE fina_indicator_cache (ts_code TEXT, end_date TEXT, eps REAL, extra_col TEXT)")
    ecm.conn.commit()

    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'end_date': ['2026-06-30'],
        'eps': [0.5],
        'extra_col': [pd.Series([1, 2])],   # 嵌套 Series（复现 v1.5 绑参失败场景）
    })
    assert ecm.cache_fina_indicator_data(df) is True
    conn = mgr.get_connection('financial_cache.db')
    n, v = conn.execute("SELECT COUNT(*), extra_col FROM fina_indicator_cache").fetchone()
    assert n == 1
    assert v == '1', f'嵌套 Series 未被展平: {v!r}'
    # 空 df 返回 False（不写入）
    assert ecm.cache_fina_indicator_data(pd.DataFrame()) is False


def test_batch_fina_counts_failures():
    """_batch_fina_indicator 按写入结果计数（虚报"完成 N 条"已消除）"""
    import data_daemon as dd
    src = inspect.getsource(dd._batch_fina_indicator)
    assert '写入失败' in src, '缺少写入失败计数分支'
    assert 'cache_fina_indicator_data(latest)' in src
    assert 'fail += 1' in src, '缺少失败累加'


# ── 5.4 P2-3：factor_precompute 分库读写 ────────────────────

def test_factor_precompute_stats_uses_shard(tmp_path, monkeypatch):
    """get_cache_stats 走 _query_shard 分库（原总库连接恒 0）"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)
    conn = mgr.get_connection('compute_cache.db')
    conn.execute("CREATE TABLE factor_cache (ts_code TEXT, factor_name TEXT, value REAL, cached_at TEXT)")
    conn.executemany(
        "INSERT INTO factor_cache VALUES (?, ?, ?, ?)",
        [('000001.SZ', 'F1', 1.0, '2026-09-10'), ('000002.SZ', 'F2', 2.0, '2026-09-11')])
    conn.commit()

    from app.data.factor_precompute import FactorPrecomputeManager
    ecm = mock.Mock()
    fp = FactorPrecomputeManager.__new__(FactorPrecomputeManager)
    fp.cache_manager = ecm
    # 让 _query_shard 指向临时分库真实查询
    ecm._query_shard.side_effect = lambda table, sql, params=None: pd.read_sql(
        sql, mgr.get_connection('compute_cache.db'), params=params)
    stats = fp.get_cache_stats()
    assert stats['total_records'] == 2
    assert stats['stock_count'] == 2
    assert stats['factor_count'] == 2


def test_factor_precompute_clear_uses_shard(tmp_path, monkeypatch):
    """clear_cache 走 _exec_shard 分库删除（原总库 DELETE 空操作）"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)
    conn = mgr.get_connection('compute_cache.db')
    conn.execute("CREATE TABLE factor_cache (ts_code TEXT, factor_name TEXT, value REAL, cached_at TEXT)")
    conn.executemany(
        "INSERT INTO factor_cache VALUES (?, ?, ?, ?)",
        [('000001.SZ', 'F1', 1.0, '2026-09-10'), ('000001.SZ', 'F2', 2.0, '2026-09-11')])
    conn.commit()

    from app.data.factor_precompute import FactorPrecomputeManager
    ecm = mock.Mock()
    fp = FactorPrecomputeManager.__new__(FactorPrecomputeManager)
    fp.cache_manager = ecm
    ecm._exec_shard.side_effect = lambda table, sql, params=None: (
        mgr.get_connection('compute_cache.db').execute(sql, params or []),
        mgr.get_connection('compute_cache.db').commit())
    fp.clear_cache(ts_code='000001.SZ')
    n = mgr.get_connection('compute_cache.db').execute(
        "SELECT COUNT(*) FROM factor_cache").fetchone()[0]
    assert n == 0
    assert ecm._exec_shard.call_count == 1
    assert ecm._exec_shard.call_args[0][0] == 'factor_cache'


# ── 5.5 P2-5：死代码已删 ────────────────────────────────────

def test_cache_pre_feat_batch_removed():
    """cache_pre_feat_batch 死代码已删除（全仓库零引用）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    assert not hasattr(EnhancedCacheManager, 'cache_pre_feat_batch')
