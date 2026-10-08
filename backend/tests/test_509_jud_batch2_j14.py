"""509号批次2 #J14 探针：中性闸门钝化修复验证（方案 B，用户拍板）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.4。

#J14 定性（探针实证）：OCR 原判「total_dim_count 在 None 检查前自增 → 分母含缺失维
    弱化闸门」与数据流不符——convert_to_factors 恒返回 13 键（辅助维恒有产出），
    `score is None` 永不触发；真正的缺陷是 6 个辅助维（time/position/signal_confirm/
    finance/event/factor）多数 direction=0（中性），计入 neutral_ratio 分母把中性占比
    系统性抬高 → 「>0.6 cap 到 0.5」闸门过度触发、共识幅值被压扁。
    量化实证：全市场 5554 只最新交易日，neutral_ratio>0.6 触发 786→236（排除辅助维后），
    约 550 只 consensus_rate 被额外压到 ±0.5（判断力钝化）。

方案 B（拍板）：neutral_ratio 只统计 7 个主判定维（signal/structure/vp/chip_fund/
    emotion/risk/valuation），辅助维仍参与族方向归并（merge_family），仅不计入中性占比。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from app.opportunity_atlas.consensus_engine import _AUX_DIMS, GROUP_MAPPING, compute  # noqa: E402


def _mk_dim(direction):
    """构造 dims_factor 维度条目（dict 形态，507 #S4 后契约）"""
    return {'direction': direction, 'strength': abs(direction) if direction else 0.5}


def _dims(main=None, aux=None):
    """7 主维 + 6 辅助维 全量 dims_factor"""
    d = {k: _mk_dim(0) for k in
         ('signal', 'structure', 'vp', 'chip_fund', 'emotion', 'risk', 'valuation')}
    d.update({k: _mk_dim(0) for k in _AUX_DIMS})
    if main:
        d.update({k: _mk_dim(v) for k, v in main.items()})
    if aux:
        d.update({k: _mk_dim(v) for k, v in aux.items()})
    return d


def _rel():
    """可靠性全量（7 主维 + 6 辅助维；真实 assess 对全部 GROUP_MAPPING 维产出）"""
    return {k: 1.0 for k in
            ('signal', 'structure', 'vp', 'chip_fund', 'emotion', 'risk', 'valuation')} | \
        {k: 1.0 for k in _AUX_DIMS}


# ── #J14：辅助维不稀释 neutral_ratio ───────────────────────

def test_j14_aux_dims_not_counted_neutral():
    """6 辅助维全中性 + 7 主维仅 3 个中性 → neutral_ratio=3/7≈0.43 不触发 cap"""
    # 主维：signal=1, structure=1, vp=1, chip_fund=0, emotion=0, risk=0, valuation=0
    dims = _dims(main={'signal': 1, 'structure': 1, 'vp': 1})
    r = compute(dims, _rel(), {}, emotion_phase='normal')
    # raw_consensus_rate 应显著 >0.5 且不被 cap（辅助维恒中性已排除）
    assert abs(r['raw_consensus_rate']) > 0.6, (
        f'3/4 主维看多时 raw rate 应高，实 {r["raw_consensus_rate"]}')
    # 若辅助维曾计入：6 辅助中性 + 4 主维中性 = 10/13 = 0.77 > 0.6 → cap 到 0.5
    # 修复后：3/7 = 0.43 < 0.6 → 不 cap → consensus_rate == raw_consensus_rate
    assert abs(r['consensus_rate']) == abs(r['raw_consensus_rate']), (
        f'辅助维不应触发 cap，实 {r["consensus_rate"]}')


def test_j14_primary_all_neutral_still_capped():
    """7 主维全中性 → neutral_ratio=7/7=1.0 → 仍触发 cap（主维中性语义保留）"""
    dims = _dims()
    r = compute(dims, _rel(), {}, emotion_phase='normal')
    assert r['consensus_rate'] == 0.0
    assert r['direction'] == 'neutral'


def test_j14_aux_dims_still_participate_family():
    """辅助维仍参与族方向归并：event=-1（负面）计入 environment 族方向"""
    # environment 族 = emotion+event+factor；主维 emotion=0，辅助 event=-1 → 族 bear
    dims = _dims(aux={'event': -1})
    r = compute(dims, _rel(), {}, emotion_phase='normal')
    gd = r['group_details']['environment']
    assert gd['direction'] == 'bear', f'event=-1 应使 environment 族 bear，实 {gd["direction"]}'
