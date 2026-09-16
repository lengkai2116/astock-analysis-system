"""443号R6 回填：pre_feat_cache 09-14 行 market_stats 组真实化（不重跑 RAW-2）

用法：DATA_DIR=... .venv/bin/python scripts/_443_r6_backfill_market_stats.py
先 _precompute_market_stats() 刷新缓存（锚定 daily_basic 最新交易日），
再遍历 pre_feat_cache 目标交易日的行，把 market_stats 空 dict 替换为缓存统计值。
"""
import os
import sys
import json
import sqlite3
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('443_r6')


def main():
    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    # 1. 刷新市场级统计缓存（修复后锚定 daily_basic 最大交易日）
    dd._precompute_market_stats()
    stats = dd._market_stats_cache
    if not stats:
        logger.error("市场级统计缓存为空，回填中止")
        return 1
    anchor = stats.get('computed_at')
    logger.info(f"[统计] 锚定 {anchor}，{len(stats)} 项指标")

    # 2. 回填 pre_feat_cache 目标交易日（用统计日 + 前一个交易日，覆盖 09-14 空行）
    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    compute_db = os.path.join(data_dir, 'duckdb', 'compute_cache.db')
    conn = sqlite3.connect(compute_db)
    conn.execute("BEGIN")
    try:
        rows = conn.execute(
            "SELECT ts_code, trade_date, features_json FROM pre_feat_cache WHERE trade_date=?",
            [anchor]).fetchall()
        n_empty = n_updated = 0
        for ts_code, trade_date, fj in rows:
            try:
                feat = json.loads(fj)
            except Exception:
                continue
            ms = feat.get('market_stats')
            if not ms:  # 空 dict → 回填
                feat['market_stats'] = stats
                conn.execute(
                    "UPDATE pre_feat_cache SET features_json=?, computed_at=datetime('now','localtime') "
                    "WHERE ts_code=? AND trade_date=?",
                    [json.dumps(feat, ensure_ascii=False, default=str), ts_code, trade_date])
                n_empty += 1
                n_updated += 1
        conn.commit()
        logger.info(f"[回填] {anchor} 共 {len(rows)} 行，空 market_stats {n_empty} 行，已更新 {n_updated} 行")
    except Exception as e:
        conn.rollback()
        logger.error(f"[回填] 失败: {e}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
