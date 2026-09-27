"""492号 JUD 全市场 v390 判定基准（只读真实数据，不写库）

对 09-24 全市场 ~5556 只个股的预计算 dim_results_json（strategy_signal_detail）
逐只跑 StatusEngine.evaluate（v390 L1-L6 + legacy dims + dim8 ①），统计：
  - opportunity_state / direction / status_bar 分布（与 K1-K5 修复前的 status_snapshot 对比）
  - consensus_rate 分布、final_score 分布
  - advice_params 中 K1/K4 键落地率（risk_budget_position / entry_zone / target_zone）
  - signals 触发率（P4：此前落库但无消费者）
  - K2/K3 生效证据：sentiment_phase 归一化后的情绪阶段 / group_details 族权重

用法（停 data_daemon 后）：backend/.venv/bin/python backend/scripts/_492_jud_full_market_baseline.py
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine, _normalize_emotion_phase  # noqa: E402

TRADE_DATE = '2026-09-24'


def _pct(n, d):
    return f'{n}/{d} ({n / d * 100:.1f}%)' if d else '0/0'


def main():
    t0 = time.time()
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date = ? AND dim_results_json IS NOT NULL",
        [TRADE_DATE],
    )
    print(f'### 492 JUD 全市场 v390 基准（trade_date={TRADE_DATE}）')
    print(f'输入：{len(rows)} 只（strategy_signal_detail.dim_results_json 非空）\n')

    se = StatusEngine()
    st_cnt = Counter()
    dir_cnt = Counter()
    bar_cnt = Counter()
    cons = []
    fscore = []
    n_ok = 0
    k1 = k4e = k4t = 0
    sig_hit = 0
    fail = 0

    for i, (code, dr_json) in enumerate(rows):
        try:
            dr = json.loads(dr_json)
        except Exception:
            fail += 1
            continue
        try:
            row = se.evaluate(code, dim_results=dr)
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [evaluate 异常] {code}: {type(e).__name__}: {e}')
            continue
        if not row:
            fail += 1
            continue
        n_ok += 1
        st_cnt[row.get('opportunity_state')] += 1
        dir_cnt[row.get('direction')] += 1
        bar_cnt[row.get('status_bar')] += 1
        try:
            cons.append(float(row.get('consensus_rate') or 0))
        except Exception:
            pass
        try:
            if row.get('final_score') is not None:
                fscore.append(float(row['final_score']))
        except Exception:
            pass
        # K2 证据：情绪阶段归一化（读 tags，需重取）
        # advice_params 键落地
        try:
            ap = json.loads(row.get('advice_params') or '{}')
        except Exception:
            ap = {}
        if ap.get('risk_budget_position') is not None:
            k1 += 1
        if ap.get('entry_zone'):
            k4e += 1
        if ap.get('target_zone'):
            k4t += 1
        try:
            if json.loads(row.get('signals') or '[]'):
                sig_hit += 1
        except Exception:
            pass
        if (i + 1) % 1000 == 0:
            print(f'  ... {i + 1}/{len(rows)}  elapsed={time.time() - t0:.0f}s  ok={n_ok} fail={fail}')

    def _stat(name, arr):
        if not arr:
            print(f'  {name}: (无数据)')
            return
        arr = sorted(arr)
        n = len(arr)
        print(f'  {name}: n={n} min={arr[0]:.3f} p25={arr[n // 4]:.3f} '
              f'med={arr[n // 2]:.3f} p75={arr[3 * n // 4]:.3f} max={arr[-1]:.3f} '
              f'mean={sum(arr) / n:.4f}')

    print('\n=== opportunity_state 分布 ===')
    for k, v in st_cnt.most_common():
        print(f'  {k}: {_pct(v, n_ok)}')
    print('=== direction 分布 ===')
    for k, v in dir_cnt.most_common():
        print(f'  {k}: {_pct(v, n_ok)}')
    print('=== status_bar 分布 ===')
    for k, v in bar_cnt.most_common():
        print(f'  {k}: {_pct(v, n_ok)}')
    print('=== consensus_rate / final_score 分布 ===')
    _stat('consensus_rate', cons)
    _stat('final_score', fscore)
    print('=== K1/K4/P4 落库证据（advice_params / signals） ===')
    print(f'  K1 risk_budget_position 非空: {_pct(k1, n_ok)}')
    print(f'  K4 entry_zone 非空        : {_pct(k4e, n_ok)}')
    print(f'  K4 target_zone 非空       : {_pct(k4t, n_ok)}')
    print(f'  P4 signals 触发非空       : {_pct(sig_hit, n_ok)}')
    print(f'\n完成：ok={n_ok}  fail={fail}  耗时={time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
