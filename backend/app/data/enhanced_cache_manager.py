"""
EnhancedCacheManager — SQLite WAL 缓存管理器（250号方案）
=========================================================
替代 DuckDB 作为盘后日线缓存层。SQLite WAL 模式：
- 并发读不阻塞写（解决了 DuckDB 的文件锁问题）
- Python sqlite3 标准库内置，零额外依赖
- 行式存储对点查（WHERE ts_code=?）比列式更快

设计原则：
- `get_ecm_instance()` 全局单例（杜绝多实例锁争抢）
- 写入串行化（_write_lock），读取不锁
- 与 DuckDB 版本接口完全兼容（调用方无感知）
"""

import logging
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

import pandas as pd

from .memory_cache import TieredMemoryCache

logger = logging.getLogger(__name__)

# 全局 ECM 单例
_ecm_instance = None
_ecm_lock = threading.Lock()


def get_ecm_instance() -> 'EnhancedCacheManager':
    global _ecm_instance
    if _ecm_instance is None:
        with _ecm_lock:
            if _ecm_instance is None:
                _ecm_instance = EnhancedCacheManager()
    return _ecm_instance


class EnhancedCacheManager:
    """SQLite WAL 缓存管理器（取代 DuckDB）"""

    def __init__(self):
        self._lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._snapshot_write_lock = threading.RLock()
        self.memory_cache = TieredMemoryCache()

        data_dir = os.getenv('DATA_DIR') or (
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), 'data')
        )
        db_dir = os.path.join(data_dir, 'duckdb')  # 复用原有目录
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, 'stock_cache.db')

        # SQLite WAL 模式：读不阻塞写，写不阻塞读
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-8192")     # 8MB 缓存
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA busy_timeout=30000")    # 30s（2026-08-12方案B：覆盖长事务窗口，原5s短于P4批量事务致锁冲突）
        self.conn.execute("PRAGMA journal_size_limit=1048576")  # 2026-08-20：WAL上限1GB，防止无限膨胀

        # 2026-08-11 根治：WAL 读写分离连接——sqlite3 单连接跨线程并发读写不安全
        # （多线程 compute_batch 工作线程读 + 主线程写共享 conn，事务交错致写库丢失）。
        # WAL 模式下多连接并发读/写天然安全（读不阻塞写、写不阻塞读），
        # 读路径（_query_df/get_*）统一走 read_conn，写路径（cache_*/write_*）走 conn（_write_lock 串行化）。
        self.read_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.read_conn.execute("PRAGMA journal_mode=WAL")
        self.read_conn.execute("PRAGMA synchronous=NORMAL")
        self.read_conn.execute("PRAGMA cache_size=-8192")
        self.read_conn.execute("PRAGMA temp_store=MEMORY")
        self.read_conn.execute("PRAGMA busy_timeout=30000")

        self._init_tables()

        # 独立快照数据库（§3.1 物理存储方案：写入锁竞争、故障隔离、文件大小管理）
        self.snapshot_db_path = os.path.join(db_dir, 'market_snapshot.db')
        self.snapshot_conn = sqlite3.connect(self.snapshot_db_path, check_same_thread=False)
        self.snapshot_conn.execute("PRAGMA journal_mode=WAL")
        self.snapshot_conn.execute("PRAGMA synchronous=NORMAL")
        self.snapshot_conn.execute("PRAGMA cache_size=-8192")
        self.snapshot_conn.execute("PRAGMA temp_store=MEMORY")
        self.snapshot_conn.execute("PRAGMA busy_timeout=30000")
        self._init_snapshot_tables()

        # 356号方案：计算分库（pattern_score_cache 等计算结果表）
        self.compute_db_path = os.path.join(db_dir, 'compute_cache.db')
        self.compute_conn = sqlite3.connect(self.compute_db_path, check_same_thread=False)
        self.compute_conn.execute("PRAGMA journal_mode=WAL")
        self.compute_conn.execute("PRAGMA synchronous=NORMAL")
        self.compute_conn.execute("PRAGMA cache_size=-16384")  # 16MB
        self.compute_conn.execute("PRAGMA temp_store=MEMORY")
        self.compute_conn.execute("PRAGMA busy_timeout=30000")
        self.compute_read_conn = sqlite3.connect(self.compute_db_path, check_same_thread=False)
        self.compute_read_conn.execute("PRAGMA journal_mode=WAL")
        self.compute_read_conn.execute("PRAGMA synchronous=NORMAL")
        self.compute_read_conn.execute("PRAGMA cache_size=-16384")
        self.compute_read_conn.execute("PRAGMA temp_store=MEMORY")
        self.compute_read_conn.execute("PRAGMA busy_timeout=30000")
        self._init_compute_tables()
        self._migrate_pattern_score_to_compute_db()  # 迁移现有数据到 compute_cache.db

        self.cache_stats = {
            'hits_duckdb': 0,  # 保留旧字段名兼容
            'misses': 0,
            'total_requests': 0
        }

    # ── 工具方法 ─────────────────────────────────────────────

    def _migrate_missing_columns(self, table: str, columns: list) -> None:
        """320号 L2/L3：幂等补齐表缺失列（CREATE IF NOT EXISTS 不修改已存在表）

        Args:
            table: 表名
            columns: [(列名, 类型), ...]
        """
        try:
            exist = {r[1] for r in self.conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            for col, ctype in columns:
                if col not in exist:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
                    logger.info(f"表 {table} 补列 {col} {ctype}")
            self.conn.commit()
        except Exception as e:
            logger.warning(f"迁移 {table} 补列失败: {e}")

    def _insert_from_df(self, table: str, df: pd.DataFrame):
        """将 DataFrame 批量写入 SQLite 表（动态列名，兼容列顺序差异）

        356号方案（重构）：单写直路由
        - 分库表 → 直接写入对应分库（不再双写 stock_cache.db）
        - 非分库表 → 写入总库 stock_cache.db
        """
        if df.empty:
            return

        # 数据格式修订（355号方案规则1-3）
        df = self._validate_and_fix_data_format(df)

        cols = list(df.columns)
        col_list = ', '.join(f'"{c}"' for c in cols)
        placeholders = ', '.join(['?' for _ in cols])
        rows = [tuple(r[c] for c in cols) for _, r in df.iterrows()]

        # 356号方案：路由到正确的数据库
        try:
            from app.data.sharding_manager import sharding_manager
            db_name = sharding_manager.get_db_for_table(table)
        except Exception:
            db_name = None

        if db_name:
            # 分库表 → 直接写分库
            try:
                # 检查分库表是否存在，不存在则自动建表
                try:
                    shard_col_rows = sharding_manager.execute_query(
                        table, f"PRAGMA table_info({table})")
                    shard_cols = {row[1] for row in shard_col_rows} if shard_col_rows else set()
                except Exception:
                    shard_cols = set()

                if not shard_cols:
                    # 从总库复制表结构到分库
                    try:
                        main_sql = self.conn.execute(
                            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
                        ).fetchone()
                        if main_sql and main_sql[0]:
                            create_sql = main_sql[0].replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS')
                            sharding_manager.get_connection(db_name).execute(create_sql)
                            sharding_manager.get_connection(db_name).commit()
                            shard_col_rows = sharding_manager.execute_query(
                                table, f"PRAGMA table_info({table})")
                            shard_cols = {row[1] for row in shard_col_rows} if shard_col_rows else set()
                            logger.info(f"分库自动建表: {table} on {db_name}")
                    except Exception as e:
                        logger.warning(f"分库自动建表失败: {table} on {db_name}: {e}")

                if shard_cols and not shard_cols.issuperset(set(cols)):
                    # 分库列是总库列的子集，过滤后写入
                    keep = [c for c in cols if c in shard_cols]
                    if keep:
                        shard_rows = [tuple(r[c] for c in keep) for _, r in df.iterrows()]
                        shard_col_list = ', '.join(f'"{c}"' for c in keep)
                        shard_ph = ', '.join(['?' for _ in keep])
                        sharding_manager.execute_batch_insert(
                            table, f"INSERT OR REPLACE INTO {table} ({shard_col_list}) VALUES ({shard_ph})", shard_rows)
                elif shard_cols:
                    sharding_manager.execute_batch_insert(
                        table, f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})", rows)
                else:
                    logger.warning(f"分库表不存在且自动建表失败: {table} on {db_name}，跳过写入")
            except Exception as e:
                logger.warning(f"分库写入失败: {table} on {db_name}, {type(e).__name__}: {e}")
        else:
            # 非分库表 → 写入总库 stock_cache.db
            try:
                self.conn.executemany(
                    f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
                    rows
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(f"总库写入失败: {table}, {type(e).__name__}: {e}")

    def _validate_and_fix_data_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据格式验证和修订（355号方案规则1-3）

        规则1：日期格式统一为 YYYY-MM-DD
        规则2：股票代码格式统一为 XXX.SH/SZ/BJ
        规则3：列名规范（小写+下划线）
        """
        if df.empty:
            return df

        # 规则1：日期格式统一为 YYYY-MM-DD
        date_columns = ['trade_date', 'list_date', 'ann_date', 'end_date']
        for col in date_columns:
            if col in df.columns:
                try:
                    # 统一转换为 YYYY-MM-DD 格式
                    df[col] = pd.to_datetime(df[col]).dt.strftime('%Y-%m-%d')
                except Exception:
                    pass  # 保持原格式

        # 规则2：股票代码格式统一为 XXX.SH/SZ/BJ
        if 'ts_code' in df.columns:
            try:
                # 确保股票代码格式正确
                df['ts_code'] = df['ts_code'].astype(str).str.upper()
                # 如果是纯数字，添加后缀
                mask = df['ts_code'].str.match(r'^\d{6}$')
                if mask.any():
                    # 根据代码规则添加后缀
                    df.loc[mask, 'ts_code'] = df.loc[mask, 'ts_code'].apply(
                        lambda x: f"{x}.SZ" if x.startswith(('0', '3')) else f"{x}.SH"
                    )
            except Exception:
                pass  # 保持原格式

        return df

    def _query_df(self, sql: str, params=None) -> pd.DataFrame:
        """执行查询并返回 DataFrame（替代 DuckDB 的 fetchdf()）

        2026-08-11 根治：改用只读连接 read_conn——与写连接 conn 分离，
        多线程并发读（compute_batch 工作线程）不与主线程写互相干扰。
        """
        try:
            return pd.read_sql(sql, self.read_conn, params=params)
        except Exception as e:
            logger.warning(f"SQLite 查询失败: {e}")
            return pd.DataFrame()

    def _query_shard(self, table: str, sql: str, params=None) -> pd.DataFrame:
        """356号方案：从分库读取数据。

        如果表在分库中，从分库读取；否则从总库读取（兼容未迁移的表）。
        """
        try:
            from app.data.sharding_manager import sharding_manager
            db_name = sharding_manager.get_db_for_table(table)
        except Exception:
            db_name = None

        if db_name:
            try:
                conn = sharding_manager.get_connection(db_name)
                return pd.read_sql(sql, conn, params=params)
            except Exception as e:
                logger.warning(f"分库查询失败: {table} on {db_name}: {e}")
                return pd.DataFrame()
        else:
            return self._query_df(sql, params)

    def _exec_shard(self, table: str, sql: str, params=None):
        """356号方案：在分库上执行写操作（UPDATE/DELETE等）。"""
        try:
            from app.data.sharding_manager import sharding_manager
            db_name = sharding_manager.get_db_for_table(table)
        except Exception:
            db_name = None

        if db_name:
            try:
                conn = sharding_manager.get_connection(db_name)
                lock = sharding_manager.get_write_lock(db_name)
                with lock:
                    conn.execute(sql, params or [])
                    conn.commit()
            except Exception as e:
                logger.warning(f"分库执行失败: {table} on {db_name}: {e}")
        else:
            self.conn.execute(sql, params or [])
            self.conn.commit()

    def _execute(self, sql: str, params=None):
        try:
            self.conn.execute(sql, params or [])
        except Exception as e:
            logger.warning(f"SQLite 执行失败: {e}")

    def wal_checkpoint(self, mode: str = 'PASSIVE') -> tuple:
        """执行 SQLite WAL checkpoint，收缩 WAL 文件（2026-08-06 根治③ + 2026-08-20 修复自我锁定）

        使用独立连接执行 checkpoint，避免与 self.conn 的写事务互相阻塞。
        mode: 'PASSIVE'（默认，不阻塞）/ 'TRUNCATE'（截断，需无活跃读事务）。

        Returns: (busy, log_frames, checkpointed_frames)
        """
        ckpt_conn = None
        try:
            ckpt_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            ckpt_conn.execute("PRAGMA journal_mode=WAL")
            result = ckpt_conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            return result or (1, 0, 0)
        except Exception as e:
            logger.warning(f"WAL checkpoint({mode}) 失败: {e}")
            return (1, 0, 0)
        finally:
            if ckpt_conn:
                try:
                    ckpt_conn.close()
                except Exception:
                    pass

    # ── 建表 ─────────────────────────────────────────────────

    def _init_tables(self):
        """建表：所有 DECIMAL→REAL, VARCHAR→TEXT, BOOLEAN→INTEGER"""

        self._execute("""
            CREATE TABLE IF NOT EXISTS daily_cache (
                ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL,
                vol REAL, amount REAL, pct_chg REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        # ── 宽表指标缓存（替代旧 EAV 格式 indicator_cache，已于 2026-08-01 删除）──
        self._execute("""
            CREATE TABLE IF NOT EXISTS indicator_ma (
                ts_code TEXT, trade_date TEXT,
                ma5 REAL, ma10 REAL, ma20 REAL, ma30 REAL, ma60 REAL,
                vol_ma5 REAL, vol_ma10 REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS indicator_macd (
                ts_code TEXT, trade_date TEXT,
                macd_dif REAL, macd_dea REAL, macd_hist REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS indicator_other (
                ts_code TEXT, trade_date TEXT,
                rsi14 REAL,
                kdj_k REAL, kdj_d REAL, kdj_j REAL,
                boll_upper REAL, boll_mid REAL, boll_lower REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                key TEXT PRIMARY KEY, value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS daily_basic_cache (
                ts_code TEXT, trade_date TEXT,
                close REAL, turnover_rate REAL, turnover_rate_f REAL, volume_ratio REAL,
                pe REAL, pe_ttm REAL, pb REAL, ps REAL, ps_ttm REAL,
                dv_ratio REAL, dv_ttm REAL,
                total_share REAL, float_share REAL, free_share REAL,
                total_mv REAL, circ_mv REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS chip_distribution_cache (
                ts_code TEXT, trade_date TEXT,
                price_bin REAL, chip_ratio REAL, accumulated_ratio REAL,
                peak_flag INTEGER,  -- SQLite 无 BOOLEAN
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, price_bin)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS moneyflow_cache (
                ts_code TEXT, trade_date TEXT,
                buy_lg_vol REAL, buy_lg_amount REAL,
                sell_lg_vol REAL, sell_lg_amount REAL,
                buy_elg_amount REAL, sell_elg_amount REAL,
                buy_sm_amount REAL, sell_sm_amount REAL,
                net_lg_amount REAL, net_elg_amount REAL, net_sm_amount REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS win_rate_cache (
                signal_type TEXT PRIMARY KEY,
                samples INTEGER, win_rate_5d REAL, win_rate_10d REAL, win_rate_20d REAL,
                avg_return_5d REAL, avg_return_20d REAL, sharpe_5d REAL, sharpe_20d REAL,
                evaluated_at TIMESTAMP
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS conditional_win_rate_cache (
                signal_type TEXT PRIMARY KEY,
                total_samples INTEGER, with_div_samples INTEGER, with_div_win_rate REAL,
                without_div_samples INTEGER, without_div_win_rate REAL,
                market_good_samples INTEGER, market_good_win_rate REAL,
                market_poor_samples INTEGER, market_poor_win_rate REAL,
                evaluated_at TIMESTAMP
            )
        """)
        # as_* 表（盘中数据，已不再写入但保留表结构避免旧代码报错）
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_market_snapshot (
                ts_code TEXT PRIMARY KEY, name TEXT, price REAL, change REAL, change_pct REAL,
                volume REAL, amount REAL, pe REAL, pb REAL, amplitude REAL,
                circ_mv REAL, total_mv REAL, volume_ratio REAL,
                open REAL, high REAL, low REAL, pre_close REAL, turnover_rate REAL,
                source TEXT DEFAULT 'akshare', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_top_stocks (
                rank_type TEXT, ts_code TEXT, name TEXT, price REAL, change_pct REAL,
                volume REAL, amount REAL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (rank_type, ts_code)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_sector_ranking (
                sector_name TEXT PRIMARY KEY, ts_code TEXT, change_pct REAL,
                up_count INTEGER, down_count INTEGER,
                lead_ts_code TEXT, lead_name TEXT, lead_change_pct REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_concept_ranking (
                concept_name TEXT PRIMARY KEY, ts_code TEXT, change_pct REAL,
                up_count INTEGER, down_count INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_limit_pool (
                limit_type TEXT, ts_code TEXT, name TEXT, price REAL, change_pct REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (limit_type, ts_code)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_minute_kline (
                ts_code TEXT, trade_date TEXT, trade_time TEXT, freq TEXT DEFAULT '5min',
                open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, trade_time, freq)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_lhb_detail (
                ts_code TEXT, trade_date TEXT, name TEXT, change_pct REAL,
                buy_amount REAL, sell_amount REAL, net_amount REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_news (
                id TEXT PRIMARY KEY, title TEXT, summary TEXT,
                source TEXT, publish_time TEXT, url TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 373号§9.3：as_quote_cache 已废弃（无写入函数，读取返回空），不再建表
        # self._execute("""
        #     CREATE TABLE IF NOT EXISTS as_quote_cache (
        #         ts_code TEXT PRIMARY KEY,
        #         bid_price REAL, bid_volume INTEGER,
        #         ask_price REAL, ask_volume INTEGER,
        #         updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        #     )
        # """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS adj_factor_cache (
                ts_code TEXT, trade_date TEXT,
                adj_factor REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        # ── 252号方案 新增持久表 ──────────────────────────────
        self._execute("""
            CREATE TABLE IF NOT EXISTS minute_kline_cache (
                ts_code TEXT, trade_date TEXT, trade_time TEXT, freq TEXT DEFAULT '5min',
                open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, trade_time, freq)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS fina_indicator_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                eps REAL, eps_diluted REAL, eps_ttm REAL, bvps REAL, roe REAL,
                revenue_ps REAL, profit_ps REAL, cf_ps REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS income_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                revenue REAL, operating_profit REAL, net_profit REAL,
                net_profit_atsopc REAL, basic_eps REAL, total_opcost REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS balancesheet_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                total_assets REAL, total_liab REAL, total_equity REAL,
                current_assets REAL, current_liab REAL, fixed_assets REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS cashflow_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                net_profit REAL, cashflow_oper REAL, cashflow_inv REAL,
                cashflow_fin REAL, free_cashflow REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS forecast_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                forecast_type TEXT, change_reason TEXT,
                net_profit_min REAL, net_profit_max REAL, 
                eps_min REAL, eps_max REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date, ann_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS margin_cache (
                ts_code TEXT, trade_date TEXT,
                rzye REAL, rzmje REAL, rqmcl REAL,
                rzrqye REAL, rqyl REAL, rqchl REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS stk_limit_cache (
                ts_code TEXT, trade_date TEXT,
                high_limit REAL, low_limit REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS lhb_cache (
                ts_code TEXT, trade_date TEXT,
                name TEXT, change_pct REAL,
                buy_amount REAL, sell_amount REAL, net_amount REAL,
                buy_rate REAL, sell_rate REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS lhb_detail_cache (
                ts_code TEXT, trade_date TEXT,
                seat_name TEXT, seat_type TEXT DEFAULT '',
                buy_amount REAL DEFAULT 0, sell_amount REAL DEFAULT 0,
                net_amount REAL DEFAULT 0,
                buy_rank INTEGER DEFAULT 0, sell_rank INTEGER DEFAULT 0,
                reason_category TEXT DEFAULT '',
                side TEXT DEFAULT '',
                data_source TEXT DEFAULT 'akshare',
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, seat_name)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS top10_holders_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                holder_name TEXT, hold_amount REAL, hold_ratio REAL,
                hold_float_ratio REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date, holder_name)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS stk_holder_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                holder_number INTEGER,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS concept_cache (
                ts_code TEXT, concept_name TEXT, concept_code TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, concept_code)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS index_member_cache (
                index_code TEXT, ts_code TEXT, coname TEXT, in_date TEXT, out_date TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (index_code, ts_code)
            )
        """)
        # 363号F57-1修复：strategy_signals旧表已删除（功能由strategy_signal_detail替代）
        # 注意：不再创建旧表，已在363号方案中确认删除
        self._execute("""
            CREATE TABLE IF NOT EXISTS strategy_signal_detail (
                ts_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                signal_json TEXT NOT NULL,
                schema_version INTEGER DEFAULT 1,
                cached_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        # 370号方案S1：新增SIG双产出列（seven_dim_json→OUT直通，dim_results_json→JUD消费）
        for col, default in [('seven_dim_json', 'NULL'), ('dim_results_json', 'NULL')]:
            try:
                self._execute(f"ALTER TABLE strategy_signal_detail ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass  # 列已存在则忽略
        self._execute("""
            CREATE TABLE IF NOT EXISTS factor_cache (
                ts_code TEXT, trade_date TEXT,
                factor_name TEXT,
                value REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, factor_name)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS sentiment_pool_cache (
                trade_date TEXT, ts_code TEXT, name TEXT,
                change_pct REAL, price REAL,
                limit_type TEXT,
                consecutive_days INTEGER DEFAULT 1,
                reason_category TEXT,
                first_seal_time TEXT,
                data_source TEXT DEFAULT 'akshare',
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, ts_code, limit_type)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS finance_report_cache (
                ts_code TEXT, end_date TEXT,
                roe REAL, roce REAL,
                quick_ratio REAL, ocfps REAL,
                current_ratio REAL, asset_liab_ratio REAL,
                ebit REAL, operating_profit REAL,
                total_assets REAL, total_liab REAL,
                current_assets REAL, current_liab REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, end_date)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS opportunity_tags_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT NOT NULL,
                tag_name TEXT NOT NULL,
                tag_group TEXT NOT NULL,
                tag_value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                evidence TEXT,
                source TEXT,
                updated_at TEXT,
                UNIQUE(ts_code, tag_name, updated_at)
            )
        """)
        # 357号方案：pre_feat_cache（原料加工特征提取产物，JSON存储10组54字段）
        self._execute("""
            CREATE TABLE IF NOT EXISTS pre_feat_cache (
                ts_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                features_json TEXT NOT NULL,
                computed_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_pre_feat_date ON pre_feat_cache(trade_date)
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS opportunity_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT NOT NULL,
                date TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                trigger_event TEXT,
                score REAL,
                detail TEXT
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS opportunity_advice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT NOT NULL,
                date TEXT NOT NULL,
                advice_type TEXT,
                target_price REAL,
                stop_loss REAL,
                reason TEXT
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS opportunity_library (
                ts_code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                pipeline TEXT,
                lib_level TEXT DEFAULT 'scan',
                added_date TEXT,
                added_reason TEXT,
                last_update TEXT,
                status TEXT,
                days_in_status INTEGER,
                total_days INTEGER,
                manual_keep INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                park_trigger_count INTEGER DEFAULT 0,
                park_last_signal TEXT,
                park_entered_signal REAL,
                base_value_score REAL,
                base_trend_score REAL,
                base_event_score REAL,
                base_technical_score REAL,
                factor_boost REAL,
                vibe_boost REAL,
                composite_score REAL,
                factor_vibe_version TEXT
            )
        """)
        # 索引
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_daily_ts_code ON daily_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_daily_basic_ts_code ON daily_basic_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_daily_basic_date ON daily_basic_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_chip_ts_code ON chip_distribution_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_chip_date ON chip_distribution_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_moneyflow_ts_code ON moneyflow_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_moneyflow_date ON moneyflow_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_as_snapshot_ts ON as_market_snapshot(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_as_minute_ts ON as_minute_kline(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_as_minute_date ON as_minute_kline(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_as_lhb_date ON as_lhb_detail(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_as_news_time ON as_news(publish_time)",
            "CREATE INDEX IF NOT EXISTS idx_minute_kline_ts ON minute_kline_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_minute_kline_date ON minute_kline_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_minute_kline_ts_freq ON minute_kline_cache(ts_code, freq)",
            "CREATE INDEX IF NOT EXISTS idx_fina_ind_ts ON fina_indicator_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_fina_ind_date ON fina_indicator_cache(end_date)",
            "CREATE INDEX IF NOT EXISTS idx_income_ts ON income_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_bs_ts ON balancesheet_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_cf_ts ON cashflow_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_forecast_ts ON forecast_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_margin_ts ON margin_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_margin_date ON margin_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stk_limit_ts ON stk_limit_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stk_limit_date ON stk_limit_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_lhb_date ON lhb_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_lhb_detail_ts ON lhb_detail_cache(ts_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_lhb_detail_date ON lhb_detail_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_top10_ts ON top10_holders_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stk_holder_ts ON stk_holder_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_concept_ts ON concept_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_index_member_code ON index_member_cache(index_code)",
            "CREATE INDEX IF NOT EXISTS idx_factor_ts_name ON factor_cache(ts_code, factor_name)",
            "CREATE INDEX IF NOT EXISTS idx_sentiment_pool_date ON sentiment_pool_cache(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_sentiment_pool_ts ON sentiment_pool_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_finance_report_ts ON finance_report_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_finance_report_date ON finance_report_cache(end_date)",
            "CREATE INDEX IF NOT EXISTS idx_tags_ts_code ON opportunity_tags_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_tags_name"
            " ON opportunity_tags_cache(tag_name, tag_value)",
            "CREATE INDEX IF NOT EXISTS idx_lib_level ON opportunity_library(lib_level, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_ind_ma_ts ON indicator_ma(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_ind_macd_ts ON indicator_macd(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_ind_other_ts ON indicator_other(ts_code)",
        ]:
            try:
                self.conn.execute(idx_sql)
            except Exception:
                pass

        # sync_requests 队列表：调用层→采集层的"数据缺失"信号
        self._execute("""
            CREATE TABLE IF NOT EXISTS sync_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                ts_code TEXT,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        self._execute("CREATE INDEX IF NOT EXISTS idx_sync_req_status ON sync_requests(status)")

        # ── tag_history 标签历史归档表（347号：P4 写标签时同步归档，支撑 L1.5 跨日核查） ──
        self._execute("""
            CREATE TABLE IF NOT EXISTS tag_history (
                ts_code TEXT, tag_name TEXT, tag_group TEXT, tag_value TEXT,
                confidence REAL, evidence TEXT, source TEXT, updated_at TEXT,
                PRIMARY KEY (ts_code, tag_name, updated_at)
            )
        """)

        # ── treemap 快照表（305号§2.2.1）：日终预提取的轻量快照，每日替换 ──
        self._execute("""
            CREATE TABLE IF NOT EXISTS treemap_snapshot (
                ts_code            TEXT PRIMARY KEY,
                name               TEXT,
                industry           TEXT,
                close              REAL,
                pct_chg            REAL,
                total_mv           REAL,
                trade_date         TEXT,
                signal_strength    REAL,
                valuation_level    TEXT,
                valuation_deviation REAL,
                main_force_phase   TEXT,
                phase_confidence   REAL,
                sentiment_phase    TEXT,
                sector_heat        TEXT,
                fina_health        TEXT,
                opportunity_type   TEXT,
                trend_alignment    TEXT,
                price_position     TEXT,
                fund_flow          TEXT,
                capital_nature     TEXT,
                chip_concentration TEXT,
                volatility_level   TEXT,
                dividend_yield     REAL,
                composite_rating   REAL,
                opportunity_label  TEXT,
                evidence_count     INTEGER,
                snapshot_date      TEXT DEFAULT (date('now'))
            )
        """)
        self._execute("CREATE INDEX IF NOT EXISTS idx_snapshot_ind ON treemap_snapshot(industry)")

        # ── 337号 §3：status_snapshot 日频现状成品表（332总纲 成品仓·日频类） ──
        # 与 treemap_snapshot 同管道生成（S2 status_engine 生产环节），原子替换每日更新；
        # 图谱 API 合并读取（九维灯/状态条/conflict 展示）
        self._execute("""
            CREATE TABLE IF NOT EXISTS status_snapshot (
                ts_code             TEXT PRIMARY KEY,
                snapshot_date       TEXT DEFAULT (date('now')),
                trade_date          TEXT,
                dim_states          TEXT,
                status_bar          TEXT,
                opportunity_state   TEXT,
                state_evidence      TEXT,
                conflict_evidence   TEXT,
                consensus_rate      REAL,
                direction           TEXT,
                l0                  TEXT,
                lifecycle           TEXT,
                advice_params       TEXT,
                summary_text        TEXT,
                one_liner_detail    TEXT,
                dim_engine_results  TEXT,
                created_at          TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._execute("CREATE INDEX IF NOT EXISTS idx_status_snapshot_state ON status_snapshot(opportunity_state)")
        # 365号批次C：新增维度引擎结果字段（兼容已有数据库）
        for col, typ in [('dim_engine_results', 'TEXT'), ('summary_text', 'TEXT'), ('one_liner_detail', 'TEXT')]:
            try:
                self._execute(f"ALTER TABLE status_snapshot ADD COLUMN {col} {typ}")
            except Exception:
                pass  # 列已存在

        # ── 管道状态表（305号§9.2）：链条驱动执行状态 ──
        self._execute("""
            CREATE TABLE IF NOT EXISTS pipeline_status (
                pipeline_date TEXT,
                step_id       TEXT,
                step_name     TEXT,
                status        TEXT DEFAULT 'pending',
                started_at    TIMESTAMP,
                completed_at  TIMESTAMP,
                detail        TEXT,
                retry_count   INTEGER DEFAULT 0,
                PRIMARY KEY (pipeline_date, step_id)
            )
        """)

        self.conn.commit()

        # ── 320号 L2/L3：存量表补列（CREATE IF NOT EXISTS 不修改已存在表）──
        # L2: indicator_ma 早期版本缺 ma30/ma60 → cache_indicators_wide 写入失败（P1 指标预计算全市场失败）
        # L3: top10_holders_cache 早期版本缺 hold_float_ratio → 前十大股东采集失败
        self._migrate_missing_columns('indicator_ma', [
            ('ma30', 'REAL'), ('ma60', 'REAL'),
        ])
        self._migrate_missing_columns('top10_holders_cache', [
            ('hold_float_ratio', 'REAL'),
        ])

    # ── 快照数据库建表 ──────────────────────────────────────────

    def _init_snapshot_tables(self):
        """建表：实时快照表（独立 market_snapshot.db，§3.3 实时快照表设计）"""
        self.snapshot_conn.execute("""
            CREATE TABLE IF NOT EXISTS as_market_snapshot (
                ts_code TEXT PRIMARY KEY,
                code TEXT, name TEXT, price REAL, open REAL, high REAL, low REAL,
                prev_close REAL, volume INTEGER, amount REAL,
                change REAL, change_pct REAL,
                bid1 REAL, ask1 REAL, bid_vol1 INTEGER, ask_vol1 INTEGER,
                bid2 REAL, ask2 REAL, bid_vol2 INTEGER, ask_vol2 INTEGER,
                bid3 REAL, ask3 REAL, bid_vol3 INTEGER, ask_vol3 INTEGER,
                bid4 REAL, ask4 REAL, bid_vol4 INTEGER, ask_vol4 INTEGER,
                bid5 REAL, ask5 REAL, bid_vol5 INTEGER, ask_vol5 INTEGER,
                cached_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        self.snapshot_conn.commit()

    # ── 计算分库建表（356号方案）──────────────────────────────────────────

    def _init_compute_tables(self):
        """建表：计算结果表（独立 compute_cache.db，356号方案）
        包含：pattern_score_cache、pre_feat_cache 等计算结果
        """
        # 353/358号方案：pattern_score_cache（形态评分缓存，日终批量计算产物）
        self.compute_conn.execute("""
            CREATE TABLE IF NOT EXISTS pattern_score_cache (
                ts_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                score REAL NOT NULL,
                details_json TEXT NOT NULL,
                computed_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self.compute_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pattern_score_date ON pattern_score_cache(trade_date)
        """)
        self.compute_conn.commit()

    def _migrate_pattern_score_to_compute_db(self):
        """迁移 pattern_score_cache 数据从 stock_cache.db 到 compute_cache.db（356号方案）"""
        try:
            # 检查主库是否有 pattern_score_cache 表
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pattern_score_cache'"
            )
            if cursor.fetchone() is None:
                return  # 主库没有表，无需迁移

            # 检查主库是否有数据
            count = self.conn.execute("SELECT COUNT(*) FROM pattern_score_cache").fetchone()[0]
            if count == 0:
                return  # 无数据，无需迁移

            logger.info(f"迁移 pattern_score_cache 数据: {count} 条记录从 stock_cache.db 到 compute_cache.db")

            # 读取所有数据
            rows = self.conn.execute("SELECT * FROM pattern_score_cache").fetchall()

            # 写入 compute_cache.db
            for row in rows:
                self.compute_conn.execute(
                    """INSERT OR REPLACE INTO pattern_score_cache
                       (ts_code, trade_date, score, details_json, computed_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    row
                )
            self.compute_conn.commit()

            # 重命名主库中的表作为备份
            self.conn.execute("ALTER TABLE pattern_score_cache RENAME TO pattern_score_cache_backup")
            self.conn.commit()

            logger.info(f"pattern_score_cache 迁移完成: {count} 条记录已迁移")
        except Exception as e:
            logger.warning(f"迁移 pattern_score_cache 失败: {e}")

    # ════════════════════════════════════════════════════════════
    # 业务方法（以下方法签名与 DuckDB 版本完全一致）
    # ════════════════════════════════════════════════════════════

    # ── 日线 ─────────────────────────────────────────────────

    @staticmethod
    def _fmt_date(date_val) -> str:
        """归一化日期格式为 YYYYMMDD 字符串"""
        if date_val is None:
            return None
        if isinstance(date_val, datetime):
            return date_val.strftime('%Y%m%d')
        if isinstance(date_val, date):
            return date_val.strftime('%Y%m%d')
        s = str(date_val).replace('-', '').replace('/', '').strip()
        if len(s) == 8 and s.isdigit():
            return s
        raise ValueError(f'无法解析日期: {date_val}')

    def get_cached_daily(self, ts_code, start_date=None, end_date=None):
        self.cache_stats['total_requests'] += 1
        query = "SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg FROM daily_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"
            s = str(start_date).replace('-', '')
            params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(start_date))
        if end_date:
            query += " AND trade_date <= ?"
            s = str(end_date).replace('-', '')
            params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(end_date))
        query += " ORDER BY trade_date"
        df = self._query_shard('daily_cache', query, params)
        if not df.empty:
            self.cache_stats['hits_duckdb'] += 1
        else:
            self.cache_stats['misses'] += 1
        return df

    def preload_all(self):
        """预加载全量日线到内存（加速批量筛选）"""
        if getattr(self, '_all_daily', None) is None:
            self._all_daily = self._query_shard('daily_cache', "SELECT * FROM daily_cache ORDER BY ts_code, trade_date")
            logger.info(f"日线预加载: {len(self._all_daily)} 行")

    def get_cached_daily_batch(self, ts_codes, start_date=None, end_date=None):
        """批量获取多只股票的日线数据（使用全量预加载 + 自动加载）"""
        df = getattr(self, '_all_daily', None)
        if df is None:
            df = self._query_shard('daily_cache', "SELECT * FROM daily_cache ORDER BY ts_code, trade_date")
            self._all_daily = df
            logger.info(f"日线自动加载: {len(df)} 行")
        if df.empty:
            return {}
        m = df['ts_code'].isin(ts_codes)
        if start_date:
            m &= df['trade_date'] >= start_date
        if end_date:
            m &= df['trade_date'] <= end_date
        subset = df[m]
        result = {}
        for ts_code, grp in subset.groupby('ts_code'):
            result[ts_code] = grp.reset_index(drop=True)
        return result

    def cache_daily_data(self, df):
        if df.empty:
            return
        # 列过滤由 _insert_from_df 的分库路由自动处理
        with self._write_lock:
            self._insert_from_df('daily_cache', df)
            self._update_metadata('last_cache_time', datetime.now().isoformat())

    # ── 指标 ─────────────────────────────────────────────────

    def cache_indicators_wide(self, ts_code: str, df: 'pd.DataFrame'):
        """批量写入宽表指标（df 需含 trade_date 及全部指标列）"""
        if df.empty:
            return
        with self._write_lock:
            ma_cols = {'trade_date', 'ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'vol_ma5', 'vol_ma10'}
            if ma_cols.issubset(set(df.columns)):
                ma_df = df[list(ma_cols)].copy()
                ma_df['ts_code'] = ts_code
                self._insert_from_df('indicator_ma', ma_df)
            macd_cols = {'trade_date', 'macd_dif', 'macd_dea', 'macd_hist'}
            if macd_cols.issubset(set(df.columns)):
                macd_df = df[list(macd_cols)].copy()
                macd_df['ts_code'] = ts_code
                self._insert_from_df('indicator_macd', macd_df)
            other_cols = {'trade_date', 'rsi14', 'kdj_k', 'kdj_d', 'kdj_j',
                           'boll_upper', 'boll_mid', 'boll_lower'}
            if other_cols.issubset(set(df.columns)):
                other_df = df[list(other_cols)].copy()
                other_df['ts_code'] = ts_code
                self._insert_from_df('indicator_other', other_df)
            self.conn.commit()

    def get_indicators_wide(self, ts_code: str) -> 'pd.DataFrame':
        """读取宽表指标数据，合并 3 张表为 1 个 DataFrame"""
        ma = self._query_shard('indicator_ma',
            "SELECT ts_code, trade_date, ma5, ma10, ma20, ma30, ma60, vol_ma5, vol_ma10 "
            "FROM indicator_ma WHERE ts_code = ? ORDER BY trade_date", [ts_code])
        macd = self._query_shard('indicator_macd',
            "SELECT trade_date, macd_dif, macd_dea, macd_hist "
            "FROM indicator_macd WHERE ts_code = ? ORDER BY trade_date", [ts_code])
        other = self._query_shard('indicator_other',
            "SELECT trade_date, rsi14, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower "
            "FROM indicator_other WHERE ts_code = ? ORDER BY trade_date", [ts_code])
        result = ma
        for _df in [macd, other]:
            if not _df.empty and not result.empty:
                result = result.merge(_df, on='trade_date', how='left')
            elif not _df.empty:
                result = _df
        return result

    # ── 内存缓存 ────────────────────────────────────────────

    def get_from_memory(self, key: str, level: str = 'realtime'):
        return self.memory_cache.get(key, level)

    def set_to_memory(self, key: str, value, level: str = 'realtime'):
        self.memory_cache.set(key, value, level)

    # ── 统计 ─────────────────────────────────────────────────

    def get_cache_stats(self):
        try:
            daily_count = self.read_conn.execute("SELECT COUNT(*) FROM daily_cache").fetchone()[0]
            # 用 indicator_ma 宽表估算指标总量（ma/macd/other 三宽表近似）
            indicator_count = 0
            try:
                row = self.read_conn.execute(
                    "SELECT COUNT(*) FROM indicator_ma"
                ).fetchone()
                if row:
                    indicator_count = int(row[0]) * 3  # ma/macd/other 三宽表近似
            except Exception:
                pass
            return pd.DataFrame([{
                'duckdb_daily_count': daily_count,
                'duckdb_indicator_count': indicator_count,
                'enhanced_hits_duckdb': self.cache_stats['hits_duckdb'],
                'enhanced_misses': self.cache_stats['misses'],
                'enhanced_hit_rate': self.cache_stats['hits_duckdb'] / max(self.cache_stats['total_requests'], 1) * 100
            }])
        except Exception:
            return pd.DataFrame()

    # ── 元数据 ───────────────────────────────────────────────

    def _update_metadata(self, key, value):
        with self._write_lock:
            try:
                self.conn.execute("INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)", [key, value])
                self.conn.commit()
            except Exception:
                pass

    # ── 清理 ─────────────────────────────────────────────────

    def invalidate_old_data(self, days=30):
        with self._write_lock:
            try:
                cutoff = datetime.now() - timedelta(days=days)
                self.conn.execute("DELETE FROM daily_cache WHERE cached_at < ?", [cutoff])
                self.conn.commit()
                return True
            except Exception as e:
                logger.warning(f"清除旧缓存失败: {e}")
                return False

    def clear_stock_cache(self, ts_code: str) -> bool:
        """清除单只股票缓存（2026-08-06 合规整改：替代调用层直连 DELETE）"""
        with self._write_lock:
            try:
                self.conn.execute("DELETE FROM daily_cache WHERE ts_code = ?", [ts_code])
                self.conn.commit()
                return True
            except Exception as e:
                logger.warning(f"清除股票缓存失败 ({ts_code}): {e}")
                return False

    def clear_old_cache(self, days=30):
        return self.invalidate_old_data(days)

    # ── 连接管理 ─────────────────────────────────────────────

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            if hasattr(self, 'snapshot_conn'):
                self.snapshot_conn.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    # ==================== daily_basic ====================

    def cache_daily_basic_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns and df['trade_date'].dtype in ('object', 'str'):
                    sample = str(df['trade_date'].iloc[0]) if len(df) > 0 else ''
                    if sample.isdigit() and len(sample) == 8:
                        df['trade_date'] = df['trade_date'].astype(str).str.replace(
                            r'^(\d{4})(\d{2})(\d{2})$', r'\1-\2-\3', regex=True
                        )
                self._insert_from_df('daily_basic_cache', df)
                self._update_metadata('last_daily_basic_cache_time', datetime.now().isoformat())
            except Exception as e:
                logger.warning(f"缓存daily_basic数据失败: {e}")

    def get_cached_daily_basic(self, ts_code, start_date=None, end_date=None):
        """从缓存获取每日基础数据（优先使用预加载内存）"""
        sd = None
        if start_date:
            s = str(start_date).replace('-', '')
            sd = f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(start_date)
        ed = None
        if end_date:
            s = str(end_date).replace('-', '')
            ed = f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(end_date)
        all_df = getattr(self, '_all_daily_basic', None)
        if all_df is not None:
            m = all_df['ts_code'] == ts_code
            if sd:
                m &= all_df['trade_date'] >= sd
            if ed:
                m &= all_df['trade_date'] <= ed
            df = all_df[m].copy()
            if not df.empty:
                return df
        query = "SELECT * FROM daily_basic_cache WHERE ts_code = ?"
        params = [ts_code]
        if sd:
            query += " AND trade_date >= ?"
            params.append(sd)
        if ed:
            query += " AND trade_date <= ?"
            params.append(ed)
        query += " ORDER BY trade_date"
        return self._query_shard('daily_basic_cache', query, params)

    def get_cached_daily_basic_batch(self, ts_codes, start_date=None, end_date=None):
        """批量获取多只股票的基础数据"""
        if not ts_codes:
            return {}
        placeholders = ','.join(['?' for _ in ts_codes])
        query = f"SELECT * FROM daily_basic_cache WHERE ts_code IN ({placeholders})"
        params = list(ts_codes)
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        df = self._query_df(query, params)
        if df.empty:
            return {}
        result = {}
        for ts_code, grp in df.groupby('ts_code'):
            result[ts_code] = grp.sort_values('trade_date').reset_index(drop=True)
        return result

    # ==================== 筹码分布 ====================

    def cache_chip_distribution(self, ts_code, trade_date, chip_data):
        if not chip_data:
            return
        with self._write_lock:
            try:
                records = [{
                    'ts_code': ts_code, 'trade_date': trade_date,
                    'price_bin': b['price_bin'], 'chip_ratio': b['chip_ratio'],
                    'accumulated_ratio': b['accumulated_ratio'],
                    'peak_flag': 1 if b['peak_flag'] else 0,
                } for b in chip_data]
                self._insert_from_df('chip_distribution_cache', pd.DataFrame(records))
            except Exception as e:
                logger.warning(f"缓存筹码分布失败: {e}")

    def batch_cache_chips(self, records):
        if not records:
            return
        with self._write_lock:
            try:
                df = pd.DataFrame(records)
                if 'peak_flag' in df.columns:
                    df['peak_flag'] = df['peak_flag'].astype(int)
                self._insert_from_df('chip_distribution_cache', df)
            except Exception as e:
                logger.warning(f"批量缓存筹码分布失败: {e}")

    def get_chip_distribution(self, ts_code, start_date=None, end_date=None):
        query = "SELECT * FROM chip_distribution_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date, price_bin"
        return self._query_shard('chip_distribution_cache', query, params)

    def get_latest_chip_distribution(self, ts_code):
        return self._query_shard('chip_distribution_cache', """
            SELECT * FROM chip_distribution_cache
            WHERE ts_code = ?
            AND trade_date = (SELECT MAX(trade_date) FROM chip_distribution_cache WHERE ts_code = ?)
            ORDER BY price_bin
        """, [ts_code, ts_code])

    # ==================== 资金流向 ====================

    def cache_moneyflow_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                # 补齐 net_* 列
                net_cols = {'net_lg_amount': 'buy_lg_amount', 'net_elg_amount': 'buy_elg_amount',
                            'net_sm_amount': 'buy_sm_amount'}
                for net_col, buy_col in net_cols.items():
                    if net_col not in df.columns and buy_col in df.columns:
                        sell_col = 'sell_' + buy_col[4:]
                        df[net_col] = df[buy_col].fillna(0) - df.get(sell_col, pd.Series([0]*len(df))).fillna(0)
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('moneyflow_cache', df)
                self._update_metadata('last_moneyflow_cache_time', datetime.now().isoformat())
            except Exception as e:
                logger.warning(f"缓存资金流向数据失败: {e}")

    def get_cached_moneyflow(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        """从缓存获取资金流向（优先使用预加载内存）"""
        if ts_code and not trade_date:
            all_df = getattr(self, '_all_moneyflow', None)
            if all_df is not None:
                m = all_df['ts_code'] == ts_code
                if start_date:
                    m &= all_df['trade_date'] >= start_date
                if end_date:
                    m &= all_df['trade_date'] <= end_date
                df = all_df[m].copy()
                if not df.empty:
                    return df
        query = "SELECT * FROM moneyflow_cache WHERE 1=1"
        params = []
        if ts_code:
            query += " AND ts_code = ?"
            params.append(ts_code)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date, ts_code"
        return self._query_shard('moneyflow_cache', query, params)

    def get_cached_moneyflow_batch(self, ts_codes, start_date=None, end_date=None):
        """批量获取多只股票的资金流向数据"""
        if not ts_codes:
            return {}
        placeholders = ','.join(['?' for _ in ts_codes])
        query = f"SELECT * FROM moneyflow_cache WHERE ts_code IN ({placeholders})"
        params = list(ts_codes)
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        df = self._query_shard('moneyflow_cache', query, params)
        if df.empty:
            return {}
        result = {}
        for ts_code, grp in df.groupby('ts_code'):
            result[ts_code] = grp.sort_values('trade_date').reset_index(drop=True)
        return result

    # ==================== 赢率缓存 ====================

    def cache_win_rates(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                self._insert_from_df('win_rate_cache', df)
            except Exception as e:
                logger.warning(f"缓存赢率数据失败: {e}")

    def get_cached_win_rates(self) -> list:
        try:
            df = self._query_df("SELECT * FROM win_rate_cache ORDER BY signal_type")
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.warning(f"查询赢率数据失败: {e}")
            return []

    def get_cached_win_rate(self, signal_type: str) -> dict:
        try:
            df = self._query_shard('win_rate_cache', "SELECT * FROM win_rate_cache WHERE signal_type = ?", [signal_type])
            return df.to_dict('records')[0] if not df.empty else {}
        except Exception as e:
            logger.warning(f"查询赢率数据失败: {e}")
            return {}

    def cache_conditional_win_rates(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                self._insert_from_df('conditional_win_rate_cache', df)
            except Exception as e:
                logger.warning(f"缓存条件概率数据失败: {e}")

    def get_cached_conditional_win_rates(self) -> list:
        try:
            df = self._query_df("SELECT * FROM conditional_win_rate_cache ORDER BY signal_type")
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.warning(f"查询条件下概率数据失败: {e}")
            return []

    # ==================== as_* 盘中数据（保留兼容） ====================

    def write_as_market_snapshot(self, records: list):
        # 373号§9.3：已废弃，保留兼容（盘中数据已迁移至 InMemoryStateStore）
        if not records:
            return
        try:
            self._insert_from_df('as_market_snapshot', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_top_stocks(self, rank_type: str, records: list):
        # 373号§9.3：已废弃，保留兼容（盘中数据已迁移至 InMemoryStateStore）
        if not records:
            return
        try:
            for r in records:
                r['rank_type'] = rank_type
            self._insert_from_df('as_top_stocks', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_sector_ranking(self, records: list):
        if not records:
            return
        try:
            self._insert_from_df('as_sector_ranking', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_concept_ranking(self, records: list):
        if not records:
            return
        try:
            self._insert_from_df('as_concept_ranking', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_limit_pool(self, records: list, limit_type: str):
        # 373号§9.3：已废弃，保留兼容（盘中数据已迁移至 InMemoryStateStore）
        if not records:
            return
        try:
            for r in records:
                r['limit_type'] = limit_type
            self._insert_from_df('as_limit_pool', pd.DataFrame(records))
        except Exception:
            pass

    def append_as_minute_kline(self, records: list):
        if not records:
            return
        try:
            self._insert_from_df('as_minute_kline', pd.DataFrame(records))
        except Exception:
            pass

    def clean_as_minute_kline(self, trade_date: str):
        """盘后清理当日分钟K线数据"""
        try:
            self.conn.execute("DELETE FROM as_minute_kline WHERE trade_date = ?", [trade_date])
            self.conn.commit()
        except Exception:
            pass

    def write_as_lhb_detail(self, records: list):
        if not records:
            return
        try:
            self._insert_from_df('as_lhb_detail', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_news(self, records: list):
        if not records:
            return
        try:
            self._insert_from_df('as_news', pd.DataFrame(records))
        except Exception:
            pass

    # ==================== 复权因子缓存 ====================

    def cache_adj_factor_data(self, df):
        """缓存复权因子数据 — 支持按年份写入不同表（356号方案大表拆分）

        拆分策略：按年份拆分，每年一个表（adj_factor_cache_YYYY）
        """
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

                # 按年份分组写入不同表
                if 'trade_date' in df.columns:
                    df['year'] = pd.to_datetime(df['trade_date']).dt.year
                    for year, group in df.groupby('year'):
                        table_name = f'adj_factor_cache_{year}'
                        # 确保表存在
                        self._ensure_adj_factor_table(table_name)
                        # 写入数据
                        group_to_insert = group.drop(columns=['year'])
                        self._insert_from_df(table_name, group_to_insert)
                else:
                    # 无日期字段，写入默认表
                    self._insert_from_df('adj_factor_cache', df)

                self._update_metadata('last_adj_factor_cache_time', datetime.now().isoformat())
            except Exception as e:
                logger.warning(f"缓存复权因子失败: {e}")

    def _ensure_adj_factor_table(self, table_name: str):
        """确保复权因子表存在（按年份拆分）"""
        try:
            # 检查表是否存在
            exists = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                [table_name]
            ).fetchone()
            if not exists:
                # 创建表
                self.conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        ts_code TEXT,
                        trade_date TEXT,
                        adj_factor REAL,
                        cached_at TIMESTAMP,
                        PRIMARY KEY (ts_code, trade_date)
                    )
                """)
                # 创建索引
                self.conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(trade_date)")
                self.conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ts ON {table_name}(ts_code)")
                self.conn.commit()
                logger.info(f"创建复权因子表: {table_name}")
        except Exception as e:
            logger.warning(f"创建复权因子表失败: {e}")

    def get_cached_adj_factor(self, ts_code=None, start_date=None, end_date=None):
        # 367号方案：优先从分库读取
        try:
            from app.data.sharding_manager import sharding_manager
            if sharding_manager.table_exists('adj_factor_cache'):
                query = "SELECT * FROM adj_factor_view WHERE 1=1"
                params = []
                if ts_code:
                    query += " AND ts_code = ?"
                    params.append(ts_code)
                if start_date:
                    query += " AND trade_date >= ?"
                    s = str(start_date).replace('-', '')
                    params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(start_date))
                if end_date:
                    query += " AND trade_date <= ?"
                    s = str(end_date).replace('-', '')
                    params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(end_date))
                query += " ORDER BY trade_date"
                df = sharding_manager.execute_query('adj_factor_cache', query, params)
                if df is not None and not df.empty:
                    import pandas as pd
                    return pd.DataFrame(df)
        except Exception as e:
            logger.debug(f"分库读取失败，降级到ECM: {e}")

        # 降级到ECM读取
        query = "SELECT * FROM adj_factor_cache WHERE 1=1"
        params = []
        if ts_code:
            query += " AND ts_code = ?"
            params.append(ts_code)
        if start_date:
            query += " AND trade_date >= ?"
            s = str(start_date).replace('-', '')
            params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(start_date))
        if end_date:
            query += " AND trade_date <= ?"
            s = str(end_date).replace('-', '')
            params.append(f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else str(end_date))
        query += " ORDER BY trade_date"
        return self._query_df(query, params)

    # ==================== 252号方案：分钟K线 ====================

    def cache_minute_kline(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                self._insert_from_df('minute_kline_cache', df)
            except Exception as e:
                logger.warning(f"缓存分钟K线失败: {e}")

    def get_cached_minute_kline(self, ts_code, trade_date=None, freq='5min'):
        # 367号方案：优先从分库读取
        try:
            from app.data.sharding_manager import sharding_manager
            if sharding_manager.table_exists('minute_kline_cache'):
                query = "SELECT * FROM minute_kline_cache WHERE ts_code = ?"
                params = [ts_code]
                if trade_date:
                    query += " AND trade_date = ?"
                    params.append(trade_date)
                query += " AND freq = ?"
                params.append(freq)
                query += " ORDER BY trade_time"
                df = sharding_manager.execute_query('minute_kline_cache', query, params)
                if df is not None and not df.empty:
                    import pandas as pd
                    return pd.DataFrame(df)
        except Exception as e:
            logger.debug(f"分库读取失败，降级到ECM: {e}")

        # 降级到ECM读取
        query = "SELECT * FROM minute_kline_cache WHERE ts_code = ?"
        params = [ts_code]
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        query += " AND freq = ?"
        params.append(freq)
        query += " ORDER BY trade_time"
        return self._query_df(query, params)

    # ==================== 252号方案：财务指标 ====================

    def cache_fina_indicator_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                # 列名映射：Tushare 原生列名 → 数据库列名
                column_map = {
                    'bps': 'bvps',
                    'dt_eps': 'eps_diluted',
                    'cfps': 'cf_ps',
                    'ocfps': 'cf_ps',
                }
                df.rename(columns=column_map, inplace=True)
                # 只写入表中已有的列，忽略 Tushare 返回的多余字段
                # 列过滤由 _insert_from_df 的分库路由自动处理
                # 转换 Series/DataFrame 类型列为标量（Tushare 某些字段返回嵌套对象或重复列名）
                for col in df.columns:
                    try:
                        s = df[col]
                        if isinstance(s, pd.DataFrame):
                            # 重复列名导致 df[col] 返回 DataFrame，取第一列
                            df[col] = s.iloc[:, 0]
                            s = df[col]
                        if hasattr(s, 'dtype') and s.dtype == 'object':
                            df[col] = s.apply(lambda x: x.iloc[0] if hasattr(x, 'iloc') else x)
                    except Exception:
                        pass
                self._insert_from_df('fina_indicator_cache', df)
            except Exception as e:
                logger.warning(f"缓存财务指标失败: {e}")

    def get_cached_fina_indicator(self, ts_code):
        return self._query_shard('fina_indicator_cache',
            "SELECT * FROM fina_indicator_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：利润表 ====================

    def cache_income_data(self, df):
        if df.empty:
            return
        # 320号 F2：tushare pro.income 列名 → income_cache 表列名映射
        # （tushare 返回 n_income/n_income_attr_p/operate_profit，表列为
        #   net_profit/net_profit_atsopc/operating_profit，不映射则净利润列全空）
        _COL_MAP = {
            'n_income': 'net_profit',
            'n_income_attr_p': 'net_profit_atsopc',
            'operate_profit': 'operating_profit',
        }
        df = df.rename(columns=_COL_MAP)
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('income_cache', df)
            except Exception as e:
                logger.warning(f"缓存利润表失败: {e}")

    def get_cached_income(self, ts_code):
        return self._query_shard('income_cache',
            "SELECT * FROM income_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：资产负债表 ====================

    def cache_balancesheet_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('balancesheet_cache', df)
            except Exception as e:
                logger.warning(f"缓存资产负债表失败: {e}")

    def get_cached_balancesheet(self, ts_code):
        return self._query_shard('balancesheet_cache',
            "SELECT * FROM balancesheet_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：现金流量表 ====================

    def cache_cashflow_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('cashflow_cache', df)
            except Exception as e:
                logger.warning(f"缓存现金流量表失败: {e}")

    def get_cached_cashflow(self, ts_code):
        return self._query_shard('cashflow_cache',
            "SELECT * FROM cashflow_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：业绩预告 ====================

    def cache_forecast_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('forecast_cache', df)
            except Exception as e:
                logger.warning(f"缓存业绩预告失败: {e}")

    def get_cached_forecast(self, ts_code):
        return self._query_shard('forecast_cache',
            "SELECT * FROM forecast_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：融资融券 ====================

    def cache_margin_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('margin_cache', df)
            except Exception as e:
                logger.warning(f"缓存融资融券失败: {e}")

    def get_cached_margin(self, ts_code, start_date=None, end_date=None):
        query = "SELECT * FROM margin_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date"
        return self._query_shard('margin_cache', query, params)

    def cache_stk_limit_data(self, df):
        """缓存涨跌停数据 — 统一日期格式为 YYYY-MM-DD"""
        if df.empty:
            return
        with self._write_lock:
            try:
                # stk_limit 列名：ts_code, trade_date, high_limit, low_limit
                # 统一日期格式为 YYYY-MM-DD（355号方案规则1）
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
                if 'up_limit' in df.columns and 'high_limit' not in df.columns:
                    df = df.rename(columns={'up_limit': 'high_limit', 'down_limit': 'low_limit'})
                self._insert_from_df('stk_limit_cache', df)
            except Exception as e:
                logger.warning(f"缓存涨跌停失败: {e}")

    def get_cached_stk_limit(self, trade_date):
        return self._query_df(
            "SELECT * FROM stk_limit_cache WHERE trade_date = ?",
            [trade_date]
        )

    # ==================== 252号方案：龙虎榜 ====================

    def cache_lhb_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self._insert_from_df('lhb_cache', df)
            except Exception as e:
                logger.warning(f"缓存龙虎榜失败: {e}")

    def get_cached_lhb(self, ts_code=None, trade_date=None):
        """从缓存获取龙虎榜数据，可按股票代码或交易日期过滤"""
        conditions = []
        params = []
        if ts_code:
            conditions.append("ts_code = ?")
            params.append(ts_code)
        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self._query_df(
            f"SELECT * FROM lhb_cache{where} ORDER BY trade_date DESC, net_amount DESC",
            params
        )

    # ==================== 278号方案：席位级龙虎榜 ====================

    def cache_lhb_detail_data(self, records: list):
        """写入席位级龙虎榜明细数据（覆盖式按 trade_date 写入）"""
        if not records:
            return
        with self._write_lock:
            try:
                df = pd.DataFrame(records)
                if df.empty:
                    return
                # 按 trade_date 删除旧数据后全量覆盖
                trade_dates = df['trade_date'].unique()
                for td in trade_dates:
                    self.conn.execute(
                        "DELETE FROM lhb_detail_cache WHERE trade_date = ?", [td]
                    )
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self._insert_from_df('lhb_detail_cache', df)
            except Exception as e:
                logger.warning(f"缓存席位级龙虎榜失败: {e}")

    def get_cached_lhb_detail(self, ts_code: str = None, trade_date: str = None) -> pd.DataFrame:
        """从缓存获取席位级龙虎榜明细"""
        conditions = []
        params = []
        if ts_code:
            conditions.append("ts_code = ?")
            params.append(ts_code)
        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self._query_df(
            f"SELECT * FROM lhb_detail_cache{where} ORDER BY trade_date DESC, buy_amount DESC",
            params
        )

    # ==================== 273a方案：情绪涨停池 ====================

    def write_sentiment_pool(self, records: list):
        """写入涨跌停池数据（覆盖式，按 trade_date + limit_type）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
            self._insert_from_df('sentiment_pool_cache', df)
        except Exception as e:
            logger.warning(f"缓存涨跌停池失败: {e}")

    def get_cached_sentiment_pool(self, trade_date: str = None) -> pd.DataFrame:
        """查询涨跌停池数据"""
        if trade_date:
            return self._query_df(
                "SELECT * FROM sentiment_pool_cache WHERE trade_date = ? ORDER BY limit_type, change_pct DESC",
                [trade_date]
            )
        return self._query_df(
            "SELECT * FROM sentiment_pool_cache ORDER BY trade_date DESC, limit_type, change_pct DESC"
        )

    # ==================== 273a方案：财务报告缓存 ====================

    def cache_finance_report_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                # 列过滤由 _insert_from_df 的分库路由自动处理
                self._insert_from_df('finance_report_cache', df)
            except Exception as e:
                logger.warning(f"缓存财务报告失败: {e}")

    def get_cached_finance_report(self, ts_code: str) -> pd.DataFrame:
        return self._query_shard('finance_report_cache',
            "SELECT * FROM finance_report_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    def cache_top10_holders(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('top10_holders_cache', df)
            except Exception as e:
                logger.warning(f"缓存前十大股东失败: {e}")

    def get_cached_top10_holders(self, ts_code):
        return self._query_shard('top10_holders_cache',
            "SELECT * FROM top10_holders_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：股东人数 ====================

    def cache_stk_holder_data(self, df):
        if df.empty:
            return
        # 列名映射（修复 2026-08-02：Tushare stk_holdernumber 返回 holder_num，
        # 表结构为 holder_number——不映射则股东户数数据全空）
        if 'holder_num' in df.columns and 'holder_number' not in df.columns:
            df = df.rename(columns={'holder_num': 'holder_number'})
        # 过滤无数据的报表日行（holder_number NaN）
        if 'holder_number' in df.columns:
            df = df[df['holder_number'].notna()]
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('stk_holder_cache', df)
            except Exception as e:
                logger.warning(f"缓存股东人数失败: {e}")

    def get_cached_stk_holder(self, ts_code):
        return self._query_shard('stk_holder_cache',
            "SELECT * FROM stk_holder_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：概念分类 ====================

    def cache_concept_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                self._insert_from_df('concept_cache', df)
            except Exception as e:
                logger.warning(f"缓存概念分类失败: {e}")

    def get_cached_concept(self, ts_code=None):
        query = "SELECT * FROM concept_cache"
        params = []
        if ts_code:
            query += " WHERE ts_code = ?"
            params.append(ts_code)
        return self._query_shard('concept_cache', query, params)

    def cache_index_member_data(self, df):
        if df.empty:
            return
        with self._write_lock:
            try:
                self._insert_from_df('index_member_cache', df)
            except Exception as e:
                logger.warning(f"缓存指数成分股失败: {e}")

    def get_cached_index_member(self, index_code):
        return self._query_shard('index_member_cache',
            "SELECT * FROM index_member_cache WHERE index_code = ?",
            [index_code]
        )

    # ==================== 策略信号详情缓存（287号方案 v2.3） ====================

    def cache_signal_detail(self, ts_code: str, result_dict: dict):
        """缓存完整策略信号详情（替代 cache_strategy_signals）"""
        import json as _json
        trade_date = result_dict.get('trade_date', datetime.now().strftime('%Y%m%d'))
        signal_json = _json.dumps(result_dict, ensure_ascii=False, default=str)
        with self._write_lock:
            try:
                self._execute(
                    """INSERT OR REPLACE INTO strategy_signal_detail
                       (ts_code, trade_date, signal_json, schema_version, cached_at)
                       VALUES (?, ?, ?, 1, datetime('now','localtime'))""",
                    [ts_code, trade_date, signal_json]
                )
                # 2026-08-11 修复：_execute 不 commit——若 conn 处于活动读事务
                # （P2 重算脚本 compute_batch 大量读取后写库），INSERT 不持久化
                # 导致 strategy_signal_detail 更新丢失（与 ECM 其他 cache_* 方法一致）
                self.conn.commit()
            except Exception as e:
                logger.warning(f"缓存信号详情失败 [{ts_code}]: {e}")

    def get_signal_detail(self, ts_code: str, trade_date: str = None) -> dict | None:
        """读取缓存策略信号详情，返回反序列化的 dict 或 None"""
        import json as _json
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        try:
            row = self.read_conn.execute(
                "SELECT signal_json FROM strategy_signal_detail WHERE ts_code=? AND trade_date=?",
                [ts_code, trade_date]
            ).fetchone()
            if row:
                data = _json.loads(row[0])
                if data.get('schema_version', 1) != 1:
                    return None
                return data
        except Exception:
            pass
        return None

    def get_latest_signal_detail(self, ts_code: str) -> dict | None:
        """320号 F3：读取最新 trade_date 的策略信号详情（P2 日终产物）

        P2 预计算在日终运行（如 08-06），当天请求可能无当日记录，
        故按 ORDER BY trade_date DESC 取最新一条。
        """
        import json as _json
        try:
            row = self.read_conn.execute(
                "SELECT signal_json FROM strategy_signal_detail "
                "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", [ts_code]
            ).fetchone()
            if row:
                data = _json.loads(row[0])
                if data.get('schema_version', 1) != 1:
                    return None
                return data
        except Exception:
            pass
        return None

    def has_signal_detail(self, ts_code: str, trade_date: str = None) -> bool:
        """检查是否存在缓存"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        try:
            row = self.read_conn.execute(
                "SELECT 1 FROM strategy_signal_detail WHERE ts_code=? AND trade_date=?",
                [ts_code, trade_date]
            ).fetchone()
            return row is not None
        except Exception:
            return False

    # ==================== 原料加工特征缓存（357号方案 PRE-FEAT） ====================

    def cache_pre_feat(self, ts_code: str, trade_date: str, features: dict):
        """缓存原料加工特征提取结果（JSON格式，10组54字段）

        Args:
            ts_code: 股票代码
            trade_date: 交易日期 YYYY-MM-DD
            features: 特征字典（10组：valuation/sentiment/sector/style/timing/volume_price/chanlun/chip/event/depth）
        """
        import json as _json
        features_json = _json.dumps(features, ensure_ascii=False, default=str)
        with self._write_lock:
            try:
                self._execute(
                    """INSERT OR REPLACE INTO pre_feat_cache
                       (ts_code, trade_date, features_json, computed_at)
                       VALUES (?, ?, ?, datetime('now','localtime'))""",
                    [ts_code, trade_date, features_json]
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(f"缓存pre_feat失败 [{ts_code}]: {e}")

    def cache_pre_feat_batch(self, records: list[dict]):
        """批量缓存原料加工特征（用于日终管道批量写入）

        Args:
            records: [{ts_code, trade_date, features: dict}, ...]
        """
        import json as _json
        rows = []
        for r in records:
            features_json = _json.dumps(r.get('features', {}), ensure_ascii=False, default=str)
            rows.append((r['ts_code'], r['trade_date'], features_json))
        with self._write_lock:
            try:
                self._execute(
                    """INSERT OR REPLACE INTO pre_feat_cache
                       (ts_code, trade_date, features_json, computed_at)
                       VALUES (?, ?, ?, datetime('now','localtime'))""",
                    rows
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(f"批量缓存pre_feat失败: {e}")

    def get_pre_feat(self, ts_code: str, trade_date: str = None) -> dict | None:
        """读取原料加工特征缓存

        Returns:
            features dict（10组特征）或 None
        """
        import json as _json
        try:
            if trade_date:
                row = self.read_conn.execute(
                    "SELECT features_json FROM pre_feat_cache WHERE ts_code=? AND trade_date=?",
                    [ts_code, trade_date]
                ).fetchone()
            else:
                row = self.read_conn.execute(
                    "SELECT features_json FROM pre_feat_cache WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
                    [ts_code]
                ).fetchone()
            if row and row[0]:
                return _json.loads(row[0])
            return None
        except Exception as e:
            logger.warning(f"读取pre_feat失败 [{ts_code}]: {e}")
            return None

    def get_pre_feat_batch(self, ts_codes: list[str], trade_date: str = None) -> dict[str, dict]:
        """批量读取原料加工特征

        Returns:
            {ts_code: features_dict, ...}
        """
        import json as _json
        result = {}
        try:
            if trade_date:
                placeholders = ','.join(['?'] * len(ts_codes))
                rows = self.read_conn.execute(
                    f"SELECT ts_code, features_json FROM pre_feat_cache WHERE ts_code IN ({placeholders}) AND trade_date=?",
                    ts_codes + [trade_date]
                ).fetchall()
            else:
                placeholders = ','.join(['?'] * len(ts_codes))
                rows = self.read_conn.execute(
                    f"""SELECT ts_code, features_json FROM pre_feat_cache
                        WHERE ts_code IN ({placeholders})
                        AND trade_date = (SELECT MAX(trade_date) FROM pre_feat_cache)""",
                    ts_codes
                ).fetchall()
            for ts_code, features_json in rows:
                if features_json:
                    result[ts_code] = _json.loads(features_json)
        except Exception as e:
            logger.warning(f"批量读取pre_feat失败: {e}")
        return result

    def has_pre_feat(self, ts_code: str, trade_date: str = None) -> bool:
        """检查是否存在pre_feat缓存"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y-%m-%d')
        try:
            row = self.read_conn.execute(
                "SELECT 1 FROM pre_feat_cache WHERE ts_code=? AND trade_date=?",
                [ts_code, trade_date]
            ).fetchone()
            return row is not None
        except Exception:
            return False

    # ==================== 形态评分缓存（353/358号方案，356号分库：compute_cache.db） ====================

    def cache_pattern_score(self, ts_code: str, trade_date: str, score: float, details: dict):
        """缓存形态评分结果（356号方案：写入 compute_cache.db）

        Args:
            ts_code: 股票代码
            trade_date: 交易日期 YYYY-MM-DD
            score: 0-10 分
            details: 详细分解（bull_count, bear_count, patterns 等）
        """
        import json as _json
        details_json = _json.dumps(details, ensure_ascii=False, default=str)
        with self._write_lock:
            try:
                self.compute_conn.execute(
                    """INSERT OR REPLACE INTO pattern_score_cache
                       (ts_code, trade_date, score, details_json, computed_at)
                       VALUES (?, ?, ?, ?, datetime('now','localtime'))""",
                    [ts_code, trade_date, score, details_json]
                )
                self.compute_conn.commit()
            except Exception as e:
                logger.warning(f"缓存形态评分失败 [{ts_code}]: {e}")

    def get_pattern_score(self, ts_code: str, trade_date: str = None) -> dict | None:
        """读取形态评分缓存（356号方案：从 compute_cache.db 读取）

        Returns:
            {'score': float, 'details': dict} 或 None
        """
        import json as _json
        try:
            if trade_date:
                row = self.compute_read_conn.execute(
                    "SELECT score, details_json FROM pattern_score_cache WHERE ts_code=? AND trade_date=?",
                    [ts_code, trade_date]
                ).fetchone()
            else:
                row = self.compute_read_conn.execute(
                    "SELECT score, details_json FROM pattern_score_cache WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
                    [ts_code]
                ).fetchone()
            if row:
                return {'score': row[0], 'details': _json.loads(row[1])}
            return None
        except Exception as e:
            logger.warning(f"读取形态评分失败 [{ts_code}]: {e}")
            return None

    def has_pattern_score(self, ts_code: str, trade_date: str = None) -> bool:
        """检查是否存在形态评分缓存（356号方案：从 compute_cache.db 读取）"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y-%m-%d')
        try:
            row = self.compute_read_conn.execute(
                "SELECT 1 FROM pattern_score_cache WHERE ts_code=? AND trade_date=?",
                [ts_code, trade_date]
            ).fetchone()
            return row is not None
        except Exception:
            return False

    # ==================== 板块排行归档读取（288号方案 v1.1） ====================

    def read_as_sector_ranking(self) -> list[dict]:
        """读取归档的行业板块排行"""
        try:
            rows = self.read_conn.execute(
                "SELECT * FROM as_sector_ranking ORDER BY change_pct DESC"
            ).fetchall()
            if rows:
                cols = ['sector_name', 'ts_code', 'change_pct', 'up_count', 'down_count',
                        'lead_ts_code', 'lead_name', 'lead_change_pct', 'updated_at']
                return [dict(zip(cols, r)) for r in rows]
        except Exception:
            pass
        return []

    def read_as_concept_ranking(self) -> list[dict]:
        """读取归档的概念板块排行"""
        try:
            rows = self.read_conn.execute(
                "SELECT * FROM as_concept_ranking ORDER BY change_pct DESC"
            ).fetchall()
            if rows:
                cols = ['concept_name', 'ts_code', 'change_pct', 'up_count', 'down_count', 'updated_at']
                return [dict(zip(cols, r)) for r in rows]
        except Exception:
            pass
        return []

    # ==================== 实时快照数据库 ====================

    def cache_market_snapshot_data(self, records: list):
        """批量写入快照数据到独立 market_snapshot.db（INSERT OR REPLACE, batch write）"""
        if not records:
            return
        with self._snapshot_write_lock:
            try:
                cols = ['ts_code', 'code', 'name', 'price', 'open', 'high', 'low',
                    'prev_close', 'volume', 'amount',
                    'change', 'change_pct',
                    'bid1', 'ask1', 'bid_vol1', 'ask_vol1',
                    'bid2', 'ask2', 'bid_vol2', 'ask_vol2',
                    'bid3', 'ask3', 'bid_vol3', 'ask_vol3',
                    'bid4', 'ask4', 'bid_vol4', 'ask_vol4',
                    'bid5', 'ask5', 'bid_vol5', 'ask_vol5']
                rows = [tuple(r.get(c, 0) for c in cols) for r in records]
                col_list = ', '.join(cols)
                placeholders = ', '.join('?' for _ in cols)
                self.snapshot_conn.executemany(
                    f"INSERT OR REPLACE INTO as_market_snapshot ({col_list}) VALUES ({placeholders})",
                    rows
                )
                self.snapshot_conn.commit()
            except Exception as e:
                logger.warning(f"快照数据库写入失败: {e}")

    def get_market_snapshot(self, ts_code: str) -> dict:
        """查询单只股票的实时快照（用于 orderbook 端点）"""
        try:
            cur = self.snapshot_conn.execute(
                "SELECT * FROM as_market_snapshot WHERE ts_code = ?", [ts_code]
            )
            row = cur.fetchone()
            if row is None:
                return {}
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        except Exception as e:
            logger.debug(f"快照查询失败 ({ts_code}): {e}")
            return {}

    def get_all_market_snapshots(self, codes: list = None) -> list:
        """查询全市场或指定股票列表的实时快照（用于 SocketIO 推送）"""
        try:
            if codes:
                placeholders = ', '.join('?' for _ in codes)
                cur = self.snapshot_conn.execute(
                    f"SELECT * FROM as_market_snapshot WHERE ts_code IN ({placeholders})",
                    codes
                )
            else:
                cur = self.snapshot_conn.execute("SELECT * FROM as_market_snapshot")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.debug(f"批量快照查询失败: {e}")
            return []

    # ════════════════════════════════════════════════════════════
    # factor_cache 统一管理方法
    # ════════════════════════════════════════════════════════════

    def cache_factor_data(self, records):
        """批量写入因子数据"""
        if not records:
            return
        # 320号 L1：datetime/Timestamp 转字符串（SQLite 原生驱动不支持 datetime 参数绑定，
        # 原 cached_at=datetime.now() 导致 "parameter 5: type 'Timestamp'" 全市场失败）
        for r in records:
            if 'cached_at' in r and isinstance(r['cached_at'], (datetime, pd.Timestamp)):
                r['cached_at'] = r['cached_at'].strftime('%Y-%m-%d %H:%M:%S')
            if 'trade_date' in r and isinstance(r['trade_date'], (datetime, pd.Timestamp)):
                r['trade_date'] = r['trade_date'].strftime('%Y-%m-%d')
        with self._write_lock:
            # 356号方案：factor_cache 写入分库 compute_cache.db
            try:
                from app.data.sharding_manager import sharding_manager
                db_name = sharding_manager.get_db_for_table('factor_cache')
            except Exception:
                db_name = None

            if db_name:
                # 写入分库
                try:
                    # 检查分库表是否存在
                    shard_col_rows = sharding_manager.execute_query(
                        'factor_cache', 'PRAGMA table_info(factor_cache)')
                    shard_cols = {row[1] for row in shard_col_rows} if shard_col_rows else set()

                    if not shard_cols:
                        # 从总库复制表结构到分库
                        try:
                            main_sql = self.conn.execute(
                                "SELECT sql FROM sqlite_master WHERE type='table' AND name='factor_cache'"
                            ).fetchone()
                            if main_sql and main_sql[0]:
                                create_sql = main_sql[0].replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS')
                                sharding_manager.get_connection(db_name).execute(create_sql)
                                sharding_manager.get_connection(db_name).commit()
                                shard_col_rows = sharding_manager.execute_query(
                                    'factor_cache', 'PRAGMA table_info(factor_cache)')
                                shard_cols = {row[1] for row in shard_col_rows} if shard_col_rows else set()
                                logger.info(f"分库自动建表: factor_cache on {db_name}")
                        except Exception as e:
                            logger.warning(f"分库自动建表失败: factor_cache on {db_name}: {e}")

                    if shard_cols:
                        # 写入分库
                        cols = list(pd.DataFrame(records).columns)
                        col_list = ', '.join(f'"{c}"' for c in cols)
                        placeholders = ', '.join(['?' for _ in cols])
                        rows = [tuple(r[c] for c in cols) for _, r in pd.DataFrame(records).iterrows()]
                        sharding_manager.execute_batch_insert(
                            'factor_cache', f'INSERT OR REPLACE INTO factor_cache ({col_list}) VALUES ({placeholders})', rows)
                        logger.debug(f"factor_cache 写入分库 {db_name}: {len(rows)} 行")
                except Exception as e:
                    logger.warning(f"factor_cache 分库写入失败: {db_name}, {e}")
            else:
                # 非分库表 → 写入总库 stock_cache.db
                try:
                    self._insert_from_df('factor_cache', pd.DataFrame(records))
                    self.conn.commit()
                except Exception as e:
                    logger.warning(f"factor_cache 总库写入失败: {e}")

    def get_cached_factor(self, ts_code: str, factor_name: str):
        """获取单个因子序列"""
        df = self._query_shard('factor_cache',
            "SELECT trade_date, value FROM factor_cache "
            "WHERE ts_code = ? AND factor_name = ? ORDER BY trade_date",
            [ts_code, factor_name]
        )
        if df.empty:
            return None
        return pd.Series(df['value'].values, index=df['trade_date'])

    def get_cached_factors(self, ts_code: str) -> 'pd.DataFrame':
        """获取某股票所有因子"""
        return self._query_shard('factor_cache',
            "SELECT trade_date, factor_name, value FROM factor_cache "
            "WHERE ts_code = ? ORDER BY trade_date, factor_name",
            [ts_code]
        )

    def clean_factor_cache(self, cutoff: str):
        """清理 factor_cache 中早于 cutoff 的记录

        B4修复：cutoff 可能是 YYYYMMDD 或 YYYY-MM-DD 格式，
        trade_date 存储为 YYYY-MM-DD，需统一格式后比较。
        """
        # 统一 cutoff 为 YYYY-MM-DD 格式（兼容 YYYYMMDD 输入）
        if cutoff and len(cutoff) == 8 and cutoff.isdigit():
            cutoff = f"{cutoff[:4]}-{cutoff[4:6]}-{cutoff[6:8]}"
        self._exec_shard('factor_cache', "DELETE FROM factor_cache WHERE trade_date < ?", [cutoff])
        logger.info(f"清理 factor_cache (cutoff={cutoff})")

    # ════════════════════════════════════════════════════════════
    # 迭代5：数据清理（存储生命周期管理）
    # ════════════════════════════════════════════════════════════

    def clean_stk_limit_cache(self, cutoff: str):
        """清理 stk_limit_cache 中早于 cutoff 的记录"""
        sql = "DELETE FROM stk_limit_cache WHERE trade_date < ?"
        self._execute(sql, [cutoff])
        self.conn.commit()
        logger.info(f"清理 stk_limit_cache (cutoff={cutoff})")

    def clean_lhb_cache(self, cutoff: str):
        """清理 lhb_cache 中早于 cutoff 的记录"""
        self._execute("DELETE FROM lhb_cache WHERE trade_date < ?", [cutoff])
        self._execute("DELETE FROM lhb_detail_cache WHERE trade_date < ?", [cutoff])
        self.conn.commit()

    def clean_fina_indicator_cache(self, cutoff: str):
        """清理 fina_indicator_cache 中早于 cutoff 的记录"""
        self._execute("DELETE FROM fina_indicator_cache WHERE end_date < ?", [cutoff])
        self.conn.commit()

    def clean_minute_cache(self, cutoff: str):
        """清理 minute_kline_cache 中早于 cutoff 的记录"""
        self._execute("DELETE FROM minute_kline_cache WHERE trade_date < ?", [cutoff])
        self.conn.commit()

    def request_data(self, task_type: str, ts_code: str = None) -> int:
        """写 sync_requests 队列表：通知 data_daemon 异步补采

        342号核查修复（2026-08-16）：原实现用写连接 self.conn + busy_timeout=30s，
        与 daemon 主循环写冲突时阻塞 30s——P2 计算线程（compute_batch worker）在
        缠论多级别取数 miss 时逐级调用，北交所/次新股被逐只阻塞（920020.BJ 实测
        93.5s，其中 request_data 锁等待占主导）。sync_requests 为通知性质（可容忍
        少量丢失，daemon 完整性检查会兜底），改用独立短连接 + 短超时 + 失败静默，
        不阻塞计算线程。

        Args:
            task_type: 任务类型（full_daily/full_moneyflow/full_basic/per_stock/full_stock_list）
            ts_code: 股票代码（None 表示全市场）

        Returns:
            request_id
        """
        try:
            import sqlite3 as _sq
            req_conn = _sq.connect(self.db_path, timeout=2)
            req_conn.execute("PRAGMA busy_timeout=2000")
            cur = req_conn.execute(
                "INSERT INTO sync_requests (task_type, ts_code, status) VALUES (?, ?, 'pending')",
                [task_type, ts_code]
            )
            req_conn.commit()
            rid = cur.lastrowid
            req_conn.close()
            return rid
        except Exception:
            # 写失败静默降级：通知丢失由 daemon 完整性检查兜底（不阻塞计算）
            return 0

    def poll_data_ready(self, request_id: int) -> str:
        """轮询 sync_requests 状态

        Args:
            request_id: request_data() 返回的 id

        Returns:
            'pending' | 'running' | 'done' | 'failed'
        """
        row = self.read_conn.execute(
            "SELECT status FROM sync_requests WHERE id=?", [request_id]
        ).fetchone()
        return row[0] if row else 'unknown'

    def consume_pending_requests(self) -> list:
        """获取所有 pending 的 sync_requests（供 data_daemon 消费）"""
        rows = self.read_conn.execute(
            "SELECT id, task_type, ts_code, status FROM sync_requests WHERE status='pending' ORDER BY requested_at ASC"
        ).fetchall()
        return [{'id': r[0], 'task_type': r[1], 'ts_code': r[2], 'status': r[3]} for r in rows]

    def mark_request_done(self, request_id: int):
        """标记 sync_requests 为完成"""
        self.conn.execute(
            "UPDATE sync_requests SET status='done', completed_at=CURRENT_TIMESTAMP WHERE id=?",
            [request_id]
        )
        self.conn.commit()

    def mark_request_failed(self, request_id: int):
        """标记 sync_requests 为失败"""
        self.conn.execute(
            "UPDATE sync_requests SET status='failed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
            [request_id]
        )
        self.conn.commit()

    def write_tags(self, ts_code: str, tags: dict, trade_date: str = None):
        """批量写入 L2 标签到 opportunity_tags_cache"""
        if not tags:
            return
        from datetime import datetime
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        # 标签元数据映射（tag_name → (group, source)）
        # 覆盖 295号§三 全部 29 个核心标签 + 引擎额外产出标签。
        # 当引擎返回嵌套 dict {'value':v, 'group':g, 'source':s} 时优先使用引擎自描述。
        TAG_META: dict[str, tuple[str, str]] = {
            # ── direction 方向类（295号§3.1，7个） ──
            'trend_alignment':      ('direction',  'PhaseDetectionEngine'),
            'ma_alignment':         ('direction',  'VolumePriceStrategy'),
            'buy_sell_point':       ('direction',  'ChanlunAnalyzer'),
            'volume_price_fit':     ('direction',  'VolumePriceStrategy'),
            'pattern_signal':       ('direction',  'EnhancedPatternDetector'),
            'gap_type':             ('direction',  'VolumePriceStrategy'),
            'breakout_attempts':    ('direction',  'VolumePriceStrategy'),
            # ── position 位置类（295号§3.2，5个） ──
            'price_position':       ('position',   'PhaseDetectionEngine'),
            'valuation_level':      ('position',   'ValuationEngine'),
            'valuation_deviation':  ('position',   'ValuationEngine'),
            'chip_position':        ('position',   'ChipDistributionService'),
            'style_exposure':       ('position',   'PrecomputeL2Labels'),
            #  引擎额外产出
            'fcf_yield':            ('position',   'ValuationEngine'),
            'dividend_yield':       ('position',   'ValuationEngine'),
            'composite_rating':     ('position',   'ValuationEngine'),
            'pe_percentile_5y':     ('position',   'ValuationEngine'),
            'pb_percentile_5y':     ('position',   'ValuationEngine'),
            # ── quality 质量类（295号§3.3，7个） ──
            'main_force_phase':     ('quality',    'PhaseDetectionEngine'),
            'phase_confidence':     ('quality',    'PhaseDetectionEngine'),
            'fund_flow':            ('quality',    'PhaseDetectionEngine'),
            'capital_nature':       ('quality',    'MainForceScorer'),
            'chip_concentration':   ('quality',    'ChipDistributionService'),
            'fina_health':          ('quality',    'FinancialRiskFilter'),
            'roce_pass':            ('quality',    'FinancialRiskFilter'),
            # ── environment 环境类（295号§3.4，7个） ──
            'sentiment_phase':      ('environment','MarketSentimentService'),
            'sector_heat':          ('environment','SectorRotationModel'),
            'catalyst_event':       ('environment','EventMonitor'),
            'catalyst_impact':      ('environment','EventMonitor'),
            'volatility_level':     ('environment','VolumePriceStrategy'),
            'upward_driver':        ('environment','EventMonitor'),
            'time_rhythm':          ('environment','TimeRhythmEngine'),
            # ── derived 衍生（295号§3.5 signal_strength） ──
            'signal_strength':      ('derived',    'PrecomputeL2Labels'),
            # ── 机会元信息（307号§3.1：七维画像 + 类型摘要 + 证据计数） ──
            'opportunity_type':     ('derived',    'PrecomputeL2Labels'),
            'opportunity_label':    ('derived',    'PrecomputeL2Labels'),
            'opportunity_profile':  ('derived',    'PrecomputeL2Labels'),
            'evidence_count':       ('derived',    'PrecomputeL2Labels'),
            'confidence':           ('derived',    'PrecomputeL2Labels'),
            # ── 闸门2右侧确认（308号/309号 S3） ──
            'right_side_confirm':   ('derived',    'PrecomputeL2Labels'),
            'confirm_evidence':     ('derived',    'PrecomputeL2Labels'),
            # ── 三元框架入场/退出条件（307号§3.2/§3.3） ──
            'entry_signals':        ('derived',    'PrecomputeL2Labels'),
            'exit_conditions':      ('derived',    'PrecomputeL2Labels'),
            # ── 主力阶段判定（312号：8 维度加权共识，分歧显性化） ──
            'phase_conflict':       ('derived',    'PhaseDetectionEngine'),
            'phase_vote_ratio':     ('derived',    'PhaseDetectionEngine'),
            # ── 主力在场判定（313号 §十：行为证据主导） ──
            'main_force_presence':  ('derived',    'PrecomputeL2Labels'),
            'presence_evidence':    ('derived',    'PrecomputeL2Labels'),
            # ── 跨维仲裁（321号：机会状态机，唯一结论收敛层） ──
            'opportunity_state':    ('derived',    'PrecomputeL2Labels'),
            'state_evidence':       ('derived',    'PrecomputeL2Labels'),
            # ── 2026-08-10 标签库核查补注册（消除 unknown 归组遗漏） ──
            # 估值锚评级/PS分位/营收增长（ValuationEngine 同源 → position）
            'asset_anchor_rating':      ('position', 'ValuationEngine'),
            'earnings_anchor_rating':   ('position', 'ValuationEngine'),
            'cashflow_anchor_rating':   ('position', 'ValuationEngine'),
            'adjusted_anchor_rating':   ('position', 'ValuationEngine'),
            'ps_percentile_5y':         ('position', 'ValuationEngine'),
            'revenue_growth':           ('position', 'ValuationEngine'),
            # 财务质量（→ quality）
            'roe':                      ('quality',  'PrecomputeL2Labels'),
            # 潜力分解/证据总量（→ derived，与 signal_strength/evidence_count 同源）
            'potential_breakdown':      ('derived',  'PrecomputeL2Labels'),
            'evidence_total':           ('derived',  'PrecomputeL2Labels'),
            # 事件监控（→ environment）
            'event_composite_score':    ('environment', 'EventMonitor'),
            'event_summary':            ('environment', 'EventMonitor'),
        }

        # 标准化 tags 格式
        records = []
        now = datetime.now().isoformat()

        for tag_name, raw_value in tags.items():
            if raw_value is None:
                continue

            # 推断值类型
            if isinstance(raw_value, dict):
                value = raw_value.get('value', '')
                meta_default = TAG_META.get(tag_name, (None, None))
                group = raw_value.get('group', meta_default[0] or 'unknown')
                confidence = raw_value.get('confidence', 1.0)
                evidence = raw_value.get('evidence', '')
                source = raw_value.get('source', meta_default[1] or 'unknown')
            else:
                value = str(raw_value)
                meta = TAG_META.get(tag_name, ('unknown', 'unknown'))
                group = meta[0]
                source = meta[1]
                confidence = 1.0
                evidence = ''

            records.append({
                'ts_code': ts_code,
                'tag_name': tag_name,
                'tag_group': group,
                'tag_value': value,
                'confidence': confidence,
                'evidence': evidence if isinstance(evidence, str) else str(evidence),
                'source': source,
                'updated_at': now[:10],  # YYYY-MM-DD 格式用于 updated_at 查询匹配
            })

        if not records:
            return

        # 批量写入（含同步归档 tag_history，347号）
        with self._write_lock:
            for r in records:
                self.conn.execute(
                    """INSERT OR REPLACE INTO opportunity_tags_cache
                       (ts_code, tag_name, tag_group, tag_value,
                        confidence, evidence, source, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r['ts_code'], r['tag_name'], r['tag_group'], r['tag_value'],
                     r['confidence'], r['evidence'], r['source'], r['updated_at']]
                )
                # 347号：同步归档到 tag_history（ts_code+tag_name+updated_at 复合主键幂等）
                self.conn.execute(
                    """INSERT OR REPLACE INTO tag_history
                       (ts_code, tag_name, tag_group, tag_value,
                        confidence, evidence, source, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r['ts_code'], r['tag_name'], r['tag_group'], r['tag_value'],
                     r['confidence'], r['evidence'], r['source'], r['updated_at']]
                )
            self.conn.commit()

    def get_tags(self, ts_code: str) -> dict:
        """读取单只股票的最新标签（323号 S0：上限提至 200，避免深度标签落库后截断丢失）"""
        df = self._query_df(
            "SELECT tag_name, tag_value, tag_group, confidence, source, updated_at "
            "FROM opportunity_tags_cache WHERE ts_code=? "
            "ORDER BY updated_at DESC LIMIT 200",
            [ts_code]
        )
        if df.empty:
            return {}
        result = {}
        for _, row in df.iterrows():
            result[row['tag_name']] = row['tag_value']
        return result

    def get_tags_by_group(self, ts_code: str, groups: list[str]) -> dict:
        """按 tag_group 取子集（323号 S0.5：引擎B 差异化取用深度字段）

        从 opportunity_tags_cache 读取指定 tag_group 的最新标签，避免拉取全量。
        Returns: {tag_name: tag_value}
        """
        if not groups:
            return {}
        ph = ','.join('?' for _ in groups)
        df = self._query_df(
            f"SELECT tag_name, tag_value FROM opportunity_tags_cache "
            f"WHERE ts_code=? AND tag_group IN ({ph}) "
            f"ORDER BY updated_at DESC",
            [ts_code] + groups
        )
        if df.empty:
            return {}
        result = {}
        for _, row in df.iterrows():
            if row['tag_name'] not in result:   # 最新值优先
                result[row['tag_name']] = row['tag_value']
        return result

    def get_tags_by_date(self, ts_code: str, trade_date: str | None = None) -> dict:
        """读取指定股票在指定日期的标签 dict（2026-08-06 合规整改网关）

        未指定 trade_date 时返回该股票最新标签（等同 get_tags）。
        指定时精确匹配 updated_at=该交易日 的行（L4 日变检测语义）。
        """
        if trade_date is None:
            return self.get_tags(ts_code)
        try:
            df = self._query_df(
                "SELECT tag_name, tag_value FROM opportunity_tags_cache "
                "WHERE ts_code=? AND updated_at=?",
                [ts_code, trade_date]
            )
            if df.empty:
                return {}
            return {r['tag_name']: r['tag_value'] for _, r in df.iterrows()}
        except Exception as e:
            logger.warning(f"get_tags_by_date({ts_code},{trade_date}) 失败: {e}")
            return {}

    def get_snapshot_max_date(self) -> str | None:
        """获取 treemap_snapshot 最新构建日期（2026-08-06 合规整改网关）"""
        try:
            row = self.read_conn.execute(
                "SELECT MAX(snapshot_date) FROM treemap_snapshot"
            ).fetchone()
            return str(row[0]) if row and row[0] else None
        except Exception as e:
            logger.warning(f"get_snapshot_max_date 失败: {e}")
            return None

    def get_snapshot_data_date(self) -> str | None:
        """获取 treemap_snapshot 数据交易日（327阶段3：区分构建时间 vs 数据时间）"""
        try:
            row = self.read_conn.execute(
                "SELECT MAX(trade_date) FROM treemap_snapshot"
            ).fetchone()
            return str(row[0]) if row and row[0] else None
        except Exception as e:
            logger.warning(f"get_snapshot_data_date 失败: {e}")
            return None

    def get_snapshot_history(self, ts_code: str = None,
                             start_date: str = None, end_date: str = None,
                             table: str = 'status_snapshot_history') -> list[dict]:
        """读取快照历史（346号：多交易日快照保留，342号 §6.2 / G3.3 依赖）

        只读网关：调用层经 DataManager 访问，禁止直查。表不存在时返回空列表。
        """
        try:
            if table not in ('status_snapshot_history', 'treemap_snapshot_history'):
                logger.warning(f"get_snapshot_history 非法表名: {table}")
                return []
            sql = f"SELECT * FROM {table} WHERE 1=1"
            params = []
            if ts_code:
                sql += " AND ts_code=?"
                params.append(ts_code)
            if start_date:
                sql += " AND snapshot_date>=?"
                params.append(start_date)
            if end_date:
                sql += " AND snapshot_date<=?"
                params.append(end_date)
            sql += " ORDER BY snapshot_date, ts_code"
            rows = self.read_conn.execute(sql, params).fetchall()
            cols = [d[0] for d in self.read_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.warning(f"get_snapshot_history 失败: {e}")
            return []

    def get_tag_history(self, ts_code: str = None, tag_name: str = None,
                        start_date: str = None, end_date: str = None) -> list[dict]:
        """读取标签历史（347号：P4 写标签同步归档，支撑 L1.5 跨日标签核查）

        只读网关：调用层经 DataManager 访问，禁止直查。表不存在时返回空列表。
        """
        try:
            sql = "SELECT * FROM tag_history WHERE 1=1"
            params = []
            if ts_code:
                sql += " AND ts_code=?"
                params.append(ts_code)
            if tag_name:
                sql += " AND tag_name=?"
                params.append(tag_name)
            if start_date:
                sql += " AND updated_at>=?"
                params.append(start_date)
            if end_date:
                sql += " AND updated_at<=?"
                params.append(end_date)
            sql += " ORDER BY updated_at, ts_code, tag_name"
            rows = self.read_conn.execute(sql, params).fetchall()
            cols = [d[0] for d in self.read_conn.execute("SELECT * FROM tag_history LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.warning(f"get_tag_history 失败: {e}")
            return []

    def get_previous_trade_date(self) -> str | None:
        """获取上一交易日（daily_cache 倒数第二日，2026-08-06 合规整改网关）"""
        try:
            row = self.read_conn.execute(
                "SELECT DISTINCT trade_date FROM daily_cache "
                "ORDER BY trade_date DESC LIMIT 1 OFFSET 1"
            ).fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"get_previous_trade_date 失败: {e}")
            return None

    def query_tags(self, tag_filters: dict[str, list[str]], limit: int = 5000) -> list[dict]:
        """按标签组合查询股票（AND 逻辑）

        Args:
            tag_filters: {tag_name: [allowed_values, ...], ...}
                        例如 {'main_force_phase': ['building', 'lifting'], 'valuation_level': ['low', 'extreme_low']}
            limit: 最大返回数量

        Returns:
            [{ts_code, tag_name, tag_value, tag_group, updated_at}, ...]
        """
        if not tag_filters:
            return []

        conditions = list(tag_filters.items())
        first_tag, first_values = conditions[0]

        placeholders = ','.join('?' for _ in first_values)
        sql = f"""
            SELECT DISTINCT a.ts_code
            FROM opportunity_tags_cache a
            WHERE a.tag_name = ? AND a.tag_value IN ({placeholders})
        """
        params = [first_tag] + first_values

        for tag_name, values in conditions[1:]:
            ph = ','.join('?' for _ in values)
            sql += f"""
                INTERSECT
                SELECT ts_code FROM opportunity_tags_cache
                WHERE tag_name = ? AND tag_value IN ({ph})
            """
            params += [tag_name] + values

        sql += f" LIMIT {int(limit)}"

        try:
            rows = self.read_conn.execute(sql, params).fetchall()
            return [{'ts_code': r[0]} for r in rows]
        except Exception as e:
            logger.warning(f"query_tags failed: {e}")
            return []

    def get_tags_batch(self, ts_codes: list[str]) -> dict[str, dict]:
        """批量获取多只股票的最新标签

        Returns:
            {ts_code: {tag_name: tag_value, ...}, ...}
        """
        if not ts_codes:
            return {}

        placeholders = ','.join('?' for _ in ts_codes)
        try:
            df = self._query_df(
                f"""SELECT ts_code, tag_name, tag_value, tag_group, source, updated_at
                   FROM opportunity_tags_cache
                   WHERE ts_code IN ({placeholders})
                   ORDER BY ts_code, tag_name""",
                ts_codes
            )
        except Exception as e:
            logger.warning(f"get_tags_batch failed: {e}")
            return {}

        if df.empty:
            return {}

        result = {}
        for ts_code, grp in df.groupby('ts_code'):
            tags = {}
            for _, row in grp.iterrows():
                tags[row['tag_name']] = row['tag_value']
            result[ts_code] = tags
        return result

    def vacuum_db(self):
        """执行 VACUUM 回收空间（应在低负载时段执行）"""
        self.conn.execute("VACUUM")
        logger.info("VACUUM 完成")

    # ════════════════════════════════════════════════════════════
    # Treemap 快照（305号§2.2）
    # ════════════════════════════════════════════════════════════

    def get_treemap_snapshot(self, ts_codes: list[str]) -> pd.DataFrame:
        """从 treemap_snapshot 表批量读取快照数据"""
        if not ts_codes:
            return pd.DataFrame()

        # 367号方案：优先从分库读取
        try:
            from app.data.sharding_manager import sharding_manager
            if sharding_manager.table_exists('treemap_snapshot'):
                placeholders = ','.join(['?' for _ in ts_codes])
                query = f"SELECT * FROM treemap_snapshot WHERE ts_code IN ({placeholders})"
                df = sharding_manager.execute_query('treemap_snapshot', query, ts_codes)
                if df is not None and not df.empty:
                    import pandas as pd
                    return pd.DataFrame(df)
        except Exception as e:
            logger.debug(f"分库读取失败，降级到ECM: {e}")

        # 降级到ECM读取
        placeholders = ','.join(['?' for _ in ts_codes])
        return self._query_df(
            f"SELECT * FROM treemap_snapshot WHERE ts_code IN ({placeholders})",
            ts_codes
        )

    def get_treemap_snapshot_items(self, ts_codes: list[str]) -> list[dict]:
        """从 treemap_snapshot 读取并组装为 dict 列表（直接可用于 API 响应）"""
        df = self.get_treemap_snapshot(ts_codes)
        if df.empty:
            return []
        items = []
        # 317号：批量补齐快照表缺失的标签（style_exposure/catalyst_event 在标签表，不在快照表）
        # 318号 S5：追加 pe_percentile_5y/pb_percentile_5y（估值举证直白化依赖）
        extra_tags = self._get_latest_tags_for_codes(
            ts_codes,
            ['style_exposure', 'catalyst_event', 'pe_percentile_5y', 'pb_percentile_5y'],
        )
        for _, r in df.iterrows():
            dy = float(r['dividend_yield']) if pd.notna(r.get('dividend_yield')) else None

            def _sv(key: str):
                """取字符串值，将 pandas NaN 转为 None 避免 JSON 序列化输出非法 NaN"""
                v = r.get(key)
                return None if (v is None or (isinstance(v, float) and (v != v))) else v

            _ts = r['ts_code']
            _extra = extra_tags.get(_ts, {})
            items.append({
                'ts_code': _ts,
                'name': r['name'],
                'industry': _sv('industry') or '',
                'price': round(float(r['close']), 2) if pd.notna(r.get('close')) else 0,
                'pct_change': round(float(r['pct_chg']), 2) if pd.notna(r.get('pct_chg')) else 0,
                'open': float(r['open']) if pd.notna(r.get('open')) else None,
                'high': float(r['high']) if pd.notna(r.get('high')) else None,
                'low': float(r['low']) if pd.notna(r.get('low')) else None,
                'amplitude': float(r['amplitude']) if pd.notna(r.get('amplitude')) else None,
                'market_cap': round(float(r['total_mv']), 2) if pd.notna(r.get('total_mv')) else 0,
                'pe': float(r['pe']) if pd.notna(r.get('pe')) else None,
                'pb': float(r['pb']) if pd.notna(r.get('pb')) else None,
                'amount': float(r['amount']) if pd.notna(r.get('amount')) else None,
                'turnover_rate': float(r['turnover_rate']) if pd.notna(r.get('turnover_rate')) else None,
                'circ_mv': float(r['circ_mv']) if pd.notna(r.get('circ_mv')) else None,
                'dividend_yield': dy,
                'signal_strength': float(r['signal_strength']) if pd.notna(r.get('signal_strength')) else 0,
                'valuation_level': _sv('valuation_level'),
                'main_force_phase': _sv('main_force_phase'),
                'sentiment_phase': _sv('sentiment_phase'),
                'sector_heat': _sv('sector_heat'),
                'fina_health': _sv('fina_health'),
                'opportunity_type': _sv('opportunity_type'),
                'opportunity_label': _sv('opportunity_label'),
                'evidence_count': int(r['evidence_count']) if pd.notna(r.get('evidence_count')) else None,
                'right_side_confirm': _sv('right_side_confirm'),
                'main_force_presence': _sv('main_force_presence'),
                'presence_evidence': _sv('presence_evidence'),
                # 321号：跨维仲裁结论透出（机会状态机，前端颜色/建议/弹窗单源引用）
                'opportunity_state': _sv('opportunity_state'),
                'state_evidence': _sv('state_evidence'),
                'confirm_evidence': _sv('confirm_evidence'),
                'consensus_rate': float(r['consensus_rate']) if pd.notna(r.get('consensus_rate')) else None,
                'opportunity_profile': _sv('opportunity_profile'),
                'entry_signals': _sv('entry_signals'),
                'exit_conditions': _sv('exit_conditions'),
                'val_deviation': float(r['valuation_deviation']) if pd.notna(r.get('valuation_deviation')) else None,
                'tags': {
                    'trend_alignment': _sv('trend_alignment'),
                    'price_position': _sv('price_position'),
                    'fund_flow': _sv('fund_flow'),
                    'capital_nature': _sv('capital_nature'),
                    'chip_concentration': _sv('chip_concentration'),
                    'volatility_level': _sv('volatility_level'),
                    'dividend_yield': str(dy) if dy is not None else None,
                    'composite_rating': str(r['composite_rating']) if pd.notna(r.get('composite_rating')) else None,
                    # 317号：补齐快照缺失的风格/催化剂标签（前端筛选"高成长/白马股/有催化剂"依赖）
                    'style_exposure': _extra.get('style_exposure'),
                    'catalyst_event': _extra.get('catalyst_event'),
                    # 318号 S5：5 年估值分位（弹窗估值举证直白化依赖）
                    'pe_percentile_5y': _extra.get('pe_percentile_5y'),
                    'pb_percentile_5y': _extra.get('pb_percentile_5y'),
                },
                'snapshot': False,
            })
        return items

    def _get_latest_tags_for_codes(self, ts_codes: list[str], tag_names: list[str]) -> dict[str, dict]:
        """批量取多只股票多个标签的最新值（317号：快照缺 style_exposure/catalyst_event）

        Returns:
            {ts_code: {tag_name: tag_value}}（仅含最新 updated_at 的取值）
        """
        if not ts_codes or not tag_names:
            return {}
        out: dict[str, dict] = {}
        try:
            placeholders = ','.join('?' for _ in ts_codes)
            tag_ph = ','.join('?' for _ in tag_names)
            rows = self.read_conn.execute(
                f"""SELECT ts_code, tag_name, tag_value, updated_at
                    FROM opportunity_tags_cache
                    WHERE ts_code IN ({placeholders}) AND tag_name IN ({tag_ph})
                    ORDER BY ts_code, tag_name, updated_at DESC""",
                ts_codes + tag_names
            ).fetchall()
            # 行已按 updated_at DESC 排序，首个出现的 (ts_code, tag_name) 即最新值
            seen: set[tuple] = set()
            for ts, tag, val, _upd in rows:
                key = (ts, tag)
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(ts, {})[tag] = val
        except Exception as e:
            logger.warning(f"_get_latest_tags_for_codes failed: {e}")
        return out

    # ════════════════════════════════════════════════════════════
    # 管道状态（305号§9.2）
    # ════════════════════════════════════════════════════════════

    def load_pipeline_status(self, pipeline_date: str) -> dict[str, dict]:
        """读取指定交易日所有环节状态，返回 {step_id: row_dict}"""
        try:
            cur = self.read_conn.execute(
                "SELECT * FROM pipeline_status WHERE pipeline_date=? ORDER BY step_id",
                [pipeline_date]
            )
            cols = [d[0] for d in cur.description]
            return {r[1]: dict(zip(cols, r)) for r in cur.fetchall()}
        except Exception:
            return {}

    def ensure_pipeline_steps(self, pipeline_date: str):
        """确保当日管道环节记录存在（幂等）— 353号方案统一命名"""
        for step_id, step_name in [
            ('COL-1', '日线采集'), ('COL-2', '基本面采集'), ('COL-3', '资金流采集'),
            ('COL-4', '涨跌停采集'), ('COL-5', '龙虎榜采集'), ('COL-6', '概念板块采集'),
            ('RAW-1', '技术指标(IND)'), ('RAW-2', '特征提取(FEAT)'), ('RAW-3', '量化因子(FAC)'),
            ('SIG', '策略分析'), ('JUD', '判定及操作建议'), ('OUT', '成品仓'),
        ]:
            self.conn.execute(
                "INSERT OR IGNORE INTO pipeline_status "
                "(pipeline_date, step_id, step_name) VALUES (?, ?, ?)",
                [pipeline_date, step_id, step_name]
            )
        self.conn.commit()

    def mark_step_running(self, pipeline_date: str, step_id: str, timeout_hours: float = 4.0) -> bool:
        """尝试将环节标记为 running（幂等锁 + running 超时自动重置），成功返回 True

        2026-08-10 修复：支持 failed → running 重试（原仅 pending→running，
        导致 P3 failed 后管道永久卡死——_drive_pipeline 对 failed 步骤调用本方法
        但 UPDATE 0 行即返回，重试分支永远到不了）。
        2026-08-12 修复（327阶段1）：running 超过 timeout_hours（默认4h，远大于
        最长环节 P2=1.6h）自动重置为 pending——daemon 重启/卡死后旧 running
        记录不再永久阻塞管道（P4/S1 永不触发，快照陈旧）。
        """
        # 先处理超时的 running（4h 内未完成的环节视为中断，重置为 pending）
        self.conn.execute(
            "UPDATE pipeline_status SET status='pending', detail='timeout 自动重置' "
            "WHERE pipeline_date=? AND step_id=? AND status='running' "
            "AND started_at < datetime('now', ?)",
            [pipeline_date, step_id, f'-{int(timeout_hours)} hours']
        )
        rc = self.conn.execute(
            "UPDATE pipeline_status SET status='running', started_at=CURRENT_TIMESTAMP "
            "WHERE pipeline_date=? AND step_id=? AND status IN ('pending', 'failed')",
            [pipeline_date, step_id]
        ).rowcount
        return rc > 0

    def mark_step_done(self, pipeline_date: str, step_id: str, detail: str = ''):
        self.conn.execute(
            "UPDATE pipeline_status SET status='done', completed_at=CURRENT_TIMESTAMP, detail=? "
            "WHERE pipeline_date=? AND step_id=?",
            [detail, pipeline_date, step_id]
        )
        self.conn.commit()

    def mark_step_failed(self, pipeline_date: str, step_id: str, detail: str = ''):
        self.conn.execute(
            "UPDATE pipeline_status SET status='failed', completed_at=CURRENT_TIMESTAMP, detail=? "
            "WHERE pipeline_date=? AND step_id=?",
            [detail, pipeline_date, step_id]
        )
        self.conn.commit()

    # ════════════════════════════════════════════════════════════
    # 372号§九：新增ECM方法（市场级聚合统计+状态查询+写入）
    # ════════════════════════════════════════════════════════════

    def get_market_ma20_ratio(self) -> float:
        """全市场MA20比率：收盘价>MA20的股票占比"""
        try:
            row = self._query_df("""
                SELECT COUNT(CASE WHEN d.close > m.close THEN 1 END) as above,
                       COUNT(*) as total
                FROM daily_cache d
                JOIN indicator_ma m ON d.ts_code = m.ts_code AND d.trade_date = m.trade_date
                WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_cache)
            """).iloc[0]
            return row['above'] / row['total'] if row['total'] > 0 else 0.5
        except Exception:
            return 0.5

    def get_market_turnover_percentile(self) -> float:
        """全市场换手率百分位（中位数归一化）"""
        try:
            df = self._query_df("""
                SELECT turnover_rate FROM daily_basic_cache
                WHERE trade_date = (SELECT MAX(trade_date) FROM daily_basic_cache)
                AND turnover_rate IS NOT NULL
            """)
            if df.empty:
                return 0.5
            median = df['turnover_rate'].median()
            return min(1.0, median / 10.0) if median else 0.5
        except Exception:
            return 0.5

    def get_market_limit_ratio(self) -> dict:
        """涨跌停比率"""
        try:
            df = self._query_df("""
                SELECT SUM(CASE WHEN change_pct >= 9.9 THEN 1 ELSE 0 END) as up_limit,
                       SUM(CASE WHEN change_pct <= -9.9 THEN 1 ELSE 0 END) as down_limit,
                       COUNT(*) as total
                FROM daily_cache
                WHERE trade_date = (SELECT MAX(trade_date) FROM daily_cache)
            """)
            if df.empty or df.iloc[0]['total'] == 0:
                return {'up': 0.0, 'down': 0.0}
            r = df.iloc[0]
            return {'up': r['up_limit'] / r['total'], 'down': r['down_limit'] / r['total']}
        except Exception:
            return {'up': 0.0, 'down': 0.0}

    def get_market_rsi_percentile(self) -> float:
        """RSI14百分位"""
        try:
            df = self._query_df("""
                SELECT rsi14 FROM indicator_other
                WHERE trade_date = (SELECT MAX(trade_date) FROM indicator_other)
                AND rsi14 IS NOT NULL
            """)
            if df.empty:
                return 0.5
            median = df['rsi14'].median()
            return median / 100.0 if median else 0.5
        except Exception:
            return 0.5

    def get_market_erp_percentile(self) -> float:
        """ERP（股权风险溢价）百分位"""
        try:
            df = self._query_df("""
                SELECT pe_ttm FROM daily_basic_cache
                WHERE trade_date = (SELECT MAX(trade_date) FROM daily_basic_cache)
                AND pe_ttm > 0
            """)
            if df.empty:
                return 0.5
            median_pe = df['pe_ttm'].median()
            erp = (1.0 / median_pe) if median_pe and median_pe > 0 else 0.03
            return min(1.0, erp / 0.08) if erp else 0.5
        except Exception:
            return 0.5

    def get_market_margin_trend(self) -> dict:
        """融资趋势（5日变化率）"""
        try:
            df = self._query_df("""
                SELECT trade_date, SUM(rzye) as total
                FROM margin_cache
                WHERE trade_date >= date('now', '-10 days')
                GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
            """)
            if len(df) < 2:
                return {'trend': 'neutral', 'change_pct': 0.0}
            oldest = df.iloc[-1]['total'] or 1
            newest = df.iloc[0]['total'] or 1
            change_pct = (newest - oldest) / oldest
            trend = 'up' if change_pct > 0.01 else ('down' if change_pct < -0.01 else 'neutral')
            return {'trend': trend, 'change_pct': round(change_pct, 4)}
        except Exception:
            return {'trend': 'neutral', 'change_pct': 0.0}

    def get_market_pe_median_percentile(self) -> float:
        """PE_TTM中位数百分位"""
        try:
            df = self._query_df("""
                SELECT pe_ttm FROM daily_basic_cache
                WHERE trade_date = (SELECT MAX(trade_date) FROM daily_basic_cache)
                AND pe_ttm > 0
            """)
            if df.empty:
                return 0.5
            median_pe = df['pe_ttm'].median()
            return min(1.0, median_pe / 100.0) if median_pe else 0.5
        except Exception:
            return 0.5

    def get_status_snapshot_row(self, ts_code: str) -> dict:
        """读取status_snapshot行（含dim_engine_results）"""
        try:
            df = self._query_df(
                "SELECT * FROM status_snapshot WHERE ts_code=? LIMIT 1", [ts_code])
            if df.empty:
                return {}
            return df.iloc[0].to_dict()
        except Exception:
            return {}

    def get_cache_freshness_stats(self) -> dict:
        """多表新鲜度统计"""
        tables = {
            'daily_cache': 'SELECT MAX(trade_date) as latest, COUNT(*) as cnt FROM daily_cache',
            'daily_basic_cache': 'SELECT MAX(trade_date) as latest, COUNT(*) as cnt FROM daily_basic_cache',
            'moneyflow_cache': 'SELECT MAX(trade_date) as latest, COUNT(*) as cnt FROM moneyflow_cache',
            'strategy_signal_detail': 'SELECT MAX(trade_date) as latest, COUNT(*) as cnt FROM strategy_signal_detail',
            'treemap_snapshot': 'SELECT MAX(snapshot_date) as latest, COUNT(*) as cnt FROM treemap_snapshot',
        }
        results = {}
        for name, query in tables.items():
            try:
                row = self.conn.execute(query).fetchone()
                results[name] = {
                    'latest_date': str(row[0]) if row[0] else None,
                    'count': row[1],
                }
            except Exception as e:
                results[name] = {'error': str(e)}
        return results

    def get_pipeline_step_status(self, date: str = None) -> list:
        """管道步骤状态查询"""
        try:
            if date is None:
                row = self.conn.execute(
                    "SELECT pipeline_date FROM pipeline_status GROUP BY pipeline_date ORDER BY pipeline_date DESC LIMIT 1"
                ).fetchone()
                date = row[0] if row else None
            if not date:
                return []
            df = self._query_df(
                "SELECT step_id, status, started_at, completed_at, detail FROM pipeline_status WHERE pipeline_date=?",
                [date])
            return df.to_dict('records') if not df.empty else []
        except Exception:
            return []

    def get_all_active_codes(self) -> list:
        """获取所有活跃股票代码"""
        try:
            df = self._query_df(
                "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date = (SELECT MAX(trade_date) FROM daily_cache)")
            return df['ts_code'].tolist() if not df.empty else []
        except Exception:
            return []

    def write_signal_record(self, record: dict):
        """写入信号记录到app.db"""
        try:
            import sqlite3 as _sqlite3
            import os
            app_db = os.path.join(os.getenv('DATA_DIR', 'data'), 'app.db')
            with _sqlite3.connect(app_db) as conn:
                cols = list(record.keys())
                placeholders = ','.join(['?' for _ in cols])
                conn.execute(
                    f"INSERT OR REPLACE INTO signal_records ({','.join(cols)}) VALUES ({placeholders})",
                    [record[c] for c in cols])
        except Exception as e:
            logger.warning(f"写入信号记录失败: {e}")

    def save_factor_combination(self, data: dict):
        """保存因子组合到factor_combinations表"""
        try:
            import sqlite3 as _sqlite3
            import os
            app_db = os.path.join(os.getenv('DATA_DIR', 'data'), 'factor_combos.db')
            with _sqlite3.connect(app_db) as conn:
                cols = list(data.keys())
                placeholders = ','.join(['?' for _ in cols])
                conn.execute(
                    f"INSERT OR REPLACE INTO factor_combinations ({','.join(cols)}) VALUES ({placeholders})",
                    [data[c] for c in cols])
                conn.commit()
        except Exception as e:
            logger.warning(f"保存因子组合失败: {e}")
