"""T10 回归测试：307号 entry_signals / exit_conditions 结构化字段

文档依据（307号§3.2/§3.3）：
- entry_signals：每种机会类型的入场条件列表（结构化 JSON，叠加 L4 共识率 ≥55% 门禁）
- exit_conditions：每种机会类型的退出条件列表（结构化 JSON，任一满足即退出）
- _compute_opportunity_meta 应在证据计数后输出这两个字段
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import importlib.util
import json
import pytest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py')


@pytest.fixture(scope='module')
def dd():
    spec = importlib.util.spec_from_file_location('dd_t10', _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _value_bottom_tags() -> dict:
    return {
        'main_force_phase': 'building',
        'fina_health': 'pass',
        'valuation_level': 'low',
        'fund_flow': '5d_inflow',
        'sentiment_phase': 'recovery',
        'volume_price_fit': 'healthy',
        'catalyst_event': 'none',
        'dividend_yield': '3.5',
        'pattern_signal': 'none',
        'buy_sell_point': 'none',
    }


def test_entry_signals_function_exists(dd):
    """_compute_entry_signals 应存在且返回结构化入场条件"""
    tags = _value_bottom_tags()
    result = dd._compute_entry_signals('value_bottom', tags)

    assert isinstance(result, dict)
    assert 'entry_signals' in result
    entry = json.loads(result['entry_signals'])
    assert isinstance(entry, list) and len(entry) >= 1, f"入场条件应为非空列表: {entry}"
    # 每个条件应为结构化 dict（含描述）
    assert all(isinstance(c, dict) and 'desc' in c for c in entry), \
        f"入场条件应为 {desc:...} 结构: {entry}"


def test_exit_conditions_function_exists(dd):
    """_compute_exit_conditions 应存在且返回结构化退出条件"""
    tags = _value_bottom_tags()
    result = dd._compute_exit_conditions('value_bottom', tags)

    assert isinstance(result, dict)
    assert 'exit_conditions' in result
    exit_ = json.loads(result['exit_conditions'])
    assert isinstance(exit_, list) and len(exit_) >= 1, f"退出条件应为非空列表: {exit_}"
    assert all(isinstance(c, dict) and 'desc' in c for c in exit_)


def test_opportunity_meta_outputs_both_fields(dd):
    """_compute_opportunity_meta 应输出 entry_signals + exit_conditions 两字段"""
    tags = _value_bottom_tags()
    dd._compute_opportunity_meta(tags)

    assert 'entry_signals' in tags, "opportunity_meta 应输出 entry_signals"
    assert 'exit_conditions' in tags, "opportunity_meta 应输出 exit_conditions"
    # 值为可解析 JSON 列表
    entry = json.loads(tags['entry_signals'])
    exit_ = json.loads(tags['exit_conditions'])
    assert isinstance(entry, list) and isinstance(exit_, list)


def test_entry_signals_match_document(dd):
    """value_bottom 入场条件应符合 307号§3.2（估值/基本面/右侧确认三条件）"""
    tags = _value_bottom_tags()
    entry = json.loads(dd._compute_entry_signals('value_bottom', tags)['entry_signals'])

    descs = ' '.join(c.get('desc', '') for c in entry)
    assert '估值' in descs or '低估' in descs, f"应含估值条件: {descs}"
    assert '财务' in descs or '基本面' in descs, f"应含基本面条件: {descs}"
    assert '右侧' in descs or 'MA20' in descs or '确认' in descs, f"应含右侧确认条件: {descs}"
