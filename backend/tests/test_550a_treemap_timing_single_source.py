"""550-A：机会地图「时机」展示单源回归（静态结构）。

用户拍板 Q1=A / Q2=A：
- 方块颜色、浮窗时机、时机筛选、只看重点、侧栏徽标统一读
  `opportunity_state`（旧快照无 state 时按 `right_side_confirm` 回退）；
- 点击方块传完整 `stockItem`，避免 ECharts 树对象丢 `opportunity_state`。

本测试只读 HTML，不启动服务、不访问数据库。
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / '_ui-prototype' / 'opportunity-treemap.html'


def _html() -> str:
    return HTML_PATH.read_text(encoding='utf-8')


def test_timing_buttons_use_state_values():
    html = _html()
    for state in ('enter', 'light', 'wait', 'avoid'):
        assert f"toggleTimingFilter('{state}')" in html
    assert "const btnMap = { 'enter': 'timingBlueBtn', 'light': 'timingYellowBtn'" in html


def test_filters_use_effective_state_not_rsc():
    html = _html()
    assert 'filtered.filter(s => effectiveState(s) === timingFilter)' in html
    assert "filtered.filter(s => effectiveState(s) !== 'avoid')" in html
    assert 's.rightSideConfirm === timingFilter' not in html
    assert "s.rightSideConfirm !== '否决'" not in html


def test_click_passes_full_stock_item():
    html = _html()
    assert 'showDetail(_stockByName[params.data.tsCode] || params.data)' in html
    assert 'stateEvidence: s.state_evidence' in html


def test_tooltip_and_sidebar_use_state_text():
    html = _html()
    assert '● 时机：${_stateText}' in html
    assert 'effectiveTimingColor(d)' in html
    assert 'STATE_BADGE[_state]' in html
    assert '右侧确认 ${d.rightSideConfirm}' in html


def test_effective_state_fallback_mapping():
    html = _html()
    assert "function effectiveState(s)" in html
    assert "'强确认': 'enter'" in html
    assert "'基础确认': 'light'" in html
    assert "'未确认': 'wait'" in html
    assert "'否决': 'avoid'" in html
