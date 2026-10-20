"""531号：板块模块容器拆分 + 净流入/热度改申万一级 + 近5日走势文字总结。

覆盖：
- `_summarize_pct_5d` / `_summarize_net_5d` 形态与文案
- `_build_sector_history_5d`：由 20 日序列派生 5 日 + 每行 summary
- `get_sector_moneyflow` 默认申万口径 + 5 日逐日序列/文字
- `dashboard.html`：净流入/热度/5日走势三块独立容器 + 5日简图与文字
"""
from pathlib import Path

import pandas as pd
from app.services.dashboard_service import DashboardService

HTML_PATH = Path(__file__).resolve().parents[2] / '_ui-prototype' / 'dashboard.html'


# ──────────────────────────────────────────────
# 文字总结
# ──────────────────────────────────────────────
def test_summarize_pct_5d_shapes():
    svc = DashboardService()
    assert '持续上行' in svc._summarize_pct_5d([1, 1, 1, 1, 1])
    assert '持续下行' in svc._summarize_pct_5d([-1, -1, -1, -1, -1])
    assert '先扬后抑' in svc._summarize_pct_5d([2, 2, 0, -1, -1])
    assert '先抑后扬' in svc._summarize_pct_5d([-2, -2, 0, 1, 1])
    assert '震荡上行' in svc._summarize_pct_5d([1, -1, 1, -1, 1])
    txt = svc._summarize_pct_5d([1, 1, 1, 1, 1])
    assert '近5日累计+5.0%' in txt and '5涨0跌' in txt and '日均涨跌之和' in txt


def test_summarize_net_5d_shapes():
    svc = DashboardService()
    assert '持续净流入' in svc._summarize_net_5d([1, 1, 1, 1, 1])
    assert '持续净流出' in svc._summarize_net_5d([-1, -1, -1, -1, -1])
    assert '流入转流出' in svc._summarize_net_5d([2, 2, 0, -1, -1])
    assert '流出转流入' in svc._summarize_net_5d([-2, -2, 0, 1, 1])
    assert '近5日累计+3.0亿' in svc._summarize_net_5d([0.5, 0.5, 0.5, 0.5, 1.0])


def test_build_sector_history_5d_takes_last_five_and_summaries():
    svc = DashboardService()
    dates = [f'2026-10-{d:02d}' for d in range(1, 21)]
    hist = {
        'dates': dates,
        'avg': [float(i) for i in range(20)],
        'industries': {'电子': [float(i) for i in range(20)],
                       '银行': [-float(i) for i in range(20)]},
    }
    res = svc._build_sector_history_5d(hist)
    assert res['dates'] == dates[-5:]
    assert res['industries']['电子'] == [15.0, 16.0, 17.0, 18.0, 19.0]
    assert len(res['industries']['银行']) == 5
    assert set(res['summary'].keys()) == {'电子', '银行'}
    assert '近5日累计' in res['summary']['电子']
    assert '持续下行' in res['summary']['银行']
    assert '近5日累计' in res['avg_summary']


def test_build_sector_history_5d_empty():
    assert DashboardService()._build_sector_history_5d({}) == {}


# ──────────────────────────────────────────────
# get_sector_moneyflow：默认申万口径 + 5日逐日序列
# ──────────────────────────────────────────────
def _rec(date, code, net):
    return {
        'trade_date': date,
        'ts_code': code,
        'buy_lg_amount': net if net > 0 else 0.0,
        'buy_elg_amount': 0.0,
        'sell_lg_amount': -net if net < 0 else 0.0,
        'sell_elg_amount': 0.0,
    }


