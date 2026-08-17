"""322号 S5：executable 机器可执行契约（虚拟实盘/复盘中心前置数据契约）

executable 结构是虚拟实盘输入（机器可读、确定性）：action_type + entry_rules/
exit_rules（价格触发条件）+ position（仓位约束）。复盘中心回放价格 → 触发规则 →
模拟记账。本测试验证契约形状与状态→动作语义。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.advice_builder import build_operation_advice  # noqa: E402


def test_executable_contract_shape():
    """executable 含 action_type/entry_rules/exit_rules/position，机器可解析"""
    dims = {'factor': {'trend': 'up'},
            'chanlun': {'status_recognition': {
                'support_resistance': {'support': 10.0, 'resistance': 12.0}}}}
    advice = build_operation_advice('T.SZ', dims, [], None)
    ex = advice['executable']
    assert ex['action_type'] in ('BUY', 'HOLD', 'REDUCE', 'SELL', 'WAIT')
    assert isinstance(ex['entry_rules'], list)
    assert isinstance(ex['exit_rules'], list)
    assert 'max_pct' in ex['position'] and 'initial_pct' in ex['position']
    # 规则 trigger 可解析为价格条件
    for r in ex['exit_rules']:
        assert 'close' in r['trigger'] and isinstance(r['size_pct'], int)


def test_avoid_state_action_is_sell():
    """avoid 状态 → executable.action_type = SELL（虚拟实盘应执行卖出）"""
    dims = {
        'chanlun': {'direction': 'down'}, 'volume_price': {'direction': 'down'},
        'chip': {'direction': 'down'}, 'emotion': {'direction': 'down'},
        'factor': {'trend': 'down'},
    }
    advice = build_operation_advice('T.SZ', dims, [], None)
    assert advice['state'] == 'avoid', f"多维看空应 avoid，实际 {advice['state']}"
    assert advice['executable']['action_type'] == 'SELL'


def test_enter_state_action_is_buy():
    """enter 状态 → executable.action_type = BUY（虚拟实盘应执行买入）"""
    dims = {
        'chanlun': {'direction': 'up'}, 'volume_price': {'direction': 'up'},
        'chip': {'direction': 'up'}, 'emotion': {'direction': 'up'},
        'factor': {'trend': 'up'},
    }
    advice = build_operation_advice('T.SZ', dims, [], None)
    assert advice['state'] == 'enter', f"多维看多应 enter，实际 {advice['state']}"
    assert advice['executable']['action_type'] == 'BUY'


def test_support_present_generates_rules():
    """有防守位（近端结构位）→ entry_rules/exit_rules 生成价格触发条件"""
    import numpy as np
    import pandas as pd
    # 构造 60 日 K线：价格 10-12 区间，近20日低点 ≈ 10.5（近端防守位）
    closes = np.linspace(11.0, 12.0, 60)
    highs = closes + 0.5
    lows = np.concatenate([np.linspace(9.0, 10.5, 30), np.linspace(10.5, 11.5, 30)])
    df = pd.DataFrame({'close': closes, 'high': highs, 'low': lows})
    dims = {'factor': {'trend': 'up'}}
    advice = build_operation_advice('T.SZ', dims, [], df)
    ex = advice['executable']
    assert len(ex['entry_rules']) >= 1, "有防守位应生成入场规则"
    assert len(ex['exit_rules']) >= 1, "有防守位应生成退出规则"
    # 触发条件为可解析价格比较（复盘中心回放 close 值即可判定）
    # 2026-08-13 知识库修正：止损=近端结构位 max(MA20, 近20日低点)（约 11.84），
    # 而非 60日低点 9.0（60日低点对右侧拉升股过宽，如 301119 曾致 -25.3% 止损）
    assert 'close <= 12.0' in ex['entry_rules'][0]['trigger'], \
        f"入场应为现价 12.0，实际 {ex['entry_rules'][0]['trigger']}"
    assert 'close < 11.84' in ex['exit_rules'][0]['trigger'], \
        f"止损应为近端结构位 max(MA20,lo20)≈11.84，实际 {ex['exit_rules'][0]['trigger']}"
    assert ex['entry_rules'][0]['trigger'] != ex['exit_rules'][0]['trigger'], \
        "入场与止损不得同价位（回放歧义）"
