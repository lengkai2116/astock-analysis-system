"""442号缺陷④回填：全市场重算 RAW-2（_precompute_raw_features），使 sector 组真实化（写入 compute_cache.db）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_442_recompute_raw2.py --smoke N   # 冒烟重算 N 只验证修复生效
    .venv/bin/python scripts/_442_recompute_raw2.py             # 全市场 5550 只重算（耗时较长）

背景：442号缺陷④修复了 RAW-2 线程池 app_context 问题，但现有 pre_feat 的 sector 组
  仍是旧的 'none'（历史重算产物），需重算 RAW-2 才真实化。
验证：重算后 pre_feat sector 组 sector_heat != 'none' 的覆盖率应大幅提升。
"""
import os
import sys
import time
import shutil
import argparse
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('442_raw2')


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_442_raw2_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', type=int, default=0, help='冒烟重算 N 只（0=全量）')
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args()

    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    compute_db = os.path.join(data_dir, 'duckdb', 'compute_cache.db')
    if not args.no_backup:
        bak = _backup(compute_db)
        if bak:
            logger.info(f"[备份] compute_cache.db → {os.path.basename(bak)}")
        else:
            logger.warning(f"[备份] 未找到 {compute_db}，跳过备份")

    # 全市场活跃票池（441-A 已剔指数）
    codes = dd._get_active_codes()
    if not codes:
        logger.error("active 股票池为空，中止")
        return 1
    if args.smoke:
        codes = codes[:args.smoke]
    logger.info(f"[RAW-2] 重算 {len(codes)} 只（{'冒烟 ' + str(args.smoke) if args.smoke else '全量'}）")

    t0 = time.time()
    n = dd._precompute_raw_features(codes)
    logger.info(f"[RAW-2] 完成 {n} 只，耗时 {time.time()-t0:.1f}s")

    # 验证：sector 组真实化覆盖率
    import sqlite3
    conn = sqlite3.connect(compute_db)
    rows = conn.execute(
        "SELECT ts_code, features_json FROM pre_feat_cache "
        "WHERE ts_code IN ({}) AND trade_date=(SELECT MAX(trade_date) FROM pre_feat_cache)"
        .format(','.join('?' * len(codes))), codes).fetchall()
    import json
    from collections import Counter
    cnt = Counter()
    for code, fj in rows:
        try:
            sec = json.loads(fj).get('sector', {})
            h = sec.get('sector_heat')
            cnt['none' if h == 'none' else ('有值' if h else '缺')] += 1
        except Exception:
            cnt['解析失败'] += 1
    conn.close()
    logger.info(f"[验证] 样本 {len(rows)} 只 sector 组分布: {dict(cnt)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
