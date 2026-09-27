"""493号 批次1（P2-b）盈亏比门禁阈值对齐回归

知识库《R-R筛选规则》：「风险回报比（R:R）< 2:1 的交易直接放弃」。
原实现门禁为 1.0（且注释自身引用「盈亏比≥2」却写成 <1.0），
493 号对齐为 2.0（与 dim6 稽核门槛 rr_value≥2.0 一致）；用户拍板：
<2.0 且当前 enter/light → 降 wait（观望）；应用范围仅 enter/light。
"""
import inspect
import os
import pathlib
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.advice_engine import RR_GATE  # noqa: E402
from app.opportunity_atlas.status_engine import apply_advice_params  # noqa: E402

_DF = pd.DataFrame({'open': [10.0] * 30, 'high': [11.0] * 30,
                    'low': [9.0] * 30, 'close': [10.0] * 30, 'vol': [1000] * 30})


# ── 阈值常量 / 签名 ─────────────────────────────────────────────────

def test_rr_gate_constant_is_2():
    assert RR_GATE == 2.0


def test_apply_advice_params_default_gate_is_2():
    assert inspect.signature(apply_advice_params).parameters['rr_gate'].default == 2.0


# ── apply_advice_params 门禁行为（patch _geometric 确定性控制 rr）──

def _params(pos=0.4):
    return {'max_position_ratio': pos, 'hard_veto': False, 'hold_only': False}


def test_gate_blocks_rr_1_5(monkeypatch):
    """rr=1.5（原实现放行）→ 新实现拦截为 wait 且仓位减半"""
    monkeypatch.setattr('app.opportunity_atlas.advice_builder._geometric',
                        lambda df: {'support_price': 9.0, 'resistance_price': 11.5})
    out = apply_advice_params(_params(), 10.0, _DF)  # rr = (11.5-10)/(10-9) = 1.5
    assert out['state'] == 'wait'
    assert out['max_position_ratio'] == round(0.4 * 0.5, 2)
    assert '盈亏比不足' in out['reason']


def test_gate_allows_rr_2_5(monkeypatch):
    """rr=2.5 → 放行 enter、仓位不减"""
    monkeypatch.setattr('app.opportunity_atlas.advice_builder._geometric',
                        lambda df: {'support_price': 9.0, 'resistance_price': 12.5})
    out = apply_advice_params(_params(), 10.0, _DF)  # rr = 2.5
    assert out['state'] == 'enter'
    assert out['max_position_ratio'] == 0.4


def test_gate_exact_2_passes(monkeypatch):
    """rr 恰为 2.0 → 不触发（<2 才拦）"""
    monkeypatch.setattr('app.opportunity_atlas.advice_builder._geometric',
                        lambda df: {'support_price': 9.0, 'resistance_price': 12.0})
    out = apply_advice_params(_params(), 10.0, _DF)  # rr = 2.0
    assert out['state'] == 'enter'


def test_veto_and_hold_take_priority(monkeypatch):
    """hard_veto→avoid、hold_only→wait 优先于门禁"""
    monkeypatch.setattr('app.opportunity_atlas.advice_builder._geometric',
                        lambda df: {'support_price': 9.0, 'resistance_price': 12.5})
    assert apply_advice_params({'max_position_ratio': 0.4, 'hard_veto': True},
                               10.0, _DF)['state'] == 'avoid'
    out = apply_advice_params({'max_position_ratio': 0.4, 'hold_only': True}, 10.0, _DF)
    assert out['state'] == 'wait' and 'L0c' in out['reason']


# ── 生效路径门禁条件（源码级断言，避免依赖右侧确认链）──────────────

def test_advice_engine_gate_condition_and_scope():
    """生效副本 advice_engine：门禁用 RR_GATE 且仅 enter/light"""
    base = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'opportunity_atlas'
    ae = (base / 'advice_engine.py').read_text(encoding='utf-8')
    assert "_rr < RR_GATE and state in ('enter', 'light')" in ae
    assert "state = 'wait'" in ae


# ── 源码断言：不再有 1.0 阈值 ───────────────────────────────────────

def test_gate_source_not_hardcoded_1():
    base = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'opportunity_atlas'
    ae = (base / 'advice_engine.py').read_text(encoding='utf-8')
    ab = (base / 'advice_builder.py').read_text(encoding='utf-8')
    se = (base / 'status_engine.py').read_text(encoding='utf-8')
    assert '_rr < 1.0' not in ae and '_rr < 1.0' not in ab
    assert 'rr_gate: float = 1.0' not in se
    assert 'RR_GATE = 2.0' in ae
