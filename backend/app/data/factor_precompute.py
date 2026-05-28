"""
因子预计算管理器
用于批量预计算和缓存因子
文件路径：backend/app/data/factor_precompute.py
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict
import os
import sqlite3

from app.factors import FactorCalculator, get_factor_registry
from app.data.enhanced_cache_manager import EnhancedCacheManager


class FactorPrecomputeManager:
    """
    因子预计算管理器
    负责批量预计算和缓存因子
    """
    
    def __init__(self, cache_manager: Optional[EnhancedCacheManager] = None):
        self.cache_manager = cache_manager or EnhancedCacheManager()
        self.calculator = FactorCalculator()
        self.registry = get_factor_registry()
        self._db_path = os.path.join(os.getenv('DATA_DIR', '/data'), 'duckdb', 'stock_cache.db')
    
    def _ensure_cache_table(self):
        """确保因子缓存表存在"""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS factor_cache (
                    ts_code VARCHAR(20),
                    trade_date DATE,
                    factor_name VARCHAR(50),
                    value DECIMAL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ts_code, trade_date, factor_name)
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def precompute_factor(self, ts_code: str, data: pd.DataFrame, 
                          factor_name: str, **kwargs) -> bool:
        """
        预计算单个因子
        """
        try:
            factor_series = self.calculator.calculate_single_factor(data, factor_name, **kwargs)
            
            if factor_series is None or factor_series.empty:
                return False
            
            self._batch_cache_factor_series(factor_series, ts_code, factor_name)
            
            return True
        except Exception as e:
            print(f"预计算因子失败 {factor_name} [{ts_code}]: {e}")
            return False
    
    def _batch_cache_factor_series(self, factor_series: pd.Series, 
                                   ts_code: str, factor_name: str):
        """
        批量缓存因子序列
        """
        if factor_series.empty:
            return
        
        self._ensure_cache_table()
        
        records = []
        now = datetime.now()
        
        for date, value in factor_series.items():
            if pd.notna(value):
                records.append({
                    'ts_code': ts_code,
                    'trade_date': date if isinstance(date, str) else date,
                    'factor_name': factor_name,
                    'value': float(value),
                    'cached_at': now
                })
        
        if records:
            self._bulk_insert_factors(records)
    
    def _bulk_insert_factors(self, records: List[Dict]):
        """
        批量插入因子数据
        """
        if not records:
            return
        
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            
            for record in records:
                try:
                    trade_date = record['trade_date']
                    if isinstance(trade_date, (datetime, pd.Timestamp)):
                        trade_date = trade_date.strftime('%Y-%m-%d')
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO factor_cache 
                        (ts_code, trade_date, factor_name, value, cached_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        record['ts_code'],
                        trade_date,
                        record['factor_name'],
                        record['value'],
                        record['cached_at']
                    ))
                except Exception as e:
                    print(f"插入因子失败: {e}")
            
            conn.commit()
        finally:
            conn.close()
    
    def precompute_multiple_factors(self, ts_code: str, data: pd.DataFrame,
                                    factor_configs: List[Dict]) -> Dict[str, bool]:
        """
        预计算多个因子
        factor_configs 格式: [{"name": "MA", "params": {"period": 20}}]
        """
        results = {}
        
        for config in factor_configs:
            factor_name = config.get('name')
            params = config.get('params', {})
            
            success = self.precompute_factor(ts_code, data, factor_name, **params)
            results[factor_name] = success
        
        return results
    
    def precompute_category_factors(self, ts_code: str, data: pd.DataFrame,
                                   category: str) -> Dict[str, bool]:
        """
        预计算某类别的所有因子
        """
        factor_names = self.registry.get_category_factors(category)
        
        results = {}
        for name in factor_names:
            success = self.precompute_factor(ts_code, data, name)
            results[name] = success
        
        return results
    
    def precompute_source_factors(self, ts_code: str, data: pd.DataFrame,
                                  source: str) -> Dict[str, bool]:
        """
        预计算某来源的所有因子
        """
        factor_names = self.registry.get_source_factors(source)
        
        results = {}
        for name in factor_names:
            success = self.precompute_factor(ts_code, data, name)
            results[name] = success
        
        return results
    
    def precompute_all_factors(self, ts_code: str, data: pd.DataFrame) -> Dict[str, bool]:
        """
        预计算所有已注册的因子
        """
        factor_names = self.registry.list_factors()
        
        results = {}
        for name in factor_names:
            try:
                success = self.precompute_factor(ts_code, data, name)
                results[name] = success
            except Exception as e:
                print(f"预计算因子失败 {name}: {e}")
                results[name] = False
        
        return results
    
    def get_cached_factor(self, ts_code: str, factor_name: str) -> Optional[pd.Series]:
        """
        获取缓存的因子
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_date, value 
                FROM factor_cache 
                WHERE ts_code = ? AND factor_name = ?
                ORDER BY trade_date
            """, (ts_code, factor_name))
            
            rows = cursor.fetchall()
            
            if not rows:
                return None
            
            dates = [row[0] for row in rows]
            values = [row[1] for row in rows]
            
            return pd.Series(values, index=dates)
        finally:
            conn.close()
    
    def get_cached_factors(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
        """
        获取多个缓存因子
        """
        result = pd.DataFrame()
        
        for name in factor_names:
            series = self.get_cached_factor(ts_code, name)
            if series is not None:
                result[name] = series
        
        return result
    
    def get_cache_stats(self) -> Dict:
        """
        获取缓存统计信息
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT ts_code) FROM factor_cache")
            stock_count = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(DISTINCT factor_name) FROM factor_cache")
            factor_count = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(*) FROM factor_cache")
            total_records = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT MAX(cached_at) FROM factor_cache")
            last_update = cursor.fetchone()[0]
            
            return {
                'stock_count': stock_count,
                'factor_count': factor_count,
                'total_records': total_records,
                'last_update': last_update
            }
        finally:
            conn.close()
    
    def clear_cache(self, ts_code: Optional[str] = None, 
                   factor_name: Optional[str] = None):
        """
        清除缓存
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            
            if ts_code and factor_name:
                cursor.execute(
                    "DELETE FROM factor_cache WHERE ts_code = ? AND factor_name = ?",
                    (ts_code, factor_name)
                )
            elif ts_code:
                cursor.execute(
                    "DELETE FROM factor_cache WHERE ts_code = ?",
                    (ts_code,)
                )
            elif factor_name:
                cursor.execute(
                    "DELETE FROM factor_cache WHERE factor_name = ?",
                    (factor_name,)
                )
            else:
                cursor.execute("DELETE FROM factor_cache")
            
            conn.commit()
        finally:
            conn.close()
