"""494号 批次4 探针（只读）：R-7 全市场 JUD 重跑核验

沿生产路径 `StatusEngine.evaluate(code, dim_results=...)`（v390 L1-L6，daemon「日终 JUD」
step 同源）逐只重跑 09-24 全市场 dim_results，统计：
  1. `opportunity_state` 五档分布（含 **reduce**，493 P2-a 后应出现）；
  2. `monthly_halt` 非空（R-5 落库源）与 `advice_params` 的 `profit_tiers`/`stop_loss_basis`（R-4）；
  3. 大级别否决命中（R-2；`state_evidence` 含「大级别否决」）；
  4. 与现存 `status_snapshot`（09-25，493 前构建）的档位迁移对照。

用法（须停 daemon）：backend/.venv/bin/python backend/scripts/_494_batch4_full_market_probe.py
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager as sm  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

TRADE_DATE = '2026-09-24'


def _pct(n, d):
    return f'{n}/{d} ({n / d * 100:.1f}%)' if d else '0/0'


def main():
    t0 = time.time()
    rows = sm.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date = ? AND dim_results_json IS NOT NULL", [TRADE_DATE])
    print(f'### 494 批次4 探针（R-7 全市场 JUD 重跑） trade_date={TRADE_DATE}  n_in={len(rows)}')

    # 现存快照（09-25，493 批次2 之前构建 → 无 reduce）用于迁移对照
    old_state = {}
    try:
        for code, st in sm.execute_query(
                'status_snapshot', "SELECT ts_code, opportunity_state FROM status_snapshot"):
            old_state[code] = st
    except Exception:
        pass

    se = StatusEngine()
    st_cnt = Counter()
    old_cnt = Counter()
    mig = Counter()
    n = fail = veto = halt = 0
    p_tiers = p_basis = 0

    for i, (code, dj) in enumerate(rows):
        try:
            dr = json.loads(dj)
        except Exception:
            fail += 1
            continue
        try:
            row = se.evaluate(code, dim_results=dr)
        except Exception:
            fail += 1
            continue
        if not row:
            fail += 1
            continue
        n += 1
        _st = row.get('opportunity_state')
        st_cnt[_st] += 1
        _old = old_state.get(code)
        old_cnt[_old] += 1
        if _old is not None and _old != _st:
            mig[f'{_old}->{_st}'] += 1
        # R-2：大级别否决命中
        try:
            if any('大级别否决' in e for e in json.loads(row.get('state_evidence') or '[]')):
                veto += 1
        except Exception:
            pass
        # R-5：monthly_halt（快照写入源）
        if row.get('monthly_halt'):
            halt += 1
        # R-4：advice_params 键
        try:
            ap = json.loads(row.get('advice_params') or '{}')
        except Exception:
            ap = {}
        if ap.get('profit_tiers'):
            p_tiers += 1
        if ap.get('stop_loss_basis'):
            p_basis += 1
        if (i + 1) % 1000 == 0:
            print(f'  ... {i + 1}/{len(rows)}  elapsed={time.time() - t0:.0f}s  ok={n} fail={fail}')

    print(f'\n=== opportunity_state 五档分布（重跑，n={n}）===')
    for k in ('enter', 'light', 'wait', 'reduce', 'avoid'):
        if st_cnt.get(k) or k == 'reduce':
            print(f'  {k:8s}: {_pct(st_cnt.get(k, 0), n)}')
    others = {k: v for k, v in st_cnt.items() if k not in ('enter', 'light', 'wait', 'reduce', 'avoid')}
    if others:
        print(f'  其他     : {others}')
    print('\n=== 与现存 status_snapshot（09-25，493 前）对照 ===')
    print(f'  旧分布: {dict(old_cnt.most_common())}')
    print(f'  迁移（旧→新，前 12）: {dict(mig.most_common(12))}')
    print('\n=== R-2/R-4/R-5 落库源证据 ===')
    print(f'  大级别否决命中（R-2）        : {_pct(veto, n)}')
    print(f'  monthly_halt 非空（R-5）     : {_pct(halt, n)}')
    print(f'  advice_params.profit_tiers（R-4）: {_pct(p_tiers, n)}')
    print(f'  advice_params.stop_loss_basis（R-4）: {_pct(p_basis, n)}')
    print(f'\n完成：ok={n} fail={fail} 耗时={time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
