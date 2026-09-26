"""461-14 只读探针：核对 dim1 completeness_score 真实数据下不再越界 >1.0

只读：置 DATA_DAEMON_RUNNING=1 并屏蔽 _notify_missing_data（阻断 sync_requests 写）。
用法：backend/.venv/bin/python -m scripts._461_14_completeness_probe（在 backend 下）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)
os.environ['DATA_DAEMON_RUNNING'] = '1'

from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine

Dim1SignalEngine._notify_missing_data = lambda self, ts, mt: None

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def main():
    engine = Dim1SignalEngine()
    bad = 0
    for code in CODES:
        r = engine.evaluate({}, {'ts_code': code}, {}, {})
        sq = r['status_quality']
        score = sq['completeness_score']
        aux = [k for k in ('weekly_df', 'hourly_df', 'relative_strength') if k in sq['loaded_keys']]
        over = score > 1.0
        if over:
            bad += 1
        print(f"{code}  completeness={score:.4f}  loaded={len(sq['loaded_keys'])}  "
              f"missing={len(sq['missing_tables'])}  quality={sq['quality_level']}  "
              f"aux载入={aux}  {'❌>1.0' if over else 'OK'}")
    print(f"\n汇总：{len(CODES)} 只，越界 {bad} 只")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
