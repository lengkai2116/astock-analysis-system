"""323号 S6 测试：advice_builder 新增 6 字段（signal_light/action_label/target_levels/
expected_holding/invalidation/confidence/evidence_top3）

方案 §五 3.1-3.6（v3.1 校准版）：
- signal_light: state 映射 🟢/🟡/🔴
- action_label: 5档（enter+ss>=80→重仓买入 / enter→买入建仓 /
  light→轻仓试探 / wait→持有观望 / avoid→清仓回避）
- target_levels: 60日高点=目标1，×1.15=目标2
- expected_holding: time_rhythm 中文化映射（早筑底/中箱体/临变盘），回退"日线波段 20-30 个交易日"
- invalidation: 止损位+情绪退潮+右侧否决
- confidence: 共识率+证据数+冲突数（阈值校准：>=4 高）
- evidence_top3: dimensions evidence 前 3 条，不足 state_reason 补
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd


def _mk_df(n=70, last_close=30.0, hi=38.0):
    """构造测试 K线（>=60 行，60日高点 hi）"""
    dates = pd.date_range('2026-05-01', periods=n, freq='D')
    return pd.DataFrame({
        'date': dates, 'open': 25.0, 'close': last_close,
        'high': hi, 'low': 20.0, 'volume': 1e6,
    })


def _mk_dims(state_hint='enter', conflict=0):
    """构造五维（S6 字段派生输入）"""
    trend = {'bullish': 'bullish', 'enter': 'bullish', 'wait': 'neutral'}.get(state_hint, 'neutral')
    return {
        'factor': {'trend': trend, 'conflict_items': list(range(conflict))},
        'chanlun': {'direction': '上升', 'buy_point': '第一类买点',
                    'active_pattern': '中枢突破'},
        'volume_price': {'direction': 'up', 'active_pattern': '放量突破'},
        'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish', 'rotation_state': '复苏期'},
    }


def test_signal_light_mapping():
    """signal_light 按 state 映射：enter🟢/light🟢/wait🟡/avoid🔴"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    for state, expect in [('enter', '🟢'), ('light', '🟢'), ('wait', '🟡'), ('avoid', '🔴')]:
        advice = build_operation_advice('TEST.SZ', _mk_dims(state), [], df,
                                        tags={'opportunity_state': state})
        assert advice['signal_light'] == expect, f"{state} 应→{expect}"


def test_action_label_5tier():
    """action_label 5档映射（enter+ss>=80→重仓买入）"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    # enter + ss=85 → 重仓买入（给足证据避免低置信度降级掩盖 5 档映射）
    a = build_operation_advice('TEST.SZ', _mk_dims('enter'), [], df,
                               tags={'opportunity_state': 'enter', 'signal_strength': 85,
                                     'evidence_count': 5, 'consensus_rate': 0.8})
    assert a['action_label'] == '重仓买入'
    # enter + ss=60 → 买入/建仓
    a = build_operation_advice('TEST.SZ', _mk_dims('enter'), [], df,
                               tags={'opportunity_state': 'enter', 'signal_strength': 60,
                                     'evidence_count': 5, 'consensus_rate': 0.8})
    assert a['action_label'] == '买入/建仓'
    # light → 轻仓试探
    a = build_operation_advice('TEST.SZ', _mk_dims('light'), [], df,
                               tags={'opportunity_state': 'light',
                                     'evidence_count': 5, 'consensus_rate': 0.8})
    assert a['action_label'] == '轻仓试探'
    # wait → 持有/观望
    a = build_operation_advice('TEST.SZ', _mk_dims('wait'), [], df,
                               tags={'opportunity_state': 'wait',
                                     'evidence_count': 5, 'consensus_rate': 0.8})
    assert a['action_label'] == '持有/观望'
    # avoid → 清仓回避
    a = build_operation_advice('TEST.SZ', _mk_dims('avoid'), [], df,
                               tags={'opportunity_state': 'avoid'})
    assert a['action_label'] == '清仓回避'


def test_target_levels():
    """target_levels（330号改进1）：目标1=60日高点真实压力、目标2=MA60 真实压力；
    K线不足返回[]；不再使用 ×1.15 虚构目标"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df(hi=38.0)
    a = build_operation_advice('TEST.SZ', _mk_dims(), [], df,
                               tags={'opportunity_state': 'enter'})
    levels = a['target_levels']
    assert len(levels) >= 1, f"应至少 1 级真实压力，实际 {levels}"
    assert levels[0]['price'] == 38.0, f"目标1=60日高点 38.0，实际 {levels[0]}"
    # 目标2 若存在须为真实压力位（MA60），不得是 ×1.15 虚构值
    if len(levels) >= 2:
        assert levels[1]['price'] != round(38.0 * 1.15, 2), \
            f"目标2 不得为 ×1.15 虚构，实际 {levels[1]}"
    # K线不足（<60 行）返回 []
    a2 = build_operation_advice('TEST.SZ', _mk_dims(), _mk_df(n=30), None,
                                tags={'opportunity_state': 'enter'})
    assert a2['target_levels'] == []


