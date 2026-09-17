"""458号：bociasi 7 个回退方法分库路由修复 单元测试

覆盖：
- ShardConn：_shard_conn 正确路由到目标表分库（market_cache.db/compute_cache.db）
- 7 个回退方法（ma20/turnover/limit/rsi/erp/dv_bond/margin）改走分库 conn
  后，能拿到真实数据返回真实值，而非主库无表的静默 0.5
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import pytest


def _mk_analyzer():
    from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
    a = BociasiQuadrantAnalyzer.__new__(BociasiQuadrantAnalyzer)
    a._market_stats = {}
    a._cache = {}
    return a


class _Rows:
    """给每个回退方法按 SQL 片段喂不同结果，模拟分库 conn 命中数据"""
    def __init__(self, by_sql):
        self._by_sql = by_sql

    def execute(self, sql, params=None):
        self._last = sql
        for frag, rows in self._by_sql.items():
            if frag in sql:
                return self._OneShot(rows)
        return self._OneShot([])

    class _OneShot:
        def __init__(self, rows):
            self._rows = rows
            self._i = 0
        def fetchone(self):
            if self._i < len(self._rows):
                r = self._rows[self._i]
                self._i += 1
                return r
            return None
        def fetchall(self):
            return self._rows


# ── ShardConn 路由 ───────────────────────────────────────────────

class TestShardConnRouting:

    def test_routes_to_market_cache_for_basic_tables(self):
        """daily_cache/daily_basic_cache/stk_limit_cache/margin_cache → market_cache.db，
        且返回的 conn 是 get_connection(get_db_for_table) 的结果"""
        import app.data.sharding_manager as sm
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        calls = []
        def fake_get_db(t):
            return {'daily_basic_cache': 'market_cache.db'}.get(t)
        def fake_get_conn(db):
            calls.append(db)
            return f'conn:{db}'
        with mock.patch.object(sm, 'sharding_manager') as ms:
            ms.get_db_for_table = fake_get_db
            ms.get_connection = fake_get_conn
            conn = BociasiQuadrantAnalyzer._shard_conn('daily_basic_cache')
        assert conn == 'conn:market_cache.db'
        assert calls == ['market_cache.db']

    def test_routes_to_compute_cache_for_indicator_other(self):
        """indicator_other → compute_cache.db"""
        import app.data.sharding_manager as sm
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        def fake_get_db(t):
            return {'indicator_other': 'compute_cache.db'}.get(t)
        def fake_get_conn(db):
            return f'conn:{db}'
        with mock.patch.object(sm, 'sharding_manager') as ms:
            ms.get_db_for_table = fake_get_db
            ms.get_connection = fake_get_conn
            conn = BociasiQuadrantAnalyzer._shard_conn('indicator_other')
        assert conn == 'conn:compute_cache.db'


# ── 7 个回退方法走分库后能查到真实值（不再静默 0.5） ────────────

class TestFallbackUsesShardConn:

    def test_ma20_ratio_hits_shard(self):
        a = _mk_analyzer()
        a._shard_conn = mock.Mock(return_value=_Rows({'close > SMA_20': [(3, 2)]}))
        assert a._compute_ma20_ratio() == pytest.approx(2 / 3)
        a._shard_conn.assert_called_once_with('daily_cache')

    def test_turnover_percentile_hits_shard(self):
        a = _mk_analyzer()
        conn = _Rows({'AVG(turnover_rate) FROM daily_basic_cache WHERE trade_date=?': [(0.08,)],
                      "date(?, '-60 days')": [(0.10,)]})
        a._shard_conn = mock.Mock(return_value=conn)
        assert a._compute_turnover_percentile() == pytest.approx(0.8)
        a._shard_conn.assert_called_once_with('daily_basic_cache')

    def test_limit_ratio_hits_shard(self):
        a = _mk_analyzer()
        a._shard_conn = mock.Mock(return_value=_Rows({'high_limit = close': [(5, 2)]}))
        assert a._compute_limit_ratio() == pytest.approx(2.5)
        a._shard_conn.assert_called_once_with('daily_cache')

    def test_rsi_percentile_hits_shard(self):
        a = _mk_analyzer()
        conn = _Rows({'AVG(rsi14) FROM indicator_other WHERE trade_date=?': [(56.0,)],
                      "date(?, '-60 days')": []})
        a._shard_conn = mock.Mock(return_value=conn)
        # avg_rsi=56 → (56-30)/40 = 0.65
        assert a._compute_rsi_percentile() == pytest.approx(0.65)
        a._shard_conn.assert_called_once_with('indicator_other')

    def test_erp_percentile_hits_shard(self):
        """pe 序列 → erp 分位非 0.5（此前主库无表恒 0.5）"""
        a = _mk_analyzer()
        rows = [('2026-09-12', 40), ('2026-09-14', 20), ('2026-09-15', 15)]
        a._shard_conn = mock.Mock(return_value=_Rows({'AVG(c.pe_ttm)': rows}))
        val = a._compute_erp_percentile()
        assert 0.0 <= val <= 1.0
        assert val != 0.5   # 主库无表时恒 0.5，修复后返回真实分位
        a._shard_conn.assert_called_once_with('daily_basic_cache')

    def test_dv_bond_diff_hits_shard(self):
        """dv 序列 → 股债差分位非 0.5（本次测试暴露的表单）"""
        a = _mk_analyzer()
        rows = [('2026-09-12', 1.2), ('2026-09-14', 1.0), ('2026-09-15', 0.8)]
        a._shard_conn = mock.Mock(return_value=_Rows({'dv_median': rows}))
        val = a._compute_dv_bond_diff()
        assert 0.0 <= val <= 1.0
        assert val != 0.5
        a._shard_conn.assert_called_once_with('daily_basic_cache')

    def test_margin_trend_hits_shard(self):
        a = _mk_analyzer()
        conn = _Rows({"GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5": [
            ('2026-09-15', 110.0), ('2026-09-14', 100.0),
            ('2026-09-11', 95.0), ('2026-09-10', 90.0), ('2026-09-09', 85.0),
        ]})
        a._shard_conn = mock.Mock(return_value=conn)
        # newest=110, oldest=85 → change=(110-85)/85=0.294 → 0.5+2.94=3.44 → clamp 1.0
        assert a._compute_margin_trend() == pytest.approx(1.0)
        a._shard_conn.assert_called_once_with('margin_cache')

    def test_slow_line_fallback_composes_real_components(self):
        """market_stats 缺 dv_bond_diff → 走分库回退而非 0.5，慢线仍由真实成分构成"""
        a = _mk_analyzer()
        a._market_stats = {'erp_percentile': 0.5, 'margin_trend': 0.5}   # 缺 dv_bond_diff
        a._compute_erp_percentile = mock.Mock(return_value=1.0)
        a._compute_margin_trend = mock.Mock(return_value=1.0)
        a._compute_dv_bond_diff = mock.Mock(return_value=0.0)
        val = a._compute_slow_line()
        # ERP(0.5→0.5) + 融资(0.5) + dv_bond(0→1.0) → 均值 0.6667
        assert val == pytest.approx(0.6667, abs=1e-3)
        a._compute_dv_bond_diff.assert_called_once_with()
