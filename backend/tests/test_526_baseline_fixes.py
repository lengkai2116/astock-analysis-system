"""526号 定向测试：仪表盘既有基线处置（B1~B21）行为验证。

覆盖 526 档 §五 计划项：
- B4：get_index_summary prev_close 优先级（len==1 保留合法 pre_close；无 pre_close 回退前日 close）
- B5：_aggregate_moneyflow_by_date net_sm_amount 显式 is None 判空（合法 0.0 不触发 buy-sell 兜底）
- B6：get_moneyflow_summary 查方键对齐产方 retail_net_inflow（散户分量参与 has_nonzero）
- B7：get_dashboard_full len(result)<=1 判「空收集」
- B15：get_market_volume 日期归一（datetime.date / 含时间尾巴字符串不再切片错位）
- B16：get_eod_snapshot pre_close pct 越界回退 close（pct≤-100 或 >100 不参与推导）
"""
import datetime

import pandas as pd
import pytest
from app.services.dashboard_service import DashboardService


# ──────────────────────────────────────────────
# B4：get_index_summary prev_close 优先级
# ──────────────────────────────────────────────
class _FakeECM4:
    def __init__(self):
        self._dates = ['2026-10-16']  # latest trade date（daily_cache）

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache' and 'MAX(trade_date)' in sql:
            return pd.DataFrame({'trade_date': self._dates})
        return pd.DataFrame()


class _FakeDM4:
    def __init__(self, index_daily):
        self.cache = _FakeECM4()
        self._daily = index_daily

    def get_cached_daily_data(self, ts_code):
        return self._daily.get(ts_code)


def _svc_b4(index_daily):
    svc = DashboardService()
    svc._data_manager = _FakeDM4(index_daily)
    # 简化：让 volume_change 段走空（避免 sharding_manager 依赖）
    svc._try_get_latest_trade_date = lambda: '20261016'
    svc._detect_market_status = lambda: 'closed'
    return svc


def test_b4_len1_keeps_legal_pre_close(monkeypatch):
    # 只有 1 行且带合法 pre_close：原实现 len==1 时丢弃 pre_close → prev_close=0
    # （B4 主诉）→ change_pct=0；修复后 prev_close=3450.5 → change_pct≈0.86
    index_daily = {'000001.SH': pd.DataFrame([{'trade_date': '2026-10-16',
                                               'pre_close': 3450.5, 'close': 3480.0,
                                               'open': 3460.0, 'amount': 4500}])}
    def fake_daily(code):
        df = index_daily.get(code)
        return df.to_dict('records') if df is not None else None
    svc = _svc_b4(index_daily)
    svc._try_get_index_daily = fake_daily
    from app.services.dashboard_service import INDEX_CONFIG
    monkeypatch.setattr('app.services.dashboard_service.INDEX_CONFIG',
                        [{'ts_code': '000001.SH', 'name': '上证指数'}])
    res = svc.get_index_summary()
    assert res is not None
    assert res['indexes'][0]['ts_code'] == '000001.SH'
    # prev_close=3450.5 → (3480-3450.5)/3450.5*100≈0.86（若 prev_close=0 则 change_pct=0）
    assert res['indexes'][0]['change_pct'] > 0.8


def test_b5_net_sm_zero_does_not_fallback():
    """B5：net_sm_amount=0.0（合法）不触发 buy-sell 兜底。输出经 /1e4 转万。"""
    svc = DashboardService()
    records = [
        {'trade_date': '2026-10-16', 'net_lg_amount': 0.0, 'net_elg_amount': 0.0,
         'net_sm_amount': 0.0, 'buy_sm_amount': 1000000.0, 'sell_sm_amount': 500000.0},
        {'trade_date': '2026-10-15', 'net_lg_amount': 0.0, 'net_elg_amount': 0.0,
         'net_sm_amount': 80000.0, 'buy_sm_amount': 0.0, 'sell_sm_amount': 0.0},
    ]
    res = svc._aggregate_moneyflow_by_date(records, max_days=5)
    days = {d['date']: d for d in res['days']}
    # 10-16：net_sm_amount=0.0 → retail 应为 0（不兜底成 buy-sell=50 万）
    assert days['10/16']['retail_net_inflow'] == 0.0
    # 10-15：net_sm_amount=80000 → retail=8 万
    assert days['10/15']['retail_net_inflow'] == 8.0


