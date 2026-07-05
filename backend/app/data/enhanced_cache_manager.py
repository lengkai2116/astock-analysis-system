import os
import duckdb
import pandas as pd
import logging
import time
import shutil

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
import threading
from .memory_cache import TieredMemoryCache

# 全局 ECM 单例（解决多个实例连接同一 DuckDB 文件冲突）
_ecm_instance = None
_ecm_lock = threading.Lock()


def get_ecm_instance() -> 'EnhancedCacheManager':
    """获取全局共享的 EnhancedCacheManager 单例。DataManager 等模块应调用此函数而非 new EnhancedCacheManager()"""
    global _ecm_instance
    if _ecm_instance is None:
        with _ecm_lock:
            if _ecm_instance is None:
                _ecm_instance = EnhancedCacheManager()
    return _ecm_instance


def _clean_stale_duckdb_locks(data_dir: str):
    """启动前清理 DuckDB 僵尸锁文件（.wal / .tmp）"""
    db_dir = os.path.join(data_dir, "duckdb")
    if not os.path.isdir(db_dir):
        return
    now = time.time()
    for fname in os.listdir(db_dir):
        if fname.endswith(".wal") or fname.endswith(".tmp"):
            fpath = os.path.join(db_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                # 超过 60 秒的锁文件 -> 僵尸进程残留，删除
                if now - mtime > 60:
                    os.remove(fpath)
                    logger.warning(f"已清理僵尸锁文件: {fpath}")
            except (OSError, FileNotFoundError):
                pass


def _kill_stale_duckdb_pids(db_path: str):
    """启动时清理持有 DuckDB 文件锁的旧进程（来自热重载崩溃遗留）"""
    try:
        import subprocess
        result = subprocess.run(
            ['lsof', '-F', 'p', db_path],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if line.startswith('p'):
                pid = int(line[1:])
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, 9)
                    logger.warning(f"已 kill 旧 DuckDB 进程 PID {pid}")
                except (OSError, ProcessLookupError):
                    pass
    except Exception:
        pass  # lsof 不可用时静默跳过


class EnhancedCacheManager:
    """
    增强型缓存管理器
    包含：
    - DuckDB主缓存
    - 缓存失效策略
    - 缓存命中率统计
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._write_lock = threading.RLock()
        self.memory_cache = TieredMemoryCache()
        
        # DuckDB配置 - 性能优化版
        # 修复: 默认值从 '/data' 改为 Config.DATA_DIR（之前使用了硬编码默认值，导致
        #       DATA_DIR 未设置时 ECM 试图连接 /data/duckdb/ 而非实际数据目录）
        data_dir = os.getenv('DATA_DIR') or (
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), 'data')
        )
        self.db_path = os.path.join(data_dir, 'duckdb', 'stock_cache.db')

        # 启动前清理僵尸锁文件（避免上次崩溃残留 .wal/.tmp 阻塞连接）
        _clean_stale_duckdb_locks(data_dir)

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # 创建临时目录
        temp_dir = os.path.join(data_dir, 'duckdb', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # 性能优化配置
        duckdb_config = {
            'threads': os.cpu_count() or 4,
            'memory_limit': '4GB',
            'enable_external_access': 'false',
            'max_memory': '4GB',
            'temp_directory': temp_dir
        }

        # 尝试 kill 旧 DuckDB PID（热重载遗留的锁持有者）
        _kill_stale_duckdb_pids(self.db_path)

        # 连接 DuckDB（带重试，指数退避 1s→2s→4s）
        _last_err = None
        for attempt in range(3):
            try:
                self.conn = duckdb.connect(self.db_path, config=duckdb_config, read_only=False)
                try:
                    self.conn.execute("PRAGMA enable_object_cache")
                except Exception:
                    pass
                try:
                    self.conn.execute("PRAGMA force_index_scan")
                except Exception:
                    pass
                break
            except Exception as e:
                _last_err = e
                if attempt < 2:
                    import time
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(f"DuckDB 连接重试 (attempt={attempt+1}/3, wait={wait}s): {e}")
                    time.sleep(wait)
        else:
            logger.warning(f"DuckDB 主库连接失败（3次重试均失败）: {_last_err}")
            # 降级策略：先尝试备份库，再创建新库，最后用内存模式
            backup_path = self.db_path + '.backup'
            try:
                self.conn = duckdb.connect(backup_path, config=duckdb_config, read_only=False)
                logger.info(f"成功连接到备份库: {backup_path}")
            except Exception as e2:
                logger.warning(f"备份库连接也失败: {e2}")
                try:
                    # 保留损坏的数据库文件（不覆盖），创建新的空库
                    if os.path.exists(self.db_path):
                        import shutil
                        rotated_path = self.db_path + f'.corrupted.{int(time.time())}'
                        shutil.copy2(self.db_path, rotated_path)
                        logger.info(f"已将损坏的数据库备份到: {rotated_path}")
                        # 限制 corrupted 文件最大数量（防止热重载无限膨胀）
                        try:
                            dir_name = os.path.dirname(self.db_path)
                            pattern = os.path.basename(self.db_path) + '.corrupted.*'
                            backups = sorted([
                                os.path.join(dir_name, f) for f in os.listdir(dir_name)
                                if f.startswith(os.path.basename(self.db_path) + '.corrupted.')
                            ])
                            while len(backups) >= 3:
                                os.remove(backups.pop(0))
                        except Exception:
                            pass
                    self.conn = duckdb.connect(self.db_path, config=duckdb_config)
                    logger.info("已创建新的 DuckDB 空数据库")
                except Exception as e3:
                    logger.error(f"创建新数据库也失败，使用内存模式: {e3}")
                    self.conn = duckdb.connect(':memory:')
                    self.db_path = ':memory:'
        
        self._init_tables()
        self._init_extensions()
        
        # 统计信息
        self.cache_stats = {
            'hits_duckdb': 0,
            'misses': 0,
            'total_requests': 0
        }
    
    def _init_extensions(self):
        try:
            extensions = ['httpfs', 'json', 'parquet']
            for ext in extensions:
                try:
                    self.conn.execute(f"INSTALL {ext}")
                    self.conn.execute(f"LOAD {ext}")
                except Exception:
                    pass
        except Exception:
            pass
    
    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_cache (
                ts_code VARCHAR,
                trade_date DATE,
                open DECIMAL,
                high DECIMAL,
                low DECIMAL,
                close DECIMAL,
                vol DECIMAL,
                amount DECIMAL,
                pct_chg DECIMAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS indicator_cache (
                ts_code VARCHAR,
                trade_date DATE,
                indicator_name VARCHAR,
                value DECIMAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, indicator_name)
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                key VARCHAR PRIMARY KEY,
                value VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_basic_cache (
                ts_code VARCHAR,
                trade_date DATE,
                close DECIMAL,
                turnover_rate DECIMAL,    -- 换手率
                turnover_rate_f DECIMAL, -- 换手率(自由流通)
                volume_ratio DECIMAL,    -- 量比
                pe DECIMAL,              -- 市盈率
                pe_ttm DECIMAL,          -- 市盈率TTM
                pb DECIMAL,              -- 市净率
                ps DECIMAL,              -- 市销率
                ps_ttm DECIMAL,          -- 市销率TTM
                dv_ratio DECIMAL,        -- 股息率
                dv_ttm DECIMAL,          -- 股息率TTM
                total_share DECIMAL,     -- 总股本
                float_share DECIMAL,     -- 流通股本
                free_share DECIMAL,      -- 自由流通股本
                total_mv DECIMAL,        -- 总市值
                circ_mv DECIMAL,         -- 流通市值
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chip_distribution_cache (
                ts_code VARCHAR,
                trade_date DATE,
                price_bin DECIMAL,      -- 价格区间（如：10.50）
                chip_ratio DECIMAL,     -- 该价格区间筹码比例（0-1）
                accumulated_ratio DECIMAL,  -- 累计筹码比例（用于筹码峰检测）
                peak_flag BOOLEAN,      -- 是否筹码峰
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, price_bin)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS moneyflow_cache (
                ts_code VARCHAR,
                trade_date DATE,
                buy_lg_vol DECIMAL,       -- 大单买入量(手)
                buy_lg_amount DECIMAL,    -- 大单买入额(万)
                sell_lg_vol DECIMAL,      -- 大单卖出量(手)
                sell_lg_amount DECIMAL,   -- 大单卖出额(万)
                buy_elg_amount DECIMAL,   -- 超大单买入额(万)
                sell_elg_amount DECIMAL,  -- 超大单卖出额(万)
                buy_sm_amount DECIMAL,    -- 小单买入额(万)
                sell_sm_amount DECIMAL,   -- 小单卖出额(万)
                net_lg_amount DECIMAL,    -- 大单净额(万)
                net_elg_amount DECIMAL,   -- 超大单净额(万)
                net_sm_amount DECIMAL,    -- 小单净额(万)
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        # 迁移：为已有表添加缺失列（安全幂等）
        _moneyflow_cols = [
            ('buy_elg_amount', 'DECIMAL'),
            ('sell_elg_amount', 'DECIMAL'),
            ('buy_sm_amount', 'DECIMAL'),
            ('sell_sm_amount', 'DECIMAL'),
            ('net_elg_amount', 'DECIMAL'),
            ('net_sm_amount', 'DECIMAL'),
        ]
        for col_name, col_type in _moneyflow_cols:
            try:
                self.conn.execute(f"ALTER TABLE moneyflow_cache ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
            except Exception:
                pass

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS win_rate_cache (
                signal_type VARCHAR PRIMARY KEY,
                samples INTEGER,
                win_rate_5d DECIMAL,
                win_rate_10d DECIMAL,
                win_rate_20d DECIMAL,
                avg_return_5d DECIMAL,
                avg_return_20d DECIMAL,
                sharpe_5d DECIMAL,
                sharpe_20d DECIMAL,
                evaluated_at TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conditional_win_rate_cache (
                signal_type VARCHAR PRIMARY KEY,
                total_samples INTEGER,
                with_div_samples INTEGER,
                with_div_win_rate DECIMAL,
                without_div_samples INTEGER,
                without_div_win_rate DECIMAL,
                market_good_samples INTEGER,
                market_good_win_rate DECIMAL,
                market_poor_samples INTEGER,
                market_poor_win_rate DECIMAL,
                evaluated_at TIMESTAMP
            )
        """)
        
        # 为查询优化
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_ts_code ON daily_cache(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_cache(trade_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_basic_ts_code ON daily_basic_cache(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_basic_date ON daily_basic_cache(trade_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chip_ts_code ON chip_distribution_cache(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chip_date ON chip_distribution_cache(trade_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_moneyflow_ts_code ON moneyflow_cache(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_moneyflow_date ON moneyflow_cache(trade_date)")
        except Exception:
            pass

        # ── AKShare 盘中数据 as_* 表（239/244号方案） ──────────────
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_market_snapshot (
                ts_code VARCHAR PRIMARY KEY,
                name VARCHAR,
                price DECIMAL,
                change DECIMAL,
                change_pct DECIMAL,
                volume DECIMAL,
                amount DECIMAL,
                pe DECIMAL,
                pb DECIMAL,
                amplitude DECIMAL,
                circ_mv DECIMAL,
                total_mv DECIMAL,
                volume_ratio DECIMAL,
                open DECIMAL,
                high DECIMAL,
                low DECIMAL,
                pre_close DECIMAL,
                turnover_rate DECIMAL,
                source VARCHAR DEFAULT 'akshare',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_top_stocks (
                rank_type VARCHAR,
                ts_code VARCHAR,
                name VARCHAR,
                price DECIMAL,
                change_pct DECIMAL,
                volume DECIMAL,
                amount DECIMAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (rank_type, ts_code)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_sector_ranking (
                sector_name VARCHAR PRIMARY KEY,
                ts_code VARCHAR,
                change_pct DECIMAL,
                up_count INTEGER,
                down_count INTEGER,
                lead_ts_code VARCHAR,
                lead_name VARCHAR,
                lead_change_pct DECIMAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_concept_ranking (
                concept_name VARCHAR PRIMARY KEY,
                ts_code VARCHAR,
                change_pct DECIMAL,
                up_count INTEGER,
                down_count INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_limit_pool (
                limit_type VARCHAR,
                ts_code VARCHAR,
                name VARCHAR,
                price DECIMAL,
                change_pct DECIMAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (limit_type, ts_code)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_minute_kline (
                ts_code VARCHAR,
                trade_date DATE,
                trade_time VARCHAR,
                freq VARCHAR DEFAULT '5min',
                open DECIMAL,
                high DECIMAL,
                low DECIMAL,
                close DECIMAL,
                volume DECIMAL,
                amount DECIMAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date, trade_time, freq)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_lhb_detail (
                ts_code VARCHAR,
                trade_date DATE,
                name VARCHAR,
                change_pct DECIMAL,
                buy_amount DECIMAL,
                sell_amount DECIMAL,
                net_amount DECIMAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_news (
                id VARCHAR PRIMARY KEY,
                title VARCHAR,
                summary VARCHAR,
                source VARCHAR,
                publish_time VARCHAR,
                url VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS as_quote_cache (
                ts_code VARCHAR PRIMARY KEY,
                bid_price DECIMAL,
                bid_volume INTEGER,
                ask_price DECIMAL,
                ask_volume INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_as_snapshot_ts ON as_market_snapshot(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_as_minute_ts ON as_minute_kline(ts_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_as_minute_date ON as_minute_kline(trade_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_as_lhb_date ON as_lhb_detail(trade_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_as_news_time ON as_news(publish_time)")
        except Exception:
            pass

    def get_cached_daily(self, ts_code, start_date=None, end_date=None):
        """
        两层缓存策略：
        2. PostgreSQL（由调用方处理）
        """
        self.cache_stats['total_requests'] += 1

        # 查询DuckDB
        query = "SELECT * FROM daily_cache WHERE ts_code = ?"
        params = [ts_code]
        
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY trade_date"
        
        try:
            df = self.conn.execute(query, params).fetchdf()
            if not df.empty:
                self.cache_stats['hits_duckdb'] += 1
                return df
        except Exception as e:
            logger.warning(f"DuckDB查询失败: {e}")
        
        self.cache_stats['misses'] += 1
        return pd.DataFrame()
    
    def cache_daily_data(self, df):
        """
        缓存日线数据到DuckDB
        """
        if df.empty:
            return

        with self._write_lock:
            # 写入DuckDB
            self.conn.register('temp_df', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO daily_cache
                (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, cached_at)
                SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, CURRENT_TIMESTAMP
                FROM temp_df
            """)
            self.conn.commit()

        self._update_metadata('last_cache_time', datetime.now().isoformat())
    
    def get_indicator_data(self, ts_code, indicator_name):
        """
        获取指标缓存数据
        """
        self.cache_stats['total_requests'] += 1

        # 查询DuckDB
        query = "SELECT * FROM indicator_cache WHERE ts_code = ? AND indicator_name = ? ORDER BY trade_date"
        try:
            df = self.conn.execute(query, [ts_code, indicator_name]).fetchdf()
            if not df.empty:
                self.cache_stats['hits_duckdb'] += 1
                return df
        except Exception as e:
            logger.warning(f"查询指标失败: {e}")
        
        self.cache_stats['misses'] += 1
        return pd.DataFrame()
    
    def cache_indicator(self, ts_code, trade_date, indicator_name, value):
        """
        缓存单个指标
        """
        with self._write_lock:

            try:

                self.conn.execute("""

                    INSERT OR REPLACE INTO indicator_cache 

                    (ts_code, trade_date, indicator_name, value)

                    VALUES (?, ?, ?, ?)

                """, [ts_code, trade_date, indicator_name, value])

                self.conn.commit()

            except Exception as e:

                logger.warning(f"缓存指标失败: {e}")

    
    def batch_cache_indicators(self, records):
        """
        批量缓存指标（高性能写入）
        借鉴Vibe-Trading和Qlib的批量处理理念
        """
        if not records:
            return
        
        with self._write_lock:

            try:

                df = pd.DataFrame(records)

                self.conn.register('temp_indicators', df)

            
                self.conn.execute("""

                    INSERT OR REPLACE INTO indicator_cache 

                    (ts_code, trade_date, indicator_name, value, cached_at)

                    SELECT ts_code, trade_date, indicator_name, value, cached_at

                    FROM temp_indicators

                """)

                self.conn.commit()

            except Exception as e:

                logger.warning(f"批量缓存指标失败: {e}")

    
    # ==================== TieredMemoryCache 集成 ====================

    def get_from_memory(self, key: str, level: str = 'realtime'):
        """从内存缓存读取（实时/盘中/分析三级）

        Args:
            key: 缓存键
            level: 缓存级别 (realtime/intraday/analysis)

        Returns:
            缓存值或 None
        """
        return self.memory_cache.get(key, level)

    def set_to_memory(self, key: str, value, level: str = 'realtime'):
        """写入内存缓存

        Args:
            key: 缓存键
            value: 缓存值
            level: 缓存级别
        """
        self.memory_cache.set(key, value, level)

    def get_cache_stats(self):
        """
        获取综合缓存统计
        """
        try:
            daily_count = self.conn.execute("SELECT COUNT(*) FROM daily_cache").fetchone()[0]
            indicator_count = self.conn.execute("SELECT COUNT(*) FROM indicator_cache").fetchone()[0]
            
            
            return pd.DataFrame([{
                'duckdb_daily_count': daily_count,
                'duckdb_indicator_count': indicator_count,
                'enhanced_hits_duckdb': self.cache_stats['hits_duckdb'],
                'enhanced_misses': self.cache_stats['misses'],
                'enhanced_hit_rate': self.cache_stats['hits_duckdb'] / max(self.cache_stats['total_requests'], 1) * 100 if self.cache_stats['total_requests'] > 0 else 0
            }])
        except Exception:
            return pd.DataFrame()
    
    def _update_metadata(self, key, value):
        """更新元数据"""
        with self._write_lock:

            try:

                self.conn.execute("""

                    INSERT OR REPLACE INTO cache_metadata (key, value)

                    VALUES (?, ?)

                """, [key, value])

                self.conn.commit()

            except Exception:

                pass

    
    def invalidate_old_data(self, days=30):
        """
        清除旧数据缓存
        
        Args:
            days: 保留天数
            
        Returns:
            是否成功
        """
        with self._write_lock:

            try:

                cutoff = datetime.now() - timedelta(days=days)

                self.conn.execute("""

                    DELETE FROM daily_cache 

                    WHERE cached_at < ?

                """, [cutoff])

                self.conn.commit()

            
                return True

            except Exception as e:

                logger.warning(f"清除旧缓存失败: {e}")

                return False

    
    def clear_old_cache(self, days=30):
        return self.invalidate_old_data(days)
    
    def close(self):
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
    
    # ==================== daily_basic 缓存方法 ====================
    
    def cache_daily_basic_data(self, df):
        """
        缓存daily_basic数据到DuckDB
        """
        if df.empty:
            return

        with self._write_lock:

            try:
                # ponytail: 统一日期格式 YYYYMMDD → YYYY-MM-DD
                if 'trade_date' in df.columns:
                    if df['trade_date'].dtype in ('object', 'str'):
                        sample = str(df['trade_date'].iloc[0]) if len(df) > 0 else ''
                        if sample.isdigit() and len(sample) == 8:
                            df['trade_date'] = df['trade_date'].astype(str).str.replace(
                                r'^(\d{4})(\d{2})(\d{2})$', r'\1-\2-\3', regex=True
                            )

                self.conn.register('temp_df', df)

                self.conn.execute("""

                    INSERT OR REPLACE INTO daily_basic_cache 

                    (ts_code, trade_date, close, turnover_rate, turnover_rate_f, volume_ratio,

                     pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm,

                     total_share, float_share, free_share, total_mv, circ_mv, cached_at)

                    SELECT ts_code, trade_date, close, turnover_rate, turnover_rate_f, volume_ratio,

                           pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm,

                           total_share, float_share, free_share, total_mv, circ_mv, CURRENT_TIMESTAMP 

                    FROM temp_df

                """)

                self.conn.commit()

                self._update_metadata('last_daily_basic_cache_time', datetime.now().isoformat())

            except Exception as e:

                logger.warning(f"缓存daily_basic数据失败: {e}")

    
    def get_cached_daily_basic(self, ts_code, start_date=None, end_date=None):
        """
        获取缓存的daily_basic数据
        """
        query = "SELECT * FROM daily_basic_cache WHERE ts_code = ?"
        params = [ts_code]
        
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY trade_date"
        
        with self._lock:

            try:

                df = self.conn.execute(query, params).fetchdf()

                return df

            except Exception as e:

                logger.warning(f"查询daily_basic数据失败: {e}")

                return pd.DataFrame()

    
    # ==================== 筹码分布缓存方法 ====================
    
    def cache_chip_distribution(self, ts_code, trade_date, chip_data):
        """
        缓存单只股票的筹码分布
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            chip_data: 筹码分布数据，格式为List[Dict]
                        [{'price_bin': 10.5, 'chip_ratio': 0.02, 'accumulated_ratio': 0.1, 'peak_flag': False}, ...]
        """
        if not chip_data:
            return
        
        with self._write_lock:

            try:

                records = []

                for bin_data in chip_data:

                    records.append({

                        'ts_code': ts_code,

                        'trade_date': trade_date,

                        'price_bin': bin_data['price_bin'],

                        'chip_ratio': bin_data['chip_ratio'],

                        'accumulated_ratio': bin_data['accumulated_ratio'],

                        'peak_flag': bin_data['peak_flag']

                    })

            
                df = pd.DataFrame(records)

                self.conn.register('temp_chips', df)

            
                self.conn.execute("""

                    INSERT OR REPLACE INTO chip_distribution_cache 

                    (ts_code, trade_date, price_bin, chip_ratio, accumulated_ratio, peak_flag, update_time)

                    SELECT ts_code, trade_date, price_bin, chip_ratio, accumulated_ratio, peak_flag, CURRENT_TIMESTAMP

                    FROM temp_chips

                """)

                self.conn.commit()

            except Exception as e:

                logger.warning(f"缓存筹码分布失败: {e}")

    
    def batch_cache_chips(self, records):
        """
        批量缓存筹码分布（高性能写入）
        """
        if not records:
            return
        
        with self._write_lock:

            try:

                df = pd.DataFrame(records)

                self.conn.register('temp_chips_batch', df)

            
                self.conn.execute("""

                    INSERT OR REPLACE INTO chip_distribution_cache 

                    (ts_code, trade_date, price_bin, chip_ratio, accumulated_ratio, peak_flag, update_time)

                    SELECT ts_code, trade_date, price_bin, chip_ratio, accumulated_ratio, peak_flag, CURRENT_TIMESTAMP

                    FROM temp_chips_batch

                """)

                self.conn.commit()

            except Exception as e:

                logger.warning(f"批量缓存筹码分布失败: {e}")

    
    def get_chip_distribution(self, ts_code, start_date=None, end_date=None):
        """
        获取筹码分布数据
        """
        query = "SELECT * FROM chip_distribution_cache WHERE ts_code = ?"
        params = [ts_code]
        
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY trade_date, price_bin"
        
        with self._lock:

            try:

                df = self.conn.execute(query, params).fetchdf()

                return df

            except Exception as e:

                logger.warning(f"查询筹码分布数据失败: {e}")

                return pd.DataFrame()

    
    def get_latest_chip_distribution(self, ts_code):
        """
        获取最新的筹码分布数据
        """
        query = """
            SELECT * FROM chip_distribution_cache 
            WHERE ts_code = ? 
            AND trade_date = (
                SELECT MAX(trade_date) FROM chip_distribution_cache WHERE ts_code = ?
            )
            ORDER BY price_bin
        """
        
        with self._lock:

            try:

                df = self.conn.execute(query, [ts_code, ts_code]).fetchdf()

                return df

            except Exception as e:

                logger.warning(f"查询最新筹码分布数据失败: {e}")

                return pd.DataFrame()

    

    # ==================== 资金流向缓存方法 ====================

    def cache_moneyflow_data(self, df):
        """
        缓存资金流向数据到DuckDB
        """
        if df.empty:
            return

        with self._write_lock:

            try:
                # 统一日期格式：Ymd → YYYY-MM-DD
                if 'trade_date' in df.columns:
                    if df['trade_date'].dtype == object:
                        df['trade_date'] = df['trade_date'].str.replace(
                            r'^(\d{4})(\d{2})(\d{2})$', r'\1-\2-\3', regex=True
                        )
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date

                self.conn.register('temp_mf', df)

                # ponytail: 补齐 net_* 列（Tushare raw 返回 net_mf_amount，无 net_lg/elg/sm）
                net_cols = {'net_lg_amount': 'buy_lg_amount', 'net_elg_amount': 'buy_elg_amount', 'net_sm_amount': 'buy_sm_amount'}
                for net_col, buy_col in net_cols.items():
                    if net_col not in df.columns and buy_col in df.columns:
                        sell_col = 'sell_' + buy_col[4:]
                        df[net_col] = df[buy_col].fillna(0) - df.get(sell_col, pd.Series([0]*len(df))).fillna(0)
                self.conn.unregister('temp_mf')
                self.conn.register('temp_mf', df)

                self.conn.execute("""
                    INSERT OR REPLACE INTO moneyflow_cache
                    (ts_code, trade_date, buy_lg_vol, buy_lg_amount,
                     sell_lg_vol, sell_lg_amount,
                     buy_elg_amount, sell_elg_amount,
                     buy_sm_amount, sell_sm_amount,
                     net_lg_amount, net_elg_amount, net_sm_amount, cached_at)
                    SELECT ts_code, trade_date, buy_lg_vol, buy_lg_amount,
                           sell_lg_vol, sell_lg_amount,
                           buy_elg_amount, sell_elg_amount,
                           buy_sm_amount, sell_sm_amount,
                           net_lg_amount, net_elg_amount, net_sm_amount, CURRENT_TIMESTAMP
                    FROM temp_mf
                """)

                self.conn.commit()

                self._update_metadata('last_moneyflow_cache_time', datetime.now().isoformat())

            except Exception as e:

                logger.warning(f"缓存资金流向数据失败: {e}")


    def get_cached_moneyflow(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        """
        获取缓存的资金流向数据

        Args:
            ts_code: 股票代码（可选）
            trade_date: 指定日期（可选）
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            DataFrame
        """
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

        try:
            df = self.conn.execute(query, params).fetchdf()
            return df
        except Exception as e:
            logger.warning(f"查询资金流向数据失败: {e}")
            return pd.DataFrame()

    # ==================== 赢率缓存方法（Phase 4） ====================

    def cache_win_rates(self, df):
        """缓存赢率数据到 DuckDB"""
        if df.empty:
            return
        with self._write_lock:

            try:

                self.conn.register('temp_wr', df)

                self.conn.execute("""

                    INSERT OR REPLACE INTO win_rate_cache

                    (signal_type, samples, win_rate_5d, win_rate_10d, win_rate_20d,

                     avg_return_5d, avg_return_20d, sharpe_5d, sharpe_20d, evaluated_at)

                    SELECT signal_type, samples, win_rate_5d, win_rate_10d, win_rate_20d,

                           avg_return_5d, avg_return_20d, sharpe_5d, sharpe_20d, evaluated_at

                    FROM temp_wr

                """)

                self.conn.commit()

            except Exception as e:

                logger.warning(f"缓存赢率数据失败: {e}")


    def get_cached_win_rates(self) -> list:
        """获取所有缓存的赢率数据"""
        with self._lock:

            try:

                df = self.conn.execute("SELECT * FROM win_rate_cache ORDER BY signal_type").fetchdf()

                return df.to_dict('records') if not df.empty else []

            except Exception as e:

                logger.warning(f"查询赢率数据失败: {e}")

                return []


    def get_cached_win_rate(self, signal_type: str) -> dict:
        """获取指定信号类型的赢率数据"""
        with self._lock:

            try:

                df = self.conn.execute('SELECT * FROM win_rate_cache WHERE signal_type = ?', [signal_type]

                ).fetchdf()

                return df.to_dict('records')[0] if not df.empty else {}

            except Exception as e:

                logger.warning(f"查询赢率数据失败: {e}")

                return {}


    def cache_conditional_win_rates(self, df):
        """缓存条件概率数据到 DuckDB"""
        if df.empty:
            return
        with self._write_lock:

            try:

                self.conn.register('temp_cwr', df)

                self.conn.execute("""

                    INSERT OR REPLACE INTO conditional_win_rate_cache

                    (signal_type, total_samples, with_div_samples, with_div_win_rate,

                     without_div_samples, without_div_win_rate,

                     market_good_samples, market_good_win_rate,

                     market_poor_samples, market_poor_win_rate, evaluated_at)

                    SELECT signal_type, total_samples, with_div_samples, with_div_win_rate,

                           without_div_samples, without_div_win_rate,

                           market_good_samples, market_good_win_rate,

                           market_poor_samples, market_poor_win_rate, CURRENT_TIMESTAMP

                    FROM temp_cwr

                """)

                self.conn.commit()

            except Exception as e:

                logger.warning(f"缓存条件概率数据失败: {e}")


    def get_cached_conditional_win_rates(self) -> list:
        """获取所有缓存的条件下概率数据"""
        with self._lock:

            try:

                df = self.conn.execute('SELECT * FROM conditional_win_rate_cache ORDER BY signal_type'

                ).fetchdf()

                return df.to_dict('records') if not df.empty else []

            except Exception as e:

                logger.warning(f"查询条件下概率数据失败: {e}")

                return []


    def close(self):
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

    def __del__(self):
        self.close()

    # ==================== as_* AKShare 盘中数据写入方法（239/244号方案） ====================

    def write_as_market_snapshot(self, records: list):
        """覆盖式写入全市场快照（as_market_snapshot）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_ms', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO as_market_snapshot
                (ts_code, name, price, change, change_pct, volume, amount,
                 pe, pb, amplitude, circ_mv, total_mv, volume_ratio,
                 open, high, low, pre_close, turnover_rate, source, updated_at)
                SELECT ts_code, name, price, change, change_pct, volume, amount,
                       pe, pb, amplitude, circ_mv, total_mv, volume_ratio,
                       open, high, low, pre_close, turnover_rate, 'akshare', CURRENT_TIMESTAMP
                FROM _tmp_as_ms
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_market_snapshot 失败: {e}")

    def write_as_top_stocks(self, rank_type: str, records: list):
        """覆盖式写入涨跌榜（as_top_stocks）"""
        if not records:
            return
        try:
            for r in records:
                r['rank_type'] = rank_type
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_ts', df)
            self.conn.execute("DELETE FROM as_top_stocks WHERE rank_type = ?", [rank_type])
            self.conn.execute("""
                INSERT INTO as_top_stocks
                (rank_type, ts_code, name, price, change_pct, volume, amount, updated_at)
                SELECT rank_type, ts_code, name, price, change_pct, volume, amount, CURRENT_TIMESTAMP
                FROM _tmp_as_ts
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_top_stocks 失败: {e}")

    def write_as_sector_ranking(self, records: list):
        """覆盖式写入行业板块排行（as_sector_ranking）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_sr', df)
            self.conn.execute("DELETE FROM as_sector_ranking")
            self.conn.execute("""
                INSERT INTO as_sector_ranking
                (sector_name, ts_code, change_pct, up_count, down_count,
                 lead_ts_code, lead_name, lead_change_pct, updated_at)
                SELECT sector_name, ts_code, change_pct, up_count, down_count,
                       lead_ts_code, lead_name, lead_change_pct, CURRENT_TIMESTAMP
                FROM _tmp_as_sr
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_sector_ranking 失败: {e}")

    def write_as_concept_ranking(self, records: list):
        """覆盖式写入概念板块排行（as_concept_ranking）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_cr', df)
            self.conn.execute("DELETE FROM as_concept_ranking")
            self.conn.execute("""
                INSERT INTO as_concept_ranking
                (concept_name, ts_code, change_pct, up_count, down_count, updated_at)
                SELECT concept_name, ts_code, change_pct, up_count, down_count, CURRENT_TIMESTAMP
                FROM _tmp_as_cr
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_concept_ranking 失败: {e}")

    def write_as_limit_pool(self, records: list, limit_type: str):
        """覆盖式写入涨跌停池（as_limit_pool）"""
        if not records:
            return
        try:
            for r in records:
                r['limit_type'] = limit_type
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_lp', df)
            self.conn.execute("DELETE FROM as_limit_pool WHERE limit_type = ?", [limit_type])
            self.conn.execute("""
                INSERT INTO as_limit_pool
                (limit_type, ts_code, name, price, change_pct, updated_at)
                SELECT limit_type, ts_code, name, price, change_pct, CURRENT_TIMESTAMP
                FROM _tmp_as_lp
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_limit_pool 失败: {e}")

    def append_as_minute_kline(self, records: list):
        """追加式写入分钟K线（as_minute_kline）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_mk', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO as_minute_kline
                (ts_code, trade_date, trade_time, freq, open, high, low, close, volume, amount, updated_at)
                SELECT ts_code, trade_date, trade_time, freq, open, high, low, close, volume, amount, CURRENT_TIMESTAMP
                FROM _tmp_as_mk
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] append_as_minute_kline 失败: {e}")

    def write_as_lhb_detail(self, records: list):
        """覆盖式写入龙虎榜数据（as_lhb_detail）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_lhb', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO as_lhb_detail
                (ts_code, trade_date, name, change_pct, buy_amount, sell_amount, net_amount, updated_at)
                SELECT ts_code, trade_date, name, change_pct, buy_amount, sell_amount, net_amount, CURRENT_TIMESTAMP
                FROM _tmp_as_lhb
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_lhb_detail 失败: {e}")

    def write_as_news(self, records: list):
        """覆盖式写入盘中新闻（as_news）"""
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            self.conn.register('_tmp_as_n', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO as_news
                (id, title, summary, source, publish_time, url, updated_at)
                SELECT id, title, summary, source, publish_time, url, CURRENT_TIMESTAMP
                FROM _tmp_as_n
            """)
            self.conn.commit()
        except Exception as e:
            logger.debug(f"[ECM] write_as_news 失败: {e}")

    # ==================== as_* AKShare 盘中数据读取方法 ====================

    def read_as_market_snapshot(self) -> 'pd.DataFrame':
        """读取全市场快照"""
        try:
            return self.conn.execute("SELECT * FROM as_market_snapshot ORDER BY change_pct DESC").fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_market_snapshot 失败: {e}")
            return pd.DataFrame()

    def read_as_market_snapshot_by_codes(self, ts_codes: list) -> 'pd.DataFrame':
        """按代码列表读取市场快照"""
        if not ts_codes:
            return pd.DataFrame()
        try:
            placeholders = ','.join('?' for _ in ts_codes)
            return self.conn.execute(
                f"SELECT * FROM as_market_snapshot WHERE ts_code IN ({placeholders})",
                ts_codes
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_market_snapshot_by_codes 失败: {e}")
            return pd.DataFrame()

    def read_as_top_stocks(self, rank_type: str = None) -> 'pd.DataFrame':
        """读取涨跌榜"""
        try:
            if rank_type:
                return self.conn.execute(
                    "SELECT * FROM as_top_stocks WHERE rank_type = ? ORDER BY ABS(change_pct) DESC",
                    [rank_type]
                ).fetchdf()
            return self.conn.execute(
                "SELECT * FROM as_top_stocks ORDER BY rank_type, ABS(change_pct) DESC"
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_top_stocks 失败: {e}")
            return pd.DataFrame()

    def read_as_sector_ranking(self, top_n: int = 50) -> 'pd.DataFrame':
        """读取行业板块排行"""
        try:
            return self.conn.execute(
                "SELECT * FROM as_sector_ranking ORDER BY change_pct DESC LIMIT ?",
                [top_n]
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_sector_ranking 失败: {e}")
            return pd.DataFrame()

    def read_as_concept_ranking(self, top_n: int = 50) -> 'pd.DataFrame':
        """读取概念板块排行"""
        try:
            return self.conn.execute(
                "SELECT * FROM as_concept_ranking ORDER BY change_pct DESC LIMIT ?",
                [top_n]
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_concept_ranking 失败: {e}")
            return pd.DataFrame()

    def read_as_limit_pool(self, limit_type: str = None) -> 'pd.DataFrame':
        """读取涨跌停池"""
        try:
            if limit_type:
                return self.conn.execute(
                    "SELECT * FROM as_limit_pool WHERE limit_type = ? ORDER BY ABS(change_pct) DESC",
                    [limit_type]
                ).fetchdf()
            return self.conn.execute(
                "SELECT * FROM as_limit_pool ORDER BY limit_type, ABS(change_pct) DESC"
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_limit_pool 失败: {e}")
            return pd.DataFrame()

    def read_as_minute_kline(self, ts_code: str, trade_date: str = '',
                             freq: str = '5min') -> 'pd.DataFrame':
        """读取分钟K线"""
        try:
            if trade_date:
                return self.conn.execute(
                    "SELECT * FROM as_minute_kline WHERE ts_code = ? AND trade_date = ? AND freq = ? ORDER BY trade_time",
                    [ts_code, trade_date, freq]
                ).fetchdf()
            return self.conn.execute(
                "SELECT * FROM as_minute_kline WHERE ts_code = ? AND freq = ? ORDER BY trade_date, trade_time",
                [ts_code, freq]
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_minute_kline 失败: {e}")
            return pd.DataFrame()

    def read_as_lhb_detail(self, trade_date: str = None) -> 'pd.DataFrame':
        """读取龙虎榜数据"""
        try:
            if trade_date:
                return self.conn.execute(
                    "SELECT * FROM as_lhb_detail WHERE trade_date = ? ORDER BY net_amount DESC",
                    [trade_date]
                ).fetchdf()
            return self.conn.execute(
                "SELECT * FROM as_lhb_detail ORDER BY trade_date DESC, net_amount DESC"
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_lhb_detail 失败: {e}")
            return pd.DataFrame()

    def read_as_news(self, limit: int = 50) -> 'pd.DataFrame':
        """读取盘中新闻"""
        try:
            return self.conn.execute(
                "SELECT * FROM as_news ORDER BY publish_time DESC LIMIT ?",
                [limit]
            ).fetchdf()
        except Exception as e:
            logger.debug(f"[ECM] read_as_news 失败: {e}")
            return pd.DataFrame()

    def read_as_quote_cache(self, ts_code: str) -> dict:
        """读取个股盘口缓存"""
        try:
            df = self.conn.execute(
                "SELECT * FROM as_quote_cache WHERE ts_code = ?", [ts_code]
            ).fetchdf()
            return df.to_dict('records')[0] if not df.empty else {}
        except Exception as e:
            logger.debug(f"[ECM] read_as_quote_cache 失败: {e}")
            return {}

    def clean_as_minute_kline(self, trade_date: str = None):
        """清理盘中分钟K线数据（日终同步后调用）"""
        try:
            if trade_date:
                self.conn.execute("DELETE FROM as_minute_kline WHERE trade_date = ?", [trade_date])
            else:
                self.conn.execute("DELETE FROM as_minute_kline")
            self.conn.commit()
            logger.info(f"[ECM] 已清理 as_minute_kline (date={trade_date or 'all'})")
        except Exception as e:
            logger.warning(f"[ECM] clean_as_minute_kline 失败: {e}")

    def get_as_table_stats(self) -> dict:
        """获取 as_* 各表的行数统计"""
        tables = [
            'as_market_snapshot', 'as_top_stocks', 'as_sector_ranking',
            'as_concept_ranking', 'as_limit_pool', 'as_minute_kline',
            'as_lhb_detail', 'as_news', 'as_quote_cache'
        ]
        stats = {}
        for t in tables:
            try:
                df = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchdf()
                stats[t] = int(df['cnt'].iloc[0])
            except Exception:
                stats[t] = -1
        return stats
