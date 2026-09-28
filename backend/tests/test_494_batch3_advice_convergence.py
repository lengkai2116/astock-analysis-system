"""494号 批次3 回归（R-3 止损/止盈口径收敛 + R-4 advice_params 白名单）

知识库依据：《结构止损》「结构止损与 ATR 止损同时可用时取较高」/《ATR止损》/
《分批止盈法》50@2R / 30@3R / 20%@移动止盈。

494号三处要点（详见方案 §四 批次3）：
- **R-3a 唯一实现**：止损/止盈实现收敛为 SSOT `dim_adapter.calc_stop_and_tiers`，
  `advice_engine` 与 `advice_builder` 共用（此前两份逐字副本）。
- **R-3b 统一取数**：优先 `dim_results.risk.status_description`（dim6：support/atr/rr），
  回退几何 `geo.support_price`/`geo.risk_reward`（461-11 已同源同值，实测 400/400 一致）。
- **R-3c 产出面补齐**：`advice_engine` 图谱路径 result 补 `stop_loss_price`/`stop_loss_basis`/
  `profit_tiers`（此前仅内部有、未进 result）；`exit_rules` 与「取较高止损」同源。
- **R-4**：`status_engine._assemble` advice_params 白名单补 `profit_tiers`/`stop_loss_basis`。
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.advice_builder import (  # noqa: E402
    _stop_and_tiers,
)
from app.opportunity_atlas.advice_builder import (
    build_operation_advice as bld_build,
)
from app.opportunity_atlas.advice_engine import (  # noqa: E402
    _apply_stop_and_tiers,
)
from app.opportunity_atlas.advice_engine import (
    build_operation_advice as eng_build,
)
from app.opportunity_atlas.dim_adapter import (  # noqa: E402
    ATR_MULT,
    RR_GATE,
    TARGET_TIERS,
    calc_stop_and_tiers,
)


def _df(n=70, close=30.0, high=38.0, low=20.0):
    return pd.DataFrame({
        'date': pd.date_range('2026-05-01', periods=n, freq='D'),
        'open': close * 0.83, 'close': close, 'high': high, 'low': low, 'volume': 1e6})


def _dims(trend='bullish'):
    return {'chanlun': {'direction': '上升', 'buy_point': '第三类买点'},
            'volume_price': {'direction': 'up'},
            'chip': {'direction': 'bullish'},
            'emotion': {'rotation_state': '复苏期'},
            'factor': {'trend': trend}}


def _risk(support=9.0, atr=2.0, rr=2.5):
    return {'risk': {'status_description': {
        'support_price': support, 'atr_pct': atr, 'rr_value': rr,
        'resistance_price': 38.0}}}


# ── 1. SSOT calc_stop_and_tiers 边界 ────────────────────────────────

def test_ssot_constants():
    assert ATR_MULT == 2.0 and RR_GATE == 2.0
    assert TARGET_TIERS == [(0.5, 2.0), (0.3, 3.0), (0.2, None)]


def test_ssot_takes_higher_of_struct_and_atr():
    """结构 9.0 vs ATR(2%) 9.6 → 取较高 9.6"""
    stop, basis, _ = calc_stop_and_tiers(10.0, {'support_price': 9.0, 'atr_pct': 2.0})
    assert stop == 9.6
    assert basis == '结构止损与ATR止损取较高'


def test_ssot_atr_only_when_no_struct():
    stop, basis, _ = calc_stop_and_tiers(10.0, {'atr_pct': 5.0})
    assert stop == 9.0 and basis == 'ATR止损'


def test_ssot_struct_above_entry_ignored():
    stop, basis, _ = calc_stop_and_tiers(10.0, {'support_price': 10.5, 'atr_pct': 2.0})
    assert stop == 9.6 and basis == 'ATR止损'


def test_ssot_geo_fallback_when_no_dim6():
    """无 dim6 → 回退几何 support_price/risk_reward"""
    stop, basis, tiers = calc_stop_and_tiers(10.0, None, {'support_price': 9.0, 'risk_reward': 2.5})
    assert stop == 9.0 and basis == '结构止损'
    assert tiers and len(tiers) == 3


def test_ssot_tiers_gated_by_rr():
    """R:R<2 → 不给分批止盈；≥2 → 给"""
    _, _, no_tiers = calc_stop_and_tiers(10.0, {'support_price': 9.0, 'rr_value': 1.5})
    assert no_tiers is None
    _, _, tiers = calc_stop_and_tiers(10.0, {'support_price': 9.0, 'rr_value': 2.0})
    assert tiers and [t['weight'] for t in tiers] == [0.5, 0.3, 0.2]


def test_ssot_zero_entry_returns_none():
    assert calc_stop_and_tiers(0, {'support_price': 9.0}) == (None, None, None)


# ── 2. 两份建议卡共用同一实现（R-3a） ───────────────────────────────

def test_both_builders_delegate_to_ssot():
    """advice_engine/_apply_stop_and_tiers 与 advice_builder/_stop_and_tiers 同结果"""
    adv = {}
    _apply_stop_and_tiers(adv, 10.0, {'support_price': 9.0, 'atr_pct': 2.0, 'rr_value': 2.5}, {})
    b_stop, b_tiers = _stop_and_tiers(10.0, 9.0, 2.5, 2.0)
    assert adv['stop_loss_price'] == b_stop == 9.6
    assert adv['stop_loss_basis'] == '结构止损与ATR止损取较高'
    assert [t['weight'] for t in adv['profit_tiers']] == [t['weight'] for t in b_tiers]


# ── 3. 产出面：两 builder result 三键（R-3c） ───────────────────────

def test_engine_result_has_three_keys_with_dim6():
    """图谱路径（dim_results 传入）→ stop_loss_price/basis/profit_tiers 非空 + exit_rules 同源

    entry=close=30.0；结构 9.0 vs ATR(2%)=30-2×30×0.02=28.8 → 取较高 28.8。
    """
    r = eng_build('T.SZ', _dims(), [], _df(), tags={'opportunity_state': 'enter'},
                  dim_results=_risk(9.0, 2.0, 2.5))
    assert r['stop_loss_price'] == 28.8
    assert r['stop_loss_basis'] == '结构止损与ATR止损取较高'
    assert r['profit_tiers']
    assert r['executable']['exit_rules'][0]['trigger'] == 'close < 28.8'


def test_builder_result_has_three_keys_with_dim6():
    """个股页路径（dim_results 传入）→ 三键非空 + exit_rules 同源"""
    r = bld_build('T.SZ', _dims(), [], _df(), tags={'opportunity_state': 'enter'},
                  dim_results=_risk(9.0, 2.0, 2.5))
    assert r['stop_loss_price'] == 28.8
    assert r['stop_loss_basis'] == '结构止损与ATR止损取较高'
    assert r['profit_tiers']
    assert r['executable']['exit_rules'][0]['trigger'] == 'close < 28.8'


def test_engine_without_dim_results_degrades_to_geo():
    """无 dim_results（旧调用）→ 回退几何（结构止损），不崩"""
    r = eng_build('T.SZ', _dims(), [], _df(), tags={'opportunity_state': 'enter'})
    assert r['stop_loss_price'] == 25.5      # 几何 support（与 _geometric 同源）
    assert r['stop_loss_basis'] == '结构止损'


def test_engine_dim6_atr_widens_stop_consistency():
    """R-3 关键：图谱路径原 ATR=0（无 dim6）→ 现读 dim6 atr_pct，止损取较高

    entry=30；结构 9.0 vs ATR(5%)=30-2×30×0.05=27.0 → 取较高 27.0（无 dim6 时仅 9.0）。
    """
    r = eng_build('T.SZ', _dims(), [], _df(), tags={'opportunity_state': 'enter'},
                  dim_results=_risk(support=9.0, atr=5.0, rr=2.5))
    assert r['stop_loss_price'] == 27.0


# ── 4. R-4：advice_params 白名单 ────────────────────────────────────

def test_advice_params_whitelist_includes_new_keys():
    """_assemble 白名单含 profit_tiers/stop_loss_basis（源码级断言，防回退）"""
    import inspect

    from app.opportunity_atlas.status_engine import StatusEngine
    src = inspect.getsource(StatusEngine._assemble)
    assert "'profit_tiers'" in src
    assert "'stop_loss_basis'" in src


def test_advice_params_whitelist_behavior():
    """模拟 L6 advice → 白名单过滤后两键保留、他键丢弃"""
    _advice = {'profit_tiers': [{'weight': 0.5}], 'stop_loss_basis': 'ATR止损',
               'atr_pct': 2.0, 'temperature': '中性50'}
    _wl = ('max_position_ratio', 'stop_loss_price', 'target_price',
           'risk_reward_ratio', 'invalidation_conditions',
           'entry_zone', 'target_zone', 'risk_budget_position',
           'profit_tiers', 'stop_loss_basis')
    kept = {k: v for k, v in _advice.items() if k in _wl}
    assert 'profit_tiers' in kept and 'stop_loss_basis' in kept
    assert 'atr_pct' not in kept and 'temperature' not in kept


# ── 5. 调用方接线（源码级，防回退） ─────────────────────────────────

def test_callers_pass_dim_results():
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent
    cv = (base / 'app' / 'opportunity_atlas' / 'cross_validate.py').read_text(encoding='utf-8')
    sa = (base / 'app' / 'routes' / 'strategy_analyze.py').read_text(encoding='utf-8')
    assert '_load_dim_engine_results(_dm, ts_code)' in cv
    assert 'dim_results=_dim_engine_for_advice' in sa
