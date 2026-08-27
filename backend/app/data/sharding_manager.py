"""
分库管理器（356号方案）
===================================
提供分库架构的数据写入和读取支持。

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
from typing import Dict, Optional, List
from datetime import datetime
import threading

logger = logging.getLogger(__name__)


class ShardingManager:
    """分库管理器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # 356号方案：使用项目根目录下的 data 目录
            # 默认路径解析到 backend/data/duckdb/（小副本），应指向项目根目录 data/duckdb/
            data_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')
        self.data_dir = os.path.abspath(data_dir)
        self.db_dir = os.path.join(self.data_dir, 'duckdb')
        
        # 数据库连接缓存
        self._connections: Dict[str, sqlite3.Connection] = {}
        self._write_locks: Dict[str, threading.RLock] = {}
        
        # 表到数据库的映射（356号方案定稿）
        self._table_to_db: Dict[str, str] = {
            # system_cache.db — 系统元数据
            'cache_metadata': 'system_cache.db',
            'concept_cache': 'system_cache.db',
            'lhb_cache': 'system_cache.db',
            'index_member_cache': 'system_cache.db',

            # market_cache.db — 行情数据（356号分库迁移目标）
            'daily_cache': 'market_cache.db',
            'daily_basic_cache': 'market_cache.db',
            'moneyflow_cache': 'market_cache.db',
            'stk_limit_cache': 'market_cache.db',
            'minute_kline_cache': 'market_cache.db',
            'margin_cache': 'market_cache.db',

            # compute_cache.db — 计算结果
            'indicator_ma': 'compute_cache.db',
            'indicator_macd': 'compute_cache.db',
            'indicator_other': 'compute_cache.db',
            'factor_cache': 'compute_cache.db',
            'opportunity_tags_cache': 'compute_cache.db',
            'chip_distribution_cache': 'compute_cache.db',
            'pre_feat_cache': 'compute_cache.db',

            # financial_cache.db — 财务数据
            'fina_indicator_cache': 'financial_cache.db',
            'income_cache': 'financial_cache.db',
            'balancesheet_cache': 'financial_cache.db',
            'cashflow_cache': 'financial_cache.db',
            'forecast_cache': 'financial_cache.db',

            # snapshot_cache.db — 快照/成品数据
            'status_snapshot': 'snapshot_cache.db',
            'treemap_snapshot': 'snapshot_cache.db',
            'status_snapshot_history': 'snapshot_cache.db',
            'treemap_snapshot_history': 'snapshot_cache.db',
            'tag_history': 'snapshot_cache.db',
            'strategy_signal_detail': 'snapshot_cache.db',
            'win_rate_cache': 'snapshot_cache.db',

            # history_cache.db — 历史数据
            'adj_factor_cache': 'history_cache.db',
            'top10_holders_cache': 'history_cache.db',
            'stk_holder_cache': 'history_cache.db',
            'finance_report_cache': 'history_cache.db',

            # 356号方案：总库保留表（不属于任何分库）
            'stocks': None,
            'pipeline_status': None,
            'sync_requests': None,
            'lhb_detail_cache': None,
            'sentiment_pool_cache': None,
            'conditional_win_rate_cache': None,

            'opportunity_advice_history': None,
            'opportunity_library': None,
            'opportunity_status_history': None,
        }

        # 356号方案：按前缀匹配的动态表名（如 adj_factor_cache_2026 → history_cache.db）
        self._prefix_rules = [
            ('adj_factor_cache_', 'history_cache.db'),
        ]
        
    def get_connection(self, db_name: str) -> sqlite3.Connection:
        """获取数据库连接"""
        if db_name not in self._connections:
            db_path = os.path.join(self.db_dir, db_name)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8192")
            conn.execute("PRAGMA busy_timeout=30000")
            self._connections[db_name] = conn
            
        return self._connections[db_name]
        
    def get_write_lock(self, db_name: str) -> threading.RLock:
        """获取写锁"""
        if db_name not in self._write_locks:
            self._write_locks[db_name] = threading.RLock()
        return self._write_locks[db_name]
        
    def get_db_for_table(self, table_name: str) -> Optional[str]:
        """获取表对应的数据库名

        优先精确匹配 → 前缀规则匹配 → None（留在总库）
        返回 None 表示该表不属于任何分库，应留在总库。
        """
        # 1. 精确匹配
        if table_name in self._table_to_db:
            return self._table_to_db[table_name]
        # 2. 前缀规则匹配（如 adj_factor_cache_2026 → history_cache.db）
        for prefix, db_name in self._prefix_rules:
            if table_name.startswith(prefix):
                return db_name
        # 3. 未匹配 → 返回None，留在总库
        return None
        
    def execute_query(self, table_name: str, sql: str, params: list = None):
        """执行查询"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return []  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return cursor.fetchall()
        
    def execute_insert(self, table_name: str, sql: str, params: list = None):
        """执行插入"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        lock = self.get_write_lock(db_name)
        
        with lock:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            conn.commit()
            
    def execute_batch_insert(self, table_name: str, sql: str, params_list: list):
        """执行批量插入"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        lock = self.get_write_lock(db_name)
        
        with lock:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            conn.commit()
            
    def create_table(self, table_name: str, create_sql: str):
        """创建表"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        lock = self.get_write_lock(db_name)
        
        with lock:
            cursor = conn.cursor()
            cursor.execute(create_sql)
            conn.commit()
            logger.info(f"创建表: {table_name} in {db_name}")
            
    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return False  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            [table_name]
        )
        return cursor.fetchone() is not None
        
    def get_table_row_count(self, table_name: str) -> int:
        """获取表行数"""
        db_name = self.get_db_for_table(table_name)
        if db_name is None:
            return 0  # 表在总库，分库管理器不处理
        conn = self.get_connection(db_name)
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
        
    def close_all(self):
        """关闭所有连接"""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
        self._write_locks.clear()


# 全局单例
sharding_manager = ShardingManager()


def init_sharding(data_dir: str = None):
    """初始化分库管理器"""
    global sharding_manager
    if data_dir:
        sharding_manager = ShardingManager(data_dir)
    logger.info("分库管理器初始化完成")
