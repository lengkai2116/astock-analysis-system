"""509号批次1：判定链语义/量纲修复验证（#J2/#J3/#J4/#J5/#J7/#J8）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.3。

批次1 实施范围（2026-10-08，拍板 Q2/Q4 已过；探针量化实证先行）：
  #J2 `cross_validate._build_opportunity_summary`：signal_strength 分级 8/6/4/2 → 80/60/40/20
      （量化实证：全市场 0-100 域，原恒 A+ 52.4%）；
  #J3 `cross_validate` 日环比阈值 ±1.0 → ±10.0（0-10 量纲残留，1pt 属噪声刷屏）；
  #J4 `reliability_assessor._assess_signal` 映射键 `decayed`→`broken`（生产者值域
      healthy/fading/broken，原 'decayed' 永不匹配 → 完全失效信号静默落 0.5）；
  #J5 `factor_arbiter` Step5：情绪极端修正由两分支等价 ×0.85 → 显式「情绪方向 vs 共识
      方向」冲突比较（Q2 拍板；方向一致不修正）；
  #J7 `factor_arbiter` Step2：consensus_rate 去 clamp [0,1] 保留符号（负分落 `<30→avoid`；
      量化实证：75.12% 空头共识被 clamp 抹除为 0）；
  #J8 `signal_analyzer.detect_decay`：各维评分展开 0-100 全域（原加权上限 ≈54 致
      broken(70-100) 永不可达；量化实证：实测 max=22 全 healthy）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# ── #J2：signal_strength 分级 80/60/40/20 ───────────────────

def test_j2_grade_thresholds_0_100():
    """0-100 域分级：80/60/40/20 各档边界正确"""
    from app.opportunity_atlas.cross_validate import L4CrossValidator

    cv = L4CrossValidator.__new__(L4CrossValidator)
    cv._safe_float = staticmethod(lambda v, d=0.0: float(v) if v is not None else d)

    assert cv._build_opportunity_summary(
        {'signal_strength': 90.0}, {}, [])['grade'] == 'A+'
    assert cv._build_opportunity_summary(
        {'signal_strength': 65.0}, {}, [])['grade'] == 'A'
    assert cv._build_opportunity_summary(
        {'signal_strength': 45.0}, {}, [])['grade'] == 'B'
    assert cv._build_opportunity_summary(
        {'signal_strength': 25.0}, {}, [])['grade'] == 'C'
    assert cv._build_opportunity_summary(
        {'signal_strength': 10.0}, {}, [])['grade'] == 'D'
    # 边界值
    assert cv._build_opportunity_summary(
        {'signal_strength': 80.0}, {}, [])['grade'] == 'A+'
    assert cv._build_opportunity_summary(
        {'signal_strength': 79.9}, {}, [])['grade'] == 'A'
    assert cv._build_opportunity_summary(
        {'signal_strength': 60.0}, {}, [])['grade'] == 'A'


# ── #J3：日环比阈值 ±10 ────────────────────────────────────

def test_j3_signal_strength_delta_threshold():
    """日环比 signal_strength：|Δ|>=10 触发（原 ±1 噪声刷屏）"""
    import inspect

    from app.opportunity_atlas import cross_validate as cv_mod

    src = inspect.getsource(cv_mod.L4CrossValidator)
    # 源码级断言：阈值已对齐 0-100
    assert 'abs(delta) >= 10.0' in src, '#J3 日环比阈值应 ≥10.0'


# ── #J4：reliability 映射键 broken ─────────────────────────

def test_j4_decay_mapping_broken():
    """_assess_signal：broken → 0.2（原 'decayed' 键永不匹配落 0.5）"""
    from app.opportunity_atlas.reliability_assessor import _assess_signal

    assert _assess_signal(
        {'signal': {'judgment': {'maintenance': {'status': 'broken'}}}}) == 0.2
    assert _assess_signal(
        {'signal': {'judgment': {'maintenance': {'status': 'healthy'}}}}) == 0.8
    assert _assess_signal(
        {'signal': {'judgment': {'maintenance': {'status': 'fading'}}}}) == 0.5
    # 未知状态 → 默认
    assert _assess_signal(
        {'signal': {'judgment': {'maintenance': {'status': 'decayed'}}}}) != 0.2


# ── #J7：consensus_rate 保留符号 ───────────────────────────

def test_j7_negative_consensus_avoid():
    """空头共识（负 rate）→ final_score 为负 → 落 avoid（不再被 clamp 抹除为 0）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': -0.8},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={}, dims_factor={}, reliability={})
    assert r['final_score'] < 0, f'空头共识 final_score 应为负，实 {r["final_score"]}'
    assert r['opportunity_state'] == 'avoid'