def test_sector_moneyflow_sw_scope_5d_series(monkeypatch):
    dates = ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19']
    groups = {
        '电子': [f'E{i:02d}.SH' for i in range(20)],
        '银行': [f'B{i:02d}.SH' for i in range(20)],
        '食品': [f'F{i:02d}.SH' for i in range(20)],
    }
    sw_map = {}
    records = []
    for ind, codes in groups.items():
        for code in codes:
            sw_map[code.split('.')[0]] = ind
    for d in dates:
        for ind, codes in groups.items():
            net = {'电子': 1e4, '银行': -0.9e4, '食品': 0.3e4}[ind]
            for code in codes:
                records.append(_rec(d, code, net))
    assert len(records) == 300

    class _FakeDM:
        def get_cached_moneyflow(self, start_date=None, end_date=None):
            return records

    monkeypatch.setattr('app.services.dashboard_service.DataManager', lambda: _FakeDM())
    monkeypatch.setattr('app.data.sw_industry_map.get_sw_industry_map',
                        lambda *a, **k: dict(sw_map))

    class _Stock:
        def __init__(self, ts_code, name):
            self.ts_code = ts_code
            self.name = name

    rows = [_Stock(c, c) for codes in groups.values() for c in codes]

    class _All:
        def all(self):
            return rows

    class _Q:
        def filter(self, *a, **k):
            return _All()

    class _Session:
        def query(self, *a, **k):
            return _Q()

    monkeypatch.setattr('app.db.session', _Session())

    svc = DashboardService()
    res = svc.get_sector_moneyflow(top_n=8, stocks_per_sector=1)
    assert res is not None
    assert res['window_5d'] == dates
    assert res['sectors'][0]['name'] == '电子'
    top = res['sectors'][0]
    assert len(top['series_5d']) == 5
    assert top['net_5d'] == 100.0       # 20 只 × 1 万 × 5 日 = 100 亿
    assert '持续净流入' in top['trend_text']
    assert '近5日累计+100.0亿' in top['trend_text']
    assert res['trend_5d'][0]['industry'] == '电子'
    assert res['out_sectors'][0]['name'] == '银行'
    assert '持续净流出' in res['out_sectors'][0]['trend_text']


def test_sector_moneyflow_eastmoney_scope_kept(monkeypatch):
    """531：dim8 等既有消费方仍可显式使用东财二级口径。"""
    pairs = {'E1.SH': '电子', 'B1.SH': '银行'}
    for i in range(10):
        pairs[f'X{i}.SH'] = '其他'

    class _Stock:
        def __init__(self, ts_code, industry):
            self.ts_code, self.industry = ts_code, industry

    stock_rows = [_Stock(k, v) for k, v in pairs.items()]

    class _All:
        def all(self):
            return stock_rows

    class _Q:
        def filter(self, *a, **k):
            return _All()

    class _Session:
        def query(self, *a, **k):
            return _Q()

    monkeypatch.setattr('app.db.session', _Session())
    # 若误走申万分支则会因映射为空返回 None；本用例断言东财分支可用
    monkeypatch.setattr('app.data.sw_industry_map.get_sw_industry_map',
                        lambda *a, **k: {})
    records = [_rec('2026-10-19', 'E1.SH', 1e4) for _ in range(60)]
    records += [_rec('2026-10-19', 'B1.SH', -1e4) for _ in range(10)]
    records += [_rec('2026-10-19', f'X{i}.SH', 0.1e4) for i in range(10)]
    assert len(records) >= 50

    class _FakeDM:
        def get_cached_moneyflow(self, start_date=None, end_date=None):
            return records

    monkeypatch.setattr('app.services.dashboard_service.DataManager', lambda: _FakeDM())
    res = DashboardService().get_sector_moneyflow(
        top_n=8, stocks_per_sector=1, industry_scope='eastmoney')
    assert res is not None
    assert res['sectors'][0]['name'] == '电子'


# ──────────────────────────────────────────────
# 前端结构：三块独立容器 + 5日简图/文字
# ──────────────────────────────────────────────
def _html():
    return HTML_PATH.read_text(encoding='utf-8')


def test_sector_containers_are_separate():
    html = _html()
    pos_mf = html.index('id="sector-inflow-chart"')
    pos_heat = html.index('id="sector-heat-panel"')
    pos_sector = html.index('id="chart-sector"')
    assert pos_mf < pos_heat < pos_sector
    # 净流入恢复原布局（左行业柱图 + 右个股明细），不再使用行列表容器
    assert 'id="sector-mf-rows"' not in html
    assert html.count('id="sector-heat-panel"') == 1


def test_history_5d_sparkline_and_text():
    html = _html()
    assert 'sd.history_5d||sd.history_20d' in html
    assert 'option.graphic.push' in html
    assert 'W/2+116' in html          # 折线缩至约半宽，右侧留文字空间
    assert '近5日板块涨跌走势' in html
    assert '531' in html
