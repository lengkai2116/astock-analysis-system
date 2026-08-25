"""
分库初始化脚本（356号方案）
===================================
创建分库架构并迁移数据。

分库架构：
- system_cache.db: 系统元数据
- market_cache.db: 行情数据
- compute_cache.db: 计算结果
- financial_cache.db: 财务数据
- snapshot_cache.db: 快照数据
- history_cache.db: 历史数据
"""

import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# 分库定义（基于实际存在的表）
SHARDING_CONFIG = {
    'system_cache.db': {
        'description': '系统元数据',
        'tables': [
            'cache_metadata', 'concept_cache', 'lhb_cache', 'index_member_cache'
        ]
    },
    'market_cache.db': {
        'description': '行情数据',
        'tables': [
            'daily_cache', 'daily_basic_cache', 'moneyflow_cache',
            'stk_limit_cache', 'minute_kline_cache', 'margin_cache'
        ]
    },
    'compute_cache.db': {
        'description': '计算结果',
        'tables': [
            'indicator_ma', 'indicator_macd', 'indicator_other',
            'factor_cache', 'opportunity_tags_cache',
            'chip_distribution_cache', 'pre_feat_cache'
        ]
    },
    'financial_cache.db': {
        'description': '财务数据',
        'tables': [
            'fina_indicator_cache', 'income_cache', 'balancesheet_cache',
            'cashflow_cache', 'forecast_cache'
        ]
    },
    'snapshot_cache.db': {
        'description': '快照数据',
        'tables': [
            'status_snapshot', 'treemap_snapshot',
            'status_snapshot_history', 'treemap_snapshot_history',
            'tag_history', 'strategy_signal_detail', 'win_rate_cache'
        ]
    },
    'history_cache.db': {
        'description': '历史数据',
        'tables': [
            'adj_factor_cache', 'top10_holders_cache', 'stk_holder_cache',
            'finance_report_cache'
        ]
    }
}


def init_sharding_databases(data_dir: str):
    """初始化分库架构

    Args:
        data_dir: 数据目录
    """
    db_dir = os.path.join(data_dir, 'duckdb')

    # 尝试多个可能的源数据库路径
    possible_source_dbs = [
        os.path.join(db_dir, 'stock_cache.db'),
        os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', 'stock_cache.db'),
        os.path.join(os.path.dirname(__file__), '..', 'data', 'duckdb', 'stock_cache.db'),
    ]

    source_db = None
    for path in possible_source_dbs:
        if os.path.exists(path):
            # 验证数据库是否有效
            try:
                import sqlite3
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                conn.close()
                if tables:
                    source_db = path
                    break
            except Exception:
                continue

    if source_db is None:
        logger.error("找不到有效的源数据库")
        return False

    logger.info(f"开始初始化分库架构...")
    logger.info(f"源数据库: {source_db}")
    logger.info(f"目标目录: {db_dir}")

    # 检查源数据库中的表
    source_conn = sqlite3.connect(source_db)
    source_cursor = source_conn.cursor()
    source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    source_tables = {row[0] for row in source_cursor.fetchall()}
    source_conn.close()
    logger.info(f"源数据库中的表: {len(source_tables)} 个")

    for db_name, config in SHARDING_CONFIG.items():
        db_path = os.path.join(db_dir, db_name)

        try:
            # 创建数据库
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            # 创建表
            source_conn = sqlite3.connect(source_db)
            source_cursor = source_conn.cursor()

            for table_name in config['tables']:
                # 检查源表是否存在
                if table_name not in source_tables:
                    logger.warning(f"源表不存在: {table_name}")
                    continue

                # 获取表结构
                source_cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                create_sql = source_cursor.fetchone()[0]

                # 创建表（使用 IF NOT EXISTS 避免重复创建错误）
                create_sql = create_sql.replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS')
                conn.execute(create_sql)

                # 迁移数据
                source_cursor.execute(f"SELECT * FROM {table_name}")
                rows = source_cursor.fetchall()

                if rows:
                    # 获取列名
                    source_cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [row[1] for row in source_cursor.fetchall()]
                    column_names = ', '.join(columns)
                    placeholders = ', '.join(['?' for _ in columns])

                    conn.executemany(
                        f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})",
                        rows
                    )
                    logger.info(f"迁移表 {table_name}: {len(rows)} 行")

                # 创建索引
                source_cursor.execute(
                    f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{table_name}' AND sql IS NOT NULL"
                )
                for idx_name, idx_sql in source_cursor.fetchall():
                    try:
                        conn.execute(idx_sql)
                    except Exception as e:
                        logger.debug(f"创建索引失败: {idx_name}, {e}")

            conn.commit()
            source_conn.close()
            conn.close()

            logger.info(f"分库创建完成: {db_name}")

        except Exception as e:
            logger.error(f"创建分库失败: {db_name}, {e}")
            # 继续执行其他分库，不返回False

    logger.info("分库架构初始化完成")
    return True


