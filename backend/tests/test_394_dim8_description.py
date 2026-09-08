"""394号方案 Phase 4 — dim8 现状描述生成器测试（适配395号新API）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _generate_six_dim_report,
    _quality_to_text,
    _unify_six_dim_text,
)


def _make_dim(plain='', light='green', direction=1, confidence=0.8):
    return {
        'judgment': {'overall_light': light, 'overall_direction': direction, 'confidence': confidence},
        'status_description': {'plain': plain, 'evidence': ['证据1', '证据2']},
        'audit': {'confidence': confidence},
    }


# ── _unify_six_dim_text 格式统一 ─────────────────────────────
def test_unify_six_dim_text_full():
    report = {
        'risk': {'title': '风险边界', 'text': '中等风险'},
        'valuation': {'title': '估值评估', 'text': '估值偏高'},
        'emotion': {'title': '情绪环境', 'text': '市场偏暖'},
        'structure': {'title': '结构位置', 'text': '价格上方'},
        'volume_price': {'title': '量价健康', 'text': '量增价涨'},
        'chip_fund': {'title': '资金筹码', 'text': '主力流入'},
    }
    text = _unify_six_dim_text(report)
    assert '【风险边界】中等风险' in text
    assert '【估值评估】估值偏高' in text
    assert '【情绪环境】市场偏暖' in text
    assert '；' in text


def test_unify_six_dim_text_empty():
    text = _unify_six_dim_text({})
    assert text == '各维数据不足'


def test_unify_six_dim_text_order():
    """验证输出顺序：风险→估值→情绪→结构→量价→资金"""
    report = {
        'chip_fund': {'title': '资金筹码', 'text': '流入'},
        'risk': {'title': '风险边界', 'text': '中等'},
        'structure': {'title': '结构位置', 'text': '上方'},
    }
    text = _unify_six_dim_text(report)
    pos_risk = text.index('【风险边界】')
    pos_struct = text.index('【结构位置】')
    pos_fund = text.index('【资金筹码】')
    assert pos_risk < pos_struct < pos_fund


# ── _quality_to_text ──────────────────────────────────────────
def test_quality_to_text_no_anomalies():
    text = _quality_to_text({'anomalies': []})
    assert '完整' in text


def test_quality_to_text_with_anomalies():
    text = _quality_to_text({'anomalies': ['risk', 'valuation']})
    assert 'risk' in text
    assert '不完整' in text


# ── _generate_six_dim_report ──────────────────────────────────
def test_generate_six_dim_report_format():
    dim_results = {
        'structure': _make_dim(plain='结构上升', light='green'),
        'volume_price': _make_dim(plain='量价配合', light='yellow'),
        'chip_fund': _make_dim(plain='资金流入', light='green'),
        'emotion': _make_dim(plain='情绪偏暖', light='yellow'),
        'risk': _make_dim(plain='风险中等', light='yellow'),
        'valuation': _make_dim(plain='估值偏低', light='green'),
    }
    report = _generate_six_dim_report(dim_results)
    assert len(report) == 6
    for key in ['risk', 'valuation', 'emotion', 'structure', 'volume_price', 'chip_fund']:
        assert key in report
        assert 'title' in report[key]
        assert 'light' in report[key]
        assert 'text' in report[key]
        assert 'judgment' in report[key]
        assert 'evidence' in report[key]
        assert 'metrics' in report[key]


def test_generate_six_dim_report_fallback_text():
    """dim_results为空时每个维度应有非空text"""
    report = _generate_six_dim_report({})
    for key in report:
        assert len(report[key]['text']) > 0, f"{key} text is empty"


# ── evaluate() 输出包含 six_dim_report ────────────────────────
def test_evaluate_contains_six_dim_report():
    engine = Dim8SummaryEngine()
    dim_results = {
        'signal': _make_dim(plain='信号确认'),
        'structure': _make_dim(plain='结构上升'),
        'volume_price': _make_dim(plain='量价配合'),
        'chip_fund': _make_dim(plain='资金流入'),
        'emotion': _make_dim(plain='情绪偏暖'),
        'risk': _make_dim(plain='风险中等'),
        'valuation': _make_dim(plain='估值偏低'),
    }
    result = engine.evaluate(dims={}, tags={}, lifecycle={'dim_results': dim_results})
    sd = result['status_description']
    assert 'six_dim_report' in sd
    assert len(sd['six_dim_report']) == 6
    assert 'plain' in sd
    assert 'quality_text' in sd


def test_evaluate_unified_text_nonempty():
    engine = Dim8SummaryEngine()
    dim_results = {
        'signal': _make_dim(plain='信号'),
        'structure': _make_dim(plain='结构好'),
        'volume_price': _make_dim(plain='量价好'),
        'chip_fund': _make_dim(plain='资金好'),
        'emotion': _make_dim(plain='情绪好'),
        'risk': _make_dim(plain='风险低'),
        'valuation': _make_dim(plain='估值低'),
    }
    result = engine.evaluate(dims={}, tags={}, lifecycle={'dim_results': dim_results})
    assert result['status_description']['plain'] != ''


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
