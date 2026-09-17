"""459号回归测试：dim6 风险等级 vs 审计自相矛盾（R2）+ 量比真实接线（R4-b）

覆盖：
- R2 改点1：仅 severity∈{高,极高} 事件才把 risk_level 升「高」，中档事件（severity='中'，
  如财务关注/估值过高/主力出货）不再误顶高风险（消除 level=高 与「无高风险事件」=True 并存的自相矛盾）。
- R2 兼容性：普通 ST（severity='高'）仍升「高」（453 已拍板语义，非矛盾）；*ST（severity='极高'）→ 极高。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine


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


def _evaluate(tags):
    eng = Dim6RiskEngine()
    return eng.evaluate({}, tags, data_context=_ctx())


def _audit(out):
    return next(c for c in out['audit']['conditions'] if c['name'] == '无高风险事件')


# ══════════════════════════════════════════════════════════
# R2 改点1：中档事件不再误顶 high
# ══════════════════════════════════════════════════════════

def test_mid_event_not_force_high():
    """仅 severity='中' 的事件（无 catalyst_event）→ risk_level 保持低，不被顶「高」"""
    tags = dict(_P_BASE, catalyst_event='none', fina_health='suspicious')
    tags['event_risk_factors'] = [
        {'category': '事件风险', 'factor': 'goodwill_risk', 'severity': '中', 'satisfied': True}]
    out = _evaluate(tags)
    assert out['judgment']['level'] in ('低', '中'), \
        f"中档事件不应顶成高, 实际 level={out['judgment']['level']}"
    cond = _audit(out)
    assert cond['satisfied'] is True, "中档事件下「无高风险事件」应仍满足"


def test_low_event_only_no_high():
    """event_risks 混入中档项 + 无高风险源 → level 保持低（原 bug 会顶成高）"""
    tags = dict(_P_BASE, catalyst_event='none')
    tags['event_risk_factors'] = [
        {'category': '事件风险', 'factor': '主力出货', 'severity': '中', 'satisfied': True}]
    out = _evaluate(tags)
    assert out['judgment']['level'] == '低', \
        f"仅中档事件应保持低风险, 实际 level={out['judgment']['level']}"


def test_high_event_raises_high():
    """事件 severity='高'（如 catalyst_event 命中）→ risk_level 升「高」仍生效"""
    tags = dict(_P_BASE, catalyst_event='regulatory')
    out = _evaluate(tags)
    assert out['judgment']['level'] == '高', \
        f"高严重度事件应升高, 实际 level={out['judgment']['level']}"


def test_extreme_event_raises_extreme():
    """事件 severity='极高'（*ST/退）→ risk_level 极度，且 audit 不满足（453 语义保持）"""
    tags = dict(_P_BASE, event_details=[{'event_type': 'st_warning', 'description': 'st',
                                          'direction': -2, 'confidence': 0.9,
                                          'event_date': '2026-09-15'}])
    out = _evaluate(tags)
    assert out['judgment']['level'] == '极高'
    cond = _audit(out)
    assert cond['satisfied'] is False


def test_no_event_baseline():
    """无事件 → level 低、审计满足（基线不变）"""
    out = _evaluate(dict(_P_BASE))
    assert out['judgment']['level'] == '低'
    assert _audit(out)['satisfied'] is True
