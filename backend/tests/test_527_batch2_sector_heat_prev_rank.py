"""527号 批次2 定向测试：板块热度排名变化（get_sector_heat prev_rank）。

- `DashboardService.get_sector_heat`：新增 `prev_rank`（前一日 rank）——读
  sector_heat_cache 上一 stat_date 全行业对比，供前端「排名变化/新进榜」说明
  （527 号 Q1~Q5 拍板：一句话趋势 + 批次1/2 为主）。
- 前端 `applySectorHeat`：prev_rank 存在时显示 ↑n/↓n/—，prev_rank=None 显示「新进榜」。
"""
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeECM:
    """模拟 cache：get_cached_sector_heat 支持 stat_date + _query_shard（MAX/DISTINCT）。"""

    def __init__(self, heat_by_date):
        self._heat = heat_by_date   # {'2026-10-16': {...}, '2026-10-15': {...}}
        self._dates = ['2026-10-16', '2026-10-15']

    def get_cached_sector_heat(self, stat_date=None):
        if stat_date is None:
            stat_date = self._dates[0]
        return self._heat.get(stat_date, {})

    # 530号 批次2：get_sector_heat 优先读资金热度表，此桩无资金数据 → 返回空回落趋势表
    def get_cached_sector_fund_heat(self, stat_date=None):
        return {}

    def _query_shard(self, table, sql, params=None):
        if table == 'sector_heat_cache':
            if 'DISTINCT stat_date' in sql:
                return pd.DataFrame({'stat_date': self._dates})
            if 'MAX(stat_date)' in sql:
                return pd.DataFrame({'d': [self._dates[0]]})
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, heat_by_date):
        self.cache = _FakeECM(heat_by_date)


def _svc():
    heat_16 = {
        '半导体': {'heat_level': 'top_10', 'strength': 0.85, 'rank': 1, 'stock_count': 130},
        '白酒': {'heat_level': 'top_20', 'strength': 0.4, 'rank': 5, 'stock_count': 19},
        '银行': {'heat_level': 'top_30', 'strength': 0.2, 'rank': 12, 'stock_count': 42},
    }
    heat_15 = {
        '半导体': {'heat_level': 'top_10', 'strength': 0.8, 'rank': 3, 'stock_count': 130},   # 前日 rank3 → 今日1（上升2位）
        '白酒': {'heat_level': 'top_20', 'strength': 0.4, 'rank': 5, 'stock_count': 19},     # 前日 rank5 → 今日5（持平）
        '银行': {'heat_level': 'top_30', 'strength': 0.2, 'rank': 8, 'stock_count': 42},     # 前日 rank8 → 今日12（下降4位）
    }
    svc = DashboardService()
    svc._data_manager = _FakeDM({'2026-10-16': heat_16, '2026-10-15': heat_15})
    return svc


def test_sector_heat_prev_rank_attached():
    res = _svc().get_sector_heat(top_n=8)
    assert res is not None
    assert res['date'] == '2026-10-16'
    by_ind = {s['industry']: s for s in res['sectors']}
    # 半导体：今日 rank=1，前日 rank=3 → prev_rank=3（排名上升）
    assert by_ind['半导体']['prev_rank'] == 3
    # 白酒：rank=5，前日 rank=5 → prev_rank=5（持平）
    assert by_ind['白酒']['prev_rank'] == 5
    # 银行：rank=12，前日 rank=8 → prev_rank=8（排名下降）
    assert by_ind['银行']['prev_rank'] == 8


def test_sector_heat_prev_rank_new_entrant():
    # 今日新进板块（前日无该行业）→ prev_rank=None → 前端显示「新进榜」
    svc = DashboardService()
    svc._data_manager = _FakeDM({
        '2026-10-16': {'新板块': {'heat_level': 'top_10', 'strength': 0.9, 'rank': 2, 'stock_count': 5}},
        '2026-10-15': {'半导体': {'heat_level': 'top_10', 'strength': 0.8, 'rank': 1, 'stock_count': 130}},
    })
    res = svc.get_sector_heat(top_n=8)
    assert res is not None
    assert res['sectors'][0]['industry'] == '新板块'
    assert res['sectors'][0]['prev_rank'] is None


def test_sector_heat_prev_rank_single_day_only():
    # 仅一天数据（无前日）→ prev_rank=None
    svc = DashboardService()
    svc._data_manager = _FakeDM({
        '2026-10-16': {'半导体': {'heat_level': 'top_10', 'strength': 0.85, 'rank': 1, 'stock_count': 130}},
    })
    svc._data_manager.cache._dates = ['2026-10-16']
    res = svc.get_sector_heat(top_n=8)
    assert res is not None
    assert res['sectors'][0]['prev_rank'] is None


def test_sector_heat_route_registered():
    from app.routes import dashboard as _dash
    assert hasattr(_dash, 'get_sector_heat')
