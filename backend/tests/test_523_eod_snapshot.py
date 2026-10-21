"""523号 批次1 定向测试：全市场日终散点接口（eod-snapshot）。

- `DashboardService.get_eod_snapshot`：daily_cache ⋈ daily_basic_cache（最新交易日），
  inner join 天然排除指数；pre_close 由 pct_chg 精确推导（close/(1+pct_chg/100)）。
- 路由 `/api/v3/market/eod-snapshot` 存在。
"""
import pandas as pd
from app.services.dashboard_service import DashboardService


class _FakeECM:
    """模拟 cache._query_shard：daily_cache 含指数行，daily_basic_cache 仅股票。"""

    def __init__(self, daily_df, basic_df):
        self._daily = daily_df
        self._basic = basic_df

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            if 'DISTINCT trade_date' in sql:
                return pd.DataFrame({'trade_date': ['2026-10-16']})
            return self._daily
        if table == 'daily_basic_cache':
            return self._basic
        return pd.DataFrame()


class _FakeDM:
    """模拟 DataManager：cache + get_stock_list（Stock.query 无 app_context 时兜底）。"""

    def __init__(self, daily_df, basic_df):
        self.cache = _FakeECM(daily_df, basic_df)

    def get_stock_list(self):
        return [
            {'ts_code': '000001.SZ', 'name': '平安银行'},
            {'ts_code': '600000.SH', 'name': '浦发银行'},
        ]


def _daily_df():
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH', '000001.SH'],  # 末行＝指数，应被 join 排除
        'open': [11.0, 10.0, 3000.0],
        'close': [11.5, 10.5, 3010.0],
        'pct_chg': [5.0, -2.0, 0.5],
    })


def _basic_df():
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH'],
        'circ_mv': [2.0e6, 3.0e6],
        'total_mv': [2.5e6, 3.5e6],
    })


def _svc():
    svc = DashboardService()
    svc._data_manager = _FakeDM(_daily_df(), _basic_df())
    # 534：get_eod_snapshot 改为 _get_best_trade_date(before=today) 锚定，
    # 该测试桩固定上一完整交易日 2026-10-16。
    svc._get_best_trade_date = lambda before=None, min_stocks=1000: '2026-10-16'
    return svc


def test_eod_snapshot_excludes_index_and_fields():
    res = _svc().get_eod_snapshot()
    assert res is not None
    assert res['trade_date'] == '2026-10-16'
    assert res['count'] == 2
    codes = {s['ts_code'] for s in res['stocks']}
    assert codes == {'000001.SZ', '600000.SH'}
    assert '000001.SH' not in codes  # 指数行被 inner join 排除
    s0 = res['stocks'][0]
    assert {'ts_code', 'name', 'open', 'close', 'pre_close',
            'pct_chg', 'circ_mv', 'total_mv'} <= set(s0.keys())


def test_eod_snapshot_pre_close_self_consistent():
    res = _svc().get_eod_snapshot()
    for s in res['stocks']:
        expect = s['pre_close'] * (1 + s['pct_chg'] / 100.0)
        assert abs(s['close'] - expect) < 0.01, s


def test_eod_snapshot_names_filled():
    res = _svc().get_eod_snapshot()
    by_code = {s['ts_code']: s['name'] for s in res['stocks']}
    assert by_code['000001.SZ'] == '平安银行'
    assert by_code['600000.SH'] == '浦发银行'


def test_eod_snapshot_route_registered():
    from app.routes import dashboard as _dash
    assert hasattr(_dash, 'get_eod_snapshot')
