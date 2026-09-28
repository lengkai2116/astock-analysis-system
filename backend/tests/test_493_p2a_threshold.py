"""493号 批次2（P2-a）操作归一化档位对齐回归

知识库《操作归一化》5 档映射：
  80-100 重仓买入（60-80%）/ 65-79 买入建仓（30-60%）/ 45-64 持有观望（维持）/
  30-44 减仓（降至30%以下）/ 0-29 清仓回避（0%）。

用户拍板（2026-09-28）：
  ① 采用 Wiki 5 档，新增 reduce（减仓）档；
  ② reduce 语义=建议持有者减仓至 30% 以下、新开仓 0；
  ③ 单票 base 仓位保持 0.6/0.4/0.1（Wiki 60-80% 属账户级总仓位口径，
     单票已受《风险预算驱动仓位》「≤总资金30%」硬约束，不搬入单票字段）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.advice_engine import compute_advice  # noqa: E402
from app.opportunity_atlas.factor_arbiter import (  # noqa: E402
    STATE_REDUCE,
    _map_score_to_state,
)

_L0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
       'hard_veto': False, 'emotion_position_cap': None}


# ── 档位边界（factor_arbiter._map_score_to_state）────────────────────

def test_threshold_enter_80():
    assert _map_score_to_state(80.0) == 'enter'
    assert _map_score_to_state(79.9) == 'light'


def test_threshold_light_65():
    assert _map_score_to_state(65.0) == 'light'
    assert _map_score_to_state(64.9) == 'wait'


def test_threshold_wait_45():
    assert _map_score_to_state(45.0) == 'wait'
    assert _map_score_to_state(44.9) == 'reduce'


def test_threshold_reduce_30():
    assert _map_score_to_state(30.0) == STATE_REDUCE == 'reduce'
    assert _map_score_to_state(29.9) == 'avoid'
    assert _map_score_to_state(0.0) == 'avoid'


# ── reduce 档语义（新开仓 0）────────────────────────────────────────

def _advice(score):
    return compute_advice(final_score=score, dims_factor={}, l0=dict(_L0),
                          dim_results={}, ts_code='000001.SZ')


def test_reduce_new_position_zero():
    """reduce（30-44）→ 新开仓 0（不可入场）"""
    assert _advice(30.0)['max_position_ratio'] == 0.0
    assert _advice(44.9)['max_position_ratio'] == 0.0


def test_wait_keeps_build_position():
    """wait（45-64）→ 维持 0.1 建仓级别（未受本批影响）"""
    # base=0.1, rr 缺省 1.0 → ×0.5 = 0.05
    assert _advice(45.0)['max_position_ratio'] == 0.05
    assert _advice(60.0)['max_position_ratio'] == 0.05


def test_light_base_unchanged():
    """light（65-79）→ base 0.4（rr=1.0 → ×0.5 = 0.2）"""
    assert _advice(70.0)['max_position_ratio'] == 0.2


def test_enter_base_unchanged():
    """enter（80-100）→ base 0.6（rr=1.0 → ×0.5 = 0.3）"""
    assert _advice(80.0)['max_position_ratio'] == 0.3


# ── action_label / signal_light 新增 reduce 映射 ────────────────────

def test_action_label_reduce():
    from app.opportunity_atlas.advice_engine import _map_action_label
    assert _map_action_label('reduce', 0.0) == '减仓'


def test_state_cn_reduce():
    from app.opportunity_atlas.advice_engine import _STATE_CN
    assert _STATE_CN['reduce'] == '建议减仓'
