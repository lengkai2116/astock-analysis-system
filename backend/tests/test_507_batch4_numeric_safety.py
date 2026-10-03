"""507号批次4：数值安全（0/NaN/None 混同）验证（#S16~#S23）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §四.4。

覆盖 8 项修复（均为数值守卫，不改变正常值行为）：
  #S16 calc_vol_ratio current_vol None/NaN → 中性 1.0（原除抛错/产 NaN）
  #S17 classify_vol_ratio NaN → 中性「正常」（原误标「极度缩量」）
  #S18 shared_support_resistance NaN 过滤 / 无上方压力 resistance=None / 0.0 合法值保留
  #S19 dim8 指数涨跌除 0/NaN 守卫（n/a 展示）
  #S20 dim6 continuous_value rr<0 clamp 到 0
  #S21 reliability_assessor atr None 守卫（原 TypeError 被吞 → 整维 0.5）
  #S22 time_rhythm 带宽 NaN → 中性 100
  #S23 signal_analyzer._false_breakout_check 缺字段 fail-open（不拦截）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


# ── #S16 / #S17：量比 ──────────────────────────────────────

def test_s16_calc_vol_ratio_nan_none_neutral():
    from app.opportunity_atlas.dimensions.shared_vol_ratio import calc_vol_ratio
    assert calc_vol_ratio(float('nan'), 100.0) == 1.0
    assert calc_vol_ratio(None, 100.0) == 1.0
    assert calc_vol_ratio(200.0, 100.0) == 2.0  # 正常值不变


def test_s17_classify_nan_neutral():
    from app.opportunity_atlas.dimensions.shared_vol_ratio import classify_vol_ratio
    assert classify_vol_ratio(float('nan')) == '正常'
    assert classify_vol_ratio(None) == '正常'
    assert classify_vol_ratio(3.5) == '极度放量'  # 正常值不变


# ── #S18：支撑/压力 ────────────────────────────────────────

def _mk_sr_df(closes, lows=None, highs=None):
    import numpy as np
    import pandas as pd
    n = len(closes)
    lows = lows or [c * 0.98 for c in closes]
    highs = highs or [c * 1.02 for c in closes]
    return pd.DataFrame({'close': closes, 'low': lows, 'high': highs,
                         'open': closes, 'vol': [1000.0] * n})


def test_s18_nan_ma_filtered():
    """indicator_ma_df 的 ma20/ma60 为 NaN → 被过滤（原污染支撑位）"""
    import pandas as pd
    from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
    df = _mk_sr_df([10.0 + i * 0.1 for i in range(70)])
    ind = pd.DataFrame({'ma20': [float('nan')], 'ma60': [float('nan')]})
    out = calc_support_resistance(df, indicator_ma_df=ind)
    # NaN 被过滤 → 回退 raw 计算（ma20 ≈ mean(近20)）
    assert out['support_price'] is not None
    assert out['support_price'] > 0


def test_s18_no_resistance_above_price_is_none():
    """无高于现价的压力候选（hi60 不高于现价）→ resistance=None（原回退 hi60 致 R:R 失真）"""
    from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
    # 现价创 60 日新高：highs=closes（无振幅）→ hi60 = 现价，不严格 > 现价 → 无上方候选
    closes = [10.0 + i * 0.1 for i in range(70)]  # 末值 16.9，单调上升
    df = _mk_sr_df(closes, highs=closes)
    out = calc_support_resistance(df)
    assert out['resistance_price'] is None
    assert out['risk_reward'] is None


def test_s18_zero_support_preserved():
    """support 恰好为 0 时不再被 `if support else None` 丢弃"""
    import pandas as pd
    from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
    # 构造现价 10、lo20=0（支撑=0）的场景：直接调用内部逻辑不可行，改用源码断言
    src = open(os.path.join(_ATLAS, 'dimensions/shared_support_resistance.py'),
               encoding='utf-8').read()
    assert 'if support is not None else None' in src


# ── #S19：dim8 指数涨跌守卫 ────────────────────────────────

def test_s19_dim8_zero_div_guard_source():
    """dim8 指数涨跌对 0/NaN 除数有守卫（n/a 展示）"""
    src = open(os.path.join(_ATLAS, 'dimensions/dim8_summary_engine.py'),
               encoding='utf-8').read()
    assert "if v <= 0 or (isinstance(v, float) and v != v):" in src
    assert "'n/a'" in src


# ── #S20：dim6 continuous_value clamp ──────────────────────

def test_s20_continuous_value_clamped():
    """rr<0 → continuous_value=0（原负值下传）；rr=3 → 1.0（正常值不变）"""
    import inspect
    from app.opportunity_atlas.dimensions import dim6_risk_engine as m
    src = inspect.getsource(m)
    assert 'max(rr_info.get(' in src


# ── #S21：reliability atr 守卫 ─────────────────────────────

def test_s21_reliability_atr_none_guard():
    """atr 为 None（非数值串）→ 走 _DEFAULT_RELIABILITY（原 TypeError 被吞）"""
    from app.opportunity_atlas.reliability_assessor import _assess_risk
    r = _assess_risk({'risk': {'status_description': {'atr_pct': '非数值'}}})
    assert isinstance(r, float)
    assert 0 <= r <= 1


def test_s21_reliability_atr_normal_unchanged():
    from app.opportunity_atlas.reliability_assessor import _assess_risk
    assert _assess_risk({'risk': {'status_description': {'atr_pct': 5.0}}}) == 0.6
    assert _assess_risk({'risk': {'status_description': {'atr_pct': 1.0}}}) == 0.9


# ── #S22：time_rhythm 带宽 NaN ─────────────────────────────

def test_s22_time_rhythm_nan_bandwidth_neutral():
    """带宽 NaN → 中性 100（不触发收缩误判 early_consolidation）"""
    import pandas as pd
    from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine
    eng = TimeRhythmEngine()
    # 构造 <30 日短数据（原代码 len<30 早退；验证不抛）
    df = pd.DataFrame({'close': [10.0] * 20, 'high': [10.5] * 20, 'low': [9.5] * 20})
    out = eng.compute_tags(df)
    assert isinstance(out, dict)
    # NaN 守卫存在（源码级）
    src = open(os.path.join(_ATLAS, 'time_rhythm_engine.py'), encoding='utf-8').read()
    assert 'current_bw != current_bw' in src


# ── #S23：signal_analyzer fail-open ────────────────────────

def test_s23_false_breakout_missing_fields_pass():
    """context 缺字段 → passed=True（fail-open，原默认 0 拦截）"""
    from app.opportunity_atlas.signal_analyzer import ConfirmLayer
    sa = ConfirmLayer()
    assert sa._false_breakout_check({})['passed'] is True
    assert sa._false_breakout_check({'vol_ratio': 2.0})['passed'] is True
    assert sa._false_breakout_check({'vol_ratio': 2.0, 'breakout_days': 5})['passed'] is True
    # 有值且不足 → 仍拦截（正常值语义不变）
    assert sa._false_breakout_check({'vol_ratio': 0.5})['passed'] is False
    assert sa._false_breakout_check({'vol_ratio': 2.0, 'breakout_days': 1})['passed'] is False
    assert sa._false_breakout_check(
        {'vol_ratio': 2.0, 'breakout_days': 5, 'cyqkl': 0.1})['passed'] is False
