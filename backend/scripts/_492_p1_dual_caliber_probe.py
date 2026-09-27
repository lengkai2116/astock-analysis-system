"""492 P1 诊断：dim8 自算口径 vs v390 判定口径 的实测量化（只读）

对比同一 dim_results 输入下：
  - v390（③）: status_engine 的 status_bar / consensus_rate / direction / opportunity_state
  - dim8（①）: dim8_summary_engine 的 status_bar / consensus_rate / 灯色
并检测「矛盾组合」（如 v390=avoid 而 dim8=strong_confirm）。

用法：backend/.venv/bin/python backend/scripts/_492_p1_dual_caliber_probe.py [N]
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.dimensions.dim8_summary_engine import (  # noqa: E402
    Dim8SummaryEngine)
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

DATE = '2026-09-24'
# v390 opportunity_state 与 dim8 status_bar 的语义对立对（应视为矛盾）
_AVOID_VS_POSITIVE = {'strong_confirm', 'trend_confirm'}


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        f"SELECT ts_code, dim_results_json FROM strategy_signal_detail WHERE trade_date='{DATE}' "
        "AND dim_results_json IS NOT NULL ORDER BY ts_code", [])
    step = max(1, len(rows) // n_sample)
    sample = rows[::step][:n_sample]
    print(f'### 492 P1 双口径量化：{len(sample)}/{len(rows)} 只（间隔 {step}）\n')

    se = StatusEngine()
    d8 = Dim8SummaryEngine()
    cmp_bar = Counter()       # (v390_bar, dim8_bar)
    d_cons = []               # consensus_rate 差值
    contradict = 0
    light_cmp = Counter()
    n = fail = 0
    for i, (code, dj) in enumerate(sample):
        try:
            tags = se._load_tags(code) or {}
            dr = json.loads(dj)
            v = se.evaluate(code, dim_results=dr) or {}
            s = d8.evaluate(dims={}, tags=tags, lifecycle={'dim_results': dr}) or {}
            jg = s.get('judgment', {}) or {}
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [异常] {code}: {type(e).__name__}: {e}')
            continue
        n += 1
        vbar = v.get('status_bar')
        dbar = jg.get('status_bar')
        cmp_bar[(vbar, dbar)] += 1
        vc = float(v.get('consensus_rate') or 0)
        dc = float(jg.get('consensus_rate') or 0)
        d_cons.append(dc - vc)
        light_cmp[jg.get('overall_light')] += 1
        # 矛盾：v390 avoid/不可交易 但 dim8 判强/趋势确认
        if v.get('opportunity_state') == 'avoid' and dbar in _AVOID_VS_POSITIVE:
            contradict += 1
        # 矛盾：v390 bull 但 dim8 灯 red（或反之）
        if (v.get('direction') == 'bull' and jg.get('overall_light') == 'red') or \
           (v.get('direction') == 'bear' and jg.get('overall_light') == 'green'):
            contradict += 1

    def _stat(name, arr):
        if not arr:
            print(f'  {name}: 无数据')
            return
        a = sorted(arr)
        N = len(a)
        print(f'  {name}: min={a[0]:.3f} p25={a[N // 4]:.3f} med={a[N // 2]:.3f} '
              f'p75={a[3 * N // 4]:.3f} max={a[-1]:.3f} mean={sum(a) / N:.3f} '
              f'|Δ|>0.2 占比={sum(1 for x in a if abs(x) > 0.2) / N * 100:.1f}%')

    print(f'n={n} fail={fail}\n')
    print('=== v390 status_bar × dim8 status_bar（Top 15 组合）===')
    for (vb, db), c in cmp_bar.most_common(15):
        print(f'  v390={vb!s:<10} dim8={db!s:<14} : {c}')
    print('=== dim8 consensus_rate − v390 consensus_rate（差值分布）===')
    _stat('Δconsensus', d_cons)
    print('=== dim8 overall_light 分布 ===')
    for k, c in light_cmp.most_common():
        print(f'  {k}: {c} ({c / n * 100:.1f}%)')
    print(f'\n=== 矛盾组合数：{contradict}/{n} ({contradict / n * 100:.1f}%) ===')


if __name__ == '__main__':
    main()
