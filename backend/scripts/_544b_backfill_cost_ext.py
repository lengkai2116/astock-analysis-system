"""544-B 定向回填：补写 2026-10-22 pre_feat_cache 的空 cost_ext。

只更新 features_json 的 cost_ext 字段，保留其余键不动。
默认 dry-run（只统计/抽样打印），--apply 才写 compute_cache.db。
写库前须停 data_daemon，避免 SQLite 写锁竞争。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
os.environ['DATA_DIR'] = str(PROJECT / 'data')
os.environ['DATA_DAEMON_RUNNING'] = '1'
sys.path.insert(0, str(PROJECT / 'backend'))

from app.data import enhanced_cache_manager as em  # noqa: E402

em._tables_initialized_paths.add(str(PROJECT / 'data' / 'duckdb' / 'stock_cache.db'))

from app.engine.framework.chip_strategy import MainForceScorer  # noqa: E402

DB_DIR = PROJECT / 'data' / 'duckdb'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default='2026-10-22')
    parser.add_argument('--limit', type=int, default=0, help='仅处理前 N 只（0=全部）')
    parser.add_argument('--apply', action='store_true', help='实际写库（默认 dry-run）')
    args = parser.parse_args()

    compute = sqlite3.connect(DB_DIR / 'compute_cache.db', timeout=30)
    compute.execute('PRAGMA busy_timeout=30000')
    market = sqlite3.connect(f'file:{DB_DIR / "market_cache.db"}?mode=ro', uri=True)

    close_map = dict(market.execute(
        'SELECT ts_code, close FROM daily_cache WHERE trade_date=?', [args.date]))
    rows = compute.execute(
        'SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?',
        [args.date]).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    mfs = MainForceScorer()
    updated = skipped = failed = 0
    samples = []
    t0 = time.perf_counter()

    for i, (code, fj) in enumerate(rows, 1):
        try:
            features = json.loads(fj)
        except Exception:
            failed += 1
            continue
        cost = features.get('cost_ext')
        if isinstance(cost, dict) and cost:
            skipped += 1
            continue
        close = close_map.get(code)
        if close is None or float(close) <= 0:
            failed += 1
            continue
        try:
            mfc = mfs._calc_main_force_cost(code, float(close))
            mcp = mfs._calc_margin_cost_price(code, float(close))
        except Exception:
            failed += 1
            continue
        features['cost_ext'] = {'main_force_cost': mfc, 'margin_cost_price': mcp}
        if args.apply:
            compute.execute(
                'UPDATE pre_feat_cache SET features_json=? '
                'WHERE ts_code=? AND trade_date=?',
                [json.dumps(features, ensure_ascii=False), code, args.date])
            if i % 200 == 0:
                compute.commit()
        updated += 1
        if len(samples) < 3:
            samples.append((code, features['cost_ext']))

    if args.apply:
        compute.commit()
    elapsed = time.perf_counter() - t0
    print(json.dumps({
        'date': args.date, 'apply': args.apply, 'total': len(rows),
        'updated': updated, 'skipped': skipped, 'failed': failed,
        'elapsed_s': round(elapsed, 2),
    }, ensure_ascii=False))
    for s in samples:
        print('SAMPLE', s)
    compute.close()
    market.close()


if __name__ == '__main__':
    main()
