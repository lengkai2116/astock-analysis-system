"""533 号批次3 定向测试：5日行业资金×涨跌 + 30日ETF份额 + 30日融资。"""
import app.data.sw_industry_map as sw_mod
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeECM:
    def __init__(self, mf=None, fund=None, fund_top=None, names=None, margin=None):
        self.mf = mf if mf is not None else pd.DataFrame()
        self.fund = fund if fund is not None else pd.DataFrame()
        self.fund_top = fund_top if fund_top is not None else pd.DataFrame()
        self.names = names if names is not None else pd.DataFrame()
        self.margin = margin if margin is not None else pd.DataFrame()

    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': [
                '2026-10-14', '2026-10-15', '2026-10-16',
                '2026-10-19', '2026-10-20']})
        if table == 'moneyflow_cache':
            return self.mf
        if table == 'fund_share_cache':
            return self.fund_top if 'JOIN fund_share_cache' in sql else self.fund
        if table == 'etf_industry_map':
            return self.names
        if table == 'margin_cache':
            return self.margin
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, **kw):
        self.cache = _FakeECM(**kw)


def _svc(monkeypatch, **kw):
    svc = DashboardService()
    svc._data_manager = _FakeDM(**kw)
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000:
                        '2026-10-19' if before == '2026-10-20' else '2026-10-20')
    monkeypatch.setattr(svc, '_get_sector_history_20d', lambda **kw: {
        'dates': ['2026-10-14', '2026-10-15', '2026-10-16',
                  '2026-10-19', '2026-10-20'],
        'industries': {'计算机': [1.0, 2.0, -1.0, 0.0, 3.0],
                       '电子': [-1.0, -2.0, 0.0, 1.0, -1.0]},
        'avg': [0.0] * 5,
    })
    monkeypatch.setattr(sw_mod, 'get_sw_industry_map', lambda ecm=None: {
        '003029': '计算机', '002028': '电子',
    })
    return svc


def _mf_df():
    return pd.DataFrame([
        {'ts_code': '003029.SZ', 'buy_lg_amount': 10000,
         'buy_elg_amount': 5000, 'sell_lg_amount': 2000,
         'sell_elg_amount': 1000},
        {'ts_code': '002028.SZ', 'buy_lg_amount': 1000,
         'buy_elg_amount': 0, 'sell_lg_amount': 3000,
         'sell_elg_amount': 2000},
    ])


def _fund_df():
    return pd.DataFrame([
        {'trade_date': '2026-10-16', 'total_share': 1000000},
        {'trade_date': '2026-10-19', 'total_share': 1010000},
        {'trade_date': '2026-10-20', 'total_share': 1000000},
    ])


def _fund_top_df():
    return pd.DataFrame([{'ts_code': '588000.SH', 'delta': 50000}])


def _names_df():
    return pd.DataFrame([{'ts_code': '588000.SH', 'fund_name': '科创50ETF'}])


def _margin_df():
    return pd.DataFrame([
        {'trade_date': '2026-10-16', 'rzye': 10_000_000_000,
         'rzmje': 1_000_000_000, 'rzrqye': 10_100_000_000},
        {'trade_date': '2026-10-19', 'rzye': 10_100_000_000,
         'rzmje': 1_100_000_000, 'rzrqye': 10_200_000_000},
        {'trade_date': '2026-10-20', 'rzye': 9_900_000_000,
         'rzmje': 1_200_000_000, 'rzrqye': 10_000_000_000},
    ])


def test_industry_flow_5d(monkeypatch):
    svc = _svc(monkeypatch, mf=_mf_df())
    res = svc.get_market_flows_30d()
    assert res is not None
    rows = {x['industry']: x for x in res['industry_flow_5d']['industries']}
    assert rows['计算机']['net_inflow_5d'] == 1.2
    assert rows['计算机']['change_5d'] == 5.0
    assert rows['电子']['net_inflow_5d'] == -0.4
    assert rows['电子']['change_5d'] == -3.0


def test_etf_30d(monkeypatch):
    svc = _svc(monkeypatch, fund=_fund_df(), fund_top=_fund_top_df(),
               names=_names_df())
    res = svc.get_market_flows_30d()
    e = res['etf_30d']
    assert e['dates'] == ['2026-10-19', '2026-10-20']
    assert e['net_share'] == [1.0, -1.0]
    assert e['cumulative_net_share'] == 0.0
    assert e['top_etfs'][0]['name'] == '科创50ETF'
    assert e['top_etfs'][0]['net_share'] == 5.0


def test_margin_30d(monkeypatch):
    svc = _svc(monkeypatch, margin=_margin_df())
    res = svc.get_market_flows_30d()
    m = res['margin_30d']
    assert m['dates'] == ['2026-10-19', '2026-10-20']
    assert m['margin_balance'] == [101.0, 99.0]
    assert m['net_buy'] == [1.0, -2.0]
    assert m['cumulative_net_buy'] == -1.0
    assert m['latest']['margin_balance'] == 99.0
    assert m['latest']['margin_buy'] == 12.0
    assert m['latest']['short_balance'] == 1.0
