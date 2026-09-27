"""490号 SIG 契约键产出 × JUD 消费核验探针（真实数据，只读不写）

对 8 只个股跑 SIG 引擎链（dim1-8），核验 490 号 A/B/C 三类修复在真实数据上的落地：
  1) A 类补产出键是否真实落 status_description（dim2/dim3/dim4/dim5/dim7）；
  2) JUD L1 因子（direction/strength）是否不再恒默认（dim3/dim5/dim7 原恒 0/0）；
  3) L2 可靠性是否不再恒 0.5（dim3/dim4/dim5）；
  4) L4 冲突规则是否真实触发；
  5) cross_validate dim_engine→legacy 是否含 chip 维。
用法：停 data_daemon 后 `backend/.venv/bin/python backend/scripts/_490_sig_contract_probe.py`
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.conflict_matrix import detect as conflict_detect  # noqa: E402
from app.opportunity_atlas.consensus_engine import compute as consensus_compute  # noqa: E402
from app.opportunity_atlas.cross_validate import _convert_dim_engine_to_legacy  # noqa: E402
from app.opportunity_atlas.dim_adapter import (  # noqa: E402
    convert_to_factors,
    multi_level_consistency,
)
from app.opportunity_atlas.reliability_assessor import assess  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

# 490 号新增/修复键（dim → status_description 键清单）
NEW_KEYS = {
    'structure': ['chanlun_strength_components', 'consistency_component',
                  'divergence_multi_algo'],
    'volume_price': ['vol_ratio_value', 'state_machine_direction',
                     'state_machine_confidence', 'stage_name', 'stage_confidence',
                     'resonance_score', 'three_laws', 'risk_notes',
                     'entry_zone', 'target_zone'],
    'chip_fund': ['phase_confidence', 'pde_conflict', 'pde_vote_ratio',
                  'pde_price_position', 'crowding_level', 'cost_concentration',
                  'cost_profit_ratio'],
    'emotion': ['market_phase', 'sector_heat', 'bociasi_fast_signal',
                'bociasi_slow_signal', 'bociasi_slow_confidence', 'bociasi_quadrant',
                'temperature_value'],
    'valuation': ['composite_rating', 'valuation_deviation', 'asset_anchor_rating',
                  'earnings_anchor_rating', 'dividend_yield_value',
                  'revenue_growth_value'],
}

WEIGHTS = {'main_behavior': 0.25, 'structure_trend': 0.20, 'volume_price': 0.20,
           'valuation_quality': 0.15, 'environment': 0.10, 'risk': 0.10}


def _is_empty(v) -> bool:
    """空值判定（numpy 数组不可用 `in`/真值判断，须按 size）"""
    if v is None:
        return True
    if isinstance(v, str):
        return v == ''
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    try:
        import numpy as _np
        if isinstance(v, _np.ndarray):
            return v.size == 0
    except Exception:
        pass
    return False


def _brief(v):
    s = json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)
    return s[:110] + ('…' if len(s) > 110 else '')


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dr = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code) or {}

    print('=' * 104)
    print(f'### {code}')

    # 1) A 类补产出键
    print('-- A 类补产出键（status_description）--')
    for dim, keys in NEW_KEYS.items():
        sd = (dr.get(dim) or {}).get('status_description') or {}
        miss = [k for k in keys if _is_empty(sd.get(k))]
        print(f'  [{dim}] 缺/空 {len(miss)}/{len(keys)}: {miss if miss else "无"}')
        for k in keys:
            if not _is_empty(sd.get(k)):
                print(f'      {k} = {_brief(sd.get(k))}')

    # 2) L1 因子
    f = convert_to_factors(dr, tags)
    print('-- L1 因子 direction/strength --')
    for dim in ('signal', 'structure', 'vp', 'chip_fund', 'emotion', 'valuation'):
        fd = f.get(dim) or {}
        print(f'  {dim}: dir={fd.get("direction")} str={fd.get("strength")}')
    print(f'  multi_level_consistency = {multi_level_consistency(dr)}')

    # 3) L2 可靠性
    rel = assess(f, dr)
    print('-- L2 可靠性 --')
    print('  ' + ', '.join(f'{k}={v}' for k, v in rel.items()))

    # 4) L3/L4
    cons = consensus_compute(f, rel, WEIGHTS, emotion_phase='normal')
    conflict = conflict_detect(f, tags, dr, consensus_rate=abs(cons.get('consensus_rate', 0)))
    print(f'-- L3 共识={cons.get("consensus_rate")} dir={cons.get("direction")} --')
    print(f'-- L4 冲突 {len(conflict.get("all_conflicts") or [])} 条 / '
          f'语义={conflict.get("semantic_type")} --')
    for c in (conflict.get('all_conflicts') or []):
        print(f'    {c}')

    # 5) cross_validate 回灌
    legacy = _convert_dim_engine_to_legacy(dr) or {}
    print(f'-- cross_validate 回灌维: {sorted(legacy.keys())} '
          f'(chip 维 {"OK" if "chip" in legacy else "缺"}）--')


def main():
    print('490号 SIG 契约键 × JUD 消费核验探针（只读）')
    for code in CODES:
        try:
            probe(code)
        except Exception as e:  # 单只失败不阻塞
            import traceback
            print(f'### {code} 探针异常: {type(e).__name__}: {e}')
            traceback.print_exc()


if __name__ == '__main__':
    main()
