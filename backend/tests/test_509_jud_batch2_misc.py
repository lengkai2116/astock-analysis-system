"""509号批次2 探针（#J9/#J10/#J11/#J12/#J13/#J15/#J17）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.4。

  #J9  `status_engine._aggregate`：`elif bull == bear and bull > 0` 不可达（前序
       total_w>0 恒先命中）+ 平票恒判 'bearish' → 合并分支、平票判 neutral；
  #J10 `status_engine._apply_l0` L0a：`int(e.get('direction'))` 无守卫，非数值
       中断整个 L0 → try 守卫按 0 处理；
  #J11 `_apply_l0` 回退读 get_pre_feat/get_cached_daily_basic 透传 asof_date
       （回测消除前视）；
  #J12 `_assemble` json.loads(advice_params) 守卫（非 JSON 重建空 dict 不中断）；
  #J13 `consensus_engine.merge_family` 全中性族 → 'neutral'（原 tie-break 误标 bull）；
  #J15 `_family_regime_weight` weights=None → 1.0（原 0.1 使 bull/bear_score 缩放，
       docstring 承诺「退化纯 STATE_WEIGHTS」不符）；
  #J17 `factor_arbiter` fatal_to_veto 强制降级 wait 用 45.0（原 0.0=avoid 档矛盾）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from app.opportunity_atlas import status_engine as se_mod  # noqa: E402
from app.opportunity_atlas.consensus_engine import _family_regime_weight, merge_family  # noqa: E402
from app.opportunity_atlas.factor_arbiter import arbitrate  # noqa: E402

# ── #J9：平票判 neutral ────────────────────────────────────

def test_j9_tie_break_neutral():
    """bull==bear>0 → direction='neutral'（原恒 'bearish'）"""
    se = se_mod.StatusEngine.__new__(se_mod.StatusEngine)
    se.cfg = {'jud_engine_version': 'legacy'}
    se.dm = type('_DM', (), {'get_cached_daily_basic': lambda *a, **k: None,
                             'cache': type('_C', (), {'get_pre_feat': lambda *a, **k: None})()})()
    l0 = se._apply_l0('000001.SZ', {}, {})
    # 全维 direction=0 → bull==bear==0 → total_w=0 → neutral
    r = se._aggregate({'state_label': '盘整'}, {}, l0, {})
    assert r['direction'] == 'neutral'


# ── #J10：L0a int 守卫 ─────────────────────────────────────

def test_j10_l0a_non_numeric_direction_guard():
    """event_details direction='st'（非数值）不再中断 _apply_l0"""
    se = se_mod.StatusEngine.__new__(se_mod.StatusEngine)
    se.cfg = {}
    se.dm = type('_DM', (), {'get_cached_daily_basic': lambda *a, **k: None,
                             'cache': type('_C', (), {'get_pre_feat': lambda *a, **k: None})()})()
    l0 = se._apply_l0(
        '000001.SZ',
        {'event_details': [{'event_type': 'st_warning', 'direction': 'st'}]},
        {})
    assert l0['hard_veto'] is False, '非数值 direction 不触发 ST 硬否决'
    assert 'soft_risks' in l0, 'L0 结构完整（未中断）'


# ── #J11：asof_date 透传 ───────────────────────────────────

def test_j11_apply_l0_asof_date_signature():
    """_apply_l0 新增 asof_date 形参，内部回退读带日期"""
    import inspect
    sig = inspect.signature(se_mod.StatusEngine._apply_l0)
    assert 'asof_date' in sig.parameters


# ── #J12：advice_params json 守卫 ──────────────────────────

def test_j12_advice_params_json_guard_source():
    """_assemble 中 advice_params 解析带 try 守卫"""
    import inspect
    src = inspect.getsource(se_mod.StatusEngine._assemble)
    assert 'json.loads(result[\'advice_params\'])' in src
    assert 'except (TypeError, ValueError)' in src
    assert '已重建' in src


# ── #J13：全中性族判 neutral ───────────────────────────────

def test_j13_all_neutral_family_neutral():
    """全中性族（无 bull/bear 票）→ 'neutral'（原误标 bull）"""
    r = merge_family(
        dim_scores={'emotion': 0, 'event': 0, 'factor': 0},
        dim_reliabilities={'emotion': 1.0, 'event': 1.0, 'factor': 1.0},
        family_dims=['emotion', 'event', 'factor'],
        dim_strengths={'emotion': 0.0, 'event': 0.0, 'factor': 0.0})
    assert r[0] == 'neutral', f'全中性族应 neutral，实 {r[0]}'
    assert r[1] == 0.0


def test_j13_bull_bear_tie_strength():
    """等票 tie-break 按加权强度（bull_strength>=bear_strength → bull）"""
    r = merge_family(
        dim_scores={'a': 1, 'b': -1},
        dim_reliabilities={'a': 1.0, 'b': 1.0},
        family_dims=['a', 'b'],
        dim_strengths={'a': 0.8, 'b': 0.6})
    assert r[0] == 'bull'


# ── #J15：weights=None 纯 STATE_WEIGHTS ────────────────────

def test_j15_regime_weight_missing_is_one():
    """weights=None/空 → 族权重 1.0（不再 ×0.1 缩放）"""
    assert _family_regime_weight(None, 'main_behavior') == 1.0
    assert _family_regime_weight({}, 'risk') == 1.0


def test_j15_regime_weight_present_unchanged():
    """weights 有值时族权重=族内均值（不回归）"""
    w = {'chip_fund': 0.3, 'signal': 0.2, 'structure': 0.4}
    assert _family_regime_weight(w, 'main_behavior') == pytest.approx(0.3)
    assert _family_regime_weight(w, 'structure_trend') == pytest.approx(0.3)


# ── #J17：fatal_to_veto 强制降级 wait=45.0 ─────────────────

def test_j17_fatal_veto_wait_score_45():
    """fatal_to_veto 强制降级 wait → final_score=45.0（wait 档下界，原 0.0 矛盾）"""
    r = arbitrate(consensus={'consensus_rate': 0.8},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': ['X']},
                  tags={}, dims_factor={}, reliability={})
    assert r['opportunity_state'] == 'wait'
    assert r['final_score'] == 45.0
