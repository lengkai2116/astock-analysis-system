"""552 虚拟重跑：在 APFS 克隆沙箱中完整重跑 2026-10-27 的 18 环节管道，测实际耗时。

隔离：DATA_DIR + DATABASE_URL + init_sharding 全部指向 /Users/kalence/552_sandbox/data，
      基准 data/ 零写入；采集器与 APScheduler 均跳过（DATA_DAEMON_RUNNING=1 / RAW2_CHILD=1）。

用法：cd backend && .venv/bin/python3 -u scripts/_552_rerun_full.py > /tmp/552_rerun_full.log 2>&1
"""
import json
import os
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.environ.get('SANDBOX_DATA', '/Users/kalence/552_sandbox/data')
DATE = '20261027'
STEPS = ['COL-1', 'COL-2', 'COL-3', 'COL-4', 'COL-5', 'COL-6', 'COL-7',
         'RAW-1', 'RAW-2', 'RAW-3', 'RAW-2B', 'RAW-2D', 'RAW-2E', 'RAW-2C',
         'SIG', 'JUD', 'OUT', 'QA-CHECK']

sys.path.insert(0, BACKEND)
os.environ['DATA_DIR'] = SANDBOX
os.environ['DATABASE_URL'] = f'sqlite:///{SANDBOX}/app.db'
os.environ['DATA_DAEMON_RUNNING'] = '1'
os.environ['RAW2_CHILD'] = '1'
os.environ.setdefault('RAW2_PROCESSES', '6')
for _k in [k for k in os.environ if 'proxy' in k.lower()]:
    os.environ.pop(_k, None)

import data_daemon as dd  # noqa: E402
from app.data.sharding_manager import init_sharding  # noqa: E402


def main():
    init_sharding(SANDBOX)
    dd._ensure_ecm()
    dd._ensure_pd()
    print(f'沙箱 DATA_DIR={SANDBOX}', flush=True)
    print(f'DATA_DIR(env)={os.environ.get("DATA_DIR")}', flush=True)

    # 重跑前快照当前状态（可追溯）
    before = dd._ecm.load_pipeline_status(DATE) or {}
    with open('/tmp/552_rerun_status_before.json', 'w', encoding='utf-8') as f:
        json.dump({k: v.get('status') for k, v in before.items()}, f, ensure_ascii=False, indent=2)

    dd._ecm.ensure_pipeline_steps(DATE)
    dd._ecm.conn.execute(
        "UPDATE pipeline_status SET status='pending', started_at=NULL, completed_at=NULL, "
        "detail=NULL, retry_count=0 WHERE pipeline_date=?", [DATE])
    dd._ecm.conn.commit()
    print(f'已重置 {DATE} 管道为 pending', flush=True)

    t0 = time.time()
    last = {}
    while True:
        try:
            dd._drive_pipeline()
        except Exception as e:
            print(f'{datetime.now():%H:%M:%S} _drive_pipeline 异常: {e}', flush=True)
        status = dd._ecm.load_pipeline_status(DATE) or {}
        changed = False
        for sid in STEPS:
            st = (status.get(sid) or {}).get('status')
            if last.get(sid) != st:
                row = status.get(sid) or {}
                print(f"{datetime.now():%H:%M:%S} {sid:9s} -> {st:8s} "
                      f"{row.get('detail') or ''}", flush=True)
                last[sid] = st
                changed = True
        if dd._is_pipeline_complete(DATE):
            print(f'{datetime.now():%H:%M:%S} 管道全部完成', flush=True)
            break
        if time.time() - t0 > 5 * 3600:
            print('TIMEOUT 5h', flush=True)
            break
        if not changed:
            time.sleep(3)
        else:
            time.sleep(1)

    elapsed = time.time() - t0
    final = dd._ecm.load_pipeline_status(DATE) or {}
    rows = []
    for sid in STEPS:
        r = final.get(sid) or {}
        rows.append({'step': sid, 'status': r.get('status'),
                     'started_at': r.get('started_at'), 'completed_at': r.get('completed_at'),
                     'detail': r.get('detail')})
    report = {'date': DATE, 'elapsed_sec': round(elapsed, 1),
              'elapsed_hms': time.strftime('%H:%M:%S', time.gmtime(elapsed)),
              'steps': rows}
    with open('/tmp/552_rerun_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
