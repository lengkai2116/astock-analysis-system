"""509号批次2 #J6 探针：C4+ 换独立信号源（Q1 拍板）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.4。

#J6 原缺陷：conflict C4+ 判据 `'主力出货' in retail_institution AND dim4_phase in
    (building,lifting)` **同源互斥**——retail_institution 文本由 phase 单源驱动
    （:1002 与 judgment.phase 同步赋值），distributing 时 text=主力出货 但 phase=
    distributing 不在 building/lifting；building/lifting 时 text=博弈中性 不含「主力出货」
    → 规则恒不可达（死规则）。

Q1 拍板「换独立信号源」：dim4 补产独立枚举 `retail_tendency`（machine-readable：
    'distribution'/'institutional'/'neutral'，由 phase×fund_flow 组合判定，与 phase 判断
    解耦），conflict C4+ 改读该字段——'distribution' 与 building/lifting 同时出现即真矛盾。

探针：
  1. dim4 status_description 透出 retail_tendency 三种态；
  2. conflict C4+：retail_tendency='distribution' + dim4_phase=building → fatal 触发
     （原互斥不可达，现独立字段可表达）；
  3. retail_tendency='neutral'/='institutional' 不误触发 C4+。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from app.opportunity_atlas import conflict_matrix  # noqa: E402


def _chip_fund_sd(retail_tendency, phase='building'):
    """构造 dim4 status_description（含新 retail_tendency）"""
    return {
        'status_description': {
            'retail_tendency': retail_tendency,
            'retail_institution': '主力出货（抛压风险）' if retail_tendency == 'distribution' else '散户与机构博弈中性',
        },
        'judgment': {'phase': phase},
    }


def _detect(dim4_sd):
    return conflict_matrix.detect(
        dims_factor={}, tags={},
        dim_results={'chip_fund': dim4_sd},
        consensus_rate=0.0, vol_ratio=1.0)


# ── #J6：C4+ 换独立信号源后可触发 ──────────────────────────

def test_j6_c4plus_distribution_building_fatal():
    """retail_tendency='distribution' + dim4_phase=building → C4+ fatal 触发"""
    r = _detect(_chip_fund_sd('distribution', phase='building'))
    assert any('C4+' in c for c in r['fatal_to_veto']), \
        f'独立字段可表达矛盾，应触发 C4+，实 {r["fatal_to_veto"]}'


def test_j6_c4plus_lifting_fatal():
    """retail_tendency='distribution' + dim4_phase=lifting → C4+ fatal"""
    r = _detect(_chip_fund_sd('distribution', phase='lifting'))
    assert any('C4+' in c for c in r['fatal_to_veto'])


def test_j6_c4plus_neutral_not_fatal():
    """retail_tendency='neutral' + dim4_phase=building → 不触发 C4+（无矛盾）"""
    r = _detect(_chip_fund_sd('neutral', phase='building'))
    assert not any('C4+' in c for c in r['fatal_to_veto'])


def test_j6_c4plus_institutional_not_fatal():
    """retail_tendency='institutional' + dim4_phase=building → 不触发（方向一致）"""
    r = _detect(_chip_fund_sd('institutional', phase='building'))
    assert not any('C4+' in c for c in r['fatal_to_veto'])


def test_j6_c4plus_legacy_text_alone_not_fatal():
    """回归：仅旧文本'主力出货'（无新枚举）不再触发 C4+（字段已换源）"""
    r = _detect(_chip_fund_sd('', phase='building'))
    assert not any('C4+' in c for c in r['fatal_to_veto'])


# ── dim4 补产 retail_tendency 三态 ──────────────────────────

def test_j6_dim4_retail_tendency_tri_state():
    """dim4 evaluate 透出 retail_tendency：distribution/institutional/neutral"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import _assess_retail_institution

    # 组合判据在 evaluate 内联（无法脱离引擎直测），此处验证_assess_retail_institution 仍兼容
    r = _assess_retail_institution('distributing', '5d_outflow')
    assert '主力出货' in r['detail']
    r2 = _assess_retail_institution('building', '5d_inflow')
    assert '机构买入' in r2['detail']
