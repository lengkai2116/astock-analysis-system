"""493号 批次1（P2-b）真实数据影响量化（只读）

P2-b 生效位置 = `advice_engine.build_operation_advice`（经 cross_validate → 机会图谱
弹窗 operation_advice），非 v390 status_snapshot。故量化口径：
  对样本逐只取日线 → `advice_builder._geometric(df)` 求 rr（目标收益/止损风险），
  统计 rr 落在 [1,2) 的比例（= 新门禁新增拦截量，原 1.0 门禁放行）。

用法：停 data_daemon 后 backend/.venv/bin/python backend/scripts/_493_p2b_rr_impact.py [N]
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.advice_builder import _geometric  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    codes = [r[0] for r in sharding_manager.execute_query(
        'daily_cache', "SELECT DISTINCT ts_code FROM daily_cache ORDER BY ts_code", [])]
    step = max(1, len(codes) // n_sample)
    sample = codes[::step][:n_sample]
    print(f'### 493 P2-b rr 影响量化：{len(sample)}/{len(codes)} 只（间隔 {step}）\n')

    se = StatusEngine()
    band = Counter()
    n = no_rr = 0
    for c in sample:
        try:
            df = se.dm.get_cached_daily_data(c)
            if df is None or getattr(df, 'empty', True) or len(df) < 20:
                continue
            geo = _geometric(df)
            rr = geo.get('risk_reward')
            if rr is None:
                no_rr += 1
                continue
            rr = float(rr)
            n += 1
            if rr < 1.0:
                band['<1.0（原有门禁已拦）'] += 1
            elif rr < 2.0:
                band['[1.0,2.0)（P2-b 新增拦截）'] += 1
            else:
                band['>=2.0（放行）'] += 1
        except Exception:
            continue

    tot = max(n + no_rr, 1)
    print(f'有 rr 的样本 n={n}（无 rr {no_rr}）')
    for k, v in band.most_common():
        print(f'  {k}: {v} ({v / max(n, 1) * 100:.1f}%)')
    inc = band.get('[1.0,2.0)（P2-b 新增拦截）', 0)
    print(f'\nP2-b 新增拦截（原放行 → 现 wait）：{inc}/{n} = {inc / max(n, 1) * 100:.1f}%')


if __name__ == '__main__':
    main()
