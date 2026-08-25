"""
数据存盘点机制（356号方案第六章）
===================================
提供定期数据盘点和质量检查功能。

盘点内容：
1. 数据完整性盘点
2. 数据时效性盘点
3. 数据重复盘点
4. 存储空间盘点
5. 索引效率盘点
"""

import os
import sqlite3
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DataInventory:
    """数据存盘点管理器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
        self.data_dir = os.path.abspath(data_dir)
        self.db_dir = os.path.join(self.data_dir, 'duckdb')

    def run_full_inventory(self) -> Dict:
        """执行全量数据盘点"""
        logger.info("开始全量数据盘点...")

        results = {
            'timestamp': datetime.now().isoformat(),
            'databases': {},
            'summary': {}
        }

        # 盘点所有分库
        db_files = [
            'stock_cache.db',
            'system_cache.db',
            'market_cache.db',
            'compute_cache.db',
            'financial_cache.db',
            'snapshot_cache.db',
            'history_cache.db'
        ]

        total_tables = 0
        total_rows = 0
        total_size = 0

        for db_name in db_files:
            db_path = os.path.join(self.db_dir, db_name)
            if os.path.exists(db_path):
                db_result = self._inventory_database(db_path, db_name)
                results['databases'][db_name] = db_result
                total_tables += db_result.get('table_count', 0)
                total_rows += db_result.get('total_rows', 0)
                total_size += db_result.get('db_size', 0)

        results['summary'] = {
            'total_databases': len([d for d in db_files if os.path.exists(os.path.join(self.db_dir, d))]),
            'total_tables': total_tables,
            'total_rows': total_rows,
            'total_size_mb': round(total_size / 1024 / 1024, 2)
        }

        logger.info(f"全量数据盘点完成: {results['summary']}")
        return results

    def _inventory_database(self, db_path: str, db_name: str) -> Dict:
        """盘点单个数据库"""
        result = {
            'db_name': db_name,
            'db_path': db_path,
            'tables': {},
            'table_count': 0,
            'total_rows': 0,
            'db_size': 0
        }

        try:
            # 获取数据库大小
            result['db_size'] = os.path.getsize(db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            for table_name in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row_count = cursor.fetchone()[0]

                    # 获取表结构信息
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [row[1] for row in cursor.fetchall()]

                    # 获取索引信息
                    cursor.execute(f"PRAGMA index_list({table_name})")
                    indexes = [row[1] for row in cursor.fetchall()]

                    result['tables'][table_name] = {
                        'row_count': row_count,
                        'column_count': len(columns),
                        'index_count': len(indexes),
                        'columns': columns
                    }
                    result['total_rows'] += row_count
                except Exception as e:
                    logger.debug(f"盘点表 {table_name} 失败: {e}")

            result['table_count'] = len(tables)
            conn.close()

        except Exception as e:
            logger.error(f"盘点数据库 {db_name} 失败: {e}")

        return result

    def check_data_timeliness(self) -> Dict:
        """检查数据时效性"""
        logger.info("检查数据时效性...")

        results = {
            'timestamp': datetime.now().isoformat(),
            'tables': {}
        }

        # 检查核心数据表的时效性
        core_tables = {
            'market_cache.db': ['daily_cache', 'daily_basic_cache', 'moneyflow_cache', 'stk_limit_cache'],
            'history_cache.db': ['adj_factor_cache'],
            'financial_cache.db': ['fina_indicator_cache', 'income_cache']
        }

        for db_name, tables in core_tables.items():
            db_path = os.path.join(self.db_dir, db_name)
            if not os.path.exists(db_path):
                continue

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            for table_name in tables:
                try:
                    cursor.execute(f"SELECT MAX(trade_date) FROM {table_name}")
                    latest_date = cursor.fetchone()[0]

                    if latest_date:
                        # 计算滞后天数
                        if isinstance(latest_date, str):
                            latest_date = datetime.strptime(latest_date, '%Y-%m-%d')
                        days_lag = (datetime.now() - latest_date).days

                        results['tables'][table_name] = {
                            'latest_date': str(latest_date),
                            'days_lag': days_lag,
                            'status': 'ok' if days_lag <= 7 else 'stale'
                        }
                except Exception as e:
                    logger.debug(f"检查表 {table_name} 时效性失败: {e}")

            conn.close()

        logger.info(f"数据时效性检查完成: {len(results['tables'])} 个表")
        return results

    def check_data_duplicates(self, table_name: str = 'daily_cache') -> Dict:
        """检查数据重复"""
        logger.info(f"检查数据重复: {table_name}...")

        result = {
            'table_name': table_name,
            'duplicate_count': 0,
            'duplicates': []
        }

        # 确定数据库
        db_name = 'market_cache.db' if table_name in ['daily_cache', 'daily_basic_cache', 'moneyflow_cache'] else 'stock_cache.db'
        db_path = os.path.join(self.db_dir, db_name)

        if not os.path.exists(db_path):
            return result

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            # 检查重复数据
            cursor.execute(f"""
                SELECT ts_code, trade_date, COUNT(*) as cnt
                FROM {table_name}
                GROUP BY ts_code, trade_date
                HAVING cnt > 1
                LIMIT 100
            """)
            duplicates = cursor.fetchall()

            result['duplicate_count'] = len(duplicates)
            result['duplicates'] = [
                {'ts_code': row[0], 'trade_date': row[1], 'count': row[2]}
                for row in duplicates
            ]

        except Exception as e:
            logger.error(f"检查数据重复失败: {e}")
        finally:
            conn.close()

        logger.info(f"数据重复检查完成: {result['duplicate_count']} 个重复")
        return result

    def check_storage_space(self) -> Dict:
        """检查存储空间"""
        logger.info("检查存储空间...")

        results = {
            'timestamp': datetime.now().isoformat(),
            'databases': {},
            'total_size_mb': 0
        }

        for db_name in os.listdir(self.db_dir):
            if db_name.endswith('.db'):
                db_path = os.path.join(self.db_dir, db_name)
                try:
                    size = os.path.getsize(db_path)
                    results['databases'][db_name] = {
                        'size_bytes': size,
                        'size_mb': round(size / 1024 / 1024, 2)
                    }
                    results['total_size_mb'] += size / 1024 / 1024
                except Exception as e:
                    logger.debug(f"获取数据库 {db_name} 大小失败: {e}")

        results['total_size_mb'] = round(results['total_size_mb'], 2)
        logger.info(f"存储空间检查完成: 总大小 {results['total_size_mb']} MB")
        return results

    def generate_inventory_report(self) -> str:
        """生成数据盘点报告"""
        results = self.run_full_inventory()
        timeliness = self.check_data_timeliness()
        space = self.check_storage_space()

        report = f"""
