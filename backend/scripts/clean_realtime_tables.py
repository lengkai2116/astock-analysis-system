"""
清理盘中实时 PG 表（244号方案 A4）
用法: python scripts/clean_realtime_tables.py
"""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

from app.data.realtime_pg import _get_conn, _put_conn, _pg_pool


def clean():
    if _pg_pool is None:
        logger.warning("realtime_pg 连接池未初始化，跳过")
        return
    conn = _get_conn()
    if not conn:
        logger.warning("realtime_pg 连接不可用，跳过")
        return
    try:
        cur = conn.cursor()
        for table in TABLES:
            try:
                cur.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
                logger.info(f"已删除实时表: {table}")
            except Exception as e:
                logger.warning(f"删除 {table} 失败: {e}")
        conn.commit()
        logger.info("实时表清理完成")
    finally:
        _put_conn(conn)


if __name__ == '__main__':
    clean()
