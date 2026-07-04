"""
清理 DuckDB as_* 盘中数据表（244号方案 A5）
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
    'as_market_snapshot',
    'as_top_stocks',
    'as_sector_ranking',
    'as_concept_ranking',
    'as_limit_pool',
    'as_minute_kline',
    'as_lhb_detail',
    'as_news',
    'as_index_cached',
    'as_stock_info',
    'as_daily_cached',
]


def clean(days: int = 30):
    """删除指定天数前的 as_* 表数据"""
    import duckdb
    ecm = get_ecm_instance()
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    # 获取所有表名
    existing = ecm.conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchdf()
    existing_tables = set(existing['table_name'].tolist()) if not existing.empty else set()

    for table in AS_TABLES:
        if table not in existing_tables:
            logger.info(f"表不存在，跳过: {table}")
            continue
        try:
            affected = ecm.conn.execute(
                f"DELETE FROM {table} WHERE trade_date < ?", [cutoff]
            ).fetchdf()
            deleted_rows = len(affected) if not affected.empty else 0
            logger.info(f"已清理 {table}: 删除 {deleted_rows} 行（截止 {cutoff}）")
        except (duckdb.CatalogException, duckdb.BinderException):
            # 表可能没有 trade_date 列
            try:
                affected = ecm.conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {table}"
                ).fetchdf()
                count = int(affected['cnt'].iloc[0])
                logger.info(f"表 {table}: {count} 行（无可清理列，跳过）")
            except Exception:
                logger.info(f"表 {table}: 存在但无法清理，跳过")
        except Exception as e:
            logger.warning(f"清理 {table} 失败: {e}")

    ecm.conn.commit()
    logger.info(f"as_* 表清理完成（保留 {days} 天）")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='清理 DuckDB as_* 表')
    parser.add_argument('--days', type=int, default=30, help='保留天数（默认 30）')
    args = parser.parse_args()
    clean(days=args.days)
