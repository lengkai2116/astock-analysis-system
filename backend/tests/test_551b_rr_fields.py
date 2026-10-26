"""551-B：RR 文案分类、字段同源与新开/持有仓位语义回归。

只读源码/纯函数，不访问数据库。
"""
import inspect
from pathlib import Path

from app.opportunity_atlas.dimensions.shared_support_resistance import format_rr_gate_reason

ROOT = Path(__file__).resolve().parents[2]


def test_rr_reason_target_near():
    geo = {'dist_to_resistance_pct': 3.29, 'dist_to_support_pct': -9.09}
    reason = format_rr_gate_reason(geo, 0.36)
    assert '目标空间不足' in reason
    assert '止损空间过宽' not in reason
    assert '3.29' in reason and '9.09' in reason


def test_rr_reason_stop_wide():
    geo = {'dist_to_resistance_pct': 5.0, 'dist_to_support_pct': -12.0}
    reason = format_rr_gate_reason(geo, 0.42)
    assert '止损空间过宽' in reason


def test_rr_reason_both_narrow():
    geo = {'dist_to_resistance_pct': 2.0, 'dist_to_support_pct': -3.0}
    reason = format_rr_gate_reason(geo, 0.67)
    assert '均偏窄' in reason


def test_advice_results_expose_same_source_fields():
    from app.opportunity_atlas import advice_builder, advice_engine
    for mod in (advice_engine, advice_builder):
        src = inspect.getsource(mod.build_operation_advice)
        assert "result['risk_reward_ratio']" in src
        assert "result['target_price']" in src
        assert "result['new_position_ratio']" in src
        assert "result['hold_position_limit']" in src


def test_diagnose_mapping_no_longer_nulls_target():
    src = (ROOT / 'backend/app/opportunity_atlas/cross_validate.py').read_text(encoding='utf-8')
    assert "unified['target_price'] = None" not in src
    assert "new_position_ratio" in src
    assert "hold_position_limit" in src


def test_frontend_uses_explicit_position_fields():
    html = (ROOT / '_ui-prototype/opportunity-treemap.html').read_text(encoding='utf-8')
    assert 'oa.new_position_ratio' in html
    assert 'oa.hold_position_limit' in html
