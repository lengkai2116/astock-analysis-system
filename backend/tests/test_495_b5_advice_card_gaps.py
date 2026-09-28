"""495号（A3）：L6 操作建议卡缺项——⑧触发条件独立字段 + ⑩决策依据

Wiki《操作建议卡》10 字段结构，此前缺：
  - ⑧ 触发条件独立字段（entry_rules/exit_rules 仅存在于 executable 机器规则，未透出人读）
  - ⑩ 决策依据（confidence + evidence_top3 为证据，判定理由未独立透出）

新增（向后兼容，不改变既有字段/契约；双侧同步——前端路径 advice_builder +
交叉验证路径 advice_engine，494 R-3 双份收敛惯例）：
  - trigger_conditions：executable entry/exit_rules → 人读文本列表（结构对齐 Wiki ⑧）
  - decision_basis：state_reason（判定理由，与 evidence_top3 证据互补）

带价格 df 使 entry/exit_rules 生成（仿 test_322_s5_executable）；不碰开发库。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas import advice_builder, advice_engine

_DIMS_BULL = {
    'chanlun': {'direction': 'up'}, 'volume_price': {'direction': 'up'},
    'chip': {'direction': 'bullish'}, 'emotion': {'direction': 'bullish'},
    'factor': {'trend': 'up'},
}
_TAGS_AVOID = {'right_side_confirm': '否决', 'buy_sell_point': 'third_sell',
               'opportunity_state': 'avoid'}


def _mk_price_df():
    """60 日 K线：价格 10-12，近20日低点 ≈10.5（近端防守位）→ entry/exit_rules 生成"""
    closes = np.linspace(11.0, 12.0, 60)
    highs = closes + 0.5
    lows = np.concatenate([np.linspace(9.0, 10.5, 30), np.linspace(10.5, 11.5, 30)])
    return pd.DataFrame({'close': closes, 'high': highs, 'low': lows})


_BUILDERS = {
    'advice_builder(前端路径)': advice_builder.build_operation_advice,
    'advice_engine(cross_validate路径)': advice_engine.build_operation_advice,
}


class TestTriggerConditions:
    """⑧ 触发条件独立字段"""

    def test_enter_state_has_human_readable_triggers(self):
        for name, bld in _BUILDERS.items():
            a = bld('T.SZ', dict(_DIMS_BULL), [], _mk_price_df())
            tc = a['trigger_conditions']
            assert isinstance(tc, list) and tc, f'{name}: enter 态应有触发条件'
            assert any('收盘价' in c for c in tc), f'{name}: 触发条件应为人读文本（收盘价...）'
            ex = a['executable']
            assert len(tc) == len(ex.get('entry_rules', [])) + len(ex.get('exit_rules', [])), \
                f'{name}: 触发条件条目数应与 executable 规则一致'

    def test_avoid_state_no_entry_trigger(self):
        for name, bld in _BUILDERS.items():
            a = bld('000975.SZ', dict(_DIMS_BULL), [], None, tags=dict(_TAGS_AVOID))
            assert a['state'] == 'avoid', name
            assert a['executable']['entry_rules'] == [], name
            assert not any('买入' in c for c in a['trigger_conditions']), \
                f'{name}: avoid 不应有入场触发'


class TestDecisionBasis:
    """⑩ 决策依据独立字段"""

    def test_decision_basis_equals_state_reason(self):
        for name, bld in _BUILDERS.items():
            a = bld('T.SZ', dict(_DIMS_BULL), [], _mk_price_df())
            assert a['decision_basis'] == a['state_reason'], name
            assert a['decision_basis'], f'{name}: 决策依据不应为空（enter 有判定理由）'

    def test_avoid_decision_basis_hard_reason(self):
        for name, bld in _BUILDERS.items():
            a = bld('000975.SZ', dict(_DIMS_BULL), [], None, tags=dict(_TAGS_AVOID))
            assert a['decision_basis'] == a['state_reason'], name
            assert a['decision_basis'], f'{name}: avoid 决策依据不应为空（否决理由）'


class TestCard10Fields:
    """Wiki 10 字段结构完整性（495 A3 定稿：字段全覆盖）"""

    def test_all_ten_fields_present(self):
        for name, bld in _BUILDERS.items():
            a = bld('T.SZ', dict(_DIMS_BULL), [], _mk_price_df())
            for key in ('action_label',       # ① 操作动作
                        'signal_light',       # ② 信号灯
                        'target_levels',      # ⑤ 目标（多级含第一/第二）
                        'expected_holding',   # ⑦ 预期持有
                        'trigger_conditions',  # ⑧ 触发条件
                        'invalidation',       # ⑨ 失效条件
                        'confidence', 'evidence_top3', 'decision_basis'):  # ⑩ 置信度与依据
                assert key in a, f'{name}: 建议卡缺字段 {key}'
            assert 'max_position_ratio' in a['action']       # ④ 建议仓位
            assert 'max_pct' in a['executable']['position']  # ④（仓位约束）
            assert 'stop_loss_price' in a                    # ⑥ 止损位

    def test_existing_fields_unchanged(self):
        for name, bld in _BUILDERS.items():
            a = bld('T.SZ', dict(_DIMS_BULL), [], _mk_price_df())
            assert isinstance(a['evidence_top3'], list), name
            assert isinstance(a['confidence'], str) and a['confidence'], name
            assert isinstance(a['target_levels'], list), name
            assert a['signal_light'] in ('🟢', '🟡', '🟠', '🔴'), name
