
"""426号方案阶段四：S5/D3 adj_factor 大表拆分收敛测试

临时库/故障注入测试：不依赖真实生产数据库。验证 §10 阶段四 4.2 检验标准：
- _ensure_adj_factor_table 在分库（history_cache.db）建表（原总库建表 →
  阶段二空壳清理后新年份表自动建表失败、静默丢写），且结构正确：
  PRIMARY KEY (ts_code, trade_date) + adj_factor REAL
- 有 PK 后 _insert_from_df 的 INSERT OR REPLACE 天然去重（行数==去重键）
- create_adj_factor_view 动态 UNION 全部年表（全年份覆盖，替代单年视图）
"""
import os
import sqlite3
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.sharding_manager import ShardingManager


def _make_ecm(tmp_path, total_db='total_stock.db'):
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.db_path = str(tmp_path / total_db)
    ecm.conn = sqlite3.connect(ecm.db_path)
    ecm._write_lock = threading.RLock()
    return ecm


@pytest.fixture
def shard_mgr(tmp_path, monkeypatch):
    """临时分库管理器（db_dir=tmp_path/duckdb），替换全局单例"""
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    mgr = ShardingManager(str(tmp_path))
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', mgr)
    return mgr


# ── 4.2 S5/D3：年表分库建表 ────────────────────────────────

def test_ensure_adj_factor_table_creates_in_shard(shard_mgr, tmp_path):
    """_ensure_adj_factor_table 在分库 history_cache.db 建表（原总库 → 静默丢写）"""
    ecm = _make_ecm(tmp_path)
    ecm._ensure_adj_factor_table('adj_factor_cache_2027')
    conn = shard_mgr.get_connection('history_cache.db')
    cols = conn.execute("PRAGMA table_info(adj_factor_cache_2027)").fetchall()
    pk_cols = [c[1] for c in cols if c[5]]
    assert pk_cols == ['ts_code', 'trade_date'], f'PK 缺失: {pk_cols}'
    adj = [c for c in cols if c[1] == 'adj_factor'][0]
    assert adj[2] == 'REAL', f'adj_factor 类型错误: {adj[2]}'
    # 总库不得建表
    total_cnt = ecm.conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='adj_factor_cache_2027'"
    ).fetchone()[0]
    assert total_cnt == 0, '年表不得建在总库'


def test_ensure_adj_factor_table_idempotent(shard_mgr, tmp_path):
    """已存在的年表不重建（幂等，避免覆盖既有数据）"""
    conn = shard_mgr.get_connection('history_cache.db')
    conn.execute("CREATE TABLE adj_factor_cache_2026 (ts_code TEXT, trade_date TEXT, adj_factor REAL)")
    conn.execute("INSERT INTO adj_factor_cache_2026 VALUES ('000001.SZ', '2026-09-10', 1.5)")
    conn.commit()
    ecm = _make_ecm(tmp_path)
    ecm._ensure_adj_factor_table('adj_factor_cache_2026')
    assert conn.execute("SELECT COUNT(*) FROM adj_factor_cache_2026").fetchone()[0] == 1
    # 结构保持原样（未加 PK，不覆盖）
    pk_cols = [c[1] for c in conn.execute("PRAGMA table_info(adj_factor_cache_2026)").fetchall() if c[5]]
    assert pk_cols == []


def test_insert_from_df_adj_factor_dedup_with_pk(shard_mgr, tmp_path):
    """有 PK 的年表：_insert_from_df 的 INSERT OR REPLACE 天然去重（行数==去重键）"""
    ecm = _make_ecm(tmp_path)
    ecm._ensure_adj_factor_table('adj_factor_cache_2026')
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 4,
        'trade_date': ['2026-09-10', '2026-09-10', '2026-09-11', '2026-09-11'],
        'adj_factor': [1.5, 1.8, 1.9, 2.1],
    })
    ecm._insert_from_df('adj_factor_cache_2026', df)
    conn = shard_mgr.get_connection('history_cache.db')
    cnt, keys = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ts_code || '|' || trade_date) FROM adj_factor_cache_2026"
    ).fetchone()
    assert cnt == keys == 2, f'REPLACE 去重失效: {cnt} 行 / {keys} 键'


# ── 4.2 S5/D3：全年份视图 ──────────────────────────────────

def test_adj_factor_view_covers_all_year_tables(tmp_path):
    """create_adj_factor_view 动态 UNION 全部年表（全年份覆盖，替代单年视图）"""
    db_dir = tmp_path / 'duckdb'
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_dir / 'history_cache.db'))
    for y in ('2001', '2025', '2026'):
        conn.execute(f"""
            CREATE TABLE adj_factor_cache_{y} (
                ts_code TEXT, trade_date TEXT, adj_factor REAL, cached_at TIMESTAMP
            )""")
    conn.commit()
    conn.close()

    from app.data.create_views import create_adj_factor_view
    assert create_adj_factor_view(str(tmp_path)) is True
    conn = sqlite3.connect(str(db_dir / 'history_cache.db'))
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='adj_factor_view'").fetchone()[0]
    conn.close()
    assert 'adj_factor_cache_2001' in sql
    assert 'adj_factor_cache_2025' in sql
    assert 'adj_factor_cache_2026' in sql
    assert sql.count('UNION ALL') == 2  # 3 张年表
