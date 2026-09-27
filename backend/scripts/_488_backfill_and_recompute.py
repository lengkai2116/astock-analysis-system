"""488-2 落地脚本：涨跌停情绪池回补 + pre_feat(RAW-2) 定向重算（8 股）

背景：488-2 修复采集器签名误用后，需 ① 回补历史交易日涨跌停池（sentiment_pool_cache
全表为空）；② 定向重算 8 股 pre_feat，使 emotion_ext 落库 limit_up_count/sealing_rate
（dim5 情绪温度「涨停家数/封板率」两入参恢复正常）。

用法（必须 daemon 停止态；只读 akshare + 定向写 pre_feat 覆盖同键）：
    .venv/bin/python scripts/_488_backfill_and_recompute.py
"""
import json
import logging
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('488_2')

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']
# 与库内现状 pre_feat 快照一致的目标交易日（探针 market_stats.computed_at=2026-09-24）
TARGET_DATE = '2026-09-24'
BACKFILL_DATES = ['2026-09-22', '2026-09-23', '2026-09-24']


def _compute_db_path() -> str:
    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    return os.path.join(data_dir, 'duckdb', 'compute_cache.db')


def _snapshot_rows(db_path: str) -> str:
    """仅备份受影响 8 股的 pre_feat 行（features_json）——10GB 全库拷贝不必要"""
    out = {}
    try:
        conn = sqlite3.connect(db_path)
        for c in CODES:
            row = conn.execute(
                "SELECT trade_date, features_json FROM pre_feat_cache WHERE ts_code=? "
                "ORDER BY trade_date DESC LIMIT 1", (c,)).fetchone()
            if row:
                out[c] = {'trade_date': row[0], 'features_json': row[1]}
        conn.close()
    except Exception as e:
        logger.warning(f"[备份] 抽样失败({e})——继续（重算为同键 INSERT OR REPLACE）")
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f'_488_prefeat_snapshot_{stamp}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return path


def _ext_of(db_path: str, code: str):
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT trade_date, features_json FROM pre_feat_cache WHERE ts_code=? "
            "ORDER BY trade_date DESC LIMIT 1", (code,)).fetchone()
        conn.close()
        if not row:
            return None, None
        f = json.loads(row[1])
        return row[0], (f.get('emotion_ext') or {})
    except Exception as e:
        return f'ERR {e}', {}


def main():
    from app import create_app
    app = create_app()
    db_path = _compute_db_path()

    with app.app_context():
        # ── 1. 回补涨跌停池 ────────────────────────────────
        from app.data.akshare_collector import backfill_sentiment_pool
        logger.info(f"===== 1. 回补 sentiment_pool_cache：{BACKFILL_DATES} =====")
        n = backfill_sentiment_pool(BACKFILL_DATES)
        logger.info(f"回补写入 {n} 条")

        from app.services.market_sentiment_service import MarketSentimentService
        ms = MarketSentimentService()
        dm = ms.data_manager
        logger.info("===== 2. 回补后校验（行数 / data_available / metrics）=====")
        for d in BACKFILL_DATES:
            df = dm.get_cached_sentiment_pool(d)
            r = ms.get_sentiment_phase(d)
            logger.info(f"  {d}: rows={0 if df is None else len(df)} "
                        f"data_available={r.get('data_available')} phase={r.get('phase')} "
                        f"limit_up={r.get('metrics', {}).get('limit_up_count')} "
                        f"sealing={r.get('metrics', {}).get('sealing_rate')}")

    # ── 3. pre_feat 定向重算（target_date 口径）─────────────
    snap = _snapshot_rows(db_path)
    logger.info(f"===== 3. pre_feat 重算备份：{os.path.basename(snap) if snap else '无'} =====")
    logger.info("===== 重算前 emotion_ext =====")
    for c in CODES:
        d, ext = _ext_of(db_path, c)
        logger.info(f"  {c} date={d} keys={sorted(ext.keys())}")

    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()
    t0 = time.time()
    n2 = dd._precompute_raw_features(CODES, target_date=TARGET_DATE)
    logger.info(f"[RAW-2] 定向重算 {n2} 只（target_date={TARGET_DATE}），耗时 {time.time()-t0:.1f}s")

    logger.info("===== 重算后 emotion_ext（488-2 目标：含 limit_up_count/sealing_rate）=====")
    ok = True
    for c in CODES:
        d, ext = _ext_of(db_path, c)
        has = ('limit_up_count' in ext) and ('sealing_rate' in ext)
        ok = ok and has
        logger.info(f"  {c} date={d} limit_up={ext.get('limit_up_count')} "
                    f"sealing={ext.get('sealing_rate')} temp={ext.get('emotion_temperature')}")
    logger.info("========= 结论 =========")
    logger.info("ALL_OK" if ok else "HAS_GAP：仍有股缺 limit_up_count/sealing_rate")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
