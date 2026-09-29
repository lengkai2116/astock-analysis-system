"""497号 批次4（P5）：status_snapshot.status_bar 单源化（v390 派生 8 态）

497号要点（详见方案 §九 批次4，候选A）：
- 快照 `status_bar` 原由 legacy `_status_bar`（dims 灯色计数）派生 5-7 态中文
  （不可交易/风险区/持有观望/强趋势/趋势确认/趋势转弱/趋势不明），与 v390 判定无因果
  （492 P2「②③ 无因果」在快照列的残留）；而 dim8 展示层已是 v390 派生 8 态。
- 候选A：快照 status_bar 改由判定层派生（`_derive_status_bar_v390` + `STATUS_BAR_STATES`
  中文映射），与 dim8 同源；legacy 路径/派生失败 → 回退 legacy `_status_bar`。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dimensions.dim8_summary_engine import (  # noqa: E402
    STATUS_BAR_STATES,
    _derive_status_bar_v390,
)
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

_SRC = (Path(__file__).resolve().parent.parent / 'app' / 'opportunity_atlas'
        / 'status_engine.py').read_text(encoding='utf-8')


def _engine():
    return StatusEngine.__new__(StatusEngine)


def _l0():
    return {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [], 'hard_veto': False}


def test_assemble_uses_single_source_helper():
    """源码级：_assemble 的 status_bar 改走单源化辅助函数"""
    assert "'status_bar': self._status_bar_v390_or_legacy(l2, dims, l0)," in _SRC
    assert "def _status_bar_v390_or_legacy" in _SRC


def test_v390_state_to_cn_all_five_states():
    """v390 五态 → 中文（与 dim8 STATUS_BAR_STATES 同源）"""
    e = _engine()
    for st, cn in (('enter', '强势确认'), ('light', '轻仓确认'), ('wait', '中性观望'),
                   ('reduce', '谨慎观望'), ('avoid', '风险警示')):
        l2 = {'opportunity_state': st, 'direction': 'bull', 'final_score': 70.0}
        assert e._status_bar_v390_or_legacy(l2, {}, _l0()) == cn, st


def test_v390_bear_non_hard_state_goes_bearish():
    """direction=bear 且非 avoid/reduce → 看空回避（与 dim8 派生一致）"""
    e = _engine()
    for st in ('wait', 'light', 'enter'):
        l2 = {'opportunity_state': st, 'direction': 'bear', 'final_score': 40.0}
        assert e._status_bar_v390_or_legacy(l2, {}, _l0()) == '看空回避', st
    # avoid/reduce 不受方向覆盖（仍按状态映射）
    assert e._status_bar_v390_or_legacy(
        {'opportunity_state': 'avoid', 'direction': 'bear', 'final_score': 20.0},
        {}, _l0()) == '风险警示'
    assert e._status_bar_v390_or_legacy(
        {'opportunity_state': 'reduce', 'direction': 'bear', 'final_score': 35.0},
        {}, _l0()) == '谨慎观望'


def test_v390_value_matches_dim8_derivation():
    """单源一致性：快照值与 dim8 派生（经中文映射）逐态相等"""
    e = _engine()
    for st in ('enter', 'light', 'wait', 'reduce', 'avoid'):
        for d in ('bull', 'bear'):
            l2 = {'opportunity_state': st, 'direction': d, 'final_score': 50.0}
            snap = e._status_bar_v390_or_legacy(l2, {}, _l0())
            dim8_cn = STATUS_BAR_STATES.get(_derive_status_bar_v390(l2), '')
            assert snap == dim8_cn, (st, d, snap, dim8_cn)


def test_legacy_path_falls_back_to_legacy_status_bar():
    """legacy（无 final_score 键）→ 回退 legacy _status_bar（保持既有 5-7 态）"""
    e = _engine()
    dims = {f'd{i}': {'light': 'green'} for i in range(7)}  # green>=6 → 强趋势
    # legacy l2 无 final_score
    l2 = {'opportunity_state': 'enter', 'direction': 'bullish'}
    assert e._status_bar_v390_or_legacy(l2, dims, _l0()) == '强趋势'
    # avoid 优先不可交易（legacy 语义保留）
    l2b = {'opportunity_state': 'avoid', 'direction': 'bearish'}
    assert e._status_bar_v390_or_legacy(l2b, {}, _l0()) == '不可交易'


def test_assemble_end_to_end_v390_status_bar():
    """端到端：v390 l2 → _assemble 产出中文派生状态条"""
    e = _engine()
    l2 = {'opportunity_state': 'enter', 'state_evidence': [], 'consensus_rate': 0.8,
          'direction': 'bull', 'bullish_dims': 5.0, 'bearish_dims': 1.0,
          'conflict_evidence': [], 'final_score': 82.0, 'semantic_type': '确认型',
          'reliability_summary': {}, 'consensus_detail': {}, 'advice': {}}
    r = e._assemble('000001.SZ', {}, None, _l0(), l2, [], None)
    assert r['status_bar'] == '强势确认'
    assert json.loads(r['dim_states'] or '{}') == {}
