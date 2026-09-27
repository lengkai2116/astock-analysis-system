"""492号 JUD 实时全链路抽样复跑（只读：实时重算 dim1-8 → JUD，验证 K1-K5 在活数据上生效）

存量 strategy_signal_detail.dim_results_json（09-24）写于 490 的 dim3 `vp_*` 透传生效前，
缺 entry_zone/target_zone/resonance_score 等键 → K4 在全市场存量上恒 0。
本脚本**实时重建** dim_results（读 pre_feat + daily），跨市场抽样验证真实生效率。

用法（停 data_daemon 后）：backend/.venv/bin/python backend/scripts/_492_jud_live_sample.py [N]
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
from app.opportunity_atlas.consensus_engine import compute as consensus_compute  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine, _normalize_emotion_phase  # noqa: E402

_REGIMES = {
    'trending_up': {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10,
                    'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15},
    'trending_down': {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10,
                      'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20},
}


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    t0 = time.time()
    codes = [r[0] for r in sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT DISTINCT ts_code FROM strategy_signal_detail "
        "WHERE trade_date = '2026-09-24' AND dim_results_json IS NOT NULL ORDER BY ts_code",
        [])]
    step = max(1, len(codes) // n_sample)
    sample = codes[::step][:n_sample]
    print(f'### 492 JUD 实时抽样复跑：{len(sample)} / {len(codes)} 只（间隔 {step}）\n')

    se = StatusEngine()
    st = Counter()
    k1 = k4e = k4t = k5 = k2_ok = k3_ok = 0
    phase = Counter()
    n = fail = 0
    for i, code in enumerate(sample):
        try:
            tags = se._load_tags(code) or {}
            sig = se._load_signals(code) or {}
            lc = se._signal_lifecycle(code, tags, sig)
            dr = se._build_dim_engine_results(tags, sig, {}, lc, ts_code=code)
            if not dr:
                fail += 1
                continue
            row = se.evaluate(code, dim_results=dr) or {}
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [异常] {code}: {type(e).__name__}: {e}')
            continue
        n += 1
        st[row.get('opportunity_state')] += 1
        ap = json.loads(row.get('advice_params') or '{}')
        if ap.get('risk_budget_position') is not None:
            k1 += 1
        if ap.get('entry_zone'):
            k4e += 1
        if ap.get('target_zone'):
            k4t += 1
        # K5：L1 signal_confirm evidence 非空
        from app.opportunity_atlas.dim_adapter import convert_to_factors
        f = convert_to_factors(dr, tags)
        if (f.get('signal_confirm') or {}).get('evidence'):
            k5 += 1
        # K2：情绪仓位上限随 sentiment_phase（非 normal 时 != 0.6）
        ph = _normalize_emotion_phase(tags)
        phase[ph] += 1
        l0 = se._apply_l0(code, tags, {}, lc)
        if l0.get('emotion_position_cap') is not None:
            k2_ok += 1
        # K3：不同 regime 权重 → 共识不同
        from app.opportunity_atlas.reliability_assessor import assess
        rel = assess(f, dr)
        a = consensus_compute(f, rel, _REGIMES['trending_up'], ph)['consensus_rate']
        b = consensus_compute(f, rel, _REGIMES['trending_down'], ph)['consensus_rate']
        if a != b:
            k3_ok += 1
        if (i + 1) % 40 == 0:
            print(f'  ... {i + 1}/{len(sample)}  ok={n} fail={fail}  {time.time() - t0:.0f}s')

    def _p(x):
        return f'{x}/{n} ({x / n * 100:.0f}%)' if n else '0/0'

    print('\n=== opportunity_state ===')
    for k, v in st.most_common():
        print(f'  {k}: {v} ({v / n * 100:.1f}%)')
    print('=== 情绪阶段归一化（K2/K3 输入）===')
    for k, v in phase.most_common():
        print(f'  {k}: {v} ({v / n * 100:.1f}%)')
    print('=== K1-K5 生效率（活数据）===')
    print(f'  K1 risk_budget_position 非空 : {_p(k1)}')
    print(f'  K2 emotion_position_cap 产出  : {_p(k2_ok)}')
    print(f'  K3 regime 权重差异化          : {_p(k3_ok)}')
    print(f'  K4 entry_zone 非空            : {_p(k4e)}')
    print(f'  K4 target_zone 非空           : {_p(k4t)}')
    print(f'  K5 signal_confirm evidence    : {_p(k5)}')
    print(f'\n完成：n={n} fail={fail} 耗时={time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
