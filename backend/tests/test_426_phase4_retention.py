
"""426号方案阶段四：存储治理与数据修复测试（4.1 S3/D1 保留期落地）

临时库/故障注入测试：不依赖真实生产数据库。验证 §10 阶段四 4.1 检验标准：
- 5 个 clean_* 全部经 _exec_shard 分库路由（执行后分库行数下降可证，
  不再打总库空壳 no-op）：
  * clean_stk_limit_cache → market_cache.db
  * clean_fina_indicator_cache → financial_cache.db
  * clean_minute_cache → market_cache.db（cutoff 由调用方按规则10 传 180 天）
  * clean_lhb_cache → lhb_cache 在 system_cache.db + lhb_detail_cache 在总库
  * clean_factor_cache → compute_cache.db（原已生效，回归防复发）
- 保留期语义（用户决策：356 规则10 时效为最低标准——超期不删、不足告警）：
  * _check_data_retention 不执行任何删除，仅检查覆盖下限并告警
  * _RETENTION_MIN_DAYS 阈值：daily 1095 / minute 180（v1.5 校正 30→180）/ factor 365
"""
import os
import sqlite3
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.sharding_manager import ShardingManager

CLEAN_METHODS = ('clean_stk_limit_cache', 'clean_lhb_cache', 'clean_fina_indicator_cache',
                 'clean_minute_cache', 'clean_factor_cache')


def _make_ecm(tmp_path, total_db='total_stock.db'):
    """构造无真实生产连接的 ECM 实例（总库指向临时文件）"""
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.db_path = str(tmp_path / total_db)
    ecm.conn = sqlite3.connect(ecm.db_path)
    return ecm