def create_adj_factor_year_tables(data_dir: str):
    """创建adj_factor_cache按年份拆分的表（356号方案大表拆分）

    Args:
        data_dir: 数据目录
    """
    db_path = os.path.join(data_dir, 'duckdb', 'history_cache.db')

    if not os.path.exists(db_path):
        logger.error(f"数据库不存在: {db_path}")
        return False

    logger.info("开始创建adj_factor_cache按年份拆分表...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 获取所有年份
        cursor.execute("SELECT DISTINCT SUBSTR(trade_date, 1, 4) as year FROM adj_factor_cache")
        years = [row[0] for row in cursor.fetchall()]

        for year in years:
            table_name = f'adj_factor_cache_{year}'

            # 创建表
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    ts_code TEXT,
                    trade_date TEXT,
                    adj_factor REAL,
                    cached_at TIMESTAMP,
                    PRIMARY KEY (ts_code, trade_date)
                )
            """)

            # 创建索引
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(trade_date)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ts ON {table_name}(ts_code)")

            # 迁移数据
            cursor.execute(f"INSERT INTO {table_name} SELECT * FROM adj_factor_cache WHERE trade_date LIKE '{year}%'")
            logger.info(f"迁移表 {table_name}: {cursor.rowcount} 行")

        conn.commit()
        logger.info("adj_factor_cache按年份拆分完成")

    except Exception as e:
        logger.error(f"创建按年份拆分表失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


def verify_sharding(data_dir: str):
    """验证分库架构

    Args:
        data_dir: 数据目录

    Returns:
        验证结果
    """
    db_dir = os.path.join(data_dir, 'duckdb')
    results = {}

    for db_name, config in SHARDING_CONFIG.items():
        db_path = os.path.join(db_dir, db_name)

        if not os.path.exists(db_path):
            results[db_name] = {'status': 'missing', 'tables': {}}
            continue

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        tables_status = {}
        for table_name in config['tables']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cursor.fetchone()[0]
                tables_status[table_name] = {'status': 'ok', 'row_count': row_count}
            except Exception as e:
                tables_status[table_name] = {'status': 'error', 'error': str(e)}

        conn.close()

        # 计算总体状态
        all_ok = all(t['status'] == 'ok' for t in tables_status.values())
        results[db_name] = {
            'status': 'ok' if all_ok else 'partial',
            'tables': tables_status
        }

    return results


if __name__ == '__main__':
    # 初始化分库
    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    init_sharding_databases(data_dir)

    # 创建按年份拆分表
    create_adj_factor_year_tables(data_dir)

    # 验证分库
    results = verify_sharding(data_dir)
    for db_name, result in results.items():
        print(f"{db_name}: {result['status']}")
        for table_name, table_result in result['tables'].items():
            if table_result['status'] == 'ok':
                print(f"  {table_name}: {table_result['row_count']} 行")
            else:
                print(f"  {table_name}: {table_result['error']}")
