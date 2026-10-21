"""534 号定向测试：散点/四象限锚定前一完整交易日 + 低样本回退。"""
import pandas as pd
from app.services.dashboard_service import DashboardService


def _stock_frame(n, pct=1.0):
    return pd.DataFrame({
        'ts_code': [f'{i:06d}.SZ' for i in range(n)],
        'open': [10.0] * n,
        'close': [10.1] * n,
        'pct_chg': [pct] * n,
        'circ_mv': [1.0e5] * n,
        'total_mv': [2.0e5] * n,
    })


class _FakeECM:
    def __init__(self, daily, basic):
        self.daily = daily
        self.basic = basic

    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            if table == 'daily_cache':
                dates = sorted(self.daily.keys())
                if params:
                    dates = [d for d in dates if d <= params[0]]
                return pd.DataFrame({'trade_date': dates[-5:]})
            if table == 'daily_basic_cache':
                return pd.DataFrame({'trade_date': sorted(self.basic.keys())})
        if table == 'daily_cache':
            df = self.daily.get(params[0], pd.DataFrame()).copy()
            if df.empty:
                return df
            return df[['ts_code', 'open', 'close', 'pct_chg']]
        if table == 'daily_basic_cache':
            df = self.basic.get(params[0], pd.DataFrame()).copy()
            if df.empty:
                return df
            return df[['ts_code', 'circ_mv', 'total_mv']]
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, ecm):
        self.cache = ecm

    def get_stock_list(self):
        return []


def _svc(ecm, monkeypatch):
    svc = DashboardService()
    svc._data_manager = _FakeDM(ecm)
    monkeypatch.setattr(svc, '_get_best_trade_date',
                        lambda before=None, min_stocks=1000:
                        '2026-10-20' if before == '2026-10-21'
                        else ('2026-10-19' if before == '2026-10-20'
                              else '2026-10-20'))
    return svc


def test_eod_snapshot_anchors_previous_complete_day(monkeypatch):
    """daily_basic 10-21 全量、daily_cache 10-21 仅 1 只 → 必须回到 10-20。"""
    daily = {
        '2026-10-21': _stock_frame(1),
        '2026-10-20': _stock_frame(1001),
        '2026-10-19': _stock_frame(1001),
    }
    basic = {
        '2026-10-21': _stock_frame(1001),
        '2026-10-20': _stock_frame(1001),
        '2026-10-19': _stock_frame(1001),
    }
    svc = _svc(_FakeECM(daily, basic), monkeypatch)
    res = svc.get_eod_snapshot()

    assert res is not None
    assert res['trade_date'] == '2026-10-20'
    assert res['count'] == 1001
    assert res['data_quality'] == 'ok'
    assert all(x['date'] <= '2026-10-20' for x in res['summary_5d'])
    assert max(x['date'] for x in res['summary_5d']) == '2026-10-20'


def test_eod_snapshot_falls_back_when_candidate_low_sample(monkeypatch):
    """若候选日 10-21 join 只有 1 只，自动回退到 10-20 的 1001 只。"""
    daily = {
        '2026-10-21': _stock_frame(1),
        '2026-10-20': _stock_frame(1001),
    }
    basic = {
        '2026-10-21': _stock_frame(1001),
        '2026-10-20': _stock_frame(1001),
    }
    svc = _svc(_FakeECM(daily, basic), monkeypatch)
    # 模拟 _get_best_trade_date 首次误返回 10-21、回退候选给出 10-20
    # （测试低样本守卫本身）。
    _calls = {'n': 0}

    def _fake_best(before=None, min_stocks=1000):
        _calls['n'] += 1
        return '2026-10-21' if _calls['n'] == 1 else '2026-10-20'

    monkeypatch.setattr(svc, '_get_best_trade_date', _fake_best)
    res = svc.get_eod_snapshot()

    assert res is not None
    assert res['trade_date'] == '2026-10-20'
    assert res['count'] == 1001
    assert res['data_quality'] == 'ok'
