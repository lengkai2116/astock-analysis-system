"""486号-3 存量 pre_feat 定向重算：使量价状态机兜底方向修复（classify_fast）落库

背景：486-3 修复 volume_price_strategy.classify_fast 兜底方向（价跌量增不再默认
  "价涨量增(强势)"）——但 vp_state_label 由 daemon RAW-2 预计算写 pre_feat_cache，
  存量快照仍为旧值。需定向重算 8 只验证新状态机输出（479-3 先例）。

用法（必须用 backend/.venv/bin/python，daemon 停止态）：
    .venv/bin/python scripts/_486_3_prefeat_recompute.py
"""
import os
import sys
import time
import shutil
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('486_3_prefeat')

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_486_3_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def _vp_label(conn, code, date):
    import json
    row = conn.execute(
        "SELECT features_json FROM pre_feat_cache WHERE ts_code=? "
        "AND trade_date=? LIMIT 1", (code, date)).fetchone()
    if not row:
        return None
    try:
        f = json.loads(row[0])
    except Exception:
        return None
    vp = f.get('volume_price', {}) or {}
    return vp.get('vp_state_label')


def main():
    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    compute_db = os.path.join(data_dir, 'duckdb', 'compute_cache.db')
    bak = _backup(compute_db)
    logger.info(f"[备份] compute_cache.db → {os.path.basename(bak)}" if bak else "[备份] 跳过")

    import sqlite3
    conn = sqlite3.connect(compute_db)
    logger.info("======== 回算前：vp_state_label 现状 ========")
    for c in CODES:
        drow = conn.execute(
            "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", (c,)).fetchone()
        d = drow[0] if drow else None
        logger.info(f"  {c} date={d} vp_state_label={_vp_label(conn, c, d)}")
    conn.close()

    t0 = time.time()
    n = dd._precompute_raw_features(CODES)
    logger.info(f"[RAW-2] 定向重算 {n} 只，耗时 {time.time()-t0:.1f}s")

    conn = sqlite3.connect(compute_db)
    logger.info("======== 回算后：vp_state_label（486-3 状态机兜底方向修复） ========")
    ok = True
    for c in CODES:
        drow = conn.execute(
            "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", (c,)).fetchone()
        d = drow[0] if drow else None
        lab = _vp_label(conn, c, d)
        logger.info(f"  {c} date={d} vp_state_label={lab}")
        if lab in (None, ''):
            ok = False
    conn.close()
    logger.info("========= 结论 =========")
    logger.info("ALL_OK" if ok else "HAS_GAP：存在空 vp_state_label，见上")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
