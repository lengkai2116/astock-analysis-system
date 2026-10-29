"""552-C live 验收：RAW-2 多进程分块 vs 既有单线程结果（等价性 + 耗时）。

用法（daemon 必须已停止）：
    cd backend && .venv/bin/python3 scripts/_552_raw2_ab_probe.py
结果写 /tmp/552_raw2_ab_report.json；不一致时自动回滚备份。
"""
import json
import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ['RAW2_CHILD'] = '1'
os.environ.setdefault('RAW2_PROCESSES', '6')
for _k in [k for k in os.environ if 'proxy' in k.lower()]:
    os.environ.pop(_k, None)

DATE = os.environ.get('PROBE_DATE', '2026-10-27')
BACKUP = f'/tmp/552_pre_feat_{DATE}.json'
REPORT = '/tmp/552_raw2_ab_report.json'


def _db_path():
    import data_daemon as dd
    data_dir = os.environ.get('DATA_DIR') or os.path.join(BASE, '..', 'data')
    data_dir = os.path.abspath(data_dir)
    # 428 同型坑：分库路由是模块级单例，独立进程必须自行 init_sharding，
    # 否则父进程读/写会落到默认 backend/data/duckdb（与 daemon 实际 DATA_DIR 不一致）。
    from app.data.sharding_manager import init_sharding
    init_sharding(data_dir)
    return dd, os.path.join(data_dir, 'duckdb', 'compute_cache.db')


def main():
    dd, db = _db_path()
    con = sqlite3.connect(db, timeout=60)
    rows = con.execute(
        "SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?", [DATE]).fetchall()
    before = {r[0]: r[1] for r in rows}
    print(f'备份 {len(before)} 只 {DATE} pre_feat → {BACKUP}', flush=True)
    with open(BACKUP, 'w', encoding='utf-8') as f:
        json.dump(before, f, ensure_ascii=False)
    con.execute("DELETE FROM pre_feat_cache WHERE trade_date=?", [DATE])
    con.commit()
    con.close()

    codes = dd._get_active_codes(DATE)
    # 与 _drive_pipeline 对齐：RAW-2 前必须已有市场级统计（emotion_ext.breadth /
    # market_stats 组直接读该进程内全局）。基准必须用「库存行里那份」——当前缓存
    # 可能已被后续 _precompute_market_stats 重算覆盖（实测 rsi_percentile 0.1843→0.2256）。
    dd._ensure_ecm()
    stored_stats = None
    if before:
        try:
            stored_stats = json.loads(next(iter(before.values()))).get('market_stats')
        except Exception:
            stored_stats = None
    dd._market_stats_cache = stored_stats or dd._ecm.get_cached_market_stats() or {}
    print(f'市场级统计: {len(dd._market_stats_cache)} 项（库存基准={bool(stored_stats)}）', flush=True)
    print(f'待算 {len(codes)} 只；RAW2_PROCESSES={os.environ.get("RAW2_PROCESSES")}', flush=True)
    t0 = time.time()
    dd._precompute_raw_features(codes, target_date=DATE)
    elapsed = time.time() - t0
    print(f'RAW-2 多进程完成: {elapsed:.1f}s（{elapsed / max(len(codes), 1):.3f}s/只）', flush=True)

    con = sqlite3.connect(db, timeout=60)
    after = {r[0]: r[1] for r in con.execute(
        "SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?", [DATE]).fetchall()}
    con.close()

    sample = sorted(before)[::27][:200]
    diffs = []
    for code in sample:
        old, new = before.get(code), after.get(code)
        if old is None or new is None:
            diffs.append({'code': code, 'reason': 'missing', 'old': old is not None, 'new': new is not None})
            continue
        try:
            a, b = json.loads(old), json.loads(new)
        except Exception as e:
            diffs.append({'code': code, 'reason': f'json: {e}'})
            continue
        if a != b:
            keys = sorted(set(a) | set(b))
            diff_keys = [k for k in keys if a.get(k) != b.get(k)]
            item = {'code': code, 'reason': 'value', 'keys': diff_keys[:10]}
            if len(diffs) < 3:
                item['old'] = {k: a.get(k) for k in diff_keys[:3]}
                item['new'] = {k: b.get(k) for k in diff_keys[:3]}
            diffs.append(item)

    report = {
        'date': DATE,
        'codes': len(codes),
        'before_rows': len(before),
        'after_rows': len(after),
        'elapsed_sec': round(elapsed, 1),
        'per_stock_sec': round(elapsed / max(len(codes), 1), 3),
        'sample': len(sample),
        'diff_count': len(diffs),
        'diffs': diffs[:20],
    }
    with open(REPORT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

    if len(diffs) > 0:
        print('发现差异，回滚备份...', flush=True)
        con = sqlite3.connect(db, timeout=60)
        con.executemany(
            "INSERT OR REPLACE INTO pre_feat_cache (ts_code, trade_date, features_json) VALUES (?,?,?)",
            [(c, DATE, j) for c, j in before.items()])
        con.commit()
        con.close()
        print('已回滚', flush=True)
        return 1
    print('等价性通过（抽样 200 只逐字段一致）', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