def test_j7_positive_consensus_enter_path():
    """多头强共识仍可进 enter（无回归）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': 0.9},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={'right_side_confirm': '强确认'},
                  dims_factor={}, reliability={})
    assert r['opportunity_state'] == 'enter'
    assert r['final_score'] == 90.0


# ── #J5：情绪极端方向冲突修正 ─────────────────────────────

def test_j5_emotion_conflict_penalty():
    """情绪极端 + 方向冲突（冰点+空头共识）→ ×0.85（再经右侧确认门控 ×0.5）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': -0.6},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={},
                  dims_factor={'emotion': {'direction': 1, 'strength': 0.8}},
                  reliability={})
    # 空头基础分 -60 → Step5 ×0.85 → -51 → Step4 未确认 ×0.5 → -25.5
    assert r['final_score'] == pytest.approx(-25.5, abs=0.01)
    assert '情绪极端修正' in ' '.join(r['state_evidence'])


def test_j5_emotion_align_no_penalty():
    """情绪极端但方向一致（冰点+多头共识）→ 不修正（原实现无条件 ×0.85）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': 0.6},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={},
                  dims_factor={'emotion': {'direction': 1, 'strength': 0.8}},
                  reliability={})
    # 多头基础分 60，方向一致不修正 → 60（×右侧确认默认 0.5=30 → wait）
    assert '情绪极端修正' not in ' '.join(r['state_evidence']), '方向一致不应修正'
    assert r['final_score'] == pytest.approx(30.0, abs=0.01)


def test_j5_emotion_weak_no_penalty():
    """情绪未极端（strength<=0.6）→ 不修正（保持原语义）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': -0.6},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={},
                  dims_factor={'emotion': {'direction': 1, 'strength': 0.5}},
                  reliability={})
    assert '情绪极端修正' not in ' '.join(r['state_evidence'])


# ── #J8：decay 评分标定（broken 可达） ─────────────────────

def test_j8_decay_broken_reachable():
    """全维最差态 → overall_score 达 70+（broken 档可达；原上限 ≈54 不可达）"""
    from app.opportunity_atlas.signal_analyzer import detect_decay

    worst = detect_decay(
        tags={'volume_price_fit': 'diverging', 'volume_ratio': 0.3,
              'main_force_phase': 'distributing', 'fund_flow': '5d_outflow'},
        lifecycle={'day': 30})
    assert worst['overall_score'] >= 70, (
        f'全维最差态应达 broken(70+)，实 {worst["overall_score"]}')
    assert worst['overall_status'] == 'broken'


def test_j8_decay_healthy_low():
    """健康态 → 低分 healthy（标定后不误升档）"""
    from app.opportunity_atlas.signal_analyzer import detect_decay

    r = detect_decay(
        tags={'volume_price_fit': 'healthy', 'volume_ratio': 1.5,
              'main_force_phase': 'building', 'fund_flow': '5d_inflow'},
        lifecycle={'day': 2})
    assert r['overall_score'] < 40, f'健康态应 <40（healthy），实 {r["overall_score"]}'
    assert r['overall_status'] == 'healthy'
