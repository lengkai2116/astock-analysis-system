"""322号 S1：operation_advice 生成——七维+几何+情景概率+executable

结论层复用 321 号 arbitrate 状态机（与机会图谱同源）；五维信号 + K线 → 状态刻画。
analyze 响应时实时组装（毫秒级），不落库不入快照。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.advice_builder import (  # noqa: E402
    _normalize_scenarios,
    build_operation_advice,
)


def test_build_operation_advice_full_structure():
    """五维+K线输入 → 完整 operation_advice（七维/几何/情景/executable）"""
    dimensions = {
        'chanlun': {'direction': '上升', 'buy_point': 'third_buy',
                    'critical_levels': {'support': 10.0, 'resistance': 12.0}},
        'volume_price': {'direction': 'up', 'active_pattern': '放量突破'},
        'chip': {'main_force_direction': '流入'},
        'emotion': {'rotation_state': 'RECOVERY'},
        'factor': {'trend': 'up', 'confidence': 0.7},
    }
    signals = []
    df = None  # K线不足时几何指标返回 None，不报错
    advice = build_operation_advice('TEST.SZ', dimensions, signals, df)
    assert 'state' in advice and 'dimensions' in advice
    assert len(advice['dimensions']) >= 5, "至少 5 个红绿灯维"
    assert 'geometric' in advice
    assert 'scenarios' in advice
    assert 'executable' in advice
    # 情景概率归一化
    probs = [s['prob'] for s in advice['scenarios']]
    assert abs(sum(probs) - 1.0) < 0.01, f"情景概率应归一化: {probs}"


def test_normalize_scenarios_sums_to_one():
    """概率归一化（和为1，非负）"""
    raw = [{'id': 'a', 'prob': 0.5}, {'id': 'b', 'prob': 0.3}, {'id': 'c', 'prob': 0.1}]
    out = _normalize_scenarios(raw)
    assert abs(sum(s['prob'] for s in out) - 1.0) < 1e-6


def test_build_operation_advice_state_from_arbitrate():
    """state 应来自 321 仲裁（与机会图谱同源）"""
    dimensions = {'factor': {'trend': 'down'}}
    advice = build_operation_advice('TEST.SZ', dimensions, [], None)
    assert advice['state'] in ('enter', 'light', 'wait', 'avoid')
    assert 'state_reason' in advice


def test_action_type_semantics():
    """executable.action_type 语义：多维多头→BUY, 单维中性→HOLD, 多维空头→SELL"""
    multi_bull = {
        'chanlun': {'direction': 'up'}, 'volume_price': {'direction': 'up'},
        'chip': {'direction': 'up'}, 'emotion': {'direction': 'up'},
        'factor': {'trend': 'up'},
    }
    enter = build_operation_advice('T.SZ', multi_bull, [], None)
    assert enter['executable']['action_type'] == 'BUY', \
        f"多维多头应 BUY，实际 {enter['state']}/{enter['executable']['action_type']}"
    wait = build_operation_advice('T.SZ', {'factor': {'trend': 'neutral'}}, [], None)
    assert wait['executable']['action_type'] == 'HOLD'
    # 单维看空证据不足 → wait/HOLD；多维看空（含 right_side_confirm 否决或强看空共识）→ SELL
    single_down = build_operation_advice('T.SZ', {'factor': {'trend': 'down'}}, [], None)
    assert single_down['executable']['action_type'] in ('HOLD', 'SELL')


def test_chinese_direction_values_normalized():
    """中文方向值域（chanlun='上升'/'下降'）应被正确识别（审查修正）"""
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({'close': np.linspace(10, 12, 62),
                       'high': np.linspace(10.2, 12.2, 62),
                       'low': np.linspace(9.8, 11.8, 62)})
    # chanlun 中文'上升' + 其他看多 → enter/BUY
    dims_cn = {
        'chanlun': {'direction': '上升'},
        'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'bullish'},
    }
    a = build_operation_advice('T.SZ', dims_cn, [], df)
    assert a['state'] == 'enter', f"中文方向看多应 enter，实际 {a['state']}"
    assert a['executable']['action_type'] == 'BUY'
    # 中文'下降' + 多维看空 → avoid/SELL
    dims_cn_down = {
        'chanlun': {'direction': '下降'},
        'volume_price': {'direction': 'down'},
        'chip': {'direction': 'bearish'},
        'emotion': {'direction': 'bearish'},
        'factor': {'trend': 'bearish'},
    }
    b = build_operation_advice('T.SZ', dims_cn_down, [], df)
    assert b['state'] == 'avoid', f"中文方向看空应 avoid，实际 {b['state']}"
    assert b['executable']['action_type'] == 'SELL'


def test_sell_point_signal_light_red():
    """缠论卖点 → signal 维红绿灯 🔴（审查修正：卖点不标✅）"""
    dims = {
        'chanlun': {'direction': '上升', 'buy_point': '卖点:第三类卖点'},
        'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'bullish'},
    }
    a = build_operation_advice('T.SZ', dims, [], None)
    signal_dim = next(d for d in a['dimensions'] if d['key'] == 'signal')
    assert signal_dim['light'] == '🔴', f"缠论卖点应标🔴，实际 {signal_dim['light']}"


def test_real_tags_override_approximation():
    """真实标签 right_side_confirm=否决 应覆盖 factor.trend 近似（两路径统一）

    背景：000975.SZ 真实标签 rsc=否决、state=avoid，但 advice_builder 用
    factor.trend=bullish 近似 → '强确认' → enter/BUY，与弹窗 diagnose 的 avoid 矛盾。
    修复：优先读真实标签，缺失才用五维近似。
    """
    dims = {
        'chanlun': {'direction': '上升'},
        'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'bullish'},
    }
    # 模拟 000975 真实标签：右侧否决
    tags = {'right_side_confirm': '否决', 'buy_sell_point': 'third_sell',
            'opportunity_state': 'avoid'}
    a = build_operation_advice('000975.SZ', dims, [], None, tags=tags)
    assert a['state'] == 'avoid', f"真实标签否决应得 avoid，实际 {a['state']}"
    assert a['executable']['action_type'] == 'SELL', \
        f"avoid 应 SELL，实际 {a['executable']['action_type']}"
    signal_dim = next(d for d in a['dimensions'] if d['key'] == 'signal')
    assert signal_dim['light'] == '🔴', "否决+卖点 signal 维应🔴"


def test_no_tags_fallback_to_approximation():
    """无真实标签时回退五维近似（保持向后兼容）"""
    dims = {
        'chanlun': {'direction': 'up'}, 'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish'}, 'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'up'},
    }
    a = build_operation_advice('T.SZ', dims, [], None)
    assert a['state'] == 'enter', f"无标签多维看多应 enter，实际 {a['state']}"


def test_avoid_state_zero_position():
    """avoid 态 → max_pct=0、entry_rules 空（与弹窗 diagnose max_ratio=0 一致）"""
    dims = {
        'chanlun': {'direction': '上升'},
        'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'bullish'},
    }
    tags = {'right_side_confirm': '否决', 'opportunity_state': 'avoid'}
    a = build_operation_advice('000975.SZ', dims, [], None, tags=tags)
    assert a['state'] == 'avoid'
    ex = a['executable']
    assert ex['position']['max_pct'] == 0.0, f"avoid 仓位应为 0，实际 {ex['position']['max_pct']}"
    assert ex['entry_rules'] == [], "avoid 不应有入场规则"
    assert ex['action_type'] == 'SELL'
