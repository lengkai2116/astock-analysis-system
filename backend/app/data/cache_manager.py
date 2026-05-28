import os
import duckdb
import pandas as pd
from datetime import datetime, timedelta

class CacheManager:
    def __init__(self, read_only=False):
        data_dir = os.getenv('DATA_DIR', '/data')
        self.db_path = os.path.join(data_dir, 'duckdb', 'stock_cache.db')
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # 使用 read_only 模式和适当的配置来避免锁问题
        try:
            if read_only:
                self.conn = duckdb.connect(self.db_path, read_only=True, config={'threads': 1})
            else:
                self.conn = duckdb.connect(self.db_path, config={'threads': 1})
        except Exception as e:
            # 如果有锁，尝试使用内存模式
            print(f"⚠️ 无法连接到数据库文件，使用内存模式: {e}")
            self.conn = duckdb.connect(':memory:')
        self._init_tables()
        self._init_extensions()
    
    def _init_extensions(self):
        """加载常用扩展"""
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
            CREATE TABLE IF NOT EXISTS cache_stats (
                stat_key VARCHAR PRIMARY KEY,
                stat_value VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    def cache_daily_data(self, df):
        if df.empty:
            return
        self.conn.register('temp_df', df)
        self.conn.execute("""
            INSERT OR REPLACE INTO daily_cache 
            (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, cached_at)
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, CURRENT_TIMESTAMP 
            FROM temp_df
        """)
        self.conn.commit()
        self._update_stats()
    
    def get_cached_daily(self, ts_code, start_date=None, end_date=None):
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
            return self.conn.execute(query, params).fetchdf()
        except Exception:
            return pd.DataFrame()
    
    def cache_indicator(self, ts_code, trade_date, indicator_name, value):
        self.conn.execute("""
            INSERT OR REPLACE INTO indicator_cache 
            (ts_code, trade_date, indicator_name, value)
            VALUES (?, ?, ?, ?)
        """, (ts_code, trade_date, indicator_name, value))
        self.conn.commit()
        self._update_stats()
    
    def get_cached_indicator(self, ts_code, indicator_name):
        query = "SELECT trade_date, value FROM indicator_cache WHERE ts_code = ? AND indicator_name = ? ORDER BY trade_date"
        return self.conn.execute(query, (ts_code, indicator_name)).fetchdf()
    
    def _update_stats(self):
        """更新缓存统计信息"""
        try:
            daily_count = self.conn.execute("SELECT COUNT(*) FROM daily_cache").fetchone()[0]
            indicator_count = self.conn.execute("SELECT COUNT(*) FROM indicator_cache").fetchone()[0]
            
            self.conn.execute("""
                INSERT OR REPLACE INTO cache_stats (stat_key, stat_value) VALUES 
                ('daily_count', ?),
                ('indicator_count', ?),
                ('last_update', ?)
            """, (str(daily_count), str(indicator_count), datetime.now().isoformat()))
        except Exception:
            pass
    
    def get_cache_stats(self):
        """获取缓存统计信息"""
        try:
            return self.conn.execute("SELECT * FROM cache_stats").fetchdf()
        except Exception:
            return pd.DataFrame()
    
    def clear_old_cache(self, days=30):
        """清除旧的缓存数据"""
        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        self.conn.execute("""
            DELETE FROM daily_cache WHERE cached_at < ?
        """, (cutoff_date,))
        self.conn.commit()
        self._update_stats()
    
    def export_cache_to_parquet(self, output_path):
        """导出缓存到Parquet文件"""
        self.conn.execute("""
            COPY daily_cache TO ? (FORMAT PARQUET)
        """, (output_path,))
    
    def import_cache_from_parquet(self, input_path):
        """从Parquet文件导入缓存"""
        self.conn.execute("""
            COPY daily_cache FROM ? (FORMAT PARQUET)
        """, (input_path,))
        self._update_stats()
    
    def close(self):
        """关闭连接"""
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
    
    def __del__(self):
        self.close()
