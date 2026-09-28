"""493号 批次4 回归（P2-c 冰点末期 / P2-e ATR止损+分批止盈 / P2-f 大级别否决）

知识库依据：
- P2-c《华泰A股情绪指数》「触及10%恐慌区间不买，回归10%之上再买入（右侧确认）」；
  《共振冰点策略》冰点确认后复苏确认渐进加仓 → 冰点仍处 ice 且有右侧确认时解除 10% 上限。
- P2-e《结构止损》「结构止损与ATR止损同时可用时取两者中较高值」；《ATR止损》
  止损=入场价−2×N值；《分批止盈法》50%@2R / 30%@3R / 20%移动止盈。
- P2-f《分层决策框架》主决策周期唯一、他周期不能否决；周线明确反向与日线买点矛盾时
  「丢弃买点」（降 wait，不判空）。

用户拍板（2026-09-28）：三项全做；P2-c=冰点末期→放开仓位上限；P2-f=降 wait。
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas import advice_engine as ae  # noqa: E402
from app.opportunity_atlas.advice_engine import (  # noqa: E402
    _apply_stop_and_tiers, _weekly_direction,
)
from app.opportunity_atlas.status_engine import (  # noqa: E402
    _emotion_is_recovering, StatusEngine,
)


def _mk_df(n=70, last_close=10.0, hi=12.0, lo=9.0):
    return pd.DataFrame({
        'date': pd.date_range('2026-05-01', periods=n, freq='D'),
        'open': last_close, 'close': last_close,
        'high': hi, 'low': lo, 'volume': 1e6,
    })


# ══ P2-c 冰点末期 ══════════════════════════════════════════════════════

def test_ice_phase_normal_is_not_recovering():
    """ice + 未确认 → 非回升，维持冰点 10% 上限"""
    assert _emotion_is_recovering({'sentiment_phase': 'ice',
                                   'right_side_confirm': '未确认'}) is False
    assert _emotion_is_recovering({'sentiment_phase': 'ice'}) is False


def test_ice_phase_confirmed_is_recovering():
    """ice + 强确认/基础确认 → 冰点末期（回升）"""
    assert _emotion_is_recovering({'sentiment_phase': 'ice',
                                   'right_side_confirm': '强确认'}) is True
    assert _emotion_is_recovering({'sentiment_phase': 'ice',
                                   'right_side_confirm': '基础确认'}) is True


def _se():
    """StatusEngine（注入 stub dm，避免 DataManager 初始化开销）"""
    return StatusEngine(dm=object())


def test_ice_recovering_cap_raised():
    """冰点末期：emotion_position_cap 由 0.10 放开至 recovery 档 0.60"""
    l0 = _se()._apply_l0('T.SZ', {'sentiment_phase': 'ice', 'right_side_confirm': '强确认'}, {})
    assert l0['emotion_position_cap'] == 0.60, f"冰点末期应放开至 0.60，实际 {l0['emotion_position_cap']}"
    assert l0.get('emotion_phase') == 'ice_recovering'


def test_ice_not_recovering_cap_kept():
    """冰点未回升：维持 0.10 上限（原行为不变）"""
    l0 = _se()._apply_l0('T.SZ', {'sentiment_phase': 'ice', 'right_side_confirm': '未确认'}, {})
    assert l0['emotion_position_cap'] == 0.10
    assert l0.get('emotion_phase') is None


# ══ P2-e ATR 止损取较高 + 分批止盈 ════════════════════════════════════

def test_stop_takes_higher_of_struct_and_atr():
    """取较高：结构位 9.0 vs ATR位 9.6（atr_pct=2%）→ 9.6"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'support_price': 9.0, 'atr_pct': 2.0}, {})
    # ATR 止损 = 10 - 2×10×0.02 = 9.6 > 结构 9.0 → 取 9.6
    assert advice['stop_loss_price'] == 9.6
    assert advice['stop_loss_basis'] == '结构止损与ATR止损取较高'


def test_stop_struct_higher_used():
    """结构位 8.0 vs ATR位 9.6（atr_pct=2%）→ 9.6（较高者）"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'support_price': 8.0, 'atr_pct': 2.0}, {})
    assert advice['stop_loss_price'] == 9.6


def test_stop_atr_only_when_no_struct():
    """无结构位 → 用 ATR 止损"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'atr_pct': 5.0}, {})
    # 10 - 2×10×0.05 = 9.0
    assert advice['stop_loss_price'] == 9.0
    assert advice['stop_loss_basis'] == 'ATR止损'


