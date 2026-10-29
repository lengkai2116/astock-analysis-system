"""552-C 严格 A/B：同一时点、同一截面上下文，线程路径 vs 多进程路径。

不依赖 10-27 的库存历史值（那些已被后续 _precompute_market_stats / 事件表漂移污染），
先构建一次 all_heat + market_stats，再用相同 _shared_ctx 分别跑：
  A = 父进程 _local_only（线程）
  B = _run_raw2_in_processes（spawn 子进程）
逐字段比对 200 只样本；结束后恢复样本行的原始备份。

用法（daemon 必须已停止）：
    cd backend && .venv/bin/python3 scripts/_552_raw2_ab_probe2.py
"""
import json
import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ['RAW2_CHILD'] = '1'
for _k in [k for k in os.environ if 'proxy' in k.lower()]:
    os.environ.pop(_k, None)

DATE = '2026-10-27'
SAMPLE_N = 200
REPORT = '/tmp/552_raw2_ab_report2.json'
BACKUP = '/tmp/552_pre_feat_2026-10-27.json'


def main():
    import data_daemon as dd
    from app.data.sharding_manager import init_sharding
    data_dir = os.path.abspath(os.environ.get('DATA_DIR') or os.path.join(BASE, '..', 'data'))
    init_sharding(data_dir)
    db = os.path.join(data_dir, 'duckdb', 'compute_cache.db')
    dd._ensure_ecm()

    con = sqlite3.connect(db, timeout=60)
    before = dict(con.execute(
        "SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?", [DATE]).fetchall())
    con.close()
    print(f'库存备份 {len(before)} 只', flush=True)

    codes_all = dd._get_active_codes(DATE)
    sample = sorted(codes_all)[:SAMPLE_N]
    print(f'样本 {len(sample)} / 全市场 {len(codes_all)}', flush=True)

    # 构建一次截面上下文（A/B 共用）
    from app import create_app
    app = create_app()
    from app.data import DataManager
    from app.engine.framework.sector_rotation_model import SectorRotationModel
    dm = DataManager()
    sr = SectorRotationModel()
    all_data = {}
    for c in codes_all:
        df = dm.get_cached_daily_data(c, adj='qfq')
        if df is not None and not df.empty:
            all_data[c] = df
    print(f'全市场日线 {len(all_data)} 只', flush=True)
    ind = {}
    for c in all_data:
        try:
            d = dd._ecm.get_indicators_wide(c)
            if d is not None and not d.empty:
                ma = [x for x in d.columns if x.startswith('ma')]
                if ma:
                    ind[c] = d[ma]
        except Exception:
            pass
    with app.app_context():
        sr.compute_all_heat(all_data, indicator_ma_dict=ind)
    stored_stats = None
    if before:
        for v in before.values():
            try:
                ms = json.loads(v).get('market_stats')
            except Exception:
                ms = None
            if ms:
                stored_stats = ms
                break
    ctx = {'all_heat': sr._cache.get('all_heat'), 'market_stats': stored_stats or {}}
    print(f"截面上下文: all_heat={len(ctx['all_heat'] or {})} 行业, "
          f"market_stats={len(ctx['market_stats'])} 项", flush=True)
    dd._market_stats_cache = ctx['market_stats']

    def _read(codes):
        con = sqlite3.connect(db, timeout=60)
        rows = con.execute(
            "SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?", [DATE]).fetchall()
        con.close()
        return {k: v for k, v in rows if k in set(codes)}

    # A：父进程线程路径
    con = sqlite3.connect(db, timeout=60)
    con.execute("DELETE FROM pre_feat_cache WHERE trade_date=? AND ts_code IN (%s)"
                % ','.join('?' * len(sample)), [DATE] + sample)
    con.commit(); con.close()
    t0 = time.time()
    dd._precompute_raw_features(sample, target_date=DATE, _shared_ctx=ctx, _local_only=True)
    a_sec = time.time() - t0
    A = _read(sample)
    print(f'A 线程路径: {len(A)} 只, {a_sec:.1f}s', flush=True)

    # B：多进程路径
    con = sqlite3.connect(db, timeout=60)
    con.execute("DELETE FROM pre_feat_cache WHERE trade_date=? AND ts_code IN (%s)"
                % ','.join('?' * len(sample)), [DATE] + sample)
    con.commit(); con.close()
    t0 = time.time()
    left = dd._run_raw2_in_processes(sample, DATE, ctx, 4)
    b_sec = time.time() - t0
    B = _read(sample)
    print(f'B 多进程路径: {len(B)} 只, {b_sec:.1f}s, 遗漏 {len(left)}', flush=True)

    diffs = []
    for code in sample:
        a, b = A.get(code), B.get(code)
        if a is None or b is None:
            diffs.append({'code': code, 'reason': 'missing', 'a': a is not None, 'b': b is not None})
            continue
        if a != b:
            ja, jb = json.loads(a), json.loads(b)
            keys = [k for k in sorted(set(ja) | set(jb)) if ja.get(k) != jb.get(k)]
            diffs.append({'code': code, 'reason': 'value', 'keys': keys[:10]})

    report = {
        'date': DATE, 'sample': len(sample), 'a_rows': len(A), 'b_rows': len(B),
        'a_sec': round(a_sec, 1), 'b_sec': round(b_sec, 1), 'left': len(left),
        'diff_count': len(diffs), 'diffs': diffs[:20],
    }
    with open(REPORT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'diffs'}, ensure_ascii=False), flush=True)
    if diffs:
        print('差异样本:', json.dumps(diffs[:5], ensure_ascii=False), flush=True)

    # 恢复样本原始行
    con = sqlite3.connect(db, timeout=60)
    con.executemany(
        "INSERT OR REPLACE INTO pre_feat_cache (ts_code, trade_date, features_json) VALUES (?,?,?)",
        [(c, DATE, before[c]) for c in sample if c in before])
    con.commit(); con.close()
    print('样本行已恢复为库存原值', flush=True)
    return 0 if not diffs else 1


if __name__ == '__main__':
    sys.exit(main())
