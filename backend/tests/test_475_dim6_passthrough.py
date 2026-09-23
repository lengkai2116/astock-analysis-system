"""475号测试：dim6 现状层补产出与修正（P1-P5 + P7 + P16 + ⑪）

覆盖：
- P1 `risk_sources` 5 源明细透传；⑫ 事件升格路径不再丢失 risk_sources（原整体替换）
- P2 `piers_leverage` 未触发也透传 metrics + `piers_leverage_triggered` 消歧
- P3 兜底「无显著风险」移至装配末端，不再与 PIERS-E 因子并存矛盾
- P4 `risk_detail` 保留源计数 + 源名，升格改为追加后缀（不覆写）
- P5 audit 条件名 `无极高风险事件`（与实现 severity=='极高' 对齐，判据不变）
- P7 `right_side_confirm='否决'` 实命中 priority-3 失效条件
- P16 `_assess_liquidity` 计算异常不再静默吞（改 logger.warning）
- ⑪ df 缺失兜底 geo 补 `dist_to_prev_high_pct` 键
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
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


def _ctx(df=None, basic=None):
    return {'daily_df': df if df is not None else _mk_df(),
            'daily_basic_df': basic if basic is not None else _mk_basic()}


def _evaluate(tags, ctx=None):
    return Dim6RiskEngine().evaluate({}, tags, data_context=ctx or _ctx())


# ══════════════════════════════════════════════════════════
# P1 risk_sources 明细透传 + ⑫ 升格不丢源
# ══════════════════════════════════════════════════════════

def test_p1_risk_sources_passthrough():
    """5 源 name/level 明细透传（茅台型：缠论 HIGH + 主力 distributing → 2 高）"""
    tags = dict(_P_BASE, risk_level='HIGH', main_force_phase='distributing')
    out = _evaluate(tags)
    sd = out['status_description']
    rs = sd['risk_sources']
    assert len(rs) == 5, f"应透传 5 源, 实际: {rs}"
    assert '缠论风险：高' in rs and '主力风险：高' in rs
    assert '财务风险：低' in rs and '事件风险：低' in rs and '流动性风险：低' in rs
    assert out['judgment']['level'] == '高'


def test_p1_d12_upgrade_keeps_risk_sources():
    """⑫：事件升格路径原以整体替换 risk_info → 会丢 risk_sources；修复后应保留且 detail 追加后缀"""
    tags = dict(_P_BASE, fina_health='fail')
    tags['event_risk_factors'] = [
        {'category': '事件风险', 'factor': 'longhubang', 'severity': '高', 'satisfied': True}]
    out = _evaluate(tags)
    sd = out['status_description']
    assert out['judgment']['level'] == '高', "1 个高风险源 + 高事件升格 → 高"
    assert len(sd['risk_sources']) == 5, f"升格不应丢 risk_sources: {sd['risk_sources']}"
    assert '财务风险：高' in sd['risk_sources']
    assert '1个高风险源：财务风险' in sd['risk_detail'], f"detail 应保留源计数: {sd['risk_detail']}"
    assert '事件升格：longhubang' in sd['risk_detail'], f"detail 应含升格后缀: {sd['risk_detail']}"


# ══════════════════════════════════════════════════════════
# P2 piers_leverage 未触发也透传 + 消歧标志
# ══════════════════════════════════════════════════════════

def test_p2_piers_metrics_passthrough_when_not_triggered():
    """未触发（dta≤70 且 roce≥15）→ 仍透传 metrics 供「达标」话术，triggered=False"""
    out = _evaluate(dict(_P_BASE, debt_to_assets=40.0, roce=20.0))
    sd = out['status_description']
    assert sd['piers_leverage'] == {'debt_to_assets': 40.0, 'roce': 20.0}
    assert sd['piers_leverage_triggered'] is False
    assert not any('PIERS-E' in f for f in sd['risk_factors'])


def test_p2_piers_triggered_flag():
    """触发（roce<15）→ triggered=True 且含 PIERS-E 因子"""
    out = _evaluate(dict(_P_BASE, debt_to_assets=40.0, roce=8.0))
    sd = out['status_description']
    assert sd['piers_leverage_triggered'] is True
    assert any('PIERS-E' in f for f in sd['risk_factors'])


# ══════════════════════════════════════════════════════════
# P3 兜底「无显著风险」不再与 PIERS-E 并存矛盾
# ══════════════════════════════════════════════════════════

def test_p3_no_fallback_when_piers_factor_exists():
    """300750 型：基础源全空但有 PIERS-E 因子 → 不应出现「综合：无显著风险」"""
    out = _evaluate(dict(_P_BASE, fina_health='pass', debt_to_assets=40.0, roce=8.0))
    rf = out['status_description']['risk_factors']
    assert any('PIERS-E' in f for f in rf), f"应有 PIERS-E 因子: {rf}"
    assert not any('无显著风险' in f for f in rf), f"不应并存兜底: {rf}"


def test_p3_fallback_when_truly_empty():
    """真正无任何因子 → 兜底仍在"""
    out = _evaluate(dict(_P_BASE, debt_to_assets=40.0, roce=20.0))
    rf = out['status_description']['risk_factors']
    assert rf == ['综合：无显著风险（无）'], f"空场景应保留兜底: {rf}"


# ══════════════════════════════════════════════════════════
# P5 audit 条件名对齐
# ══════════════════════════════════════════════════════════

def test_p5_audit_condition_renamed():
    out = _evaluate(dict(_P_BASE))
    names = [c['name'] for c in out['audit']['conditions']]
    assert '无极高风险事件' in names, f"应改名, 实际: {names}"
    assert '无高风险事件' not in names
    cond = next(c for c in out['audit']['conditions'] if c['name'] == '无极高风险事件')
    assert cond['threshold'] == '无极高风险'


def test_p5_judge_unchanged_extreme_not_satisfied():
    """判据不变：极高事件 → 条件不满足"""
    tags = dict(_P_BASE, event_details=[{'event_type': 'st_warning', 'description': 'st',
                                         'direction': -2, 'confidence': 0.9,
                                         'event_date': '2026-09-15'}])
    out = _evaluate(tags)
    cond = next(c for c in out['audit']['conditions'] if c['name'] == '无极高风险事件')
    assert cond['satisfied'] is False
    assert 'ST预警' in cond['actual']


# ══════════════════════════════════════════════════════════
# P7 right_side_confirm 实命中（非死代码）
# ══════════════════════════════════════════════════════════

def test_p7_right_side_deny_hits_invalidation():
    out = _evaluate(dict(_P_BASE, right_side_confirm='否决'))
    assert '右侧确认转否决' in out['status_description']['invalidation']


def test_p7_right_side_other_values_no_hit():
    out = _evaluate(dict(_P_BASE, right_side_confirm='强确认'))
    assert '右侧确认转否决' not in out['status_description']['invalidation']


# ══════════════════════════════════════════════════════════
# P16 静默吞异常 → logger.warning
# ══════════════════════════════════════════════════════════

def test_p16_liquidity_exception_logs_warning(caplog):
    """amount 无法转 float → 原 bare except:pass 静默；现应记 warning"""
    bad_df = _mk_df(amount=['abc'] * 70)
    with caplog.at_level(logging.WARNING,
                         logger='app.opportunity_atlas.dimensions.dim6_risk_engine'):
        out = _evaluate(dict(_P_BASE), ctx=_ctx(df=bad_df))
    assert out['status_description']['liquidity_risk'] is False, "异常时保守不触发"
    assert any('_assess_liquidity 成交额计算异常' in r.message for r in caplog.records), \
        f"应记 warning, 实际: {[r.message for r in caplog.records]}"


# ══════════════════════════════════════════════════════════
# ⑪ df 缺失兜底 geo 补键
# ══════════════════════════════════════════════════════════

def test_d11_empty_df_fallback_has_prev_high_key():
    """df 为空 → 兜底 geo 含 dist_to_prev_high_pct 键（原缺），status_description 该项为 None"""
    out = _evaluate(dict(_P_BASE), ctx=_ctx(df=pd.DataFrame()))
    sd = out['status_description']
    assert 'dist_to_prev_high_pct' in sd
    assert sd['dist_to_prev_high_pct'] is None
