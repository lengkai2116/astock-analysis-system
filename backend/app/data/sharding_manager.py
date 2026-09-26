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

import logging
import os
import sqlite3
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 未登记路由表告警去重集合（426号 S1/D8：未登记表操作一次性告警，防刷屏）
_unmapped_warned: set[str] = set()


def _warn_unmapped(table: str, op: str):
    """未登记路由的表执行 {op} 时告警（一次性去重）"""
    key = f'{table}:{op}'
    if key in _unmapped_warned:
        return
    _unmapped_warned.add(key)
    logger.warning(f"未登记分库路由的表 {op} 被跳过: {table}（请登记 _table_to_db 或确认归属）")


# 每库 PRAGMA（356号 §3 规则14 + 426号 S4/D2：cache_size 与 journal_size_limit 按库设定）
# 注：busy_timeout 统一保持 30000（2026-08-12 方案B 为修 P4 批量写锁冲突特意提高，
#     设计值 10s 会回归锁冲突，不采用）。
_DB_PRAGMAS = {
    'market_cache.db': {'cache_size': -32768, 'journal_size_limit': 268435456},   # 32MB / 256MB
    'compute_cache.db': {'cache_size': -16384, 'journal_size_limit': 16777216},   # 16MB / 16MB
    # 其余分库默认 8MB cache / 8MB journal_size_limit
}


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

        # 表到数据库的映射（356号方案定稿）；值为 None 表示显式总库表
        self._table_to_db: Dict[str, Optional[str]] = {
            # system_cache.db — 系统元数据
            # 426号 S2/D4：cache_metadata 实际读写全走总库（ECM conn），
            # system_cache.db 侧为历史迁移残留（3 行陈旧含 test_key）——
            # 注销路由改归总库（None），system 侧副本在数据整改时 DROP。
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
            'pre_feat_cache': 'compute_cache.db',
            # 426号 P1-2：三表补登 compute_cache.db 路由（原未登记→读写落总库空壳/
            # pattern_score 走 compute_conn 硬编码；读方 _query_shard 降级总库读空）
            'market_stats_cache': 'compute_cache.db',
            'sector_heat_cache': 'compute_cache.db',
            'pattern_score_cache': 'compute_cache.db',
            # 438号缺口③：个股相对强弱持久化（双基准超额收益）→ compute_cache.db 计算结果
            'relative_strength_cache': 'compute_cache.db',
            # 481号 ③：个股行业位置持久化（近20日收益行业排名/百分位）→ compute_cache.db
            'industry_position_cache': 'compute_cache.db',

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
            'strategy_signal_detail': 'snapshot_cache.db',
            'win_rate_cache': 'snapshot_cache.db',

            # market_snapshot.db — 盘中实时快照（356号§3.3 独立库，ECM snapshot_conn 直连；
            # 426号 S7/D5：补登路由消除"未登记"告警，读写仍走 snapshot_conn 单路径）
            'as_market_snapshot': 'market_snapshot.db',
            # 426号 落地复核修正：as_sector_ranking 为 akshare_collector 活跃写入的
            # 盘中板块排名（同 as_market_snapshot 家族）——未登记时 426 S1 会告警跳过
            # 致静默丢写（总库 0 行）、读取降级总库读空；补登同一实时快照库
            'as_sector_ranking': 'market_snapshot.db',

            # history_cache.db — 历史数据
            'adj_factor_cache': 'history_cache.db',
            'top10_holders_cache': 'history_cache.db',
            'stk_holder_cache': 'history_cache.db',
            'finance_report_cache': 'history_cache.db',
            # 484号（448 R）：股权质押/股东增减持（股东行为参考数据，与 top10/stk_holder 同族）
            'pledge_stat_cache': 'history_cache.db',
            'stk_holdertrade_cache': 'history_cache.db',

            # 356号方案：总库保留表（不属于任何分库）
            # 426号 落地复核修正（stocks）：实际表在 data/app.db（SQLAlchemy ORM 管理，
            # 读写经 app.db 直连/SQLAlchemy，不经 sharding_manager 路由）——此处登记
            # None 仅为"不属于分库"的语义标记，勿据此在总库查找 stocks 表
            'stocks': None,
            'pipeline_status': None,
            'sync_requests': None,
            'lhb_detail_cache': None,
            'sentiment_pool_cache': None,
            'conditional_win_rate_cache': None,
            'cache_metadata': None,
            # 428 P2-1：显式主库表登记（写路径直连 ECM conn/总库，非走分库路由）。
            # 此前未登记被 list_unmapped_tables 启动自检误报为"未登记表"。
            'qa_audit_log': None,           # WriteGateway/stg_quality 写总库
            'watchlist_status_diff': None,  # OUT 阶段写总库

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
            conn.execute("PRAGMA busy_timeout=30000")    # 30s（2026-08-12方案B，见模块注释）
            # 426号 S4/D2：cache_size 与 journal_size_limit 按库设定（356号 §3 规则14）
            pr = _DB_PRAGMAS.get(db_name, {'cache_size': -8192, 'journal_size_limit': 8388608})
            conn.execute(f"PRAGMA cache_size={pr['cache_size']}")
            conn.execute(f"PRAGMA journal_size_limit={pr['journal_size_limit']}")
            self._connections[db_name] = conn
            # 424号 P2-1：snapshot_cache.db 补索引（356号 §3.2.5 设计未落地）
            if db_name == 'snapshot_cache.db':
                self._ensure_snapshot_indexes(conn)

        return self._connections[db_name]

    def _ensure_snapshot_indexes(self, conn: sqlite3.Connection):
        """424号 P2-1：为 snapshot_cache.db 高频查询表补索引（356号 §3.2.5）

        status_snapshot / strategy_signal_detail / treemap_snapshot /
        tag_history / *_history 原仅主键自增索引，API 按 ts_code/日期查询全表扫描。
        """
        index_sqls = [
            "CREATE INDEX IF NOT EXISTS idx_status_ts ON status_snapshot(ts_code, snapshot_date)",
            "CREATE INDEX IF NOT EXISTS idx_signal_ts ON strategy_signal_detail(ts_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_treemap_ind ON treemap_snapshot(industry)",
            "CREATE INDEX IF NOT EXISTS idx_status_hist_date ON status_snapshot_history(snapshot_date)",
            "CREATE INDEX IF NOT EXISTS idx_treemap_hist_date ON treemap_snapshot_history(snapshot_date)",
        ]
        for sql in index_sqls:
            try:
                conn.execute(sql)
            except Exception as e:
                logger.debug(f"snapshot_cache 索引创建失败: {e}")
        conn.commit()

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

    def is_registered(self, table_name: str) -> bool:
        """表是否已登记路由（精确匹配或前缀规则命中；显式总库表也算已登记）

        426号 S1/D8：解决 get_db_for_table 返回 None 的二义性——显式总库表
        （_table_to_db 值为 None）与完全未登记表都返回 None，调用方据此区分。
        """
        if table_name in self._table_to_db:
            return True
        for prefix, _db in self._prefix_rules:
            if table_name.startswith(prefix):
                return True
        return False

    def list_unmapped_tables(self, total_conn=None) -> list:
        """扫描全部分库 + 总库，返回未登记路由的表清单（启动自检打印用）

        total_conn: 总库（stock_cache.db）连接；None 时跳过总库扫描。
        含前缀规则动态表（adj_factor_cache_YYYY）判定；system_cache.db 等
        登记分库表不算未登记。
        """
        unmapped = set()
        for db_name in self.get_all_db_names():
            try:
                conn = self.get_connection(db_name)
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'").fetchall()
                for (t,) in rows:
                    if not self.is_registered(t):
                        unmapped.add(t)
            except Exception as e:
                logger.warning(f"扫描 {db_name} 未登记表失败: {e}")
        if total_conn is not None:
            try:
                rows = total_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'").fetchall()
                for (t,) in rows:
                    if not self.is_registered(t):
                        unmapped.add(t)
            except Exception as e:
                logger.warning(f"扫描总库未登记表失败: {e}")
        return sorted(unmapped)

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
            if not self.is_registered(table_name):
                _warn_unmapped(table_name, 'execute_insert')  # 426号 S1：未登记表不再静默跳过
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
            if not self.is_registered(table_name):
                _warn_unmapped(table_name, 'execute_batch_insert')  # 426号 S1
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
            if not self.is_registered(table_name):
                _warn_unmapped(table_name, 'create_table')  # 426号 S1
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

    def get_all_db_names(self) -> list:
        """获取全部分库名（去重，不含总库）

        424号P0-2：WAL 治理需遍历所有分库执行 checkpoint 与大小监控。
        """
        dbs = set()
        for db_name in self._table_to_db.values():
            if db_name:
                dbs.add(db_name)
        return sorted(dbs)

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