@pytest.fixture
def shard_mgr(tmp_path, monkeypatch):
    """临时分库管理器（db_dir=tmp_path/duckdb），替换全局单例"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)
    return mgr


def _seed(mgr, db_name, table, ddl, values):
    conn = mgr.get_connection(db_name)
    conn.execute(f"CREATE TABLE {table} ({ddl})")
    placeholders = ','.join('?' * len(values[0]))
    conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", values)
    conn.commit()


def _count(mgr, db_name, table):
    conn = mgr.get_connection(db_name)
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── 4.1 S3/D1：clean_* 分库路由（执行后分库行数下降可证）───

def test_clean_stk_limit_routed_to_market(shard_mgr, tmp_path):
    """clean_stk_limit_cache 删除发生在 market_cache.db（原 _execute 打主库 no-op）"""
    _seed(shard_mgr, 'market_cache.db', 'stk_limit_cache', 'ts_code TEXT, trade_date TEXT',
          [('000001.SZ', '2025-01-01'), ('000001.SZ', '2026-09-01')])
    ecm = _make_ecm(tmp_path)
    ecm.clean_stk_limit_cache('2026-01-01')
    assert _count(shard_mgr, 'market_cache.db', 'stk_limit_cache') == 1


def test_clean_fina_indicator_routed_to_financial(shard_mgr, tmp_path):
    """clean_fina_indicator_cache 删除发生在 financial_cache.db"""
    _seed(shard_mgr, 'financial_cache.db', 'fina_indicator_cache', 'ts_code TEXT, end_date TEXT',
          [('000001.SZ', '2022-06-30'), ('000001.SZ', '2026-06-30')])
    ecm = _make_ecm(tmp_path)
    ecm.clean_fina_indicator_cache('2023-01-01')
    assert _count(shard_mgr, 'financial_cache.db', 'fina_indicator_cache') == 1


def test_clean_minute_routed_to_market(shard_mgr, tmp_path):
    """clean_minute_cache 删除发生在 market_cache.db（cutoff 按规则10 传 180 天档位）"""
    _seed(shard_mgr, 'market_cache.db', 'minute_kline_cache', 'ts_code TEXT, trade_date TEXT',
          [('000001.SZ', '2026-01-05'), ('000001.SZ', '2026-09-01')])
    ecm = _make_ecm(tmp_path)
    ecm.clean_minute_cache('2026-03-16')  # 6 个月 cutoff
    assert _count(shard_mgr, 'market_cache.db', 'minute_kline_cache') == 1


def test_clean_lhb_routes_system_and_total(shard_mgr, tmp_path):
    """clean_lhb_cache：lhb_cache 删 system 分库、lhb_detail_cache 删总库（显式总库表）"""
    _seed(shard_mgr, 'system_cache.db', 'lhb_cache', 'ts_code TEXT, trade_date TEXT',
          [('000001.SZ', '2025-01-01'), ('000001.SZ', '2026-09-01')])
    ecm = _make_ecm(tmp_path)
    ecm.conn.execute("CREATE TABLE lhb_detail_cache (ts_code TEXT, trade_date TEXT)")
    ecm.conn.executemany("INSERT INTO lhb_detail_cache VALUES (?, ?)",
                         [('000001.SZ', '2025-01-01'), ('000001.SZ', '2026-09-01')])
    ecm.conn.commit()
    ecm.clean_lhb_cache('2026-01-01')
    assert _count(shard_mgr, 'system_cache.db', 'lhb_cache') == 1
    assert ecm.conn.execute("SELECT COUNT(*) FROM lhb_detail_cache").fetchone()[0] == 1


def test_clean_factor_cache_routed_to_compute(shard_mgr, tmp_path):
    """clean_factor_cache 仍走 compute_cache.db（原已生效，回归防复发）"""
    _seed(shard_mgr, 'compute_cache.db', 'factor_cache',
          'ts_code TEXT, trade_date TEXT, factor_name TEXT, value REAL',
          [('000001.SZ', '2025-01-01', 'F1', 1.0), ('000001.SZ', '2026-09-01', 'F1', 2.0)])
    ecm = _make_ecm(tmp_path)
    ecm.clean_factor_cache('2026-01-01')
    assert _count(shard_mgr, 'compute_cache.db', 'factor_cache') == 1


# ── 保留期下限语义（用户决策：超期不删、不足告警）──────────

def test_retention_thresholds():
    """_RETENTION_MIN_DAYS 阈值：daily 3 年 / minute 180 天（v1.5 校正 30→180）/ factor 1 年"""
    import data_daemon as dd
    assert dd._RETENTION_MIN_DAYS['daily_cache'] == 1095
    assert dd._RETENTION_MIN_DAYS['minute_kline_cache'] == 180
    assert dd._RETENTION_MIN_DAYS['factor_cache'] == 365


def test_check_data_retention_no_delete_when_covered(monkeypatch, caplog):
    """覆盖充足：_check_data_retention 不调用任何 clean_*（不删除超期数据），仅 info"""
    import data_daemon as dd
    ecm = mock.Mock()
    ecm._query_shard.return_value = pd.DataFrame({'min_d': ['2021-07-07']})
    monkeypatch.setattr(dd, '_ecm', ecm)
    with caplog.at_level('INFO', logger='data_daemon'):
        dd._check_data_retention()
    for name in CLEAN_METHODS:
        assert getattr(ecm, name).call_count == 0, f'{name} 不得被调用（不删除数据）'
    assert any('满足最低保留期' in r.message for r in caplog.records)


def test_check_data_retention_gap_warns(monkeypatch, caplog):
    """覆盖不足：告警且不删除（规则时效为最低标准，缺口交由回补机制）"""
    import data_daemon as dd
    ecm = mock.Mock()
    # daily_cache 最早 2026-08-01（远晚于 3 年截止）→ 覆盖不足
    ecm._query_shard.return_value = pd.DataFrame({'min_d': ['2026-08-01']})
    monkeypatch.setattr(dd, '_ecm', ecm)
    with caplog.at_level('WARNING', logger='data_daemon'):
        dd._check_data_retention()
    assert any('覆盖不足' in r.message for r in caplog.records)
    for name in CLEAN_METHODS:
        assert getattr(ecm, name).call_count == 0, f'{name} 不得被调用（不删除数据）'


def test_check_data_retention_empty_table_warns(monkeypatch, caplog):
    """空表（无数据）：告警覆盖不足，不删除"""
    import data_daemon as dd
    ecm = mock.Mock()
    ecm._query_shard.return_value = pd.DataFrame({'min_d': [None]})
    monkeypatch.setattr(dd, '_ecm', ecm)
    with caplog.at_level('WARNING', logger='data_daemon'):
        dd._check_data_retention()
    assert any('无数据' in r.message for r in caplog.records)
    for name in CLEAN_METHODS:
        assert getattr(ecm, name).call_count == 0, f'{name} 不得被调用（不删除数据）'
