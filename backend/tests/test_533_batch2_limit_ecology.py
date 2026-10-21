"""533 号批次2 定向测试：涨停生态（涨跌停对比 + 行业个股 + 昨涨停今表现 + 连板 + 5日封板率）。"""
import app.data.sw_industry_map as sw_mod
import pandas as pd
from app.services.dashboard_service import DashboardService

DATES = ['2026-10-14', '2026-10-15', '2026-10-16',
         '2026-10-19', '2026-10-20']


class _FakeECM:
    def __init__(self, up=None, down=None, prev=None, seal=None):
        self.up = up if up is not None else pd.DataFrame()
        self.down = down if down is not None else pd.DataFrame()
        self.prev = prev if prev is not None else pd.DataFrame()
        self.seal = seal if seal is not None else pd.DataFrame()

    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': DATES})
        if table == 'limit_detail_cache':
            if 'GROUP BY trade_date' in sql:
                return self.seal
            if 'LEFT JOIN daily_cache' in sql:
                return self.prev
            return self.up
        if table == 'daily_cache' and 'stk_limit_cache' in sql:
            return self.down
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, **kw):
        self.cache = _FakeECM(**kw)


def _svc(monkeypatch, **kw):
    svc = DashboardService()
    svc._data_manager = _FakeDM(**kw)

    def _best(before=None, min_stocks=1000):
        return '2026-10-19' if before == '2026-10-20' else '2026-10-20'

    monkeypatch.setattr(svc, '_get_best_trade_date', _best)
    monkeypatch.setattr(svc, '_get_stock_names', lambda codes: {
        '002028.SZ': {'name': '思源电气', 'industry': '电力设备'},
    })
    monkeypatch.setattr(sw_mod, 'get_sw_industry_map', lambda ecm=None: {
        '003029': '计算机', '002724': '电子', '001323': '轻工制造',
        '002028': '电力设备',
    })
    return svc


def _up_df():
    return pd.DataFrame([
        {'ts_code': '003029.SZ', 'name': '吉大正元', 'industry': '软件开发',
         'pct_chg': 10.0, 'limit_times': 4, 'open_times': 4,
         'first_time': '92500', 'last_time': '95730'},
        {'ts_code': '002724.SZ', 'name': '海洋王', 'industry': '照明设备',
         'pct_chg': 9.98, 'limit_times': 3, 'open_times': 3,
         'first_time': '93018', 'last_time': '93845'},
        {'ts_code': '001323.SZ', 'name': '慕思股份', 'industry': '家居用品',
         'pct_chg': 10.0, 'limit_times': 1, 'open_times': 0,
         'first_time': '92500', 'last_time': '92500'},
    ])


def _down_df():
    return pd.DataFrame([
        {'ts_code': '002028.SZ', 'close': 112.59,
         'pct_chg': -10.0, 'low_limit': 112.59},
    ])


def _prev_df():
    return pd.DataFrame([
        {'ts_code': '003029.SZ', 'name': '吉大正元', 'industry': '软件开发',
         'limit_times': 3, 'pct_chg': 5.0},
        {'ts_code': '002724.SZ', 'name': '海洋王', 'industry': '照明设备',
         'limit_times': 1, 'pct_chg': -2.0},
    ])


def _seal_df():
    return pd.DataFrame([
        {'trade_date': '2026-10-14', 'up_cnt': 36, 'zha_cnt': 24},
        {'trade_date': '2026-10-15', 'up_cnt': 36, 'zha_cnt': 7},
        {'trade_date': '2026-10-16', 'up_cnt': 61, 'zha_cnt': 49},
        {'trade_date': '2026-10-19', 'up_cnt': 46, 'zha_cnt': 21},
        {'trade_date': '2026-10-20', 'up_cnt': 54, 'zha_cnt': 29},
    ])


def test_limit_ecology_counts_and_industries(monkeypatch):
    svc = _svc(monkeypatch, up=_up_df(), down=_down_df(),
               prev=_prev_df(), seal=_seal_df())
    res = svc.get_limit_ecology()

    assert res is not None
    assert res['as_of'] == '2026-10-20'
    assert res['prev_trade_date'] == '2026-10-19'
    assert res['up']['count'] == 3
    assert res['down']['count'] == 1
    assert res['down']['stocks'][0]['name'] == '思源电气'
    assert res['down']['stocks'][0]['industry'] == '电力设备'
    up_inds = {x['industry']: x['count'] for x in res['up']['industries']}
    assert up_inds == {'计算机': 1, '电子': 1, '轻工制造': 1}


def test_limit_ecology_prev_limit_up(monkeypatch):
    svc = _svc(monkeypatch, up=_up_df(), down=_down_df(),
               prev=_prev_df(), seal=_seal_df())
    res = svc.get_limit_ecology()
    p = res['prev_limit_up']
    assert p['total'] == 2
    assert p['up_count'] == 1
    assert p['down_count'] == 1
    assert p['win_rate'] == 50.0
    assert p['avg_pct'] == 1.5
    assert p['distribution'][3]['count'] == 1   # ≥5%
    assert p['distribution'][1]['count'] == 1   # -5%~0


def test_limit_ecology_boards_and_sealing(monkeypatch):
    svc = _svc(monkeypatch, up=_up_df(), down=_down_df(),
               prev=_prev_df(), seal=_seal_df())
    res = svc.get_limit_ecology()
    b = res['boards']
    assert b['count'] == 2
    assert b['max_height'] == 4
    assert b['stocks'][0]['name'] == '吉大正元'
    assert b['stocks'][0]['limit_times'] == 4
    assert {x['days']: x['count'] for x in b['distribution']} == {
        1: 1, 3: 1, 4: 1}

    seal = res['sealing_5d']
    assert seal['dates'] == DATES
    assert seal['rows'][-1]['rate'] == 65.1
    assert seal['rows'][0]['rate'] == 60.0


def test_limit_ecology_no_data_returns_none(monkeypatch):
    svc = _svc(monkeypatch, up=pd.DataFrame(), down=pd.DataFrame(),
               prev=pd.DataFrame(), seal=pd.DataFrame())
    res = svc.get_limit_ecology()
    # 有 as_of 与 5 日日期时仍返回空结构（不 503），计数为 0
    assert res is not None
    assert res['up']['count'] == 0
    assert res['down']['count'] == 0
