"""
419号方案：indicator_other 补 trade_date 索引（幂等）
====================================================
修复项：
- indicator_other 表缺 trade_date 索引 → BociasiQuadrantAnalyzer 回退查询
  `WHERE trade_date=?` 全表扫描 617 万行（单次 5.2s）。
- 幂等：sqlite_master 检查存在性，可重复执行。

主库: data/duckdb/stock_cache.db
分库: data/duckdb/compute_cache.db
"""
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

DB_PATHS = [
    (ROOT / 'data' / 'duckdb' / 'stock_cache.db', '主库 stock_cache.db'),
    (ROOT / 'data' / 'duckdb' / 'compute_cache.db', '分库 compute_cache.db'),
]

# 需要补 trade_date 索引的表（key: 表名，value: 索引名）
INDEX_TARGETS = {
    'indicator_other': 'idx_ind_other_date',
}


def ensure_trade_date_index(conn: sqlite3.Connection, table: str, index_name: str):
    """幂等建 trade_date 索引：已存在则跳过"""
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", [index_name]
        ).fetchone()
        if exists:
            logger.info(f"  {table} 索引 {index_name} 已存在，跳过")
            return
        conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}(trade_date)")
        logger.info(f"  {table} 建索引 {index_name}(trade_date)")
    except Exception as e:
        logger.warning(f"  {table} 建索引失败: {e}")


def migrate():
    for db_path, name in DB_PATHS:
        if not db_path.exists():
            logger.warning(f"{name} 不存在: {db_path}，跳过")
            continue
        logger.info(f"处理 {name}: {db_path}")
        conn = sqlite3.connect(db_path)
        try:
            for table, index_name in INDEX_TARGETS.items():
                ensure_trade_date_index(conn, table, index_name)
            conn.commit()
        except Exception as e:
            logger.error(f"{name} 迁移失败: {e}")
            conn.rollback()
        finally:
            conn.close()
    logger.info("迁移完成")


if __name__ == '__main__':
    migrate()
