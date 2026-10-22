"""541号 B2 定向测试。

覆盖：
- OUT 成品仓读取模式 off/prefer/strict；
- last-valid 元信息与 stale 判定；
- 请求参数切片（指数/资金/榜单/板块/热度）；
- `/dashboard/full` 的 EOD 模块已改走 reader。
"""
import pytest
from app.services import out_market_reader as omr


def _panel(asof='20261022', payload=None):
    return {
        'module': 'market_state',
        'asof_date': asof,
        'payload': payload if payload is not None else {'state': 'ranging'},
        'data_dates': {'data_date': asof},
        'schema_version': 1,
        'built_at': '2026-10-22 18:00:00',
    }


# ── 元信息 / stale ──────────────────────────────────────

def test_attach_meta_not_stale():
    out = omr.attach_meta({'state': 'ranging'}, _panel('20261022'),
                          expected_date='20261022')
    assert out['panel_source'] == 'out'
    assert out['panel_date'] == '20261022'
    assert out['panel_built_at'] == '2026-10-22 18:00:00'
    assert out['stale'] is False


def test_attach_meta_stale_when_panel_older():
    out = omr.attach_meta({'state': 'ranging'}, _panel('20261021'),
                          expected_date='2026-10-22')
    assert out['stale'] is True


def test_attach_meta_normalizes_actual_date():
    out = omr.attach_meta({'state': 'ranging'}, _panel('2026-10-21'),
                          expected_date='20261022')
    assert out['stale'] is True


def test_expected_date_does_not_cache_failure(monkeypatch):
    class _DM:
        def __init__(self):
            self.calls = 0

        def get_snapshot_data_date(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('db busy')
            return '20261022'

    dm = _DM()
    monkeypatch.setattr(omr, '_data_manager', lambda: dm)
    monkeypatch.setitem(omr._EXPECTED_CACHE, 'at', 0.0)
    monkeypatch.setitem(omr._EXPECTED_CACHE, 'value', None)

    assert omr._expected_date() is None
    assert omr._expected_date() == '20261022'
    assert dm.calls == 2


# ── 读取模式 ────────────────────────────────────────────

def test_prefer_reads_panel(monkeypatch):
    monkeypatch.setenv('OUT_MARKET_PANEL_MODE', 'prefer')
    monkeypatch.setattr(omr, 'load_panel', lambda module, asof_date=None: _panel())

    called = {'legacy': False}

    def _legacy():
        called['legacy'] = True
        return {'state': 'legacy'}

    out = omr.get_out_or_legacy('market_state', _legacy, expected_date='20261022')
    assert out['state'] == 'ranging'
    assert out['panel_source'] == 'out'
    assert called['legacy'] is False


def test_prefer_falls_back_and_marks_legacy(monkeypatch):
    monkeypatch.setenv('OUT_MARKET_PANEL_MODE', 'prefer')
    monkeypatch.setattr(omr, 'load_panel', lambda module, asof_date=None: None)

    out = omr.get_out_or_legacy(
        'market_state', lambda: {'state': 'legacy', 'source': 'daily_cache'})
    assert out['state'] == 'legacy'
    assert out['source'] == 'daily_cache'
    assert out['panel_source'] == 'legacy'
    assert out['panel_missing'] is True
    assert out['stale'] is True


def test_strict_missing_returns_none(monkeypatch):
    monkeypatch.setenv('OUT_MARKET_PANEL_MODE', 'strict')
    monkeypatch.setattr(omr, 'load_panel', lambda module, asof_date=None: None)

    assert omr.get_out_or_legacy(
        'market_state', lambda: {'state': 'legacy'}) is None


def test_off_bypasses_panel(monkeypatch):
    monkeypatch.setenv('OUT_MARKET_PANEL_MODE', 'off')

    def _boom(*args, **kwargs):
        raise AssertionError('off 模式不应读取成品仓')

    monkeypatch.setattr(omr, 'load_panel', _boom)
    out = omr.get_out_or_legacy(
        'market_state', lambda: {'state': 'legacy'})
    assert out['state'] == 'legacy'


# ── 参数切片 ────────────────────────────────────────────

def test_slice_index_daily_keeps_latest():
    payload = {'days': [1, 2, 3, 4]}
    assert omr.slice_index_daily(payload, 2)['days'] == [3, 4]


def test_slice_moneyflow_summary_keeps_latest():
    payload = {'days': [1, 2, 3, 4]}
    assert omr.slice_moneyflow_summary(payload, 3)['days'] == [2, 3, 4]


def test_slice_daily_top_keeps_head():
    payload = {'stocks': [{'i': 1}, {'i': 2}, {'i': 3}]}
    assert [x['i'] for x in omr.slice_daily_top(payload, 2)['stocks']] == [1, 2]


def test_slice_sector_changes_limits_both_sides():
    payload = {'gainers': [1, 2, 3], 'losers': [4, 5, 6]}
    out = omr.slice_sector_changes(payload, 2)
    assert out['gainers'] == [1, 2]
    assert out['losers'] == [4, 5]


def test_slice_sector_moneyflow_limits_sectors_and_stocks():
    payload = {
        'sectors': [
            {'industry': 'a', 'stocks': [1, 2, 3]},
            {'industry': 'b', 'stocks': [4]},
        ],
        'out_sectors': [
            {'industry': 'c', 'stocks': [5, 6, 7]},
        ],
    }
    out = omr.slice_sector_moneyflow(payload, 1, 2)
    assert len(out['sectors']) == 1
    assert out['sectors'][0]['stocks'] == [1, 2]
    assert out['out_sectors'][0]['stocks'] == [5, 6]


def test_slice_sector_heat_limits_rows():
    payload = {'sectors': [{'i': 1}, {'i': 2}, {'i': 3}]}
    assert len(omr.slice_sector_heat(payload, 2)['sectors']) == 2


# ── /dashboard/full 接线 ────────────────────────────────

def test_dashboard_full_uses_reader_for_eod_modules(monkeypatch):
    from app.services.dashboard_service import DashboardService

    calls = []

    def _fake_out_or_legacy(module, fallback, transform=None, expected_date=None):
        calls.append(module)
        return {'module': module}

    monkeypatch.setattr(omr, 'get_out_or_legacy', _fake_out_or_legacy)

    svc = DashboardService()
    # 混合模块仍走旧路径，测试中替换为轻量返回，避免真实 DB
    monkeypatch.setattr(svc, 'get_index_summary', lambda: {'indexes': []})
    monkeypatch.setattr(svc, 'get_limit_ecology', lambda: {'up': 1})
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: {'up_count': 1})
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: {'phase': 'x'})

    result = svc.get_dashboard_full()
    assert result is not None

    for module in (
        'market_index_daily', 'market_moneyflow_summary', 'market_sector_changes',
        'market_sector_moneyflow', 'market_daily_top_up', 'market_daily_top_down',
        'market_overview_panel', 'market_flows_30d', 'market_state',
        'market_sector_heat', 'market_alerts',
    ):
        assert module in calls