def test_expected_holding_mapping():
    """expected_holding：time_rhythm 中文化映射；缺失回退默认"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    a = build_operation_advice('TEST.SZ', _mk_dims(), [], df,
                               tags={'opportunity_state': 'enter',
                                     'time_rhythm': 'early_consolidation'})
    assert '筑底' in a['expected_holding'], \
        f"early_consolidation 应中文化，实际 {a['expected_holding']}"
    # 缺失/unknown 回退默认
    a = build_operation_advice('TEST.SZ', _mk_dims(), [], df,
                               tags={'opportunity_state': 'enter'})
    assert a['expected_holding'] == '日线波段 20-30 个交易日'


def test_invalidation():
    """invalidation：止损位 + 情绪退潮 + 右侧否决"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    # 有 support（K线足够）→ 含止损条件
    a = build_operation_advice('TEST.SZ', _mk_dims(), [], df,
                               tags={'opportunity_state': 'enter'})
    assert a['invalidation'], "invalidation 不应为空（有 support）"
    assert any('止损' in c for c in a['invalidation']), "应含止损位条件"
    # 右侧否决 → 含否决条件
    a = build_operation_advice('TEST.SZ', _mk_dims('avoid'), [], df,
                               tags={'opportunity_state': 'avoid',
                                     'right_side_confirm': '否决'})
    assert any('否决' in c for c in a['invalidation']), "应含右侧否决条件"


def test_confidence_calc():
    """confidence：共识+证据+冲突合成（阈值校准 >=4）"""
    from app.opportunity_atlas.advice_builder import _calc_confidence
    assert _calc_confidence(0.8, 5, 0) == '高'
    assert _calc_confidence(0.8, 3, 0) == '中'   # 证据 3 < 4 → 中
    assert _calc_confidence(0.6, 2, 1) == '中'
    assert _calc_confidence(0.3, 0, 0) == '低'   # 证据 0 → 低
    assert _calc_confidence(0.5, 3, 3) == '低'   # 冲突 3 → 低


def test_low_confidence_downgrade():
    """低置信度强制'轻仓试探' + max_pct<=0.3"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    # enter + ss 高，但 conflict>=3 → 低置信度 → 降级轻仓试探
    a = build_operation_advice('TEST.SZ', _mk_dims('enter', conflict=3), [], df,
                               tags={'opportunity_state': 'enter',
                                     'signal_strength': 85, 'evidence_count': 2})
    assert a['confidence'] == '低', f"冲突3应低置信度，实际 {a['confidence']}"
    assert a['action_label'] == '轻仓试探', "低置信度应降级轻仓试探"
    assert a['executable']['position']['max_pct'] <= 0.3, "低置信度 max_pct<=0.3"


def test_evidence_top3():
    """evidence_top3：dimensions evidence 前 3 条，不足 state_reason 补"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    dims = _mk_dims()
    dims['chanlun']['buy_point'] = '第一类买点'
    dims['volume_price']['active_pattern'] = '放量突破'
    a = build_operation_advice('TEST.SZ', dims, [], df,
                               tags={'opportunity_state': 'enter'})
    ev = a['evidence_top3']
    assert isinstance(ev, list) and len(ev) <= 3, f"≤3条，实际 {len(ev)}"
    assert ev, "evidence_top3 不应为空（有 evidence + state_reason 兜底）"