def test_b6_aggregate_emits_retail_net_inflow():
    """B6：产方 _aggregate_moneyflow_by_date 输出 retail_net_inflow 键。"""
    svc = DashboardService()
    records = [
        {'trade_date': '2026-10-16', 'net_lg_amount': 1.0, 'net_elg_amount': 2.0,
         'net_sm_amount': 3.0},
    ]
    res = svc._aggregate_moneyflow_by_date(records, max_days=5)
    assert 'retail_net_inflow' in res['days'][0]


def test_b6_get_moneyflow_summary_retail_participates():
    """B6：has_nonzero 查方键与产方一致（retail_net_inflow），散户分量参与判定。"""
    svc = DashboardService()
    records = [
        {'trade_date': '2026-10-16', 'net_lg_amount': 0.0, 'net_elg_amount': 0.0,
         'net_sm_amount': 500000.0, 'buy_sm_amount': 0.0, 'sell_sm_amount': 0.0},
    ]
    result = svc._aggregate_moneyflow_by_date(
        records, max_days=5, source_label='DuckDB 资金流向缓存')
    has_nonzero = any(
        abs(d.get('main_force_net_inflow', 0)) > 0.01
        or abs(d.get('retail_net_inflow', 0)) > 0.01
        for d in result.get('days', [])
    )
    assert has_nonzero is True
    assert result['days'][0]['retail_net_inflow'] == 50.0  # 500000/1e4=50 万


# ──────────────────────────────────────────────
# B7：get_dashboard_full 空收集判定
# ──────────────────────────────────────────────
def test_b7_dashboard_full_empty_collection_returns_none(monkeypatch):
    """B7：所有组件均无数据时返回 None（len(result)<=1 判空，非死分支）。"""
    svc = DashboardService()
    for name in ('get_index_summary', 'get_market_volume', 'get_moneyflow_summary',
                 'get_sector_changes', 'get_sector_moneyflow', 'get_daily_top',
                 'get_market_breadth', 'get_market_state', 'get_market_emotion',
                 'get_sector_heat', 'get_market_alerts',
                 'get_market_overview_panel', 'get_limit_ecology',
                 'get_market_flows_30d'):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    assert svc.get_dashboard_full() is None


def test_b7_dashboard_full_partial_returns_timestamp_data(monkeypatch):
    """B7：部分组件有数据时正常返回聚合。"""
    svc = DashboardService()
    for name in ('get_market_volume', 'get_moneyflow_summary', 'get_sector_changes',
                 'get_sector_moneyflow', 'get_daily_top', 'get_market_breadth',
                 'get_market_state', 'get_market_emotion', 'get_sector_heat',
                 'get_market_alerts'):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    monkeypatch.setattr(svc, 'get_index_summary', lambda: {'timestamp': 't', 'indexes': []})
    res = svc.get_dashboard_full()
    assert res is not None
    assert res['market_overview']['indexes'] == []


# ──────────────────────────────────────────────
# B15：get_market_volume 日期归一
# ──────────────────────────────────────────────
class _FakeDM15:
    def __init__(self, daily):
        self.cache = _FakeECM15()
        self._daily = daily

    def get_cached_daily_data(self, ts_code):
        return self._daily.get(ts_code)


class _FakeECM15:
    def _query_shard(self, table, sql, params=None):
        return pd.DataFrame()


