"""491-4（491 批次4 / R3）：dim6 未消费键逐键定性

覆盖（用户 2026-09-27 拍板 A/B/C/D/E）：
- A 采用：`risk_sources` / `piers_leverage_triggered` / `liquidity_risk`
  进 dim8 risk E 表（作「因」）→ _compose_dim_evidence 产句；bool 渲染「是/否」；
  risk_sources 字符串列表**逐项展开**为多条佐证。
- B 保留契约：event_summary 仍**不在** dim8 risk E 表（对齐 479 P13：主源 event_details）。
- C 删除：dim6 `risk_evidence` 键及本地构建链已移除，产出 dict 不再含该键。
- E 附带：`light_derive.risk_light` 兜底分支兼容 dim6 字符串列表形态（475 P1 后
  原按 dict 解析 → 恒不可达），修正后按「名称：等级」高源计数派生。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
from app.opportunity_atlas import light_derive as LD
from app.opportunity_atlas.dimensions import dim8_summary_engine as D8
from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine


def _mk_df(n=70, amount=None):
    closes = np.linspace(10, 20, n)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99, 'close': closes,
        'vol': [1e5] * n,
        'amount': amount if amount is not None else [30000.0 * 10.0] * n,
    }, index=idx)


def _mk_basic(circ_mv_wan=500000.0):
    return pd.DataFrame({
        'ts_code': ['TEST.XSHG'], 'trade_date': ['2026-09-15'],
        'circ_mv': [circ_mv_wan],
    })


_P_BASE = {'risk_level': 'LOW', 'fina_health': 'good', 'catalyst_event': 'none',
           'main_force_phase': 'accumulating', 'volatility_level': 'low',
           'debt_to_assets': 40.0, 'roce': 20.0, 'ts_code': 'TEST.XSHG'}


def _evaluate(tags, circ_mv_wan=500000.0):
    return Dim6RiskEngine().evaluate(
        {}, tags, data_context={'daily_df': _mk_df(), 'daily_basic_df': _mk_basic(circ_mv_wan)})


# ══════════════════════════════════════════════════════════
# A：dim8 采用（risk_sources / piers_leverage_triggered / liquidity_risk）
# ══════════════════════════════════════════════════════════

class TestA_AdoptedIntoEvidence:

    def test_e_table_contains_adopted_keys(self):
        risk_e = D8._DIM8_E_FIELDS['risk']
        assert 'risk_sources' in risk_e
        assert 'piers_leverage_triggered' in risk_e
        assert 'liquidity_risk' in risk_e

    def test_risk_sources_list_expanded_into_evidence(self):
        """risk_sources 为「名称：等级」字符串列表 → 逐项展开（非整体拼成一条）"""
        sd = {'risk_sources': ['缠论风险：高', '财务风险：低', '主力风险：高']}
        ev = D8._compose_dim_evidence('risk', sd)
        assert '缠论风险：高' in ev
        assert '财务风险：低' in ev
        assert '主力风险：高' in ev

    def test_bool_fields_rendered_cn(self):
        """bool 达标状态字段渲染「标签：是/否」，不裸放 True/False"""
        sd = {'liquidity_risk': False, 'piers_leverage_triggered': True}
        ev = D8._compose_dim_evidence('risk', sd)
        assert '流动性风险触发：否' in ev
        assert '杠杆/资本回报触发：是' in ev
        assert not any(e in ('True', 'False') for e in ev)

    def test_subsections_contain_adopted_keys(self):
        subs = D8._DIM8_SUBSECTIONS['risk']
        status = next(items for title, items in subs if title == '风险状态')
        assert 'risk_sources' in status
        assert 'liquidity_risk' in status
        assert 'piers_leverage_triggered' in status

    def test_end_to_end_evidence_from_engine(self):
        """端到端：dim6 产出 → dim8 risk evidence 含 5 源「因」"""
        out = _evaluate(dict(_P_BASE, risk_level='HIGH', main_force_phase='distributing'))
        sd = out['status_description']
        ev = D8._compose_dim_evidence('risk', sd)
        assert any('缠论风险：高' in e for e in ev)
        assert any('主力风险：高' in e for e in ev)


# ══════════════════════════════════════════════════════════
# B：保留契约（event_summary 不入 dim8 E 表，对齐 479 P13）
# ══════════════════════════════════════════════════════════

class TestB_KeptKeys:

    def test_event_summary_not_adopted(self):
        assert 'event_summary' not in D8._DIM8_E_FIELDS['risk']

    def test_engine_still_outputs_kept_keys(self):
        """保留契约键仍由引擎产出（atr_14d / 流动性两原值 / event_count / event_summary）"""
        sd = _evaluate(_P_BASE)['status_description']
        for k in ('atr_14d', 'liquidity_avg_amount_wan', 'liquidity_circ_mv_wan',
                  'event_count', 'event_summary', 'support_resistance'):
            assert k in sd, f'保留契约键缺失: {k}'


# ══════════════════════════════════════════════════════════
# C：删除（risk_evidence）
# ══════════════════════════════════════════════════════════

class TestC_Removed:

    def test_risk_evidence_not_produced(self):
        sd = _evaluate(_P_BASE)['status_description']
        assert 'risk_evidence' not in sd


# ══════════════════════════════════════════════════════════
# E：light_derive.risk_light 兼容 dim6 字符串列表形态
# ══════════════════════════════════════════════════════════

class TestE_RiskLightSourceForms:

    def test_string_form_high_counter(self):
        """dim6 产出形态（字符串列表）——原按 dict 解析恒不可达，修正后按高源计数"""
        two_high = {'risk': {'judgment': {}, 'status_description': {
            'risk_sources': ['缠论风险：高', '主力风险：高', '财务风险：低']}}}
        assert LD.risk_light(two_high) == 'red'
        one_high = {'risk': {'judgment': {}, 'status_description': {
            'risk_sources': ['缠论风险：高', '财务风险：低']}}}
        assert LD.risk_light(one_high) == 'yellow'
        zero_high = {'risk': {'judgment': {}, 'status_description': {
            'risk_sources': ['缠论风险：低', '财务风险：低']}}}
        assert LD.risk_light(zero_high) == 'green'

    def test_dict_form_still_supported(self):
        """dict 形态（{'name','level'}）向后兼容"""
        src = {'risk': {'judgment': {}, 'status_description': {
            'risk_sources': [{'level': '高'}, {'level': '高'}, {'level': '低'}]}}}
        assert LD.risk_light(src) == 'red'

    def test_judgment_level_still_priority(self):
        assert LD.risk_light({'risk': {'judgment': {'level': '高'}}}) == 'red'
        assert LD.risk_light({}) == LD.DATA_MISSING
