"""323号 S8 测试：映射与降级机制（方向冲突降级/市场状态过滤/交易机制硬约束）

方案 §七（建议卡 §三）：
- 方向冲突降级：1维反向→置信度中+仓位减半；≥2维反向→强制观望
- 市场状态过滤：sentiment=climax/ebb 时买入类降级
- 低置信度限制：置信度低→禁止重仓买入（S6 已实现，此处验证集成）
- 交易机制硬约束：T+1/涨跌停/停牌前置过滤（本期评估）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import pandas as pd


def _mk_df(n=70, last_close=30.0, hi=38.0):
    dates = pd.date_range('2026-05-01', periods=n, freq='D')
    return pd.DataFrame({
        'date': dates, 'open': 25.0, 'close': last_close,
        'high': hi, 'low': 20.0, 'volume': 1e6,
    })


def _dims_with_dirs(dirs):
    """dirs: 五维 direction 列表（bullish/bearish/neutral）——chanlun/volume_price/chip/emotion/factor"""
    c, vp, ch, em, fa = dirs
    return {
        'factor': {'trend': fa, 'conflict_items': []},
        'chanlun': {'direction': c},
        'volume_price': {'direction': vp},
        'chip': {'direction': ch},
        'emotion': {'direction': em},
    }


def test_multi_dim_bearish_forces_wait():
    """≥2 维反向 → 强制观望（state 降级 wait/avoid，不出买入）"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    # 3空2多（chanlun/volume_price/chip bearish，emotion/factor bullish）→ 看空占优
    dims = _dims_with_dirs(['bearish', 'bearish', 'bearish', 'bullish', 'bullish'])
    a = build_operation_advice('TEST.SZ', dims, [], df,
                               tags={'opportunity_state': 'enter'})
    assert a['state'] in ('wait', 'avoid'), \
        f"≥2维反向应强制观望，实际 state={a['state']}"
    assert a['executable']['position']['max_pct'] <= 0.2, \
        "观望态仓位应 ≤0.2"


def test_single_dim_bearish_reduces_position():
    """1 维反向 → 仓位减半（相对 enter 基准 0.6 → 0.3）"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    # 4多1空（仅 chip bearish）→ 1 维反向
    dims = _dims_with_dirs(['bullish', 'bullish', 'bearish', 'bullish', 'bullish'])
    a = build_operation_advice('TEST.SZ', dims, [], df,
                               tags={'opportunity_state': 'enter'})
    if a['state'] == 'enter':
        assert a['executable']['position']['max_pct'] <= 0.3, \
            f"1维反向仓位应减半≤0.3，实际 {a['executable']['position']['max_pct']}"


def test_market_climax_downgrades_buy():
    """市场高潮期（sentiment climax）→ 买入类降级（不重仓）"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = _mk_df()
    dims = _dims_with_dirs(['bullish', 'bullish', 'bullish', 'bullish', 'bullish'])
    dims['emotion']['rotation_state'] = '高潮期'
    a = build_operation_advice('TEST.SZ', dims, [], df,
                               tags={'opportunity_state': 'enter',
                                     'signal_strength': 90,
                                     'evidence_count': 5})
    assert a['action_label'] != '重仓买入', \
        f"高潮期不应重仓买入，实际 {a['action_label']}"
    assert any('高潮' in c or '退潮' in c for c in a['invalidation']), \
        "高潮期应出现在失效条件中"


def test_hard_constraint_suspended_no_entry():
    """停牌/涨跌停硬约束：停牌股不应给出买入建议（评估期：至少不提升仓位）"""
    from app.opportunity_atlas.advice_builder import _apply_hard_constraints
    # 停牌（volume=0 或未交易）
    df = _mk_df()
    df.loc[df.index[-1], 'volume'] = 0
    constraint = _apply_hard_constraints(df, 'enter')
    assert constraint.get('state') in ('wait', 'avoid'), \
        f"停牌股应降级观望，实际 {constraint}"
