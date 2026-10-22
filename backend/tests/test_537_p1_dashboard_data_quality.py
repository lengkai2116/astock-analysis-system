"""537 P1：仪表盘数据可用性/覆盖度回归。"""
import app.data.akshare_reader as ak_mod
import app.services.market_sentiment_service as mss_mod
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeDM:
    def __init__(self, ecm):
        self.cache = ecm


def _svc(ecm, monkeypatch, as_of='2026-10-21'):
    svc = DashboardService()
    svc._data_manager = _FakeDM(ecm)
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000: as_of)
    return svc


class _DailyTopECM:
    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            return pd.DataFrame([
                {'ts_code': f'30000{i}.SZ', 'close': 10.0 + i,
                 'pct_chg': 10.0 - i}
                for i in range(10)
            ])
        return pd.DataFrame()


def test_daily_top_names_fallback_without_full_orm(monkeypatch):
    svc = _svc(_DailyTopECM(), monkeypatch)
    monkeypatch.setattr(ak_mod.reader, 'get_top_stocks', lambda **kw: [])
    monkeypatch.setattr(svc, '_get_stock_names', lambda codes: {
        code: {'name': f'名称{code[:3]}', 'industry': ''} for code in codes})

    res = svc.get_daily_top(type='up', limit=10)
    assert res is not None
    assert len(res['stocks']) == 10
    assert all(s['name'] for s in res['stocks'])
    assert all(s['name'] != s['ts_code'] for s in res['stocks'])


class _MissingLimitECM:
    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': [
                '2026-10-15', '2026-10-16', '2026-10-19',
                '2026-10-20', '2026-10-21']})
        if table == 'limit_detail_cache':
            return pd.DataFrame()
        if table == 'daily_cache':
            return pd.DataFrame()
        return pd.DataFrame()


def test_limit_ecology_marks_missing_detail(monkeypatch):
    svc = _svc(_MissingLimitECM(), monkeypatch)
    monkeypatch.setattr('app.data.sw_industry_map.get_sw_industry_map',
                        lambda ecm=None: {})
    res = svc.get_limit_ecology()
    assert res is not None
    assert res['data_available'] is False
    assert res['limit_detail_count'] == 0
    assert res['up']['count'] == 0


def test_emotion_missing_detail_is_not_ice(monkeypatch):
    svc = _svc(_MissingLimitECM(), monkeypatch)
    monkeypatch.setattr(svc, 'get_limit_ecology', lambda: {
        'as_of': '2026-10-21', 'data_available': False,
        'limit_detail_count': 0,
        'up': {'count': 0}, 'down': {'count': 5},
        'boards': {'max_height': 0},
        'sealing_5d': {'rows': []},
    })

    class _FakeMSS:
        def __init__(self, dm=None):
            pass

        def get_sentiment_phase(self, trade_date=None, metrics_override=None):
            return {'phase': 'neutral', 'phase_label': '情绪中性',
                    'metrics': {}, 'data_available': False}

    monkeypatch.setattr(mss_mod, 'MarketSentimentService', _FakeMSS)
    res = svc.get_market_emotion()
    assert res is not None
    assert res['data_available'] is False
    assert res['phase'] == 'neutral'
    assert res['metrics'] == {}


def test_alerts_suppress_ice_when_data_unavailable(monkeypatch):
    svc = DashboardService()
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: {
        'phase': 'ice', 'phase_label': '情绪冰点',
        'metrics': {}, 'data_available': False})
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: None)
    res = svc.get_market_alerts()
    assert res is not None
    assert 'ice_window' not in [a['type'] for a in res['alerts']]


def test_split_complete_rows_drops_coverage_cliff():
    rows = [
        {'date': '2026-10-20', 'n': 4481},
        {'date': '2026-10-21', 'n': 2366},
    ]
    kept, partial = DashboardService._split_complete_rows(rows)
    assert kept == [{'date': '2026-10-20', 'n': 4481}]
    assert partial == ['2026-10-21']


class _FlowsECM:
    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': [
                '2026-10-15', '2026-10-16', '2026-10-19',
                '2026-10-20', '2026-10-21']})
        if table == 'fund_share_cache':
            if 'JOIN fund_share_cache' in sql:
                return pd.DataFrame()
            return pd.DataFrame([
                {'trade_date': '2026-10-19', 'total_share': 1_000_000, 'n': 1798},
                {'trade_date': '2026-10-20', 'total_share': 1_010_000, 'n': 1798},
                {'trade_date': '2026-10-21', 'total_share': 500_000, 'n': 791},
            ])
        if table == 'margin_cache':
            return pd.DataFrame([
                {'trade_date': '2026-10-19', 'rzye': 2_430_000_000_000,
                 'rzmje': 60_000_000_000, 'rzrqye': 2_440_000_000_000,
                 'n': 4481},
                {'trade_date': '2026-10-20', 'rzye': 2_431_820_000_000,
                 'rzmje': 61_000_000_000, 'rzrqye': 2_442_000_000_000,
                 'n': 4481},
                {'trade_date': '2026-10-21', 'rzye': 1_255_770_000_000,
                 'rzmje': 20_000_000_000, 'rzrqye': 1_260_000_000_000,
                 'n': 2366},
            ])
        return pd.DataFrame()


def test_flows_excludes_incomplete_last_day(monkeypatch):
    svc = _svc(_FlowsECM(), monkeypatch)
    monkeypatch.setattr(svc, '_get_sector_history_20d',
                        lambda **kw: {'dates': [], 'industries': {}, 'avg': []})
    monkeypatch.setattr('app.data.sw_industry_map.get_sw_industry_map',
                        lambda ecm=None: {})
    res = svc.get_market_flows_30d()
    assert res is not None

    m = res['margin_30d']
    assert m['dates'][-1] == '2026-10-20'
    assert m['latest']['date'] == '2026-10-20'
    assert m['margin_balance'][-1] == 24318.2
    assert m['partial_dates'] == ['2026-10-21']
    assert m['data_quality'] == 'partial'

    e = res['etf_30d']
    assert e['dates'][-1] == '2026-10-20'
    assert e['partial_dates'] == ['2026-10-21']
    assert e['data_quality'] == 'partial'
