"""509号批次2 #J16 探针：周线无条件降 wait（Q3 拍板）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.4。

#J16 原缺陷：factor_arbiter Step 7 大级别否决带 `_daily_is_bullish` 门——
    周线 down 时仅当日线结构/量价看多（direction>0）才降 wait；日线不看多（平/负）
    时 enter/light 得以保留，与「周线向下即丢弃买点」语义不符（日线不看多时本就不应
    enter/light，保留门会让错误状态存活）。

Q3 拍板「无条件降 wait」：周线 down 且状态 ∈ enter/light → 无条件降 wait（去门）。

探针：
  1. 周线 down + 日线看多 → 降 wait（原行为保留）；
  2. 周线 down + 日线平/负（原被门放过）→ 现无条件降 wait；
  3. 周线 up/'' → 不降（无回归）；
  4. `_daily_is_bullish` 死函数已删除。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from app.opportunity_atlas.factor_arbiter import arbitrate  # noqa: E402


def _arb(weekly, main_dims=None):
    """构造：周线方向 + 主维方向（structure/vp）"""
    dims_factor = {'emotion': {'direction': 0, 'strength': 0.5}}
    for k, v in (main_dims or {}).items():
        dims_factor[k] = {'direction': v, 'strength': 0.5}
    # 强确认 + 高 consensus 确保进入 enter 档（Step7 前状态）
    return arbitrate(
        consensus={'consensus_rate': 0.9},
        conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
        tags={'right_side_confirm': '强确认'},
        dims_factor=dims_factor,
        reliability={},
        weekly_direction=weekly)


# ── #J16：周线无条件降 wait ────────────────────────────────

def test_j16_weekly_down_daily_bullish_wait():
    """周线 down + 日线看多 → 降 wait（原行为保留）"""
    r = _arb('down', {'structure': 1, 'vp': 1})
    assert r['opportunity_state'] == 'wait'
    assert '大级别否决' in ' '.join(r['state_evidence'])


def test_j16_weekly_down_daily_flat_wait():
    """周线 down + 日线平（原被门放过）→ 现无条件降 wait（Q3 修复核心）"""
    r = _arb('down', {'structure': 0, 'vp': 0})
    assert r['opportunity_state'] == 'wait', \
        f'周线 down 无条件降 wait（日线平也应降），实 {r["opportunity_state"]}'


def test_j16_weekly_down_daily_bearish_wait():
    """周线 down + 日线看空 → 降 wait"""
    r = _arb('down', {'structure': -1, 'vp': -1})
    assert r['opportunity_state'] == 'wait'


def test_j16_weekly_up_no_downgrade():
    """周线 up → 不降（保持 enter）"""
    r = _arb('up', {'structure': 1, 'vp': 1})
    assert r['opportunity_state'] == 'enter'


def test_j16_weekly_empty_no_downgrade():
    """周线 ''（缺失）→ 不降"""
    r = _arb('', {'structure': 1, 'vp': 1})
    assert r['opportunity_state'] == 'enter'


def test_j16_daily_is_bullish_removed():
    """死函数 _daily_is_bullish 已删除"""
    import app.opportunity_atlas.factor_arbiter as fa

    assert not hasattr(fa, '_daily_is_bullish'), '死函数应已删除'
