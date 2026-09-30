"""
因子预计算管理器
用于批量预计算和缓存因子
文件路径：backend/app/data/factor_precompute.py
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.factors import FactorCalculator, get_factor_registry

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
        """预计算单个因子

        500号批次1（#44）：因子身份**只由 `factor_name` 承载**——`kwargs`（如 period）
        被转发给 `calculate_single_factor` 计算，但**不进入缓存键**（`factor_cache` 主键
        = ts_code+trade_date+factor_name，无参数字段）。因此调用方须保证**同名不同参的
        因子使用不同 `factor_name`**（现状即如此：`MA_5`/`MA_20`、`VOLATILITY_20` 等均已
        将实参烘焙进因子名）。若需同名多参并存，应为每个参数组合注册唯一因子名。
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

    @staticmethod
    def _normalize_trade_date(value) -> Optional[str]:
        """把索引/值归一为 YYYY-MM-DD；无法识别返回 None（500号#43）

        ——原实现仅转换「8 位纯数字串」，`2026/08/01`/`2026-8-1`/非日期字符串会
        原样入库，破坏 `ORDER BY trade_date` 与 `< cutoff` 的字符串比较；现统一用
        `pd.to_datetime` 严格解析，解析失败返回 None 由调用方跳过（#41）。
        """
        if value is None:
            return None
        ts = pd.to_datetime(value, errors='coerce')
        if ts is pd.NaT or pd.isna(ts):
            return None
        return ts.strftime('%Y-%m-%d')

    def _batch_cache_factor_series(self, factor_series: pd.Series,
                                   ts_code: str, factor_name: str,
                                   data: pd.DataFrame = None):
        """
        批量缓存因子序列

        500号批次1：
          - #41：日期无法映射时**跳过该行**（原 `trade_date = str(idx)` 会把越界/偏移
            索引写成 "0"/"1"… 无意义键，永不匹配日期有序读且与他处位置键碰撞）。
          - #42：删除永不可达的重复 `pd.Timestamp` 分支。
          - #43：日期归一改用 `_normalize_trade_date`（`pd.to_datetime` 严格解析）。
        """
        if factor_series.empty:
            return

        records = []
        now = datetime.now()
        # 获取原始trade_date列表用于映射
        dates = data['trade_date'].tolist() if data is not None and 'trade_date' in data.columns else None

        for idx, value in factor_series.items():
            if not pd.notna(value):
                continue
            # 映射日期：优先从原始 DataFrame 按位置索引取，其次按索引/值解析为日期
            trade_date = None
            if isinstance(idx, (int, np.integer)):
                # 位置索引：仅当原始 DataFrame 有对应 trade_date 时才可映射；否则跳过
                # （#41 避免 str(idx)→"0"/"1"，也避免 pd.to_datetime(0)→1970-01-01 脏键）
                if dates and 0 <= idx < len(dates):
                    trade_date = self._normalize_trade_date(dates[idx])
            elif isinstance(idx, (datetime, pd.Timestamp, str)) or hasattr(idx, 'strftime'):
                trade_date = self._normalize_trade_date(idx)
            if trade_date is None:
                # 无法映射为合法交易日 → 跳过（#41，避免写入脏键）
                continue

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
        """预计算所有已注册的因子

        500号批次1（#45）：移除冗余 try/except——`calculate_single_factor` 与
        `precompute_factor` 内部均已吞异常并给出结果（None/False），此层异常处理器
        永不可触发，仅增噪声且 `results[name]=False` 混淆「未满足数据要求」与「真失败」。
        """
        factor_names = self.registry.list_factors()

        results = {}
        for name in factor_names:
            results[name] = self.precompute_factor(ts_code, data, name)

        return results

    def get_cached_factor(self, ts_code: str, factor_name: str) -> Optional[pd.Series]:
        """获取缓存的因子 — 委托给 ECM"""
        return self.cache_manager.get_cached_factor(ts_code, factor_name)

    def get_cached_factors(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
        """获取多个缓存因子（500号#46：显式 outer join，避免索引对齐引入 NaN 行/重复索引 ValueError）

        原实现 `result[name] = series` 依赖 pandas 索引对齐：各因子 series 日期索引不一致
        时产生并集行（NaN 填充），重复 trade_date 时抛 ValueError。现按 trade_date 外连接。
        """
        frames = []
        for name in factor_names:
            series = self.cache_manager.get_cached_factor(ts_code, name)
            if series is None or len(series) == 0:
                continue
            s = pd.Series(series.values, index=pd.Index(list(series.index), name='trade_date'), name=name)
            s = s[~s.index.duplicated(keep='last')]
            frames.append(s)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=1, join='outer').sort_index()

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息 — 426号 P2-3：改走分库读取

        原实现用 self.cache_manager.conn（总库），factor_cache 在 compute_cache.db
        → 统计恒 0。改走 _query_shard 分库读取。

        500号#47：`_query_shard` 失败返回空 DataFrame 时，**DB 瞬时错误与「真空缓存」
        不可区分**、恒报 0；此处补 warning 日志（读侧不可区分属 `_query_shard` 既定契约，
        至少让故障在日志可见）。
        """
        stats = self.cache_manager._query_shard(
            'factor_cache',
            "SELECT COUNT(DISTINCT ts_code) AS stock_count, "
            "COUNT(DISTINCT factor_name) AS factor_count, "
            "COUNT(*) AS total_records, MAX(cached_at) AS last_update "
            "FROM factor_cache"
        )
        if stats is None or stats.empty:
            # 空结果：可能为真空缓存，也可能为分库读失败 → 记 warning 便于区分
            logger.warning("factor_cache 统计读取为空（真空缓存或分库读失败，返回 0）")
            return {'stock_count': 0, 'factor_count': 0, 'total_records': 0, 'last_update': None}
        row = stats.iloc[0]
        return {
            'stock_count': int(row['stock_count'] or 0),
            'factor_count': int(row['factor_count'] or 0),
            'total_records': int(row['total_records'] or 0),
            'last_update': row['last_update'],
        }

    def clear_cache(self, ts_code: Optional[str] = None,
                   factor_name: Optional[str] = None):
        """清除缓存 — 426号 P2-3：改走分库 _exec_shard

        原实现用 self.cache_manager.conn（总库），factor_cache 在 compute_cache.db
        → DELETE 空操作。改走 _exec_shard 分库执行（内部含提交）。
        """
        if ts_code and factor_name:
            self.cache_manager._exec_shard(
                'factor_cache',
                "DELETE FROM factor_cache WHERE ts_code = ? AND factor_name = ?",
                [ts_code, factor_name])
        elif ts_code:
            self.cache_manager._exec_shard(
                'factor_cache',
                "DELETE FROM factor_cache WHERE ts_code = ?",
                [ts_code])
        elif factor_name:
            self.cache_manager._exec_shard(
                'factor_cache',
                "DELETE FROM factor_cache WHERE factor_name = ?",
                [factor_name])
        else:
            self.cache_manager._exec_shard('factor_cache', "DELETE FROM factor_cache")

    def clean_old_data(self, cutoff: str):
        """清理 factor_cache — 委托给 ECM"""
        self.cache_manager.clean_factor_cache(cutoff)
