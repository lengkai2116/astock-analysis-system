"""
清理 as_* 盘中数据表（250号方案 — SQLite WAL 版）
用法: python scripts/clean_as_tables.py
30 天以上数据将被删除
"""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

from app.data.enhanced_cache_manager import get_ecm_instance

AS_TABLES = [
    'as_market_snapshot', 'as_top_stocks', 'as_sector_ranking',
    'as_concept_ranking', 'as_limit_pool', 'as_minute_kline',
    'as_lhb_detail', 'as_news',
]


def clean(days: int = 30):
    """删除指定天数前的 as_* 表数据"""
    ecm = get_ecm_instance()
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # 获取所有表名
    existing = ecm.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    existing_tables = set(r[0] for r in existing)

    for table in AS_TABLES:
        if table not in existing_tables:
            logger.info(f"表不存在，跳过: {table}")
            continue
        try:
            ecm.conn.execute(f"DELETE FROM {table} WHERE trade_date < ?", [cutoff])
            ecm.conn.commit()
            logger.info(f"已清理 {table}: 条件 trade_date < {cutoff}")
        except Exception:
            try:
                cnt = ecm.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                logger.info(f"表 {table}: {cnt} 行（无可清理列，跳过）")
            except Exception:
                logger.info(f"表 {table}: 存在但无法清理，跳过")

    logger.info(f"as_* 表清理完成（保留 {days} 天）")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='清理 as_* 表')
    parser.add_argument('--days', type=int, default=30, help='保留天数（默认 30）')
    args = parser.parse_args()
    clean(days=args.days)
