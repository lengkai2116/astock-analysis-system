"""552 沙箱补测：RAW 段（前置全链路重跑因断点续算跳过 RAW，需删除 10-27 原料产物后重算）。

前置：/tmp/552_rerun_full.py 的驱动进程已退出（SIG/JUD/OUT 已完成）。
本脚本只在沙箱 /Users/kalence/552_sandbox/data 内删除 10-27 的原料行并重跑 RAW。
"""
import json
import os
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.environ.get('SANDBOX_DATA', '/Users/kalence/552_sandbox/data')
DATE = '20261027'
DATE_FMT = '2026-10-27'   # 原料表的 trade_date 是 YYYY-MM-DD（紧凑格式会删 0 行）
RAW_STEPS = ['RAW-1', 'RAW-2', 'RAW-3', 'RAW-2B', 'RAW-2D', 'RAW-2E', 'RAW-2C']
TABLES = ['pre_feat_cache', 'indicator_ma', 'indicator_macd', 'indicator_other', 'factor_cache']

sys.path.insert(0, BACKEND)
os.environ['DATA_DIR'] = SANDBOX
os.environ['DATABASE_URL'] = f'sqlite:///{SANDBOX}/app.db'
os.environ['DATA_DAEMON_RUNNING'] = '1'
os.environ['RAW2_CHILD'] = '1'
os.environ.setdefault('RAW2_PROCESSES', '6')
for _k in [k for k in os.environ if 'proxy' in k.lower()]:
    os.environ.pop(_k, None)

import data_daemon as dd  # noqa: E402
from app.data.sharding_manager import init_sharding, sharding_manager as sm  # noqa: E402


def main():
    init_sharding(SANDBOX)
    dd._ensure_ecm()
    print(f'沙箱 {SANDBOX}', flush=True)

    for t in TABLES:
        conn = sm.get_connection(sm.get_db_for_table(t))
        cur = conn.execute(f"DELETE FROM {t} WHERE trade_date=?", [DATE_FMT])
        conn.commit()
        print(f'  删除 {t} {DATE_FMT}: {cur.rowcount} 行', flush=True)

    dd._ecm.conn.execute(
        "UPDATE pipeline_status SET status='pending', started_at=NULL, completed_at=NULL, detail=NULL "
        f"WHERE pipeline_date=? AND step_id IN ({','.join('?' * len(RAW_STEPS))})",
        [DATE] + RAW_STEPS)
    dd._ecm.conn.commit()
    print('RAW 环节已重置为 pending', flush=True)

    t0 = time.time()
    last = {}
    while True:
        try:
            dd._drive_pipeline()
        except Exception as e:
            print(f'{datetime.now():%H:%M:%S} 异常: {e}', flush=True)
        status = dd._ecm.load_pipeline_status(DATE) or {}
        for sid in RAW_STEPS:
            st = (status.get(sid) or {}).get('status')
            if last.get(sid) != st:
                print(f"{datetime.now():%H:%M:%S} {sid:8s} -> {st}", flush=True)
                last[sid] = st
        if dd._is_pipeline_complete(DATE):
            break
        if time.time() - t0 > 2 * 3600:
            print('TIMEOUT 2h', flush=True)
            break
        time.sleep(2)

    elapsed = time.time() - t0
    final = dd._ecm.load_pipeline_status(DATE) or {}
    rows = [{'step': s, 'status': (final.get(s) or {}).get('status'),
             'started_at': (final.get(s) or {}).get('started_at'),
             'completed_at': (final.get(s) or {}).get('completed_at'),
             'detail': (final.get(s) or {}).get('detail')} for s in RAW_STEPS]
    report = {'date': DATE, 'raw_elapsed_sec': round(elapsed, 1),
              'raw_elapsed_hms': time.strftime('%H:%M:%S', time.gmtime(elapsed)), 'steps': rows}
    with open('/tmp/552_rerun_raw_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
