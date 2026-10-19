"""524号 批次4 定向测试：市场预警（market/alerts，L5 四条规则）。

- `DashboardService.get_market_alerts`：R1 冰点→关键上涨窗口（emotion phase=ice）/
  R2 融资拥挤背离→顶部（margin_trend 近20日 80 分位 + HS300 近5日涨幅≤0）/
  R3 宽度极端→反转（up_ratio≥85 或 ≤15）/ R4 状态切换→风控（前日 vs 今日 4 状态）。
- 路由 `/api/v3/market/alerts` 存在 + 并入 `dashboard/full.market_alerts`。
- 状态判定复用 `_classify_state`（524 Q1 4 状态·状态机）。
"""
import pandas as pd
import pytest
from app.services.dashboard_service import DashboardService


class _FakeECM:
    def __init__(self, stats=None, stats_hist=None):
        self._stats = stats or {}
        self._stats_hist = stats_hist or []

    def get_cached_market_stats(self, stat_date=None):
        return self._stats

    def _query_shard(self, table, sql, params=None):
        if table == 'market_stats_cache':
            rows = list(reversed(self._stats_hist))  # 模拟 ORDER BY stat_date DESC（最新在前）
            if 'ORDER BY stat_date DESC LIMIT 20' in sql:
                return pd.DataFrame({'stat_date': [r[0] for r in rows],
                                     'margin_trend': [r[1] for r in rows]})
            if 'ORDER BY stat_date DESC LIMIT 2' in sql:
                return pd.DataFrame({'stat_date': [r[0] for r in rows[:2]],
                                     'turnover_percentile': [r[2] for r in rows[:2]]})
        return pd.DataFrame()


class _FakeDM:
    def __init__(self, ecm):
        self.cache = ecm


def _mk_ecm(stats=None, hist=None):
    return _FakeECM(stats, hist)


def _svc(ecm):
    svc = DashboardService()
    svc._data_manager = _FakeDM(ecm)
    return svc


# ── R1 冰点 ─────────────────────────────────────────────

def test_alerts_r1_ice_window(monkeypatch):
    import app.services.dashboard_service as mod
    svc = _svc(_mk_ecm())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: {
        'phase': 'ice', 'phase_label': '情绪冰点', 'metrics': {},
        'data_available': True, 'source': 'sentiment_pool_cache 六段论'})
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: {'state': 'ranging', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    assert res is not None
    types = [a['type'] for a in res['alerts']]
    assert 'ice_window' in types


# ── R2 拥挤背离 ─────────────────────────────────────────

def test_alerts_r2_crowding_top(monkeypatch):
    # margin_trend 近20日：最新 0.9 为最高（80 分位上方），HS300 近5日涨幅 -2%
    hist = [(f'2026-10-{i:02d}', i / 10, 0.5) for i in range(1, 21)]  # margin 0.1..2.0
    hist[-1] = ('2026-10-16', 1.9, 0.9)  # 最新 margin 1.9
    svc = _svc(_mk_ecm(hist=hist))

    class _FakeBS:
        def get_index_daily(self, ts_code=None, **kw):
            return pd.DataFrame({'trade_date': [f'2026-10-{i:02d}' for i in range(1, 7)],
                                 'close': [100.0, 100.0, 100.0, 100.0, 100.0, 98.0]})  # 近5日 -2%

    monkeypatch.setattr('app.services.benchmark_service.BenchmarkService', lambda dm: _FakeBS())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: {'state': 'ranging', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    types = [a['type'] for a in res['alerts']]
    assert 'crowding_top' in types


def test_alerts_r2_no_crowding_when_margin_low(monkeypatch):
    # margin 最新值低（0.1），不满足 80 分位 → 无 R2
    hist = [(f'2026-10-{i:02d}', 0.1, 0.5) for i in range(1, 21)]
    svc = _svc(_mk_ecm(hist=hist))
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: {'state': 'ranging', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    assert 'crowding_top' not in [a['type'] for a in res['alerts']]


# ── R3 宽度极端 ─────────────────────────────────────────

def test_alerts_r3_breadth_overheat(monkeypatch):
    svc = _svc(_mk_ecm())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: {
        'trade_date': '2026-10-16', 'up_ratio': 90.0})
    monkeypatch.setattr(svc, 'get_market_state', lambda: {'state': 'ranging', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    assert 'breadth_extreme' in [a['type'] for a in res['alerts']]


def test_alerts_r3_breadth_normal_no_alert(monkeypatch):
    svc = _svc(_mk_ecm())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: {
        'trade_date': '2026-10-16', 'up_ratio': 55.0})
    monkeypatch.setattr(svc, 'get_market_state', lambda: {'state': 'ranging', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    assert 'breadth_extreme' not in [a['type'] for a in res['alerts']]


# ── R4 状态切换 ─────────────────────────────────────────

def test_alerts_r4_state_switch(monkeypatch):
    svc = _svc(_mk_ecm())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: {
        'state': 'high_volatility', 'state_label': '高波动', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'trend_up')  # 趋势 → 高波动
    res = svc.get_market_alerts()
    assert 'state_switch' in [a['type'] for a in res['alerts']]


def test_alerts_r4_same_state_no_alert(monkeypatch):
    svc = _svc(_mk_ecm())
    monkeypatch.setattr(svc, 'get_market_emotion', lambda: None)
    monkeypatch.setattr(svc, 'get_market_breadth', lambda: None)
    monkeypatch.setattr(svc, 'get_market_state', lambda: {
        'state': 'ranging', 'state_label': '震荡', 'data_date': '2026-10-16'})
    monkeypatch.setattr(svc, '_get_prev_market_state', lambda: 'ranging')
    res = svc.get_market_alerts()
    assert 'state_switch' not in [a['type'] for a in res['alerts']]


# ── 状态判定辅助 + 路由 + 聚合 ──────────────────────────

def test_classify_state_matrix():
    svc = DashboardService()
    assert svc._classify_state(0.9, 6.0, 100.0, 95.0)[0] == 'high_volatility'
    assert svc._classify_state(0.5, 5.0, 100.0, 95.0)[0] == 'trend_up'
    assert svc._classify_state(0.5, -5.0, 95.0, 100.0)[0] == 'trend_down'
    assert svc._classify_state(0.3, 1.0, 100.0, 100.0)[0] == 'consolidation'
    assert svc._classify_state(0.5, 0.5, 100.0, 100.0)[0] == 'ranging'


def test_market_alerts_route_registered():
    from app.routes import dashboard as _dash
    assert hasattr(_dash, 'get_market_alerts')


def test_dashboard_full_merges_market_alerts(monkeypatch):
    svc = _svc(_mk_ecm())
    for name in ('get_index_summary', 'get_market_volume', 'get_moneyflow_summary',
                 'get_sector_changes', 'get_sector_moneyflow', 'get_daily_top',
                 'get_market_breadth', 'get_market_state', 'get_market_emotion',
                 'get_sector_heat'):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    monkeypatch.setattr(svc, 'get_market_alerts', lambda: {
        'date': '2026-10-16', 'count': 1,
        'alerts': [{'level': 'info', 'type': 'ice_window', 'title': 't', 'detail': 'd'}]})
    res = svc.get_dashboard_full()
    assert res is not None
    assert res['market_alerts']['count'] == 1
