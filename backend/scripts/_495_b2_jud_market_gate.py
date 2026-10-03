"""495号 批次2（A4）：JUD 全市场真实数据门禁（只读，不写库）

沿生产路径 `StatusEngine.evaluate(code, dim_results=...)`（v390 L1-L6 + dim8 单源化）
逐只重跑**最近交易日**全市场预计算 dim_results_json（strategy_signal_detail），
固化为回归门禁：

【硬性阻断】（任一不过 → 退出码 1）
  H1  evaluate 失败率 = 0（dim_results 非空输入下不允许任何异常/空返回）
  H2  单源化不变量 = 0（495 批次1）：
      - 映射不一致：|(v390_consensus_rate+1)/2 - dim8_summary.consensus_rate| > 0.01 的样本
      - 矛盾组合：v390 opportunity_state=avoid 且 dim8 summary.status_bar ∈ 正向确认
  H3  consensus_rate ∈ [-1, 1]（判定权威）且 final_score ∈ [0, 100]（全部样本）

【范围断言】（基准 ±5pt 容差，基准=2026-09-28 全市场实测；497号批次3 重定）
  R1  opportunity_state 五档占比：avoid 78.5 / wait 13.5 / reduce 6.9 / enter 0.6 / light 0.4

【观察项】（打印不阻断）
  K1 risk_budget_position / K4 entry_zone/target_zone（C1 待 daemon 日终 RAW-2 刷新，0% 属已知）
  P4 signals 触发率 / status_bar 分布 / direction 分布

用法（停 data_daemon 后，约 1 分钟）：
  backend/.venv/bin/python backend/scripts/_495_b2_jud_market_gate.py            # 门禁（最近交易日）
  backend/.venv/bin/python backend/scripts/_495_b2_jud_market_gate.py --date 2026-09-24  # 指定交易日
  backend/.venv/bin/python backend/scripts/_495_b2_jud_market_gate.py --print-baseline     # 只打印分布
"""
import argparse
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

# 五档分布基线 + 容差 ±5pt
# 497号（批次3/P1，2026-09-29）：分布基线重定——经归因确认（09-28 vs 09-24 探针，
#   `scripts/_497_b3_attribution_probe.py`）偏移为「行情真实反映 + 数据真实化」而非误判：
#   09-24 旧基线定于数据退化期（valuation/vp 维恒 100% 中性、factor 恒 -1、finance 9.2%，
#   均无真实产出）；09-28 经 484 数据补采 + 496 RAW-2 全量重算后各维真实化（valuation 63.4%、
#   finance 64.2%、signal 66.6% 看空），叠加当日大跌（均值 -2.24%/跌 82%）→ 看空占比真实抬升。
#   L2 reliability 两日基本一致（risk 0.670/0.685）→ 排除单维权重异常放大。
#   2026-09-28 全市场 5552 只实测：enter 0.6 / light 0.4 / wait 13.5 / reduce 6.9 / avoid 78.5
# 507号（批次1/#S4，2026-10-03）：分布基线重定——`consensus_engine` 中性维计数修复
#   （dict 值 float() 失败致「中性占比 >0.6」上限从未生效；修复后上限复活）。
#   同日对照（09-30 全市场 5554 只，仅 S4 开关）：
#     旧 enter0.4/light0.5/wait12.7/reduce6.7/avoid79.8 → 新 enter0.2/light0.3/wait10.5/reduce5.6/avoid83.3
#   即 ≈195 只（3.5pt）由 wait/reduce/enter 下移 avoid（去「虚假高置信」）；direction 分布不变。
#   2026-09-30 全市场 5554 只实测：enter 0.2 / light 0.3 / wait 10.5 / reduce 5.6 / avoid 83.3
STATE_BASELINE = {'avoid': 83.3, 'wait': 10.5, 'reduce': 5.6, 'enter': 0.2, 'light': 0.3}
STATE_TOL = 5.0
_POSITIVE_BARS = {'strong_confirm', 'trend_confirm', 'light_confirm'}


def _latest_trade_date() -> str:
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        'SELECT MAX(trade_date) FROM strategy_signal_detail', [])
    return str(rows[0][0]) if rows and rows[0][0] else ''


