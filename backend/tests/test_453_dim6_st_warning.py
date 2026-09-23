"""453号：dim6 事件集 st_warning 纳入（ST预警分档）测试

445 §6.3 dim6「事件集不完整：st_warning 已注册未纳入」。检测器 C3
`event_monitor._detect_st_warning` 早已产出 st_warning 事件（*ST/退市整理 direction=-2，
普通 ST direction=-1，进 tags.event_details），但消费链两处未纳入：

1. SIG 侧 dim6：EVENT_RISK_SET 不含 st_warning → ST 预警不做事件风险源/因子/audit 呈现。
2. JUD 侧 _apply_l0：event_hard_risks 不含 st_warning → 不直接硬否决，
   （仅靠 CATALYST_EVENT_MAP['st_warning']='regulatory' 兜底，但 catalyst_event 取 |direction| 最大，
    *ST 的 regulatory 或可，普通 ST 可能被其它事件覆盖）。

修复（用户拍板：SIG + JUD 分档）：
  - SIG：EVENT_RISK_SET 纳入 st_warning；evaluate 直读 event_details，direction<=-2（*ST/退）→「极高」，
    direction=-1（ST）→「高」；audit「无高风险事件」据此消除恒真。
  - JUD：_apply_l0 直读 event_details，st_warning direction<=-2 → L0a 硬否决；
    direction=-1（未硬否决者）→ L0b 软风险（st_warning，仓位×0.8，yaml soft_risk_coeff）。

注：本测试 dim6 侧全部注入 data_context（daily_df+daily_basic_df），JUD 侧用 mock dm，
不触发真实 DB 回退（避免开发态基准库与 daemon 的 SQLite 锁竞争）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest  # noqa: E402

from app.opportunity_atlas.dimensions.dim6_risk_engine import (
    Dim6RiskEngine, EVENT_RISK_SET, ST_WARNING_EVENT,
)
from app.opportunity_atlas.status_engine import StatusEngine

# ── 数据构造助手 ──
def _mk_df(n=70, amount_wan=30000.0):
    closes = np.linspace(10, 20, n)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99,
        'close': closes, 'vol': [1e5] * n, 'amount': [amount_wan * 10.0] * n,
    }, index=idx)


def _mk_basic(circ_mv_wan=500000.0):
    return pd.DataFrame({
        'ts_code': ['TEST.XSHG'], 'trade_date': ['2026-09-15'],
        'circ_mv': [circ_mv_wan],
    })


_P_BASE = {'risk_level': 'LOW', 'fina_health': 'good', 'catalyst_event': 'none',
           'main_force_phase': 'accumulating', 'volatility_level': 'low',
           'debt_to_assets': 40.0, 'roce': 20.0, 'ts_code': 'TEST.XSHG'}


def _ctx():
    return {'daily_df': _mk_df(amount_wan=60000), 'daily_basic_df': _mk_basic(500000)}


def _ev(e_type, direction, desc=''):
    return {'event_type': e_type, 'description': desc or e_type,
            'direction': direction, 'confidence': 0.9, 'event_date': '2026-09-15'}


class _NoTurnoverDM:
    """JUD _apply_l0 用：无换手率数据，避免 low_liquidity 干扰断言"""
    def get_cached_daily_basic(self, ts_code):
        return pd.DataFrame({'ts_code': [ts_code], 'trade_date': ['2026-09-15'],
                             'turnover_rate': [3.0]})


# ══════════════════════════════════════════════════════════
# SIG 侧 dim6：EVENT_RISK_SET + evaluate 分档
# ══════════════════════════════════════════════════════════

def test_event_risk_set_contains_st_warning():
    """EVENT_RISK_SET 应含 st_warning（445 缺项，SIG 纳入）"""
    assert 'st_warning' in EVENT_RISK_SET
    assert ST_WARNING_EVENT == 'st_warning'


def test_evaluate_st_extreme_raises_extreme_level():
    """*ST/退市整理（direction=-2）→ risk_level 极高、risk_factors 含 ST预警（极高）"""
    tags = dict(_P_BASE, event_details=[_ev('st_warning', -2)])
    eng = Dim6RiskEngine()
    out = eng.evaluate({}, tags, data_context=_ctx())
    assert out['judgment']['level'] == '极高'
    assert out['status_description']['risk_level'] == '极高'
    # risk_factors 是字符串列表 f"{category}：{factor}（{severity}）"
    st_factors = [f for f in out['status_description']['risk_factors'] if 'ST预警' in f]
    assert st_factors, f"应含 ST预警因子, 实际: {out['status_description']['risk_factors']}"
    assert '极高' in st_factors[0], f"ST预警应升极高, 实际: {st_factors}"


def test_evaluate_st_normal_raises_high_level():
    """普通 ST（direction=-1）→ risk_level 高（事件风险源），因子 severity 高"""
    tags = dict(_P_BASE, event_details=[_ev('st_warning', -1)])
    eng = Dim6RiskEngine()
    out = eng.evaluate({}, tags, data_context=_ctx())
    assert out['judgment']['level'] == '高'
    # 因子含 ST预警
    assert any('ST预警' in f for f in out['status_description']['risk_factors'])
    # audit「无高风险事件」在普通 ST 下应满足（ST 是「高」非「极高」）
    cond = next(c for c in out['audit']['conditions'] if c['name'] == '无极高风险事件')
    assert cond['satisfied'] is True, f"普通ST不应计极高, audit: {cond}"


def test_evaluate_st_extreme_audit_not_satisfied():
    """*ST/退市整理 → audit「无高风险事件」不满足（极高风险）"""
    tags = dict(_P_BASE, event_details=[_ev('st_warning', -2)])
    eng = Dim6RiskEngine()
    out = eng.evaluate({}, tags, data_context=_ctx())
    cond = next(c for c in out['audit']['conditions'] if c['name'] == '无极高风险事件')
    assert cond['satisfied'] is False
    assert cond['actual'] == "['ST预警']"


def test_evaluate_no_st_unchanged():
    """无 st_warning 事件 → 不影响基线（仍低风险，因子无 ST预警）"""
    tags = dict(_P_BASE)
    eng = Dim6RiskEngine()
    out = eng.evaluate({}, tags, data_context=_ctx())
    assert out['judgment']['level'] == '低'
    assert not any('ST预警' in f for f in out['status_description']['risk_factors'])


# ══════════════════════════════════════════════════════════
# JUD 侧 _apply_l0：direction 分档
# ══════════════════════════════════════════════════════════

def test_l0_st_extreme_hard_veto():
    """*ST/退市整理（direction=-2）→ L0a 硬否决（ST/退市整理文案）"""
    tags = {'catalyst_event': 'none',
            'event_details': [_ev('st_warning', -2, '退市整理期')]}
    se = StatusEngine(dm=_NoTurnoverDM())
    l0 = se._apply_l0('TEST.XSHG', tags, {}, None)
    assert l0['hard_veto'] is True, f"*ST/退应硬否决, 实际: {l0}"
    assert 'ST' in l0['hard_reason'] or '退市' in l0['hard_reason'], \
        f"hard_reason 应含 ST/退市, 实际: {l0['hard_reason']}"


def test_l0_st_normal_soft_risk():
    """普通 ST（direction=-1）→ 不硬否决，转为 L0b 软风险（仓位×0.8）"""
    tags = {'catalyst_event': 'none',
            'event_details': [_ev('st_warning', -1, 'ST 预警')]}
    se = StatusEngine(dm=_NoTurnoverDM())
    l0 = se._apply_l0('TEST.XSHG', tags, {}, None)
    assert l0['hard_veto'] is False
    assert 'st_warning' in l0['soft_risks'], f"普通ST应入软风险, 实际: {l0['soft_risks']}"
    assert abs(l0['position_coeff'] - 0.8) < 1e-6, \
        f"普通ST仓位系数应为0.8, 实际: {l0['position_coeff']}"


def test_l0_no_st_no_soft_risk():
    """无 st_warning 事件 → 不触发 ST 软风险"""
    tags = {'catalyst_event': 'none', 'event_details': []}
    se = StatusEngine(dm=_NoTurnoverDM())
    l0 = se._apply_l0('TEST.XSHG', tags, {}, None)
    assert 'st_warning' not in l0['soft_risks']


def test_l0_st_still_allows_fraud_extreme():
    """回归：st_warning 事件与 fraud_sign 并存时，fraud_sign 仍硬否决优先"""
    tags = {'catalyst_event': 'none',
            'event_details': [_ev('st_warning', -1, 'ST'), _ev('fraud_sign', -2)]}
    se = StatusEngine(dm=_NoTurnoverDM())
    l0 = se._apply_l0('TEST.XSHG', tags, {}, None)
    assert l0['hard_veto'] is True
    assert '造假' in l0['hard_reason'] or '财务' in l0['hard_reason']


def test_l0_st_normal_direction_gt_minus2_no_effect():
    """st_warning direction=-1 且已有其它硬否决事件时，硬否决文案以首个硬事件为准"""
    tags = {'catalyst_event': 'regulatory',
            'event_details': [_ev('st_warning', -1, 'ST')]}
    se = StatusEngine(dm=_NoTurnoverDM())
    l0 = se._apply_l0('TEST.XSHG', tags, {}, None)
    # catalyst_event=regulatory → L0a 硬否决（原有监管路径），ST 软风险不叠加
    assert l0['hard_veto'] is True
    assert '监管' in l0['hard_reason']

# ══════════════════════════════════════════════════════════
# 源码接线（inspect 手法）
# ══════════════════════════════════════════════════════════

def test_source_status_engine_handles_st():
    """status_engine._apply_l0 应含 st_warning 分档逻辑"""
    import inspect
    src = inspect.getsource(StatusEngine._apply_l0)
    assert 'st_warning' in src
    assert '_st_extreme_dir' in src or '-2' in src


def test_source_dim6_handles_st():
    """dim6 evaluate 事件循环应含 st_warning 分档"""
    import inspect
    src = inspect.getsource(Dim6RiskEngine.evaluate)
    assert 'ST_WARNING_EVENT' in src or "'st_warning'" in src
