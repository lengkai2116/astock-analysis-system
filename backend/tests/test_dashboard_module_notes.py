"""仪表盘「各模块说明文字」展示规范回归（2026-10-21 目检反馈）。

用户要求：
1. 所有模块的说明文字统一按 532/531 迭代后的 14px（原 11/12px 偏小）；
2. 说明文字不再用「今日/当日」等相对表述，改为各模块自己的数据交易日。

本测试只校验静态结构与动态文案中的日期注入点，不连接数据源。
"""
import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / '_ui-prototype' / 'dashboard.html'

NOTE_IDS = [
    'volume-trend-note',
    'moneyflow-trend-note',
    'eod-state-note-1',
    'eod-state-note-2',
    'sector-mf-trend-note',
    'sector-change-note',
    'sector-history-note',
    'market-state-line',
    'market-breadth-panel',
    'market-emotion-panel',
    'market-alert-list',
]


def _html() -> str:
    return HTML_PATH.read_text(encoding='utf-8')


def test_module_notes_are_14px():
    html = _html()
    for nid in NOTE_IDS:
        m = re.search(r'id="%s"[^>]*style="([^"]*)"' % nid, html)
        assert m, f'未找到说明文字容器 #{nid}'
        assert 'font-size:14px' in m.group(1), f'#{nid} 说明文字应为 14px'


def test_axis_notes_and_index_trend_are_14px():
    html = _html()
    # 散点/四象限两条轴定义说明
    assert html.count(
        'font-size:14px;color:var(--text-muted);margin-bottom:var(--space-6);') >= 2
    # 指数卡近5/20/60日趋势角标
    assert html.count('style="font-size:14px;color:var(--text-muted);text-align:center;"') == 4


def test_no_relative_today_wording_in_notes():
    html = _html()
    assert '今日上涨' not in html
    assert '今日 高开高收' not in html
    assert '仅当日Top' not in html
    assert '较昨日' not in html


def test_notes_inject_module_trade_date():
    html = _html()
    # 散点/四象限：summary_5d 末条日期（回退 dd.trade_date）
    assert 'var dLabel=today.date||dd.trade_date' in html
    assert "dPref+'上涨 " in html
    assert "dPref+'高开高收 " in html
    # 成交额：index-daily 末条 trade_date
    assert 'var dLabel=last.trade_date||last.date' in html
    # 资金流向：moneyflow-summary 末条 date
    assert 'var dLabel=(md.days[md.days.length-1]||{}).date' in html
    # 板块涨跌幅：sector-sector 的 date + 申万一级口径
    assert "sd.date?('申万一级 31 类 · 固定 '+sd.date" in html
    # 板块净流入：window_5d 末日
    assert 'var dCut=w5.length?w5[w5.length-1]' in html
