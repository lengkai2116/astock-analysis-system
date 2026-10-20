"""530号 第二轮：仪表盘近20日板块走势「行列表格 + 全宽容器」结构回归。

用户目检反馈：近20日折线不再是「一张图堆 10 条线」，改为
每行＝行业名 + 该行业20日折线小图，并从 ⑦「行业板块涨跌幅」卡内
移到全宽独立容器（位置 ⑦后⑧前）。
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / '_ui-prototype' / 'dashboard.html'


def _html() -> str:
    return HTML_PATH.read_text(encoding='utf-8')


def test_history_table_moved_between_sector_and_market_state():
    html = _html()
    pos_sector = html.index('id="chart-sector"')
    pos_hist = html.index('id="chart-sector-history"')
    pos_state = html.index('id="market-state-line"')
    assert pos_sector < pos_hist < pos_state

    # 折线容器已移出 ⑦ 卡：⑦ 卡在折线块前闭合，折线块独占自己的 chart-card
    between = html[pos_sector:pos_hist]
    assert between.count('<div class="chart-card"') == 1
    assert '530 第二轮' in html


def test_history_rows_use_per_row_grid_and_zero_line():
    js = _html()
    assert 'gridIndex:i' in js
    assert 'yAxisIndex:i' in js
    assert 'data:[{yAxis:0}]' in js
    # 展开交互复用最近一次数据（原实现未赋值 _sectorHistoryLast）
    assert '_sectorHistoryLast=sd' in js
    assert "rows.push({name:'全市场平均'" in js
