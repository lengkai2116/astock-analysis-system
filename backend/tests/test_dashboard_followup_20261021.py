"""2026-10-21 仪表盘目检后续修正：阶段说明 + 板块涨跌幅固定上一交易日。

- `get_sector_changes` 默认 use_intraday=False → 不读盘中板块快照，固定 DB 最近完整交易日。
- 前端五维榜增加阶段说明与徽标 tooltip，并注明「主力5日」口径。
"""
import inspect
from pathlib import Path

import pandas as pd
from app.services.dashboard_service import DashboardService

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / '_ui-prototype' / 'dashboard.html'


def test_sector_changes_default_disables_intraday():
    sig = inspect.signature(DashboardService.get_sector_changes)
    assert sig.parameters['use_intraday'].default is False


def test_sector_changes_default_skips_intraday_reader(monkeypatch):
    class _Boom:
        def get_sector_rankings(self, top_n=None):
            raise AssertionError('默认不应读取盘中板块快照')

    monkeypatch.setattr('app.data.akshare_reader.reader', _Boom())
    svc = DashboardService()
    svc._data_manager = type('DM', (), {'cache': object()})()
    svc._get_sector_streaks = lambda **kwargs: {'up': [], 'down': []}
    svc._get_sector_history_20d = lambda **kwargs: {'dates': [], 'avg': [], 'industries': {}}
    svc._build_sector_history_5d = lambda h: {}
    svc._get_best_trade_date = lambda **kwargs: None
    assert svc.get_sector_changes() is None


def test_get_best_trade_date_before_filters_today(monkeypatch):
    calls = []

    class _ECM:
        def _query_shard(self, table, sql, params=None):
            calls.append((sql, params))
            return pd.DataFrame({'trade_date': ['2026-10-20']})

    svc = DashboardService()
    svc._data_manager = type('DM', (), {'cache': _ECM()})()
    assert svc._get_best_trade_date(before='2026-10-21') == '2026-10-20'
    assert 'trade_date < ?' in calls[0][0]
    assert calls[0][1] == ['2026-10-21', 1000]


def test_sector_changes_uses_sw_industry(monkeypatch):
    """柱状图与连续涨跌统一走申万一级，不再用 110 个东财二级行业。"""
    codes = [f'{i:06d}.SH' for i in range(12)]
    rows = [{'ts_code': c, 'pct_chg': (1.0 if i < 6 else -1.0)}
            for i, c in enumerate(codes)]

    class _ECM:
        def _query_shard(self, table, sql, params=None):
            if table == 'daily_cache' and 'WHERE trade_date = ?' in sql:
                return pd.DataFrame(rows)
            return pd.DataFrame()

    svc = DashboardService()
    svc._data_manager = type('DM', (), {'cache': _ECM()})()
    svc._get_best_trade_date = lambda **kwargs: '2026-10-20'
    svc._get_sector_streaks = lambda **kwargs: {'up': [], 'down': []}
    svc._get_sector_history_20d = lambda **kwargs: {}
    svc._build_sector_history_5d = lambda h: {}

    sw_map = {f'{i:06d}': ('计算机' if i < 6 else '银行') for i in range(12)}
    monkeypatch.setattr('app.data.sw_industry_map.get_sw_industry_map',
                        lambda *a, **k: sw_map)

    res = svc.get_sector_changes()
    assert res is not None
    assert {s['name'] for s in res['gainers']} == {'计算机'}
    assert {s['name'] for s in res['losers']} == {'银行'}


def test_frontend_stage_note_and_tooltip():
    html = HTML_PATH.read_text(encoding='utf-8')
    assert '阶段说明：主线＝趋势与资金共振' in html
    assert '「主力5日」＝大单+特大单净流入' in html
    assert '_shStageDesc' in html
    assert 'escapeHtml(_shStageDesc(s.stage))' in html
    assert '🏭 行业板块涨跌幅（申万一级）' in html
    assert '申万一级 31 类 · 固定 ' in html
    assert 'var _sectorChartSig=' in html
    assert 'if(sig===_sectorChartSig)return;' in html
