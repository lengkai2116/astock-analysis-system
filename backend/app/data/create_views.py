"""
分库视图创建（356号方案）
===================================
创建统一视图，提供跨库查询支持。

视图：
  adj_factor_view: 复权因子统一视图（合并按年份拆分的 adj_factor_cache_YYYY 表）

**500号批次6（2026-09-30）**：原模块含 3 个视图函数，核查后仅 `create_adj_factor_view`
为活代码——其构建的 `adj_factor_view` 被 `EnhancedCacheManager.get_cached_adj_factor`
生产读取（分库优先路径）。其余 4 个函数 `create_daily_data_view` /
`create_financial_data_view` / `create_all_views` / `drop_all_views` 全仓零引用（死代码），
已删除；`daily_data_view` / `financial_data_view` 亦无任何消费方。故本模块保留。
"""

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)


def create_adj_factor_view(data_dir: str):
    """创建复权因子统一视图

    合并 adj_factor_cache_2001 ~ adj_factor_cache_2026 为一个视图。
    该视图被 `EnhancedCacheManager.get_cached_adj_factor` 生产读取（活路径）。
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
