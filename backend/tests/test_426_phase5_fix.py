
"""426号方案落地复核修正测试（2026-09-12 复查发现的 3 处遗漏/轻微修复）

只读核查发现并修复：
1. 遗漏①：health.py data_freshness 的 win_rate_cache 不在 sharded_tables →
   读总库（表已被空壳清理 DROP）→ 健康监控恒报错；已补入分库读取
2. 遗漏②：as_sector_ranking 活跃写入但未登记路由 → 426 S1 后 _insert_from_df
   告警跳过（静默丢写）+ 读取降级总库读空；已登记 market_snapshot.db
3. 轻微：get_pattern_score/has_pattern_score 读仍硬编码 compute_read_conn
   （P1-2 写已收口）；已改 _query_shard 路由 API 统一
"""
import inspect
import os
import sqlite3
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from app.data.sharding_manager import ShardingManager, sharding_manager

# ── 遗漏①：health.py win_rate 监控走分库 ───────────────────

def test_health_sharded_tables_includes_win_rate():
    """data_freshness 的 sharded_tables 含 win_rate_cache（原读总库恒报错）"""
    from app.routes import health
    src = inspect.getsource(health.data_freshness)
    assert "'win_rate_cache'" in src, 'win_rate_cache 未加入分库读取集合'
    assert "'win_rate_cache'" in src.split('sharded_tables')[1].split('for name')[0]


# ── 遗漏②：as_sector_ranking 路由登记 ──────────────────────

def test_as_sector_ranking_registered():
    """as_sector_ranking 已登记 market_snapshot.db（原未登记 → S1 静默丢写）"""
    assert sharding_manager.get_db_for_table('as_sector_ranking') == 'market_snapshot.db'
    assert sharding_manager.is_registered('as_sector_ranking')


def test_write_as_sector_ranking_goes_shard(tmp_path, monkeypatch):
    """write_as_sector_ranking 经 _insert_from_df 写入分库（不再被 S1 拦截）"""
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
    ecm.conn.execute("CREATE TABLE as_sector_ranking (industry TEXT, change_pct REAL)")
    ecm.conn.commit()

    ecm.write_as_sector_ranking([{'industry': '银行', 'change_pct': 1.5}])
    conn = mgr.get_connection('market_snapshot.db')
    n = conn.execute("SELECT COUNT(*) FROM as_sector_ranking").fetchone()[0]
    assert n == 1, f'as_sector_ranking 未写入分库（{n} 行）——仍被 S1 拦截或落错库'
    v = conn.execute("SELECT industry, change_pct FROM as_sector_ranking").fetchone()
    assert v == ('银行', 1.5)


# ── 轻微：pattern_score 读路径收口 ─────────────────────────

def test_get_pattern_score_uses_shard():
    """get_pattern_score/has_pattern_score 改走 _query_shard（不再 compute_read_conn 硬编码）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager.get_pattern_score)
    assert '_query_shard(' in src, 'get_pattern_score 未走路由 API'
    assert 'self.compute_read_conn' not in src, 'get_pattern_score 仍硬编码 compute_read_conn'
    src2 = inspect.getsource(EnhancedCacheManager.has_pattern_score)
    assert '_query_shard(' in src2, 'has_pattern_score 未走路由 API'
    assert 'self.compute_read_conn' not in src2, 'has_pattern_score 仍硬编码 compute_read_conn'
