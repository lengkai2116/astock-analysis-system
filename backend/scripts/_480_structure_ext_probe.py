"""480号 structure_ext 恒空修复验证：定向重跑 RAW-2 8 股，确认 structure_ext 非空

背景：480号修复 data_daemon _raw2_one 第 474号 valuation_ext 段 `_cl` 变量遮蔽——
  :3829 的 `_cl = _bs0.get('current_liab')`（scalar）覆盖了 :3594 的
  `_cl = features.get('chanlun', {})`（dict），污染 :3929 `_cl.get('trend_direction','')`
  抛错被 except 吞 → `structure_ext={}` 恒空。改名 `_cur_liab` 消除遮蔽。
  需定向重算 8 股验证 structure_ext 真实落库（indicator_status 的 ma/trend + 支撑阻力）。

用法（必须用 backend/.venv/bin/python，daemon 停止态）：
    .venv/bin/python scripts/_480_structure_ext_probe.py
"""
import os
import sys
import time
import shutil
import logging
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('480_struct_ext')

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

EXPECTED_FIELDS = ('support_price', 'resistance_price', 'indicator_status')


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_480_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def _struc(conn, code, date):
    row = conn.execute(
        "SELECT features_json FROM pre_feat_cache WHERE ts_code=? "
        "AND trade_date=? LIMIT 1", (code, date)).fetchone()
    if not row:
        return None
    try:
        f = json.loads(row[0])
    except Exception:
        return None
    return f.get('structure_ext') or {}


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

    logger.info("======== 回算前：structure_ext 现状 ========")
    pre_bad = 0
    for c in CODES:
        d = conn.execute("SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?",
                         (c,)).fetchone()[0]
        se = _struc(conn, c, d)
        empty = (se is None) or (not se) or (se.get('indicator_status') is None)
        if empty:
            pre_bad += 1
        logger.info(f"  {c} date={d} structure_ext={'空' if empty else se}")
    logger.info(f"  回算前恒空股数: {pre_bad}/{len(CODES)}")
    conn.close()

    t0 = time.time()
    n = dd._precompute_raw_features(CODES)
    logger.info(f"[RAW-2] 定向重算 {n} 只，耗时 {time.time()-t0:.1f}s")

    conn = sqlite3.connect(compute_db)
    logger.info("======== 回算后：structure_ext ========")
    ok = True
    for c in CODES:
        d = conn.execute("SELECT MAX(trade_date) FROM pre_feat_cache WHERE ts_code=?",
                         (c,)).fetchone()[0]
        se = _struc(conn, c, d)
        if not se:
            logger.info(f"  {c} date={d} ❌ structure_ext 仍空")
            ok = False
            continue
        missing = [k for k in EXPECTED_FIELDS if se.get(k) in (None, '')]
        if missing:
            logger.info(f"  {c} date={d} ⚠️ 缺字段 {missing} → {se}")
            ok = False
        else:
            logger.info(f"  {c} date={d} ✅ indicator_status='{se['indicator_status']}' "
                        f"support={se['support_price']} resistance={se['resistance_price']}")
    conn.close()

    logger.info("========= 结论 =========")
    logger.info("ALL_OK：8 只 structure_ext 全部真实落库" if ok else "HAS_GAP，见上")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
