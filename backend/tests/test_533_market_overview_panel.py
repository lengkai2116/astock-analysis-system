"""533 号批次1 定向测试：大盘总览面板（前一交易日日终 + 涨跌平 + 近5日强弱家数）。"""
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeECM:
    def __init__(self, dates=None, df=None):
        self._dates = dates or []
        self._df = df if df is not None else pd.DataFrame()

    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': self._dates})
        if table == 'daily_cache':
            return self._df
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, dates=None, df=None):
        self.cache = _FakeECM(dates, df)


def _build_svc(dates, df, monkeypatch):
    svc = DashboardService()
    svc._data_manager = _FakeDM(dates, df)

    def _best(before=None, min_stocks=1000):
        return '2026-10-19' if before == '2026-10-20' else '2026-10-20'

    monkeypatch.setattr(svc, '_get_best_trade_date', _best)
    return svc


def test_overview_panel_counts_and_5d_series(monkeypatch):
    dates = ['2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19', '2026-10-20']
    rows = []
    # 10-20：涨2/跌2/平0，≥5% 1 只、≤-5% 1 只
    for pct in (6.0, 2.0, -6.0, -1.0):
        rows.append({'trade_date': '2026-10-20', 'pct_chg': pct})
    # 10-19：涨1/跌1/平1，≥5% 1 只、≤-5% 1 只
    for pct in (5.0, 1.0, -5.0):
        rows.append({'trade_date': '2026-10-19', 'pct_chg': pct})
    for d in dates[:3]:
        rows.append({'trade_date': d, 'pct_chg': 1.0})

    svc = _build_svc(dates, pd.DataFrame(rows), monkeypatch)
    res = svc.get_market_overview_panel()

    assert res is not None
    assert res['as_of'] == '2026-10-20'
    assert res['prev_trade_date'] == '2026-10-19'
    b = res['breadth']
    assert b['count'] == 4
    assert b['up_count'] == 2
    assert b['down_count'] == 2
    assert b['flat_count'] == 0
    assert b['up_ratio'] == 50.0
    assert b['strong_count'] == 1
    assert b['weak_count'] == 1
    sw = res['strong_weak_5d']
    assert sw['dates'] == dates
    assert len(sw['strong']) == 5
    assert sw['strong'][-1] == 1
    assert sw['weak'][-1] == 1
    assert sw['thresholds'] == {'strong': 5, 'weak': -5}


def test_overview_panel_empty_returns_none(monkeypatch):
    svc = _build_svc([], pd.DataFrame(), monkeypatch)
    assert svc.get_market_overview_panel() is None


def test_overview_panel_no_basic_join_returns_none(monkeypatch):
    dates = ['2026-10-20']
    svc = _build_svc(dates, pd.DataFrame(), monkeypatch)
    assert svc.get_market_overview_panel() is None
