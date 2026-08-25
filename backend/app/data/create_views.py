"""
分库视图创建脚本（356号方案）
===================================
创建统一视图，提供跨库查询支持。

视图设计：
1. adj_factor_view: 复权因子统一视图（合并按年份拆分的表）
2. daily_data_view: 日线数据统一视图
3. financial_data_view: 财务数据统一视图
"""

import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def create_adj_factor_view(data_dir: str):
    """创建复权因子统一视图

    合并 adj_factor_cache_2001 ~ adj_factor_cache_2026 为一个视图
    """
    db_path = os.path.join(data_dir, 'duckdb', 'history_cache.db')

    if not os.path.exists(db_path):
        logger.error(f"数据库不存在: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 删除旧视图（如果存在）
        cursor.execute("DROP VIEW IF EXISTS adj_factor_view")

        # 获取所有年份表
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'adj_factor_cache_%'
        """)
        year_tables = [row[0] for row in cursor.fetchall()]

        if not year_tables:
            logger.warning("没有找到按年份拆分的adj_factor_cache表")
            return False

        # 按年份排序
        year_tables.sort()

        # 创建UNION ALL视图
        view_sql = "CREATE VIEW adj_factor_view AS\n"
        view_sql += " UNION ALL\n".join([f"SELECT * FROM {table}" for table in year_tables])

        cursor.execute(view_sql)
        conn.commit()

        logger.info(f"创建复权因子统一视图: {len(year_tables)} 个年份表")
        return True

    except Exception as e:
        logger.error(f"创建复权因子视图失败: {e}")
        return False
    finally:
        conn.close()


def create_daily_data_view(data_dir: str):
    """创建日线数据统一视图

    合并 daily_cache 为统一视图（支持按年份拆分后使用）
    """
    db_path = os.path.join(data_dir, 'duckdb', 'market_cache.db')

    if not os.path.exists(db_path):
        logger.error(f"数据库不存在: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 删除旧视图（如果存在）
        cursor.execute("DROP VIEW IF EXISTS daily_data_view")

        # 检查是否有按年份拆分的表
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'daily_cache_%'
        """)
        year_tables = [row[0] for row in cursor.fetchall()]

        if year_tables:
            # 有按年份拆分的表，创建UNION ALL视图
            year_tables.sort()
            view_sql = "CREATE VIEW daily_data_view AS\n"
            view_sql += " UNION ALL\n".join([f"SELECT * FROM {table}" for table in year_tables])
            cursor.execute(view_sql)
            logger.info(f"创建日线数据统一视图: {len(year_tables)} 个年份表")
        else:
            # 没有按年份拆分的表，直接使用daily_cache
            cursor.execute("CREATE VIEW daily_data_view AS SELECT * FROM daily_cache")
            logger.info("创建日线数据统一视图: 使用原始daily_cache表")

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"创建日线数据视图失败: {e}")
        return False
    finally:
        conn.close()


def create_financial_data_view(data_dir: str):
    """创建财务数据统一视图

    合并财务相关表为统一视图
    """
    db_path = os.path.join(data_dir, 'duckdb', 'financial_cache.db')

    if not os.path.exists(db_path):
        logger.error(f"数据库不存在: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 删除旧视图（如果存在）
        cursor.execute("DROP VIEW IF EXISTS financial_data_view")

        # 创建财务数据统一视图（合并多个财务表）
        cursor.execute("""
            CREATE VIEW financial_data_view AS
            SELECT
                i.ts_code,
                i.trade_date,
                i.roe,
                i.roa,
                i.grossprofit_margin,
                i.netprofit_margin,
                inc.revenue,
                inc.n_income,
                bs.total_assets,
                bs.total_liab,
                cf.n_cashflow_act
            FROM fina_indicator_cache i
            LEFT JOIN income_cache inc ON i.ts_code = inc.ts_code AND i.trade_date = inc.end_date
            LEFT JOIN balancesheet_cache bs ON i.ts_code = bs.ts_code AND i.trade_date = bs.end_date
            LEFT JOIN cashflow_cache cf ON i.ts_code = cf.ts_code AND i.trade_date = cf.end_date
        """)

        conn.commit()
        logger.info("创建财务数据统一视图")
        return True

    except Exception as e:
        logger.error(f"创建财务数据视图失败: {e}")
        return False
    finally:
        conn.close()


def create_all_views(data_dir: str):
    """创建所有统一视图"""
    logger.info("开始创建统一视图...")

    results = {
        'adj_factor_view': create_adj_factor_view(data_dir),
        'daily_data_view': create_daily_data_view(data_dir),
        'financial_data_view': create_financial_data_view(data_dir)
    }

    success_count = sum(1 for v in results.values() if v)
    logger.info(f"统一视图创建完成: {success_count}/{len(results)} 成功")

    return results


def drop_all_views(data_dir: str):
    """删除所有统一视图"""
    views = ['adj_factor_view', 'daily_data_view', 'financial_data_view']

    for view_name in views:
        for db_name in ['history_cache.db', 'market_cache.db', 'financial_cache.db']:
            db_path = os.path.join(data_dir, 'duckdb', db_name)
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.debug(f"删除视图 {view_name} 失败: {e}")

    logger.info("统一视图删除完成")


if __name__ == '__main__':
    # 创建所有视图
    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    create_all_views(data_dir)
