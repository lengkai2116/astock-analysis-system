"""394号方案 Phase 2 — dim8 输出质量检查测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    RECALC_LIMIT,
    _calc_quality_score,
    _check_dim_quality,
    _extract_dim_audit_confidence,
)


def _make_dim(result_dict):
    """构造一个维度引擎结果"""
    return result_dict


def _good_dim(judgment=None, plain='这是一段描述', confidence=0.8, direction=1):
    return {
        'judgment': judgment or {'overall_light': 'green', 'overall_direction': direction},
        'status_description': {'plain': plain},
        'audit': {'confidence': confidence},
    }


# ── T1.1: audit confidence 提取修复 ────────────────────────
def test_extract_dim_audit_confidence_normal():
    dim_results = {'structure': _good_dim(confidence=0.85)}
    assert _extract_dim_audit_confidence(dim_results, 'structure') == 0.85


def test_extract_dim_audit_confidence_missing():
    assert _extract_dim_audit_confidence({}, 'structure') == 0


def test_extract_dim_audit_confidence_no_audit():
    dim_results = {'structure': {'judgment': {}, 'status_description': {'plain': 'x'}}}
    assert _extract_dim_audit_confidence(dim_results, 'structure') == 0


# ── T2.1: _check_dim_quality 单维度检查 ──────────────────────
def test_check_dim_quality_all_pass():
    dim_results = {'signal': _good_dim()}
    r = _check_dim_quality(dim_results, 'signal')
    assert r['passed'] is True
    assert r['score'] == 1.0


def test_check_dim_quality_missing_dim():
    r = _check_dim_quality({}, 'signal')
    assert r['passed'] is False
    assert r['checks']['exists'] is False


def test_check_dim_quality_no_judgment():
    dim_results = {'signal': {'status_description': {'plain': 'x'}, 'audit': {'confidence': 0.5}}}
    r = _check_dim_quality(dim_results, 'signal')
    assert r['checks']['has_judgment'] is False
    assert r['passed'] is False


def test_check_dim_quality_no_plain():
    dim_results = {'signal': {'judgment': {'overall_light': 'green', 'overall_direction': 1}, 'status_description': {'plain': ''}, 'audit': {'confidence': 0.5}}}
    r = _check_dim_quality(dim_results, 'signal')
    assert r['checks']['has_plain'] is False
    assert r['passed'] is False


def test_check_dim_quality_low_confidence():
    dim_results = {'signal': _good_dim(confidence=0.1)}
    r = _check_dim_quality(dim_results, 'signal')
    assert r['checks']['confidence_ok'] is False
    assert r['passed'] is False


def test_check_dim_quality_direction_zero_exception():
    """emotion 和 valuation 允许 direction=0"""
    dim_results = {'emotion': _good_dim(direction=0)}
    r = _check_dim_quality(dim_results, 'emotion')
    assert r['checks']['direction_consistent'] is True


def test_check_dim_quality_direction_zero_fail():
    """signal 不允许 direction=0"""
    dim_results = {'signal': _good_dim(direction=0)}
    r = _check_dim_quality(dim_results, 'signal')
    assert r['checks']['direction_consistent'] is False


# ── T2.2: _calc_quality_score 聚合评分 ────────────────────────
def test_calc_quality_score_all_good():
    dim_results = {d: _good_dim() for d in ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']}
    r = _calc_quality_score(dim_results)
    assert r['overall_score'] == 1.0
    assert r['anomalies'] == []


def test_calc_quality_score_all_missing():
    r = _calc_quality_score({})
    # emotion/valuation 允许 direction=0，所以总分不完全为0
    assert r['overall_score'] < 0.1
    assert len(r['anomalies']) == 7


def test_calc_quality_score_partial():
    dim_results = {
        'signal': _good_dim(),
        'structure': _good_dim(),
        'volume_price': _good_dim(),
        'chip_fund': _good_dim(),
        'emotion': _good_dim(),
        'risk': _good_dim(),
        'valuation': {},  # missing
    }
    r = _calc_quality_score(dim_results)
    assert 'valuation' in r['anomalies']
    assert 0 < r['overall_score'] < 1.0


# ── T3.4: RECALC_LIMIT ──────────────────────────────────────
def test_recalc_limit_value():
    assert RECALC_LIMIT == 100


# ── T2.4: audit conditions 数量验证 ─────────────────────────
def test_audit_conditions_count():
    """dim8.evaluate() 应产出 7×5=35 条 audit conditions"""
    from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
    engine = Dim8SummaryEngine()
    dim_results = {d: _good_dim() for d in ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']}
    result = engine.evaluate(dims={}, tags={}, lifecycle={'dim_results': dim_results})
    conditions = result['audit']['conditions']
    assert len(conditions) == 35, f'Expected 35 conditions, got {len(conditions)}'


def test_audit_conditions_naming():
    """每个 condition 名称格式: {dim}-{检查项}"""
    from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
    engine = Dim8SummaryEngine()
    dim_results = {d: _good_dim() for d in ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']}
    result = engine.evaluate(dims={}, tags={}, lifecycle={'dim_results': dim_results})
    names = [c['name'] for c in result['audit']['conditions']]
    assert 'signal-引擎存在' in names
    assert 'valuation-confidence≥0.3' in names


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
