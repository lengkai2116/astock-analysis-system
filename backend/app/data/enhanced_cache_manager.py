import os
import duckdb
import pandas as pd
import logging
import time
import shutil

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
from .redis_cache_manager import RedisCacheManager

class EnhancedCacheManager:
    """
    增强型缓存管理器
    包含：
    - DuckDB主缓存
    - Redis二级缓存（热点数据）
    - 缓存失效策略
    - 缓存命中率统计
    """
    
    def __init__(self):
        self.redis_cache = RedisCacheManager()
        
        # DuckDB配置 - 性能优化版
        data_dir = os.getenv('DATA_DIR', '/data')
        self.db_path = os.path.join(data_dir, 'duckdb', 'stock_cache.db')
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
        except Exception as e:
            logger.warning(f"DuckDB 主库连接失败: {e}")
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
            'hits_redis': 0,
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
                net_lg_amount DECIMAL,    -- 大单净额(万)
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)

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
    
    def get_cached_daily(self, ts_code, start_date=None, end_date=None):
        """
        三层缓存策略：
        1. Redis缓存（最快）
        2. DuckDB缓存
        3. PostgreSQL（由调用方处理）
        """
        self.cache_stats['total_requests'] += 1
        
        # 1. 先查Redis
        redis_df = self.redis_cache.get_daily_data(ts_code, start_date, end_date)
        if redis_df is not None and not redis_df.empty:
            self.cache_stats['hits_redis'] += 1
            return redis_df
        
        # 2. 查询DuckDB
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
                # 同时缓存到Redis
                self.redis_cache.set_daily_data(ts_code, df, start_date, end_date)
                return df
        except Exception as e:
            logger.warning(f"DuckDB查询失败: {e}")
        
        self.cache_stats['misses'] += 1
        return pd.DataFrame()
    
    def cache_daily_data(self, df):
        """
        缓存日线数据到DuckDB和Redis
        """
        if df.empty:
            return
        
        # 写入DuckDB
        self.conn.register('temp_df', df)
        self.conn.execute("""
            INSERT OR REPLACE INTO daily_cache 
            (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, cached_at)
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, CURRENT_TIMESTAMP 
            FROM temp_df
        """)
        self.conn.commit()
        
        # 缓存到Redis（只缓存最近的数据）
        ts_codes = df['ts_code'].unique()
        for ts_code in ts_codes:
            stock_df = df[df['ts_code'] == ts_code].sort_values('trade_date')
            recent_df = stock_df.tail(250)  # 约1年数据
            self.redis_cache.set_daily_data(ts_code, recent_df)
        
        self._update_metadata('last_cache_time', datetime.now().isoformat())
    
    def get_indicator_data(self, ts_code, indicator_name):
        """
        获取指标缓存数据
        """
        self.cache_stats['total_requests'] += 1
        
        # Redis优先查Redis
        redis_df = self.redis_cache.get_indicator_data(ts_code, indicator_name)
        if redis_df is not None and not redis_df.empty:
            self.cache_stats['hits_redis'] += 1
            return redis_df
        
        # 查询DuckDB
        query = "SELECT * FROM indicator_cache WHERE ts_code = ? AND indicator_name = ? ORDER BY trade_date"
        try:
            df = self.conn.execute(query, [ts_code, indicator_name]).fetchdf()
            if not df.empty:
                self.cache_stats['hits_duckdb'] += 1
                self.redis_cache.set_indicator_data(ts_code, indicator_name, df)
                return df
        except Exception as e:
            logger.warning(f"查询指标失败: {e}")
        
        self.cache_stats['misses'] += 1
        return pd.DataFrame()
    
    def cache_indicator(self, ts_code, trade_date, indicator_name, value):
        """
        缓存单个指标
        """
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
    
    def get_cache_stats(self):
        """
        获取综合缓存统计
        """
        try:
            daily_count = self.conn.execute("SELECT COUNT(*) FROM daily_cache").fetchone()[0]
            indicator_count = self.conn.execute("SELECT COUNT(*) FROM indicator_cache").fetchone()[0]
            
            redis_stats = self.redis_cache.get_hit_rate()
            
            return pd.DataFrame([{
                'duckdb_daily_count': daily_count,
                'duckdb_indicator_count': indicator_count,
                'redis_hits': redis_stats['hits'],
                'redis_misses': redis_stats['misses'],
                'redis_hit_rate': redis_stats['hit_rate_percent'],
                'enhanced_hits_duckdb': self.cache_stats['hits_duckdb'],
                'enhanced_hits_redis': self.cache_stats['hits_redis'],
                'enhanced_misses': self.cache_stats['misses'],
                'enhanced_hit_rate': (self.cache_stats['hits_redis'] + self.cache_stats['hits_duckdb']) / 
                                   max(self.cache_stats['total_requests'], 1) * 100 if self.cache_stats['total_requests'] > 0 else 0
            }])
        except Exception:
            return pd.DataFrame()
    
    def _update_metadata(self, key, value):
        """更新元数据"""
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
        try:
            cutoff = datetime.now() - timedelta(days=days)
            self.conn.execute("""
                DELETE FROM daily_cache 
                WHERE cached_at < ?
            """, [cutoff])
            self.conn.commit()
            
            self.redis_cache.clear_all()
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
        
        try:
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

        try:
            self.conn.register('temp_mf', df)
            self.conn.execute("""
                INSERT OR REPLACE INTO moneyflow_cache
                (ts_code, trade_date, buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount, net_lg_amount, cached_at)
                SELECT ts_code, trade_date, buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount, net_lg_amount, CURRENT_TIMESTAMP
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
        try:
            df = self.conn.execute("SELECT * FROM win_rate_cache ORDER BY signal_type").fetchdf()
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.warning(f"查询赢率数据失败: {e}")
            return []

    def get_cached_win_rate(self, signal_type: str) -> dict:
        """获取指定信号类型的赢率数据"""
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
        try:
            df = self.conn.execute('SELECT * FROM conditional_win_rate_cache ORDER BY signal_type'
            ).fetchdf()
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.warning(f"查询条件下概率数据失败: {e}")
            return []

    def __del__(self):
        self.close()
