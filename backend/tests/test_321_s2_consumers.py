"""321号 S2 消费点改造测试：operation_advice/verdict 从机会状态机派生

背景：S1 已实现仲裁核心 arbitrate()（P0-P7 状态机）。S2 将 L4 消费点接入仲裁：
- _build_operation_advice：avoid → max_position_ratio=0（修 T4：label="右侧否决"但仓位>0）
- _build_verdict：avoid → 输出"回避"语义（修 T3：verdict 说"优质机会建议关注"但时机行"回避"）
- 状态输入：diagnose 用权威 gate + 情绪加权 consensus 调用 arbitrate（预计算与诊断同源）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture(scope='module')
def validator():
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    return L4CrossValidator()


# ══════════════════════════════════════════════════════════
# T4：右侧否决 → max_position_ratio=0（仓位归零）
# ══════════════════════════════════════════════════════════

def test_t4_deny_max_ratio_zero(validator):
    """T4 修复：rsc=否决（即使共识率高）→ operation_advice.max_position_ratio 必须为 0

    修复前：rsc 否决只覆盖 label，max_ratio 仍按共识率映射（实证 000039 max_ratio=0.4）
    """
    tags = {'right_side_confirm': '否决', 'main_force_phase': 'building'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80, 'total_active': 8}
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    advice = validator._build_operation_advice('TEST.SZ', consensus, tags, gate, None)
    assert advice['action'] == 'not_recommended'
    assert advice['max_position_ratio'] == 0.0, \
        f"右侧否决时仓位必须归零，实际 {advice['max_position_ratio']}（修复前为 0.4）"
    assert '回避' in advice['label'] or '否决' in advice['label']


def test_t4_deny_without_gate_ratio_zero(validator):
    """T4 变体：gate 缺省（从 tags 推导深度高估）→ 335号 S2.3 改仓位压缩（≤0.3）非归零"""
    tags = {
        'right_side_confirm': '强确认',
        'valuation_level': 'extreme_high',
        'pe_percentile_5y': '95',
    }
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80, 'total_active': 8}
    advice = validator._build_operation_advice('TEST.SZ', consensus, tags, None, None)
    assert advice['max_position_ratio'] <= 0.3, \
        f"深度高估（gate 缺省推导）应仓位压缩≤0.3，实际 {advice['max_position_ratio']}"


# ══════════════════════════════════════════════════════════
# T3：右侧否决 → verdict 含"回避"语义（不再说"优质机会建议关注"）
# ══════════════════════════════════════════════════════════

def test_t3_deny_verdict_avoid(validator):
    """T3 修复：rsc=否决 + 强看多共识 → verdict 必须含"回避"语义

    修复前：_build_verdict 按共识方向输出"综合判断为优质机会，建议关注"，与时机行矛盾
    """
    tags = {'right_side_confirm': '否决'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80, 'total_active': 8}
    verdict = validator._build_verdict(consensus, [], tags)
    assert '回避' in verdict or '否决' in verdict, \
        f"右侧否决时 verdict 应含回避语义，实际: {verdict}"
    assert '优质机会' not in verdict, \
        f"右侧否决时 verdict 不应再输出'优质机会'，实际: {verdict}"


def test_t3_deny_verdict_avoid_via_diagnose_tags(validator):
    """T3 变体：verdict 从 tags 自省仲裁状态（不依赖外部传入）"""
    tags = {'right_side_confirm': '否决', 'trend_alignment': 'up_aligned'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.80, 'total_active': 8}
    verdict = validator._build_verdict(consensus, [], tags)
    assert '回避' in verdict or '否决' in verdict


# ══════════════════════════════════════════════════════════
# 正向路径不受影响：强确认+看多 → enter，仓位正常、verdict 正常
# ══════════════════════════════════════════════════════════

def test_enter_keeps_position(validator):
    """强确认 + L4 看多共识 → enter，max_ratio>0，verdict 不误报回避"""
    tags = {'right_side_confirm': '强确认'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.70, 'total_active': 8}
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    advice = validator._build_operation_advice('TEST.SZ', consensus, tags, gate, None)
    assert advice['max_position_ratio'] > 0.0
    verdict = validator._build_verdict(consensus, [], tags)
    assert '回避' not in verdict
    assert '优质机会' in verdict or '关注' in verdict or '看多' in verdict


def test_wait_caps_position(validator):
    """右侧未确认 → wait，仓位上限 ≤0.2（保守），不进入建仓建议"""
    tags = {'right_side_confirm': '未确认'}
    consensus = {'direction': 'bullish', 'consensus_rate': 0.70, 'total_active': 8}
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
    advice = validator._build_operation_advice('TEST.SZ', consensus, tags, gate, None)
    assert advice['max_position_ratio'] <= 0.2, \
        f"右侧未确认仓位应 ≤0.2，实际 {advice['max_position_ratio']}"
    assert '等待' in advice['label'] or '观察' in advice['label']


# ══════════════════════════════════════════════════════════
# 权威 gate/consensus 传入仲裁：diagnose 全链路含机会状态
# ══════════════════════════════════════════════════════════

def test_diagnose_includes_state(validator):
    """diagnose 返回应含 opportunity_state（来自仲裁，与 gate/consensus 同源）"""
    tags = {'right_side_confirm': '否决', 'main_force_phase': 'building'}
    # 用轻量调用验证：diagnose 内部会算权威 gate + 情绪加权 consensus
    result = validator.diagnose('TEST.SZ', dict(tags))
    assert result['opportunity_state'] == 'avoid'
    assert result['state_evidence'], "state_evidence 不应为空"
    advice = result['operation_advice']
    assert advice['max_position_ratio'] == 0.0
    assert '回避' in result['cross_validation']['verdict'] or \
           '否决' in result['cross_validation']['verdict']


def test_diagnose_consensus_uses_nine_dim_not_five_dim(validator):
    """336号 S2 遗留：弹窗共识应来自 L1 九维推导（status_verdict），非五维推导（consensus_5d）

    336号 §2.2 要求：弹窗摘要/个股页/快照全部读同一 L2 输出共识（成品仓唯一消费）。
    五维推导（consensus_5d）是 S1 过渡口径，S2 后应切换到 L1 九维推导。
    """
    # 用真实股票验证（300705.SZ StatusEngine 九维：7看多/4中性/0看空）
    result = validator.diagnose('300705.SZ')
    consensus = result.get('cross_validation', {}).get('consensus', {})
    # 关键断言：source 不应是 'five_dim'（S1 过渡口径）
    source = consensus.get('_source', '')
    assert source != 'five_dim', \
        f"弹窗共识仍用五维推导（source={source}），应切换到 L1 九维推导（336号 S2）"
    # 九维推导下 neutral_votes 应 ≥ 2（量价/位置/筹码资金/时间 至少 2 个中性）
    neutral = consensus.get('neutral_votes', 0)
    assert neutral >= 2, \
        f"中性维度数 {neutral} 过少（五维推导特征），L1 九维推导应有 ≥2 个中性维度"
