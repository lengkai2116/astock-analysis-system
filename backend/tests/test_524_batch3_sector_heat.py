"""524号 批次3 定向测试：板块热度接口（market/sector-heat）+ dashboard/full 并入。

- `DashboardService.get_sector_heat`：读 `sector_heat_cache`（E1 实证最新日全行业）
  → `{date, count, sectors:[{industry, heat_level, strength, rank, stock_count}]}`，rank 升序。
- 路由 `/api/v3/market/sector-heat` 存在 + 并入 `dashboard/full.sector_heat`。
"""
import pandas as pd
import pytest
from app.services.dashboard_service import DashboardService


class _FakeECM:
    """模拟 cache：get_cached_sector_heat + _query_shard（MAX(stat_date)）。"""

    def __init__(self, heat):
        self._heat = heat

    def get_cached_sector_heat(self, stat_date=None):
        return self._heat

    # 530号 批次2：get_sector_heat 优先读资金热度表，此桩无资金数据 → 返回空回落趋势表
    def get_cached_sector_fund_heat(self, stat_date=None):
        return {}

    def _query_shard(self, table, sql, params=None):
        if table == 'sector_heat_cache':
            return pd.DataFrame({'d': ['2026-10-16']})
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, heat):
        self.cache = _FakeECM(heat)


def _svc():
    heat = {
        '半导体': {'heat_level': 'top_10', 'strength': 0.85, 'rank': 1, 'stock_count': 130},
        '白酒': {'heat_level': 'top_20', 'strength': 0.4, 'rank': 5, 'stock_count': 19},
        '银行': {'heat_level': 'top_30', 'strength': 0.2, 'rank': 12, 'stock_count': 42},
    }
    svc = DashboardService()
    svc._data_manager = _FakeDM(heat)
    return svc


def test_sector_heat_sorted_by_rank():
    res = _svc().get_sector_heat(top_n=8)
    assert res is not None
    assert res['date'] == '2026-10-16'
    assert res['count'] == 3
    # 530号 批次2：趋势表 source 带口径后缀（资金表为空回落趋势表路径）
    assert res['source'].startswith('DuckDB sector_heat_cache')
    ranks = [s['rank'] for s in res['sectors']]
    assert ranks == sorted(ranks)          # rank 升序
    assert res['sectors'][0]['industry'] == '半导体'
    assert res['sectors'][0]['heat_level'] == 'top_10'
    assert res['sectors'][0]['strength'] == 0.85
    assert res['sectors'][0]['stock_count'] == 130


def test_sector_heat_top_n_limit():
    res = _svc().get_sector_heat(top_n=2)
    assert res is not None
    assert len(res['sectors']) == 2
    assert res['sectors'][0]['industry'] == '半导体'


def test_sector_heat_skips_invalid_industry():
    svc = DashboardService()
    svc._data_manager = _FakeDM({'nan': {'heat_level': 'none', 'strength': 0, 'rank': 99, 'stock_count': 0},
                                 '银行': {'heat_level': 'top_10', 'strength': 0.9, 'rank': 2, 'stock_count': 42}})
    res = svc.get_sector_heat(top_n=8)
    assert res['count'] == 1
    assert res['sectors'][0]['industry'] == '银行'


def test_sector_heat_no_data_returns_none():
    svc = DashboardService()
    svc._data_manager = _FakeDM({})
    assert svc.get_sector_heat() is None


def test_sector_heat_route_registered():
    from app.routes import dashboard as _dash
    assert hasattr(_dash, 'get_sector_heat')


def test_dashboard_full_merges_sector_heat(monkeypatch):
    svc = _svc()
    for name in ('get_index_summary', 'get_market_volume', 'get_moneyflow_summary',
                 'get_sector_changes', 'get_sector_moneyflow', 'get_daily_top',
                 'get_market_breadth', 'get_market_state', 'get_market_emotion'):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    res = svc.get_dashboard_full()
    assert res is not None
    assert res['sector_heat'] is not None
    assert res['sector_heat']['count'] == 3