def _load_rows(trade_date: str):
    return sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date = ? AND dim_results_json IS NOT NULL", [trade_date])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default='')
    ap.add_argument('--print-baseline', action='store_true',
                    help='只打印分布（供更新基线），不执行门禁')
    args = ap.parse_args()

    trade_date = args.date or _latest_trade_date()
    rows = _load_rows(trade_date)
    print(f'### 495-B2 JUD 全市场真实数据门禁  trade_date={trade_date}  n_in={len(rows)}')
    if not rows:
        print('ERROR: 无 dim_results_json 数据（SIG 未跑或交易日无数据）')
        sys.exit(2)

    t0 = time.time()
    se = StatusEngine()
    st_cnt = Counter()
    dir_cnt = Counter()
    bar_cnt = Counter()
    cons_bad = fscore_bad = 0
    mismap = contradict = 0
    k1 = k4e = k4t = sig_hit = 0
    n = fail = 0
    for i, (code, dj) in enumerate(rows):
        try:
            dr = json.loads(dj)
            row = se.evaluate(code, dim_results=dr)
        except Exception:
            fail += 1
            if fail <= 3:
                print(f'  [evaluate 异常] {code}')
            continue
        if not row:
            fail += 1
            continue
        n += 1
        st = row.get('opportunity_state')
        st_cnt[st] += 1
        dir_cnt[row.get('direction')] += 1
        bar_cnt[row.get('status_bar')] += 1
        # H3 数值范围
        try:
            cr = float(row.get('consensus_rate') or 0)
            if not (-1.0 <= cr <= 1.0):
                cons_bad += 1
        except (TypeError, ValueError):
            cons_bad += 1
        try:
            fs = float(row.get('final_score') or 0)
            if not (0.0 <= fs <= 100.0):
                fscore_bad += 1
        except (TypeError, ValueError):
            fscore_bad += 1
        # H2 单源化不变量（dim8 summary 消费判定层，映射一致 + 无矛盾组合）
        try:
            der = json.loads(row.get('dim_engine_results') or '{}')
            jg = (der.get('summary') or {}).get('judgment') or {}
            dc = float(jg.get('consensus_rate') or 0)
            expect = round(max(0.0, min(1.0, (cr + 1) / 2)), 2)
            if abs(dc - expect) > 0.01:
                mismap += 1
            dbar = jg.get('status_bar')
            if st == 'avoid' and dbar in _POSITIVE_BARS:
                contradict += 1
        except Exception:
            pass  # dim8 缺失不阻断（H2 只统计有 summary 的样本）
        # 观察项：K1/K4/P4 落地率
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
            print(f'  ... {i + 1}/{len(rows)}  elapsed={time.time() - t0:.0f}s  ok={n} fail={fail}')

    def _pct(c, d):
        return f'{c}/{d} ({c / d * 100:.1f}%)' if d else '0/0'

    def _pct_f(c, d):
        return c / d * 100 if d else 0.0

    print(f'\n=== opportunity_state 五档分布（n={n}）===')
    for k in ('enter', 'light', 'wait', 'reduce', 'avoid'):
        p = _pct_f(st_cnt.get(k, 0), n)
        base = STATE_BASELINE.get(k, 0)
        mark = 'OK' if base - STATE_TOL <= p <= base + STATE_TOL else 'OUT'
        print(f'  {k:8s}: {p:6.1f}%  (基线 {base:.1f}±{STATE_TOL:.0f})  [{mark}]')
    others = {k: v for k, v in st_cnt.items()
              if k not in ('enter', 'light', 'wait', 'reduce', 'avoid')}
    if others:
        print(f'  其他     : {others}')
    print('\n=== direction / status_bar 分布（观察）===')
    for k, v in dir_cnt.most_common():
        print(f'  direction {k:8s}: {_pct(v, n)}')
    for k, v in bar_cnt.most_common():
        print(f'  status_bar {k!s:8s}: {_pct(v, n)}')
    print('\n=== 落库证据（观察；K4 属 C1 待 daemon 日终刷新） ===')
    print(f'  K1 risk_budget_position: {_pct(k1, n)}')
    print(f'  K4 entry_zone          : {_pct(k4e, n)}')
    print(f'  K4 target_zone         : {_pct(k4t, n)}')
    print(f'  P4 signals 触发        : {_pct(sig_hit, n)}')
    print(f'\n完成：ok={n}  fail={fail}  耗时={time.time() - t0:.0f}s')

    if args.print_baseline:
        print('\n[print-baseline] 新基线（百分比，用于更新 STATE_BASELINE）：')
        print('  ' + ' / '.join(f"{k} {_pct_f(st_cnt.get(k, 0), n):.1f}"
                                for k in ('enter', 'light', 'wait', 'reduce', 'avoid')))
        sys.exit(0)

    # ── 门禁评估 ──
    checks = []
    checks.append(('H1 evaluate 失败率 = 0', fail == 0, f'fail={fail}/{len(rows)}'))
    checks.append(('H2 映射不一致 = 0', mismap == 0, f'mismap={mismap}'))
    checks.append(('H2 矛盾组合 = 0', contradict == 0, f'contradict={contradict}'))
    checks.append(('H3 consensus ∈ [-1,1]', cons_bad == 0, f'bad={cons_bad}'))
    checks.append(('H3 final_score ∈ [0,100]', fscore_bad == 0, f'bad={fscore_bad}'))
    all_ok = True
    print('\n=== 门禁结果 ===')
    for name, ok, detail in checks:
        print(f'  [{"PASS" if ok else "FAIL"}] {name}  ({detail})')
        all_ok = all_ok and ok
    for k in ('enter', 'light', 'wait', 'reduce', 'avoid'):
        p = _pct_f(st_cnt.get(k, 0), n)
        base = STATE_BASELINE.get(k, 0)
        lo, hi = max(0.0, base - STATE_TOL), base + STATE_TOL
        ok = lo <= p <= hi
        print(f'  [{"PASS" if ok else "FAIL"}] R1 {k} 占比 {p:.1f}% ∈ [{lo:.1f}, {hi:.1f}]')
        all_ok = all_ok and ok
    print(f'\n结论：{"✅ 门禁通过" if all_ok else "❌ 门禁未通过"}')
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
