"""551-A：机会地图「机会 / 执行」两层拆分回归（静态结构）。

拍板口径 A：
- 地图与结论卡主行只回答“有没有机会”（opportunity_state）；
- 弹窗新增独立“执行（新开）”行，取 operation_advice.state/action_label/
  state_reason/geometric，展示 RR、目标/止损空间与门禁原因；
- 不再把“动作待复核”作为状态与动作冲突的兜底提示。

只读 HTML，不访问数据库。
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / '_ui-prototype' / 'opportunity-treemap.html'


def _html() -> str:
    return HTML_PATH.read_text(encoding='utf-8')


def test_execution_row_and_helpers_exist():
    html = _html()
    assert 'id="d-execution-row"' in html
    assert 'function executionMeta(oa)' in html
    assert 'function renderExecutionRow(oa)' in html
    assert 'renderExecutionRow(oa);' in html


def test_opportunity_is_labeled_as_opportunity_not_timing():
    html = _html()
    assert '🎯 机会（方向）' in html
    assert '● 机会：${_stateText}' in html
    assert '机会状态 ·' in html
    assert '机会状态回答“有没有机会”' in html


def test_execution_row_splits_wait_and_position():
    html = _html()
    assert '暂不新开（' in html
    assert '新开 0% · 持有上限' in html
    assert 'RR ${m.rr.toFixed(2)}' in html
    assert '上方 ${m.dr > 0' in html
    assert '下方 ${m.ds.toFixed(2)}%' in html


def test_old_action_conflict_badge_removed():
    html = _html()
    assert '动作待复核' not in html
    assert 'actionConflict' not in html