def test_stop_skips_struct_above_entry():
    """结构位高于入场价（无效）→ 仅 ATR"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'support_price': 10.5, 'atr_pct': 2.0}, {})
    assert advice['stop_loss_price'] == 9.6
    assert advice['stop_loss_basis'] == 'ATR止损'


def test_tiers_50_30_20_with_rr_pass():
    """R:R≥2 → 50%@2R / 30%@3R / 20%@None；R=10-9=1 → 目标 12/13"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'support_price': 9.0, 'atr_pct': 0.0,
                                         'rr_value': 2.5}, {})
    tiers = advice['profit_tiers']
    assert len(tiers) == 3
    assert tiers[0]['weight'] == 0.5 and tiers[0]['price'] == 12.0
    assert tiers[1]['weight'] == 0.3 and tiers[1]['price'] == 13.0
    assert tiers[2]['weight'] == 0.2 and tiers[2]['price'] is None
    assert tiers[2]['target_r'] is None


def test_tiers_absent_when_rr_below_gate():
    """R:R<2 → 不给分批止盈计划（与 RR_GATE 一致）"""
    advice = {}
    _apply_stop_and_tiers(advice, 10.0, {'support_price': 9.0, 'atr_pct': 0.0,
                                         'rr_value': 1.5}, {})
    assert advice.get('profit_tiers') is None


# ══ P2-f 大级别否决 ═══════════════════════════════════════════════════

def test_weekly_direction_from_tags_json():
    tags = {'multi_level': json.dumps({'direction_map': {'weekly': 'down', 'daily': 'up'}})}
    assert _weekly_direction(tags) == 'down'


def test_weekly_direction_from_dimensions():
    dims = {'chanlun': {'multi_level': {'direction_map': {'weekly': 'up'}}}}
    assert _weekly_direction(None, dims) == 'up'


def test_weekly_direction_unknown_returns_empty():
    assert _weekly_direction({'multi_level': json.dumps({'direction_map': {'weekly': 'unknown'}})}) == ''
    assert _weekly_direction(None, None) == ''


def _dims_bull():
    return {
        'chanlun': {'direction': '上升', 'buy_point': '第一类买点'},
        'volume_price': {'direction': 'up'}, 'chip': {'direction': 'bullish'},
        'emotion': {'direction': 'bullish'},
        'factor': {'trend': 'bullish'},
    }


def test_weekly_down_degrades_to_wait():
    """日线看多 + 周线向下 → 降 wait（丢弃买点，不判空）"""
    from app.opportunity_atlas.advice_engine import build_operation_advice
    tags = {'multi_level': json.dumps({'direction_map': {'weekly': 'down', 'daily': 'up'}}),
            'opportunity_state': 'enter'}
    a = build_operation_advice('T.SZ', _dims_bull(), [], _mk_df(), tags=tags)
    assert a['state'] == 'wait', f"周线向下应降 wait，实际 {a['state']}"
    assert '大级别' in a['state_reason']


def test_weekly_up_keeps_state():
    """日线看多 + 周线向上 → 不否决"""
    from app.opportunity_atlas.advice_engine import build_operation_advice
    tags = {'multi_level': json.dumps({'direction_map': {'weekly': 'up', 'daily': 'up'}}),
            'opportunity_state': 'enter'}
    a = build_operation_advice('T.SZ', _dims_bull(), [], _mk_df(), tags=tags)
    assert a['state'] in ('enter', 'light')


def test_weekly_down_only_when_daily_bull():
    """日线非看多（无买点）→ 不触发大级别否决（避免对纯空头重复判）"""
    from app.opportunity_atlas.advice_engine import build_operation_advice
    tags = {'multi_level': json.dumps({'direction_map': {'weekly': 'down', 'daily': 'down'}}),
            'opportunity_state': 'enter'}
    a = build_operation_advice('T.SZ', {'factor': {'trend': 'down'}}, [], _mk_df(), tags=tags)
    assert '大级别' not in (a.get('state_reason') or '')


def test_constants_present():
    assert ae.ATR_MULT == 2.0
    assert ae.TARGET_TIERS == [(0.5, 2.0), (0.3, 3.0), (0.2, None)]
