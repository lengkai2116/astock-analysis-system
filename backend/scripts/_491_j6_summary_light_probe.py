"""491-J6 复核探针（真实数据，只读）：summary 灯「旧内联阈值 vs SSOT summary_light」等价性

B 方案口径下两者应逐股**完全一致**（口径归 SSOT，值不变）。
用法（daemon 停止态）：backend/.venv/bin/python backend/scripts/_491_j6_summary_light_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas import light_derive as LD  # noqa: E402
from app.opportunity_atlas.dimensions import dim8_summary_engine as D8  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def main():
    print('491-J6 summary 灯等价性（旧内联阈值 vs SSOT summary_light）')
    diff = 0
    for code in CODES:
        try:
            se = StatusEngine()
            tags = se._load_tags(code) or {}
            signals = se._load_signals(code) or {}
            lc = se._signal_lifecycle(code, tags, signals)
            dr = se._build_dim_engine_results(tags, signals, {}, lc, ts_code=code) or {}
            cr = D8._calc_consensus_rate(dr)
            legacy = 'green' if cr >= 0.6 else ('red' if cr < 0.3 else 'yellow')
            ssot = LD.summary_light(cr)
            row = D8._build_eight_dim_summary(dr)['summary']['light']
            ok = (legacy == ssot == row)
            if not ok:
                diff += 1
            print(f'  {code} cr={cr:.2f} 旧={legacy:6s} SSOT={ssot:6s} '
                  f'eight_dim.summary={row:6s} {"✓" if ok else "✗"}')
        except Exception as e:
            print(f'  {code} 异常: {type(e).__name__}: {e}')
    print(f'\n不一致 {diff}/{len(CODES)}（B 口径应全 0）')


if __name__ == '__main__':
    main()
