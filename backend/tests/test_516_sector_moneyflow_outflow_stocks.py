"""516号 核查档 批次1 定向测试。

- **P1**：`_aggregate_sector_moneyflow` 流出板块应取「净额最负」个股
  （原实现对**所有**板块一律取净额最大前 N → 流出板块误列板块内净流入个股）。
- **P3**：`dashboard.html` 删除 `MOCK_GAINERS` 假数据兜底（§13 对齐，接口失败走空态），
  且前端流出卡片不再用 `Math.abs` 强制取绝对值。
"""
import os

from app.services.dashboard_service import DashboardService

_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "_ui-prototype",
    "dashboard.html",
)


def _rec(code, net):
    """构造一条 moneyflow 记录：net = buy_lg+buy_elg-sell_lg-sell_elg。"""
    buy = net if net > 0 else 0.0
    sell = -net if net < 0 else 0.0
    return {
        'ts_code': code,
        'buy_lg_amount': buy,
        'buy_elg_amount': 0.0,
        'sell_lg_amount': sell,
        'sell_elg_amount': 0.0,
    }


def _run():
    industry_map = {
        'IN1.SH': 'S_IN', 'IN2.SH': 'S_IN',
        'OUT1.SH': 'S_OUT', 'OUT2.SH': 'S_OUT', 'OUT3.SH': 'S_OUT', 'OUT4.SH': 'S_OUT',
    }
    raw = [
        _rec('IN1.SH', +3e8), _rec('IN2.SH', +1e8),        # 流入板块（两只均净流入）
        _rec('OUT1.SH', +2e8), _rec('OUT2.SH', +1e8),      # 流出板块内「净流入」个股
        _rec('OUT3.SH', -4e8), _rec('OUT4.SH', -6e8),      # 流出板块内「净流出」个股
    ]
    svc = DashboardService()
    return svc._aggregate_sector_moneyflow(
        raw, industry_map, top_n=8, stocks_per_sector=2, trade_date='20261012')


def test_inflow_sector_keeps_largest_inflow_stocks():
    res = _run()
    inflow = {s['name']: s for s in res['sectors']}
    assert 'S_IN' in inflow
    stocks = inflow['S_IN']['stocks']
    assert [s['ts_code'] for s in stocks] == ['IN1.SH', 'IN2.SH']
    assert all(s['net_inflow'] > 0 for s in stocks)


def test_outflow_sector_lists_most_negative_stocks():
    res = _run()
    outflow = {s['name']: s for s in res['out_sectors']}
    assert 'S_OUT' in outflow
    stocks = outflow['S_OUT']['stocks']
    # 修复后：取净额最负的两只（OUT4 < OUT3 < 0），而非旧行为的净流入 OUT1/OUT2
    assert [s['ts_code'] for s in stocks] == ['OUT4.SH', 'OUT3.SH']
    assert all(s['net_inflow'] < 0 for s in stocks)


def test_no_outflow_sector_stock_is_net_inflow():
    res = _run()
    for s in res['out_sectors']:
        for st in s['stocks']:
            assert st['net_inflow'] <= 0, (s['name'], st)


def test_dashboard_html_removed_mock_and_forced_abs():
    with open(_HTML, encoding='utf-8') as f:
        html = f.read()
    # P3：假数据兜底已删（不再声明假数组、不再兜底调用；注释说明文本不计）
    assert 'var MOCK_GAINERS' not in html
    assert 'renderGainers(MOCK_GAINERS)' not in html
    # P1：前端流出卡片不再强制取绝对值（改按真实符号渲染）
    assert 'Math.abs(st.net_inflow)' not in html
