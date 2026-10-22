"""538 P2：板块涨跌家数/领涨股回归。"""
import app.data.akshare_reader as ak_mod
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeECM:
    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            return pd.DataFrame([
                {'ts_code': '000001.SZ', 'pct_chg': 3.0},
                {'ts_code': '000002.SZ', 'pct_chg': 1.0},
                {'ts_code': '000003.SZ', 'pct_chg': -2.0},
                {'ts_code': '000004.SZ', 'pct_chg': 0.0},
            ])
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, ecm):
        self.cache = ecm


def test_sector_changes_counts_and_lead(monkeypatch):
    svc = DashboardService()
    svc._data_manager = _FakeDM(_FakeECM())
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000: '2026-10-21')
    monkeypatch.setattr(svc, '_get_sector_streaks',
                        lambda **kw: {'up': [], 'down': []})
    monkeypatch.setattr(svc, '_get_sector_history_20d',
                        lambda **kw: {'dates': [], 'industries': {}, 'avg': []})
    monkeypatch.setattr(ak_mod.reader, 'get_sector_rankings', lambda **kw: [])
    monkeypatch.setattr(
        'app.data.sw_industry_map.get_sw_industry_map',
        lambda ecm=None: {'000001': '银行', '000002': '银行',
                          '000003': '电子', '000004': '电子'})
    monkeypatch.setattr(svc, '_get_stock_names', lambda codes: {
        '000001.SZ': {'name': '甲'}, '000002.SZ': {'name': '乙'},
        '000003.SZ': {'name': '丙'}, '000004.SZ': {'name': '丁'}})

    res = svc.get_sector_changes()
    assert res is not None
    assert res['date'] == '2026-10-21'

    gainers = {x['name']: x for x in res['gainers']}
    assert gainers['银行']['up_count'] == 2
    assert gainers['银行']['down_count'] == 0
    assert gainers['银行']['lead_stock'] == '甲'

    losers = {x['name']: x for x in res['losers']}
    assert losers['电子']['up_count'] == 0
    assert losers['电子']['down_count'] == 1
    assert losers['电子']['lead_stock'] == '丁'
