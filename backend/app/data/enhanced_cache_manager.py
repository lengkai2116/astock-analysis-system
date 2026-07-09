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

import os
import sqlite3
import pandas as pd
import logging
import time
import shutil
from datetime import datetime, timedelta
import threading
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
        self.conn.execute("PRAGMA busy_timeout=5000")    # 等待 5s 而非立刻报错

        self._init_tables()

        self.cache_stats = {
            'hits_duckdb': 0,  # 保留旧字段名兼容
            'misses': 0,
            'total_requests': 0
        }

    # ── 工具方法 ─────────────────────────────────────────────

    def _insert_from_df(self, table: str, df: pd.DataFrame):
        """将 DataFrame 批量写入 SQLite 表（动态列名，兼容列顺序差异）"""
        if df.empty:
            return
        cols = list(df.columns)
        col_list = ', '.join(f'"{c}"' for c in cols)
        placeholders = ', '.join(['?' for _ in cols])
        rows = [tuple(r[c] for c in cols) for _, r in df.iterrows()]
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
            rows
        )
        self.conn.commit()

    def _query_df(self, sql: str, params=None) -> pd.DataFrame:
        """执行查询并返回 DataFrame（替代 DuckDB 的 fetchdf()）"""
        try:
            return pd.read_sql(sql, self.conn, params=params)
        except Exception as e:
            logger.warning(f"SQLite 查询失败: {e}")
            return pd.DataFrame()

    def _execute(self, sql: str, params=None):
        try:
            self.conn.execute(sql, params or [])
        except Exception as e:
            logger.warning(f"SQLite 执行失败: {e}")

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
        self._execute("""
            CREATE TABLE IF NOT EXISTS indicator_cache (
                ts_code TEXT, trade_date TEXT, indicator_name TEXT,
                value REAL, cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, indicator_name)
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
        self._execute("""
            CREATE TABLE IF NOT EXISTS as_quote_cache (
                ts_code TEXT PRIMARY KEY,
                bid_price REAL, bid_volume INTEGER,
                ask_price REAL, ask_volume INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
            CREATE TABLE IF NOT EXISTS top10_holders_cache (
                ts_code TEXT, end_date TEXT, ann_date TEXT,
                holder_name TEXT, hold_amount REAL, hold_ratio REAL,
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
            "CREATE INDEX IF NOT EXISTS idx_top10_ts ON top10_holders_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stk_holder_ts ON stk_holder_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_concept_ts ON concept_cache(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_index_member_code ON index_member_cache(index_code)",
        ]:
            try:
                self.conn.execute(idx_sql)
            except Exception:
                pass
        self.conn.commit()

    # ════════════════════════════════════════════════════════════
    # 业务方法（以下方法签名与 DuckDB 版本完全一致）
    # ════════════════════════════════════════════════════════════

    # ── 日线 ─────────────────────────────────────────────────

    def get_cached_daily(self, ts_code, start_date=None, end_date=None):
        self.cache_stats['total_requests'] += 1
        query = "SELECT * FROM daily_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date"
        df = self._query_df(query, params)
        if not df.empty:
            self.cache_stats['hits_duckdb'] += 1
        else:
            self.cache_stats['misses'] += 1
        return df

    def preload_all(self):
        """预加载全量日线到内存（加速批量筛选）"""
        if getattr(self, '_all_daily', None) is None:
            self._all_daily = self._query_df("SELECT * FROM daily_cache ORDER BY ts_code, trade_date")
            logger.info(f"日线预加载: {len(self._all_daily)} 行")

    def get_cached_daily_batch(self, ts_codes, start_date=None, end_date=None):
        """批量获取多只股票的日线数据（使用全量预加载 + 自动加载）"""
        df = getattr(self, '_all_daily', None)
        if df is None:
            df = self._query_df("SELECT * FROM daily_cache ORDER BY ts_code, trade_date")
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
        # 过滤 DataFrame 列到表结构子集：Tushare 可能新增字段（如 pre_close）
        table_cols = {r[1] for r in self.conn.execute(f'PRAGMA table_info(daily_cache)').fetchall()}
        extra = set(df.columns) - table_cols
        if extra:
            logger.warning(f"忽略 daily_cache 中不存在的列: {extra}")
            df = df[[c for c in df.columns if c in table_cols]]
        with self._write_lock:
            self._insert_from_df('daily_cache', df)
            self._update_metadata('last_cache_time', datetime.now().isoformat())

    # ── 指标 ─────────────────────────────────────────────────

    def get_indicator_data(self, ts_code, indicator_name):
        self.cache_stats['total_requests'] += 1
        df = self._query_df(
            "SELECT * FROM indicator_cache WHERE ts_code = ? AND indicator_name = ? ORDER BY trade_date",
            [ts_code, indicator_name]
        )
        if not df.empty:
            self.cache_stats['hits_duckdb'] += 1
        else:
            self.cache_stats['misses'] += 1
        return df

    def cache_indicator(self, ts_code, trade_date, indicator_name, value):
        with self._write_lock:
            self._execute(
                "INSERT OR REPLACE INTO indicator_cache (ts_code, trade_date, indicator_name, value) VALUES (?, ?, ?, ?)",
                [ts_code, trade_date, indicator_name, value]
            )
            self.conn.commit()

    def batch_cache_indicators(self, records):
        if not records:
            return
        with self._write_lock:
            self._insert_from_df('indicator_cache', pd.DataFrame(records))

    # ── 内存缓存 ────────────────────────────────────────────

    def get_from_memory(self, key: str, level: str = 'realtime'):
        return self.memory_cache.get(key, level)

    def set_to_memory(self, key: str, value, level: str = 'realtime'):
        self.memory_cache.set(key, value, level)

    # ── 统计 ─────────────────────────────────────────────────

    def get_cache_stats(self):
        try:
            daily_count = self.conn.execute("SELECT COUNT(*) FROM daily_cache").fetchone()[0]
            indicator_count = self.conn.execute("SELECT COUNT(*) FROM indicator_cache").fetchone()[0]
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

    def clear_old_cache(self, days=30):
        return self.invalidate_old_data(days)

    # ── 连接管理 ─────────────────────────────────────────────

    def close(self):
        try:
            self.conn.close()
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
        all_df = getattr(self, '_all_daily_basic', None)
        if all_df is not None:
            m = all_df['ts_code'] == ts_code
            if start_date:
                m &= all_df['trade_date'] >= start_date
            if end_date:
                m &= all_df['trade_date'] <= end_date
            df = all_df[m].copy()
            if not df.empty:
                return df
        query = "SELECT * FROM daily_basic_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date"
        return self._query_df(query, params)

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
        return self._query_df(query, params)

    def get_latest_chip_distribution(self, ts_code):
        return self._query_df("""
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
                # 过滤 DataFrame 列到表结构子集
                table_cols = {r[1] for r in self.conn.execute(f'PRAGMA table_info(moneyflow_cache)').fetchall()}
                extra = set(df.columns) - table_cols
                if extra:
                    logger.warning(f"忽略 moneyflow_cache 中不存在的列: {extra}")
                    df = df[[c for c in df.columns if c in table_cols]]
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
            query += " AND ts_code = ?"; params.append(ts_code)
        if trade_date:
            query += " AND trade_date = ?"; params.append(trade_date)
        if start_date:
            query += " AND trade_date >= ?"; params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"; params.append(end_date)
        query += " ORDER BY trade_date, ts_code"
        return self._query_df(query, params)

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
        df = self._query_df(query, params)
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
            df = self._query_df("SELECT * FROM win_rate_cache WHERE signal_type = ?", [signal_type])
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
        if not records:
            return
        try:
            self._insert_from_df('as_market_snapshot', pd.DataFrame(records))
        except Exception:
            pass

    def write_as_top_stocks(self, rank_type: str, records: list):
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
        if df.empty:
            return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self._insert_from_df('adj_factor_cache', df)
                self._update_metadata('last_adj_factor_cache_time', datetime.now().isoformat())
            except Exception as e:
                logger.warning(f"缓存复权因子失败: {e}")

    def get_cached_adj_factor(self, ts_code=None, start_date=None, end_date=None):
        query = "SELECT * FROM adj_factor_cache WHERE 1=1"
        params = []
        if ts_code:
            query += " AND ts_code = ?"; params.append(ts_code)
        if start_date:
            query += " AND trade_date >= ?"; params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"; params.append(end_date)
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
        query = "SELECT * FROM minute_kline_cache WHERE ts_code = ?"
        params = [ts_code]
        if trade_date:
            query += " AND trade_date = ?"; params.append(trade_date)
        query += " AND freq = ?"; params.append(freq)
        query += " ORDER BY trade_time"
        return self._query_df(query, params)

    # ==================== 252号方案：财务指标 ====================

    def cache_fina_indicator_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('fina_indicator_cache', df)
            except Exception as e:
                logger.warning(f"缓存财务指标失败: {e}")

    def get_cached_fina_indicator(self, ts_code):
        return self._query_df(
            "SELECT * FROM fina_indicator_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：利润表 ====================

    def cache_income_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('income_cache', df)
            except Exception as e:
                logger.warning(f"缓存利润表失败: {e}")

    def get_cached_income(self, ts_code):
        return self._query_df(
            "SELECT * FROM income_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：资产负债表 ====================

    def cache_balancesheet_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('balancesheet_cache', df)
            except Exception as e:
                logger.warning(f"缓存资产负债表失败: {e}")

    def get_cached_balancesheet(self, ts_code):
        return self._query_df(
            "SELECT * FROM balancesheet_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：现金流量表 ====================

    def cache_cashflow_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('cashflow_cache', df)
            except Exception as e:
                logger.warning(f"缓存现金流量表失败: {e}")

    def get_cached_cashflow(self, ts_code):
        return self._query_df(
            "SELECT * FROM cashflow_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：业绩预告 ====================

    def cache_forecast_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                self._insert_from_df('forecast_cache', df)
            except Exception as e:
                logger.warning(f"缓存业绩预告失败: {e}")

    def get_cached_forecast(self, ts_code):
        return self._query_df(
            "SELECT * FROM forecast_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：融资融券 ====================

    def cache_margin_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self._insert_from_df('margin_cache', df)
            except Exception as e:
                logger.warning(f"缓存融资融券失败: {e}")

    def get_cached_margin(self, ts_code, start_date=None, end_date=None):
        query = "SELECT * FROM margin_cache WHERE ts_code = ?"
        params = [ts_code]
        if start_date:
            query += " AND trade_date >= ?"; params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"; params.append(end_date)
        query += " ORDER BY trade_date"
        return self._query_df(query, params)

    # ==================== 252号方案：涨跌停 ====================

    def cache_stk_limit_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
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
        if df.empty: return
        with self._write_lock:
            try:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self._insert_from_df('lhb_cache', df)
            except Exception as e:
                logger.warning(f"缓存龙虎榜失败: {e}")

    def get_cached_lhb(self, trade_date):
        return self._query_df(
            "SELECT * FROM lhb_cache WHERE trade_date = ? ORDER BY net_amount DESC",
            [trade_date]
        )

    # ==================== 252号方案：前十大股东 ====================

    def cache_top10_holders(self, df):
        if df.empty: return
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
        return self._query_df(
            "SELECT * FROM top10_holders_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：股东人数 ====================

    def cache_stk_holder_data(self, df):
        if df.empty: return
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
        return self._query_df(
            "SELECT * FROM stk_holder_cache WHERE ts_code = ? ORDER BY end_date DESC",
            [ts_code]
        )

    # ==================== 252号方案：概念分类 ====================

    def cache_concept_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                self._insert_from_df('concept_cache', df)
            except Exception as e:
                logger.warning(f"缓存概念分类失败: {e}")

    def get_cached_concept(self, ts_code=None):
        query = "SELECT * FROM concept_cache"
        params = []
        if ts_code:
            query += " WHERE ts_code = ?"; params.append(ts_code)
        return self._query_df(query, params)

    # ==================== 252号方案：指数成分股 ====================

    def cache_index_member_data(self, df):
        if df.empty: return
        with self._write_lock:
            try:
                self._insert_from_df('index_member_cache', df)
            except Exception as e:
                logger.warning(f"缓存指数成分股失败: {e}")

    def get_cached_index_member(self, index_code):
        return self._query_df(
            "SELECT * FROM index_member_cache WHERE index_code = ?",
            [index_code]
        )
