"""493 批次4 端到端探针（只读）：P2-c/P2-e/P2-f 真实数据效果

- P2-f：统计 (weekly=down, daily=up) 样本 → 大级别否决触发面
- P2-e：对样本取 dim6 risk_sd → 校验止损取较高 + 分批止盈输出
- P2-c：统计当前 ice 样本 + right_side_confirm 分布
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager as sm  # noqa: E402
from app.opportunity_atlas.advice_engine import (  # noqa: E402
    _apply_stop_and_tiers, _weekly_direction,
)

TRADE_DATE = '2026-09-24'


def main():
    rows = sm.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date=? AND dim_results_json IS NOT NULL ORDER BY ts_code",
        [TRADE_DATE])
    step = max(1, len(rows) // 800)
    sample = rows[::step][:800]
    print(f'### 493 批次4 探针  n_in={len(rows)}  n_sample={len(sample)}')

    veto_pairs = Counter()
    n_daily_up = n_weekly_down = n_veto = 0
    stop_bases = Counter()
    tier_cnt = 0
    ice_cnt = 0
    for code, dj in sample:
        try:
            dr = json.loads(dj)
        except Exception:
            continue
        ml = ((dr.get('structure') or {}).get('status_description') or {}).get('multi_level') or {}
        dm = ml.get('direction_map') or {}
        d = str(dm.get('daily', ''))
        w = str(dm.get('weekly', ''))
        if d == 'up':
            n_daily_up += 1
        if w == 'down':
            n_weekly_down += 1
        if d == 'up' and w == 'down':
            n_veto += 1
            veto_pairs[f'{d}/{w}'] += 1
        # P2-e：止损取较高 + 分批止盈
        risk_sd = (dr.get('risk') or {}).get('status_description') or {}
        adv = {}
        _apply_stop_and_tiers(adv, 10.0, risk_sd, dr)
        if adv.get('stop_loss_basis'):
            stop_bases[adv['stop_loss_basis']] += 1
        if adv.get('profit_tiers'):
            tier_cnt += 1
        # P2-c：冰点样本
        sp = ((dr.get('emotion') or {}).get('status_description') or {})
        if 'ice' in json.dumps(sp, ensure_ascii=False):
            ice_cnt += 1

    print(f'\n--- P2-f（大级别否决）---')
    print(f'  daily=up: {n_daily_up}  weekly=down: {n_weekly_down}  '
          f'**daily=up&weekly=down（触发否决）: {n_veto}**')
    print(f'\n--- P2-e（止损取较高 + 分批止盈）---')
    for k, v in stop_bases.most_common():
        print(f'  {k}: {v}')
    print(f'  含分批止盈计划: {tier_cnt}')
    print(f'\n--- P2-c（冰点）---  命中 ice 样本: {ice_cnt}')


if __name__ == '__main__':
    main()