# 数据存盘点报告

生成时间: {results['timestamp']}

## 一、数据库概况

| 数据库 | 表数量 | 总行数 | 大小(MB) |
|--------|--------|--------|----------|
"""
        for db_name, db_result in results['databases'].items():
            report += f"| {db_name} | {db_result['table_count']} | {db_result['total_rows']:,} | {db_result['db_size']/1024/1024:.2f} |\n"

        report += f"""
**总计**: {results['summary']['total_databases']} 个数据库, {results['summary']['total_tables']} 个表, {results['summary']['total_rows']:,} 行, {results['summary']['total_size_mb']} MB

## 二、数据时效性

| 表名 | 最新日期 | 滞后天数 | 状态 |
|------|----------|----------|------|
"""
        for table_name, info in timeliness['tables'].items():
            report += f"| {table_name} | {info['latest_date']} | {info['days_lag']} | {info['status']} |\n"

        report += f"""
## 三、存储空间

| 数据库 | 大小(MB) |
|--------|----------|
"""
        for db_name, info in space['databases'].items():
            report += f"| {db_name} | {info['size_mb']} |\n"

        report += f"\n**总大小**: {space['total_size_mb']} MB\n"

        return report


# 全局单例
data_inventory = DataInventory()


def run_inventory():
    """执行数据盘点"""
    return data_inventory.run_full_inventory()


def generate_report():
    """生成盘点报告"""
    return data_inventory.generate_inventory_report()
