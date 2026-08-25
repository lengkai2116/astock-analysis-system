"""
因子预计算管理器
用于批量预计算和缓存因子
文件路径：backend/app/data/factor_precompute.py
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict

from app.factors import FactorCalculator, get_factor_registry
from app.data.enhanced_cache_manager import EnhancedCacheManager



import logging
logger = logging.getLogger(__name__)
class FactorPrecomputeManager:
    """
    因子预计算管理器
    负责批量预计算和缓存因子
    """

    def __init__(self, cache_manager: Optional[EnhancedCacheManager] = None):
        self.cache_manager = cache_manager or EnhancedCacheManager()
        self.calculator = FactorCalculator()
        self.registry = get_factor_registry()
        # 表由 ECM 统一管理，不再使用独立连接

    def precompute_factor(self, ts_code: str, data: pd.DataFrame,
                          factor_name: str, **kwargs) -> bool:
        """
        预计算单个因子
        """
        try:
            factor_series = self.calculator.calculate_single_factor(data, factor_name, **kwargs)

            if factor_series is None or factor_series.empty:
                return False

            # 因子可能返回整数索引(RangeIndex)，需要映射回原始trade_date
            self._batch_cache_factor_series(factor_series, ts_code, factor_name, data)

            return True
        except Exception as e:
            logger.error(f"预计算因子失败 {factor_name} [{ts_code}]: {e}")
            return False

    def _batch_cache_factor_series(self, factor_series: pd.Series,
                                   ts_code: str, factor_name: str,
                                   data: pd.DataFrame = None):
        """
        批量缓存因子序列
        """
        if factor_series.empty:
            return

        records = []
        now = datetime.now()
        # 获取原始trade_date列表用于映射
        dates = data['trade_date'].tolist() if data is not None and 'trade_date' in data.columns else None

        for idx, value in factor_series.items():
            if pd.notna(value):
                # 映射日期：优先从原始DataFrame获取，否则用索引值
                trade_date = None
                if dates and isinstance(idx, (int, np.integer)) and 0 <= idx < len(dates):
                    trade_date = dates[idx]
                elif isinstance(idx, str):
                    trade_date = idx
                elif isinstance(idx, (datetime, pd.Timestamp)):
                    trade_date = idx.strftime('%Y-%m-%d')
                elif isinstance(idx, pd.Timestamp):
                    trade_date = idx.strftime('%Y-%m-%d')
                else:
                    trade_date = str(idx)

                # 统一转换为 YYYY-MM-DD 字符串格式
                if isinstance(trade_date, (datetime, pd.Timestamp)):
                    trade_date = trade_date.strftime('%Y-%m-%d')
                elif hasattr(trade_date, 'strftime'):
                    # datetime.date 对象
                    trade_date = trade_date.strftime('%Y-%m-%d')
                elif isinstance(trade_date, str):
                    # 兼容 YYYYMMDD 格式
                    clean = trade_date.replace('-', '')
                    if len(clean) == 8 and clean.isdigit():
                        trade_date = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
                    # 如果包含时间部分（如 "2026-08-21 00:00:00"），截取日期部分
                    if ' ' in trade_date:
                        trade_date = trade_date.split(' ')[0]
                else:
                    trade_date = str(trade_date)

                records.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'factor_name': factor_name,
                    'value': float(value),
                    'cached_at': now
                })

        if records:
            self._bulk_insert_factors(records)

    def _bulk_insert_factors(self, records: List[Dict]):
        """批量插入因子数据 — 委托给 ECM"""
        if not records:
            return
        for r in records:
            td = r['trade_date']
            if isinstance(td, (datetime, pd.Timestamp)):
                r['trade_date'] = td.strftime('%Y-%m-%d')
        self.cache_manager.cache_factor_data(records)

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
                logger.error(f"预计算因子失败 {name}: {e}")
                results[name] = False

        return results

    def get_cached_factor(self, ts_code: str, factor_name: str) -> Optional[pd.Series]:
        """获取缓存的因子 — 委托给 ECM"""
        return self.cache_manager.get_cached_factor(ts_code, factor_name)

    def get_cached_factors(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
        """
        获取多个缓存因子
        """
        result = pd.DataFrame()

        for name in factor_names:
            series = self.cache_manager.get_cached_factor(ts_code, name)
            if series is not None:
                result[name] = series

        return result

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息 — 使用 ECM 连接"""
        conn = self.cache_manager.conn
        stock_count = conn.execute("SELECT COUNT(DISTINCT ts_code) FROM factor_cache").fetchone()[0] or 0
        factor_count = conn.execute("SELECT COUNT(DISTINCT factor_name) FROM factor_cache").fetchone()[0] or 0
        total_records = conn.execute("SELECT COUNT(*) FROM factor_cache").fetchone()[0] or 0
        last_update = conn.execute("SELECT MAX(cached_at) FROM factor_cache").fetchone()[0]

        return {
            'stock_count': stock_count,
            'factor_count': factor_count,
            'total_records': total_records,
            'last_update': last_update
        }

    def clear_cache(self, ts_code: Optional[str] = None,
                   factor_name: Optional[str] = None):
        """清除缓存 — 使用 ECM 连接"""
        conn = self.cache_manager.conn

        if ts_code and factor_name:
            conn.execute(
                "DELETE FROM factor_cache WHERE ts_code = ? AND factor_name = ?",
                (ts_code, factor_name)
            )
        elif ts_code:
            conn.execute(
                "DELETE FROM factor_cache WHERE ts_code = ?",
                (ts_code,)
            )
        elif factor_name:
            conn.execute(
                "DELETE FROM factor_cache WHERE factor_name = ?",
                (factor_name,)
            )
        else:
            conn.execute("DELETE FROM factor_cache")

        conn.commit()

    def clean_old_data(self, cutoff: str):
        """清理 factor_cache — 委托给 ECM"""
        self.cache_manager.clean_factor_cache(cutoff)
