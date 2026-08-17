"""319号 R1-R3 回归测试：估值体系统一（valuation_level 主导）

背景：常润股份等 447+160 只股票存在"估值定位=低估但风险提示=估值偏高"冲突，
根因是 _evaluate_gate 用 PE 分位独立判定估值分级，与 valuation_level 两套口径并存。
修复：估值分级与风险提示统一由 valuation_level 主导；level 低但 PE 分位高 → 盈利下滑提示。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def validator():
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    return L4CrossValidator()


# ────────────────────────────────────────────────────────────
# R1: _evaluate_gate 估值分级改 valuation_level 主导
# ────────────────────────────────────────────────────────────

def test_gate_level_low_with_high_pe_pct_no_valuation_risk(validator):
    """level=low 且 PE 分位高（常润股份场景）→ 估值分级应为 none（不报估值偏高）

    修复前：pe_pct=86.5 → gate['valuation']='moderate'（与 level=low 冲突）
    修复后：valuation_level 主导，level=low 不进入估值分级 → 'none'
    """
    tags = {
        'valuation_level': 'low',
        'pe_percentile_5y': '86.5',
        'valuation_deviation': '8.7',
        'fina_health': 'pass',
    }
    gate = validator._evaluate_gate('603201.SH', tags)
    assert gate['valuation'] == 'none', f"level=low 不应产生估值分级，实际 {gate['valuation']}"


def test_gate_level_high_pe_gt90_deep(validator):
    """level=high 且 PE 分位>90（双信号共振）→ deep 判定（处置=强提示+仓位压缩，335号非硬否决）"""
    tags = {
        'valuation_level': 'high',
        'pe_percentile_5y': '93.0',
        'valuation_deviation': '-25.0',
    }
    gate = validator._evaluate_gate('TEST.SH', tags)
    assert gate['valuation'] == 'deep', f"level=high + PE>90 应判 deep，实际 {gate['valuation']}"


def test_gate_level_high_pe_pct_low_mild(validator):
    """level=high 但 PE 分位低（相对市场贵）→ mild（不硬否决）"""
    tags = {
        'valuation_level': 'high',
        'pe_percentile_5y': '35.0',
        'valuation_deviation': '5.0',
    }
    gate = validator._evaluate_gate('TEST.SH', tags)
    assert gate['valuation'] in ('mild', 'none'), f"level=high+PE 低分位应 mild/none，实际 {gate['valuation']}"


def test_gate_fair_never_deep(validator):
    """level=fair 无论 PE 分位多高都不应判 deep（合理股不误伤）"""
    tags = {
        'valuation_level': 'fair',
        'pe_percentile_5y': '95.0',
        'valuation_deviation': '-30.0',
    }
    gate = validator._evaluate_gate('TEST.SH', tags)
    assert gate['valuation'] != 'deep', f"level=fair 不应判 deep，实际 {gate['valuation']}"


# ────────────────────────────────────────────────────────────
# R2: _build_risk_warnings 估值提示与 level 对齐（319号修订版：
#     数据驱动分叉——EPS 方向 × PB 分位，取消"需核实"推诿文案）
# ────────────────────────────────────────────────────────────

def test_risk_warnings_level_low_pe_high_eps_neg(validator):
    """level=low + PE 分位高 + EPS 下滑 → 提示盈利下滑风险"""
    tags = {
        'valuation_level': 'low',
        'pe_percentile_5y': '86.5',
        'pb_percentile_5y': '30.4',
        'valuation_deviation': '8.7',
        'fina_health': 'pass',
        'sector_heat': 'top_10',
    }
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate, eps_yoy=-0.35, pb_pct=30.4)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert val_warnings, "应有估值相关提示"
    assert all('偏高' not in w or '盈利下滑' in w for w in val_warnings), \
        f"不应报'估值偏高'（level=low），实际 {val_warnings}"
    assert any('盈利下滑' in w for w in val_warnings), f"应提示盈利下滑，实际 {val_warnings}"


def test_risk_warnings_level_low_pe_high_eps_pos_pb_low(validator):
    """level=low + PE 分位高 + EPS 增长 + PB 分位低（困境反转）→ 机会类描述，非风险"""
    tags = {
        'valuation_level': 'low',
        'pe_percentile_5y': '86.5',
        'pb_percentile_5y': '25.0',
        'valuation_deviation': '8.7',
        'fina_health': 'pass',
        'sector_heat': 'top_10',
    }
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate, eps_yoy=0.25, pb_pct=25.0)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert val_warnings, "应有估值相关说明"
    joined = ' '.join(val_warnings)
    assert any('困境反转' in w or '盈利改善' in w or '资产端便宜' in w for w in val_warnings), \
        f"EPS 增长+PB 低应输出机会类描述，实际 {val_warnings}"
    assert all('偏高' not in w for w in val_warnings), f"不应报估值偏高，实际 {val_warnings}"


def test_risk_warnings_level_low_pe_high_eps_pos_pb_high(validator):
    """level=low + PE 分位高 + EPS 增长 + PB 分位高 → 估值收缩风险描述"""
    tags = {
        'valuation_level': 'low',
        'pe_percentile_5y': '86.5',
        'pb_percentile_5y': '70.0',
        'valuation_deviation': '8.7',
        'fina_health': 'pass',
        'sector_heat': 'top_10',
    }
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate, eps_yoy=0.25, pb_pct=70.0)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert val_warnings, "应有估值相关提示"
    joined = ' '.join(val_warnings)
    assert any('增长' in w and '收缩' in w for w in val_warnings), \
        f"EPS 增长+PB 高应提示估值收缩风险，实际 {val_warnings}"


def test_risk_warnings_level_low_pe_high_no_eps(validator):
    """level=low + PE 分位高 + 无 EPS 数据 → 不输出 PE 相关提示（避免无依据输出）"""
    tags = {
        'valuation_level': 'low',
        'pe_percentile_5y': '86.5',
        'valuation_deviation': '8.7',
        'fina_health': 'pass',
        'sector_heat': 'top_10',
    }
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate, eps_yoy=None, pb_pct=None)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert not val_warnings, f"无 EPS 数据不应输出 PE 相关提示，实际 {val_warnings}"


def test_risk_warnings_level_high_reports_overvalued(validator):
    """level=high + PE 分位高 → 正常报"估值偏高"（真实高估）"""
    tags = {
        'valuation_level': 'high',
        'pe_percentile_5y': '88.0',
        'valuation_deviation': '-15.0',
    }
    gate = {'valuation': 'moderate', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert val_warnings and any('估值偏高' in w for w in val_warnings), \
        f"level=high 应报估值偏高，实际 {val_warnings}"


def test_risk_warnings_no_conflict_for_level_fair(validator):
    """level=fair + PE 分位正常 → 无估值风险提示"""
    tags = {
        'valuation_level': 'fair',
        'pe_percentile_5y': '45.0',
        'valuation_deviation': '2.0',
    }
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    warnings = validator._build_risk_warnings(tags, gate)
    val_warnings = [w['content'] for w in warnings if w['type'] == 'valuation']
    assert not val_warnings, f"level=fair+PE 正常分位不应有估值提示，实际 {val_warnings}"


# ────────────────────────────────────────────────────────────
# 335号 §3：deep 定位修正——由"硬否决"改为"高风险机会强提示"（仓位压缩，非剔除）
# ────────────────────────────────────────────────────────────

def test_deep_strong_hint_not_hard_veto(validator):
    """335号：deep 判定保留，但不触发硬否决（不进 hard_risks），L0 软约束压缩仓位"""
    tags = {
        'valuation_level': 'extreme_high',
        'pe_percentile_5y': '95.0',
        'valuation_deviation': '-30.0',
    }
    gate = validator._evaluate_gate('TEST.SH', tags)
    assert gate['valuation'] == 'deep', f"应判 deep，实际 {gate['valuation']}"
    # 非否决：deep 不进 hard_risks（硬否决仅限不可逆项：regulatory 等）
    assert 'event_negative' not in gate['hard_risks'], \
        f"deep 不应触发硬否决，实际 hard_risks={gate['hard_risks']}"

    # L0 软约束（status_engine）：deep → 仓位系数 ×0.3（强提示+压缩，非剔除）
    from app.opportunity_atlas.status_engine import StatusEngine
    se = StatusEngine()
    l0 = se._apply_l0(tags, {}, None)
    assert not l0['hard_veto'], "deep 不应硬否决"
    assert l0['position_coeff'] < 1.0, f"deep 应压缩仓位，实际 position_coeff={l0['position_coeff']}"
