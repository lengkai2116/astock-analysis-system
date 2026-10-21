"""535 号 P1 定向测试：breadth/daily-top 锚定前一完整交易日 + emotion 统一涨停口径。"""
import app.data.akshare_reader as ak_mod
import app.services.market_sentiment_service as mss_mod
import pandas as pd
from app.services.dashboard_service import DashboardService


def _frame(n=1001):
    return pd.DataFrame({
        'ts_code': [f'{i:06d}.SZ' for i in range(n)],
        'open': [10.0] * n,
        'close': [10.1] * n,
        'pct_chg': [1.0] * n,
    })


class _FakeECM:
    def __init__(self, daily, basic):
        self.daily = daily
        self.basic = basic

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            if 'DISTINCT trade_date' in sql:
                dates = sorted(self.daily.keys())
                if params:
                    dates = [d for d in dates if d <= params[0]]
                return pd.DataFrame({'trade_date': dates[-5:]})
            return self.daily.get(params[0], pd.DataFrame()).copy()
        if table == 'daily_basic_cache':
            if 'DISTINCT trade_date' in sql:
                return pd.DataFrame({'trade_date': sorted(self.basic.keys())})
            df = self.basic.get(params[0], pd.DataFrame()).copy()
            if df.empty:
                return df
            # breadth 只查 ts_code；避免与 daily 的 pct_chg 同名列冲突
            return df[['ts_code']]
        return pd.DataFrame()

    def get_cached_market_stats(self, stat_date=None):
        return {}


class _FakeDM:
    def __init__(self, ecm):
        self.cache = ecm

    def get_stock_list(self):
        return []


def _svc(ecm, monkeypatch):
    svc = DashboardService()
    svc._data_manager = _FakeDM(ecm)
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000: '2026-10-20')
    return svc


def test_breadth_anchors_previous_complete_day(monkeypatch):
    daily = {'2026-10-21': _frame(1), '2026-10-20': _frame(1001)}
    basic = {'2026-10-21': _frame(1001), '2026-10-20': _frame(1001)}
    svc = _svc(_FakeECM(daily, basic), monkeypatch)
    res = svc.get_market_breadth()
    assert res is not None
    assert res['trade_date'] == '2026-10-20'
    assert res['count'] == 1001
    assert res['data_quality'] == 'ok'
    assert res['up_count'] == 1001


def test_daily_top_db_fallback_anchors_previous_day(monkeypatch):
    daily = {'2026-10-21': _frame(1), '2026-10-20': _frame(1001)}
    basic = {'2026-10-21': _frame(1001), '2026-10-20': _frame(1001)}
    svc = _svc(_FakeECM(daily, basic), monkeypatch)
    # 阻断 AKShare 实时分支，强制走 DB 降级
    monkeypatch.setattr(ak_mod.reader, 'get_top_stocks', lambda **kw: [])

    res = svc.get_daily_top(type='up', limit=10)
    assert res is not None
    assert res['date'] == '2026-10-20'
    assert res['source'] == 'DuckDB 盘后数据（前一完整交易日）'
    assert len(res['stocks']) == 10


def test_market_emotion_uses_limit_ecology_metrics(monkeypatch):
    svc = DashboardService()
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000: '2026-10-20')
    monkeypatch.setattr(svc, 'get_limit_ecology', lambda: {
        'as_of': '2026-10-20',
        'up': {'count': 54},
        'down': {'count': 7},
        'boards': {'max_height': 4},
        'sealing_5d': {'rows': [{'date': '2026-10-20', 'rate': 65.1}]},
    })

    captured = {}

    class _FakeMSS:
        def __init__(self, dm=None):
            pass

        def get_sentiment_phase(self, trade_date=None, metrics_override=None):
            captured.update(metrics_override or {})
            return {
                'phase': 'ferment',
                'phase_label': '情绪发酵',
                'metrics': metrics_override or {},
                'data_available': True,
            }

    monkeypatch.setattr(mss_mod, 'MarketSentimentService', _FakeMSS)
    res = svc.get_market_emotion()

    assert res is not None
    assert res['metrics']['limit_up_count'] == 54
    assert res['metrics']['limit_down_count'] == 7
    assert res['metrics']['max_board_height'] == 4
    assert captured['sealing_rate'] == 65.1
    assert 'limit_detail_cache' in res['source']


def test_classify_phase_same_thresholds():
    mss = mss_mod.MarketSentimentService()
    assert mss._classify_phase({
        'limit_up_count': 54, 'limit_down_count': 7,
        'max_board_height': 4, 'sealing_rate': 65.1,
    }) == 'ferment'