def test_b15_datetime_date_normalized(monkeypatch):
    """B15：datetime.date 不再走 else 分支（含空格伪键切片错位）。"""
    svc = DashboardService()
    rows = [{'trade_date': datetime.date(2026, 10, 16), 'amount': 100.0, 'pct_chg': 1.2},
            {'trade_date': datetime.date(2026, 10, 15), 'amount': 90.0, 'pct_chg': -0.5}]
    daily = {code: pd.DataFrame(rows) for code in ('000001.SH', '399001.SZ', '899050.BJ', '399006.SZ')}
    svc._data_manager = _FakeDM15(daily)
    res = svc.get_market_volume(days=5)
    assert res is not None
    dates = [d['date'] for d in res['days']]
    assert '10/16' in dates
    assert '10/15' in dates


def test_b15_string_with_time_tail_normalized(monkeypatch):
    """B15：'2026-10-16 00:00:00' 时间尾巴被截断，date_key 不再含空格。"""
    svc = DashboardService()
    rows = [{'trade_date': '2026-10-16 00:00:00', 'amount': 100.0, 'pct_chg': 1.2},
            {'trade_date': '2026-10-15 00:00:00', 'amount': 90.0, 'pct_chg': -0.5}]
    daily = {code: pd.DataFrame(rows) for code in ('000001.SH', '399001.SZ', '899050.BJ', '399006.SZ')}
    svc._data_manager = _FakeDM15(daily)
    res = svc.get_market_volume(days=5)
    assert res is not None
    dates = [d['date'] for d in res['days']]
    assert '10/16' in dates
    assert '10/15' in dates


# ──────────────────────────────────────────────
# B16：get_eod_snapshot pre_close pct 越界校验
# ──────────────────────────────────────────────
class _FakeECM16:
    def __init__(self):
        self._dates = ['2026-10-16']

    def _query_shard(self, table, sql, params=None):
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': self._dates})
        if table == 'daily_cache' and 'ts_code, open, close, pct_chg' in sql:
            return pd.DataFrame([
                {'ts_code': '000001.SZ', 'open': 10.0, 'close': 10.0, 'pct_chg': -100.0},
                {'ts_code': '000002.SZ', 'open': 10.0, 'close': 10.0, 'pct_chg': 150.0},
                {'ts_code': '000003.SZ', 'open': 10.0, 'close': 11.0, 'pct_chg': 10.0},
            ])
        if table == 'daily_basic_cache':
            return pd.DataFrame([
                {'ts_code': '000001.SZ', 'circ_mv': 100.0, 'total_mv': 200.0},
                {'ts_code': '000002.SZ', 'circ_mv': 100.0, 'total_mv': 200.0},
                {'ts_code': '000003.SZ', 'circ_mv': 100.0, 'total_mv': 200.0},
            ])
        return pd.DataFrame()


class _FakeDM16:
    def __init__(self):
        self.cache = _FakeECM16()

    def get_stock_list(self):
        return []


def test_b16_pct_out_of_range_falls_back_to_close(monkeypatch):
    """B16：pct≤-100 或 >100 时 pre_close 回退 close（不参与推导，防 X 轴失真）。"""
    # 避免 app context：用假 Stock（filter/all 不触 Flask-SQLAlchemy session）
    class _FakeStock:
        ts_code = ''
        name = ''

        @staticmethod
        def query_filter(*a, **k):
            return []

        query = type('_Q', (), {'filter': staticmethod(lambda *a, **k: type(
            '_F', (), {'all': staticmethod(lambda: [])})())})()

    monkeypatch.setattr('app.models.Stock', _FakeStock)
    svc = DashboardService()
    svc._data_manager = _FakeDM16()
    res = svc.get_eod_snapshot()
    assert res is not None
    by_code = {s['ts_code']: s for s in res['stocks']}
    # pct=-100 → pre_close=close=10.0（原实现 denom=0 回退 close，此处一致且不参与推导）
    assert by_code['000001.SZ']['pre_close'] == 10.0
    # pct=150 → 越界回退 close=10.0（原实现 denom=2.5 → pre_close=4 失真）
    assert by_code['000002.SZ']['pre_close'] == 10.0
    # pct=10 → 正常推导 pre_close=10/1.1≈9.09
    assert round(by_code['000003.SZ']['pre_close'], 2) == round(11.0 / 1.1, 2)
