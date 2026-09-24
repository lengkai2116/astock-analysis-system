"""479号-3 存量 pre_feat 真实重算：定向重跑 RAW-2 8 只，使 A5/A8 新键落库

背景：479-3 已落 data_daemon volume_price 组透传 A5（vp_state_label/vp_rule）+
  A8（divergence_type/divergence_confidence/divergence_macd_confirmed），但存量
  pre_feat_cache 是旧 JSON（无新键）；daemon 对已 done 交易日跳 RAW-2 不重算。
  需主动定向重算 8 只验证新键真实入库（467 先例）。

用法（必须用 backend/.venv/bin/python，daemon 停止态）：
    .venv/bin/python scripts/_479_3_prefeat_recompute.py
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
logger = logging.getLogger('479_3_prefeat')

# 479 系列 8 股探针集合（与各子项探针一致）
CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

# 479-3 A5/A8 新键（透传点 data_daemon:3452-3456）
A5_A8_KEYS = ('vp_state_label', 'vp_rule',
              'divergence_type', 'divergence_confidence', 'divergence_macd_confirmed')


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_479_3_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def _vp_group(conn, code, date):
    """读某股最新 pre_feat_cache 的 volume_price 组"""
    import json
    row = conn.execute(
        "SELECT features_json FROM pre_feat_cache WHERE ts_code=? "
        "AND trade_date=? LIMIT 1", (code, date)).fetchone()
    if not row:
        return None, None
    try:
        f = json.loads(row[0])
    except Exception:
        return None, None
    vp = f.get('volume_price', {}) or {}
    return vp, f.get('trade_date') or date


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

    # 回算前：查各股 volume_price 组是否已含 A5/A8 新键
    logger.info("======== 回算前：volume_price 组 A5/A8 新键现状 ========")
    pre_keys = {}
    for c in CODES:
        drow = conn.execute(
            "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", (c,)).fetchone()
        d = drow[0] if drow else None
        vp, _ = _vp_group(conn, c, d)
        present = {k: (k in vp) for k in A5_A8_KEYS} if vp is not None else None
        pre_keys[c] = (d, present)
        logger.info(f"  {c} date={d} 新键存在? {present}")
    conn.close()

    t0 = time.time()
    n = dd._precompute_raw_features(CODES)
    logger.info(f"[RAW-2] 定向重算 {n} 只，耗时 {time.time()-t0:.1f}s")

    # 回算后：验证 A5/A8 新键落库
    conn = sqlite3.connect(compute_db)
    logger.info("======== 回算后：volume_price 组 A5/A8 新键 ========")
    ok = True
    for c in CODES:
        drow = conn.execute(
            "SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?", (c,)).fetchone()
        d = drow[0] if drow else None
        vp, _ = _vp_group(conn, c, d)
        if vp is None:
            logger.info(f"  {c} date={d} volume_price 组缺失！")
            ok = False
            continue
        keys = {k: vp.get(k) for k in A5_A8_KEYS}
        missing = [k for k, v in keys.items() if v in (None, '')]
        if missing:
            logger.info(f"  {c} date={d} 缺键/空: {missing} → {keys}")
            ok = False
        else:
            logger.info(f"  {c} date={d} ✅ 5 新键齐全: {keys}")
    conn.close()

    logger.info("========= 结论 =========")
    logger.info("ALL_OK：8 只 A5/A8 新键全部落库" if ok else "HAS_GAP：仍有缺键，见上")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
