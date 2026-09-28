"""493 批次2（P2-a）诊断：归一化档位候选方案对 opportunity_state 分布的影响（只读）

对全市场预计算 dim_results_json 逐只跑 StatusEngine.evaluate（v390），
取每条 l2.final_score，按「当前档位」与「Wiki 候选档位」分别映射 state，
对照分布差异（含新增「减仓」档的占比），供批次2 拍板提供量化依据。

用法（停 data_daemon 后）：backend/.venv/bin/python backend/scripts/_493_p2a_threshold_impact.py
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
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

TRADE_DATE = '2026-09-24'

# 当前实现（factor_arbiter._THRESHOLDS，4 态）
CURRENT = [(70, 'enter'), (55, 'light'), (30, 'wait')]
# 候选 A：Wiki 4 态（只改边界，不加档）
CAND_A = [(80, 'enter'), (65, 'light'), (45, 'wait')]
# 候选 B：Wiki 5 态（加「减仓」档）
CAND_B = [(80, 'enter'), (65, 'light'), (45, 'wait'), (30, 'reduce')]


def _map(score, table):
    for th, st in table:
        if score is not None and score >= th:
            return st
    return 'avoid'


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
    print(f'### 493 P2-a 档位影响诊断（trade_date={TRADE_DATE}）')
    print(f'输入：{len(rows)} 只\n')

    se = StatusEngine()
    cur = Counter()
    a = Counter()
    b = Counter()
    scores = []
    n_ok = fail = 0
    # 「仅调边界不改档」时有多少只 state 变轻
    changed_cur_a = 0

    for i, (code, dj) in enumerate(rows):
        try:
            dr = json.loads(dj)
            row = se.evaluate(code, dim_results=dr)
        except Exception:
            fail += 1
            continue
        if not row:
            fail += 1
            continue
        n_ok += 1
        fs = row.get('final_score')
        scores.append(float(fs) if fs is not None else 0.0)
        cur[_map(fs, CURRENT)] += 1
        sa = _map(fs, CAND_A)
        a[sa] += 1
        b[_map(fs, CAND_B)] += 1
        if sa != _map(fs, CURRENT):
            changed_cur_a += 1
        if (i + 1) % 1000 == 0:
            print(f'  ... {i + 1}/{len(rows)}  elapsed={time.time() - t0:.0f}s')

    def _dump(name, cnt):
        print(f'=== {name} ===')
        for k in ('enter', 'light', 'wait', 'reduce', 'avoid'):
            if cnt.get(k):
                print(f'  {k}: {_pct(cnt[k], n_ok)}')

    _dump('当前档位 70/55/30（4 态）', cur)
    _dump('候选A Wiki 80/65/45（4 态，仅改边界）', a)
    _dump('候选B Wiki 80/65/45/30（5 态，含减仓）', b)
    print(f'\n档位边界变更导致 state 变化: {_pct(changed_cur_a, n_ok)}')
    s = sorted(scores)
    n = len(s)
    if n:
        print(f'final_score: n={n} min={s[0]:.1f} p25={s[n // 4]:.1f} med={s[n // 2]:.1f} '
              f'p75={s[3 * n // 4]:.1f} p90={s[int(n * 0.9)]:.1f} max={s[-1]:.1f}')
    print(f'\n完成：ok={n_ok}  fail={fail}  耗时={time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
