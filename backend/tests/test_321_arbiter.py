"""321号 S1 仲裁核心测试：机会状态机 + 显式仲裁优先级表（P0-P7）

背景：机会图谱 4 条平行维度链（潜力/时机/阶段/共识）独立产标签、并列展示，
缺跨维串联仲裁 → 矛盾输出（否决+建仓 305 / 否决+看多类型 490 / 否决+看多共识 522 /
否决+仓位>0）。321号方案引入机会状态机（enter/light/wait/avoid）作为唯一结论，
所有消费点从状态派生。本测试覆盖仲裁优先级表全部分支 + 4 类矛盾输入输出。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.arbiter import arbitrate  # noqa: E402

# ══════════════════════════════════════════════════════════
# P0 硬否决：right_side_confirm=否决 → avoid（覆盖一切）
# ══════════════════════════════════════════════════════════

def test_p0_rsc_deny_always_avoid():
    """右侧否决（缠论卖点/量价背离/预跌形态）→ avoid，即使潜力高、共识强"""
    tags = {
        'right_side_confirm': '否决',
        'signal_strength': 92,          # 高潜力
        'main_force_phase': 'building',  # 主力建仓
    }
    consensus = {'direction': 'bullish', 'consensus_rate': 0.85}  # 强看多共识
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] == 'avoid'
    assert any('否决' in e for e in result['state_evidence']), \
        f"state_evidence 应包含右侧否决依据: {result['state_evidence']}"


# ══════════════════════════════════════════════════════════
# P1 硬风险：gate.hard_risks 含 event_negative（监管立案）→ avoid
# ══════════════════════════════════════════════════════════

def test_p1_hard_risk_avoid():
    """监管立案硬风险 → avoid，即使时机为强确认"""
    tags = {'right_side_confirm': '强确认'}
    gate = {'valuation': 'none', 'hard_risks': ['event_negative'], 'soft_risks': []}
    result = arbitrate(tags, gate=gate)
    assert result['opportunity_state'] == 'avoid'
    assert any('监管' in e or '负面事件' in e for e in result['state_evidence'])


def test_p1_hard_risk_derived_from_tags():
    """无 gate 传入时，从 tags 推导硬风险（catalyst_event=regulatory）"""
    tags = {'right_side_confirm': '强确认', 'catalyst_event': 'regulatory'}
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'avoid'


# ══════════════════════════════════════════════════════════
# 深度高估（335号 S2.3）：不再硬否决，改强提示（估值非绝对精准，可能突破）
# ══════════════════════════════════════════════════════════

def test_p2_deep_overval_not_avoid():
    """深度高估（PE分位>90 或 dev<-20）→ 不再 avoid（335号改强提示），正常走时机判定"""
    tags = {'right_side_confirm': '强确认'}
    gate = {'valuation': 'deep', 'hard_risks': [], 'soft_risks': []}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80}
    result = arbitrate(tags, gate=gate, consensus=consensus)
    assert result['opportunity_state'] != 'avoid'
    assert any('高估' in e for e in result['state_evidence']), \
        "deep 应保留高估强提示"


def test_p2_deep_overval_derived_from_tags():
    """无 gate 传入时，从 tags 推导深度高估 → 强提示不否决"""
    tags = {
        'right_side_confirm': '强确认',
        'valuation_level': 'extreme_high',
        'pe_percentile_5y': 95,
    }
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] != 'avoid'


# ══════════════════════════════════════════════════════════
# P3 强看空：L4 bearish 且 consensus_rate≥0.67 → avoid（336号 C1 对齐 ≥2/3，原 0.65）
# ══════════════════════════════════════════════════════════

def test_p3_strong_bearish_avoid():
    """L4 强看空（bearish≥67%）→ avoid，即使时机为强确认"""
    tags = {'right_side_confirm': '强确认'}
    consensus = {'direction': 'bearish', 'consensus_rate': 0.70}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] == 'avoid'


def test_p3_weak_bearish_not_avoid():
    """L4 弱看空（bearish<67%）不触发 P3 avoid，但 P6 需 bullish 才可入场 → wait"""
    tags = {'right_side_confirm': '强确认'}
    consensus = {'direction': 'bearish', 'consensus_rate': 0.50}
    result = arbitrate(tags, consensus=consensus)
    # 321号 §3.2 P6：可入场=强确认且 L4 bullish≥67%；弱看空不满足 → 回落到 wait
    assert result['opportunity_state'] not in ('avoid', 'enter')


def test_p3_bearish_exact_boundary_067():
    """336号 C1 边界：bearish consensus_rate=0.67（恰好 ≥2/3）→ avoid；0.66 → 不 avoid"""
    tags = {'right_side_confirm': '强确认'}
    hit = arbitrate(tags, consensus={'direction': 'bearish', 'consensus_rate': 0.67})
    assert hit['opportunity_state'] == 'avoid', f"0.67 应触发 P3，实际 {hit['opportunity_state']}"
    miss = arbitrate(tags, consensus={'direction': 'bearish', 'consensus_rate': 0.66})
    assert miss['opportunity_state'] != 'avoid', f"0.66 不应触发 P3，实际 {miss['opportunity_state']}"


# ══════════════════════════════════════════════════════════
# P4 未确认 → wait
# ══════════════════════════════════════════════════════════

def test_p4_unconfirmed_wait():
    """右侧未确认 → wait（覆盖潜力）"""
    tags = {'right_side_confirm': '未确认', 'signal_strength': 88}
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'wait'


# ══════════════════════════════════════════════════════════
# P5 可轻仓：基础确认 + 非强看空 → light
# ══════════════════════════════════════════════════════════

def test_p5_basic_confirm_light():
    """右侧基础确认 + L4 中性 → light"""
    tags = {'right_side_confirm': '基础确认'}
    consensus = {'direction': 'neutral', 'consensus_rate': 0.5}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] == 'light'


# ══════════════════════════════════════════════════════════
# P6 可入场：强确认 + bullish≥0.67 → enter（336号 C1 门槛对齐 ≥2/3，原 0.55）
# ══════════════════════════════════════════════════════════

def test_p6_strong_confirm_bullish_enter():
    """右侧强确认 + L4 看多共识≥67%（336号 C1 门槛对齐 ≥2/3）→ enter"""
    tags = {'right_side_confirm': '强确认'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] == 'enter'


def test_p6_strong_confirm_bearish_not_enter():
    """右侧强确认 + L4 看空 → 不 enter（P3 未到阈值时回落到 wait）"""
    tags = {'right_side_confirm': '强确认'}
    consensus = {'direction': 'bearish', 'consensus_rate': 0.50}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] != 'enter'


# ══════════════════════════════════════════════════════════
# P7 默认：无明确时机信号 → wait（保守）
# ══════════════════════════════════════════════════════════

def test_p7_default_wait():
    """无 right_side_confirm 且无负向信号 → wait（保守默认）"""
    tags = {'signal_strength': 50}
    result = arbitrate(tags)
    assert result['opportunity_state'] in ('wait', 'light')


# ══════════════════════════════════════════════════════════
# 4 类矛盾输入输出正确性（321号 §一 实证）
# ══════════════════════════════════════════════════════════

def test_t1_deny_building_avoid():
    """T1 矛盾：右侧否决 + 主力建仓 → avoid（状态机收敛，不再并列矛盾）"""
    tags = {'right_side_confirm': '否决', 'main_force_phase': 'building'}
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'avoid'
    # 建仓事实保留在 tags（本函数只收敛结论），state_evidence 说明否决依据
    assert result['state_evidence'], "state_evidence 不应为空"


def test_t2_deny_bullish_type_avoid():
    """T2 矛盾：右侧否决 + 看多型机会类型（building_watch）→ avoid"""
    tags = {'right_side_confirm': '否决', 'opportunity_type': 'building_watch'}
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'avoid'


def test_t3_deny_bullish_consensus_avoid():
    """T3 矛盾：右侧否决 + L4 看多共识 → avoid（P0 硬否决压过 P6）"""
    tags = {'right_side_confirm': '否决'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80}
    result = arbitrate(tags, consensus=consensus)
    assert result['opportunity_state'] == 'avoid'


def test_t4_deny_zero_position_state():
    """T4 矛盾：右侧否决 → avoid，为 S2 的 max_position_ratio=0 提供依据"""
    tags = {'right_side_confirm': '否决'}
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'avoid'
    assert 'avoid' in result['opportunity_state']


# ══════════════════════════════════════════════════════════
# consensus 缺省推导（P4.5 阶段无 diagnose 时从 tags 轻量投票）
# ══════════════════════════════════════════════════════════

def test_consensus_derived_from_tags():
    """无 consensus 传入时，从 tags 轻量投票推导方向（强看空 → avoid）"""
    tags = {
        'right_side_confirm': '强确认',
        'trend_alignment': 'down_aligned',   # -1
        'fund_flow': '5d_outflow',           # -1
        'fina_health': 'fail',               # -1
        'valuation_level': 'extreme_high',   # -1
        'buy_sell_point': 'first_sell',      # -1
    }
    result = arbitrate(tags)
    assert result['opportunity_state'] == 'avoid'
