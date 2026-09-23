"""476号存量回算：全市场重算 RAW-2（_precompute_raw_features），使 fcf 分位口径修正后的估值组真实化

背景：476号 修 build_fcf_percentile 分布口径（fcf/(mv*1e4)*100，对齐消费侧）——
  RAW a3（cashflow_anchor_rating）系统性偏低（600519 0.33 → 应≈1.19），composite/level 连带变化。
  需重算 RAW-2 落新 tags（pre_feat_cache valuation 组 + opportunity_tags_cache）。

用法（必须用 backend/.venv/bin/python，daemon 停止态）：
    .venv/bin/python scripts/_476_recompute_raw2.py --smoke N   # 冒烟重算 N 只验证 600519 a3 修正
    .venv/bin/python scripts/_476_recompute_raw2.py             # 全市场 5550 只重算（耗时较长）
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
logger = logging.getLogger('476_raw2')


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_476_raw2_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def _probe_tags(code, conn, date):
    """读取 pre_feat_cache 某股 valuation 组（StatusEngine._load_tags 同源）"""
    import json
    row = conn.execute(
        "SELECT features_json FROM pre_feat_cache WHERE ts_code=? "
        "AND trade_date=? LIMIT 1", (code, date)).fetchone()
    if not row:
        return {}
    try:
        val = json.loads(row[0]).get('valuation', {})
    except Exception:
        return {}
    keys = ('composite_rating', 'valuation_level', 'valuation_deviation',
            'cashflow_anchor_rating', 'fcf_yield', 'fina_health')
    return {k: val.get(k) for k in keys}


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

    # 冒烟目标：600519 修正前 cashflow_anchor_rating=0.33（口径修正后应≈1.19）
    import sqlite3
    conn = sqlite3.connect(compute_db)
    probe_codes = ['600519.SH', '300750.SZ']
    date_row = conn.execute(
        "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", ('600519.SH',)).fetchone()
    cur_date = date_row[0] if date_row else None
    logger.info(f"[回算前] 当前最新日期: {cur_date}")
    for c in probe_codes:
        logger.info(f"[回算前] {c} tags: {_probe_tags(c, conn, cur_date)}")
    conn.close()

    # 全市场活跃票池（441-A 已剔指数）
    codes = dd._get_active_codes()
    if not codes:
        logger.error("active 股票池为空，中止")
        return 1
    if args.smoke:
        # 冒烟保证包含探针股
        smoke = list(dict.fromkeys(probe_codes + codes[:max(0, args.smoke - len(probe_codes))]))
        codes = smoke
    logger.info(f"[RAW-2] 重算 {len(codes)} 只（{'冒烟 ' + str(args.smoke) if args.smoke else '全量'}）")

    t0 = time.time()
    n = dd._precompute_raw_features(codes)
    logger.info(f"[RAW-2] 完成 {n} 只，耗时 {time.time()-t0:.1f}s")

    conn = sqlite3.connect(compute_db)
    date_row = conn.execute(
        "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", ('600519.SH',)).fetchone()
    cur_date = date_row[0] if date_row else None
    for c in probe_codes:
        logger.info(f"[回算后] {c} tags: {_probe_tags(c, conn, cur_date)}")
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
