"""495号 批次1 真链验证：JUD 判定单源化（A1）全市场抽样（只读）

对比同一股票生产路径（StatusEngine.evaluate，dim8 在判定后注入 jud_result）：
  - status_verdict.consensus_rate ∈ [-1,1]（判定权威）
  - dim_engine_results.summary.judgment.consensus_rate ∈ [0,1]（展示派生 = (cr+1)/2 映射）
  - status_bar 由 opportunity_state 派生（avoid→risk_warning 等，矛盾组合应为 0）
验证口径：|映射差| < 0.01 全过；v390=avoid 且 dim8 positive 组合 = 0。

用法：backend/.venv/bin/python backend/scripts/_495_b1_single_source_probe.py [N]
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

DATE = '2026-09-24'
_POSITIVE_BARS = {'strong_confirm', 'trend_confirm', 'light_confirm'}


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        f"SELECT ts_code, dim_results_json FROM strategy_signal_detail WHERE trade_date='{DATE}' "
        "AND dim_results_json IS NOT NULL ORDER BY ts_code", [])
    step = max(1, len(rows) // n_sample)
    sample = rows[::step][:n_sample]
    print(f'### 495-B1 单源化真链验证：{len(sample)}/{len(rows)} 只（间隔 {step}）\n')

    se = StatusEngine()
    bar_map = Counter()
    n = fail = 0
    mismap = 0
    contradict = 0
    missing_summary = 0
    for i, (code, dj) in enumerate(sample):
        try:
            dr = json.loads(dj)
            row = se.evaluate(code, dim_results=dr) or {}
            der = json.loads(row.get('dim_engine_results') or '{}')
            sm = (der.get('summary') or {}).get('judgment') or {}
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [异常] {code}: {type(e).__name__}: {e}')
            continue
        if not sm:
            missing_summary += 1
            continue
        n += 1
        # 判定权威（v390 落 status_verdict）与展示派生（dim8 summary）映射一致性
        vc = float(row.get('consensus_rate') or 0)
        dc = float(sm.get('consensus_rate') or 0)
        expect = round(max(0.0, min(1.0, (vc + 1) / 2)), 2)
        if abs(dc - expect) > 0.01:
            mismap += 1
            if mismap <= 5:
                print(f'  [映射不一致] {code}: v390={vc} → expect={expect} dim8={dc}')
        # 矛盾组合：v390=avoid 但 dim8 展示正向确认
        state = row.get('opportunity_state')
        dbar = sm.get('status_bar')
        bar_map[(state, dbar)] += 1
        if state == 'avoid' and dbar in _POSITIVE_BARS:
            contradict += 1

    print(f'n={n} fail={fail} missing_summary={missing_summary}\n')
    print('=== opportunity_state × dim8 status_bar（Top 12）===')
    for (st, db), c in bar_map.most_common(12):
        print(f'  v390={st!s:<8} dim8={db!s:<15} : {c}')
    print(f'\n映射不一致（|Δ|>0.01）：{mismap}/{n}')
    print(f'矛盾组合（v390=avoid 且 dim8 正向确认）：{contradict}/{n}')
    print('结论：单源化' + ('✅ 通过' if mismap == 0 and contradict == 0 else '❌ 未通过'))


if __name__ == '__main__':
    main()
