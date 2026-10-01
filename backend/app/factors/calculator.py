"""
因子计算器
用于批量计算因子
"""
import logging
from typing import Dict, List, Optional

import pandas as pd

from .registry import get_factor_registry

logger = logging.getLogger(__name__)
class FactorCalculator:
    """
    因子计算器
    """

    def __init__(self):
        # 501 #R29：注册表改为惰性获取——原 __init__ 急切 get_factor_registry()，
        # 若注册表尚未填充（并发首调）会缓存空/半成品实例于实例生命周期。
        self.registry = None

    def _get_registry(self):
        """501 #R29：方法内取全局注册表（每次调用现取，注册表双检锁保证完整）"""
        if self.registry is None:
            self.registry = get_factor_registry()
        return self.registry

    def calculate_single_factor(self, data: pd.DataFrame,
                                factor_name: str,
                                ts_code: str = None,
                                **kwargs) -> Optional[pd.Series]:
        """
        计算单个因子
        优先读取 factor_cache（需提供 ts_code），无缓存时实时计算

        500号批次1（#44）：缓存命中路径**仅在无参数时使用**——`factor_cache` 主键
        为 (ts_code, trade_date, factor_name)，不含计算参数（period 等）。若调用方传入
        `**kwargs`（非默认参数），缓存值可能是**另一套参数**的结果，直接命中会返回错误
        序列；故有 kwargs 时**跳过缓存直算**，保证语义正确。
        """
        # 缓存优先（仅默认参数；带 kwargs 的调用不可复用无参数缓存）
        if ts_code is not None and not kwargs:
            try:
                from app.data import get_data_manager
                dm = get_data_manager()
                cached = dm.get_cached_factors(ts_code, [factor_name])
                if cached is not None and not cached.empty:
                    cached = cached[cached['factor_name'] == factor_name]
                    if not cached.empty:
                        cached = cached.sort_values('trade_date')
                        result = cached.set_index('trade_date')['value']
                        logger.debug("factor_cache 命中: %s", factor_name)
                        return result
            except Exception as e:
                # 501 #R63：惰性日志——参数化避免 f-string 无条件格式化
                logger.debug("factor_cache 读取失败(%s): %s", factor_name, e)

        # 501 #R37：入口统一 copy——原仅归一化分支 copy，缓存未命中路径/无归一化
        # 路径共用调用方原对象，check_data/calculate 就地 mutate 会污染调用方数据
        data = data.copy()
        # 414号P2.6: 列名标准化 — 因子引用 'vol'，分钟数据用 'volume'
        if 'volume' in data.columns and 'vol' not in data.columns:
            data['vol'] = data['volume']

        # 实时计算（#R29：惰性取注册表）
        factor = self._get_registry().get_factor(factor_name, **kwargs)
        if factor is None:
            logger.error(f"未找到因子: {factor_name}")
            return None
        if not factor.check_data(data):
            logger.error(f"数据不满足因子 {factor_name} 的要求")
            return None
        try:
            result = factor.calculate(data)
            return result
        except Exception as e:
            logger.error(f"计算因子 {factor_name} 失败: {e}")
            return None

    def calculate_multiple_factors(self, data: pd.DataFrame,
                                   factor_configs: List[Dict]) -> pd.DataFrame:
        """
        批量计算多个因子
        factor_configs 格式: [{"name": "MA", "params": {"period": 20}}]

        501号批次3：
          - #R35：重复因子名（同名不同参）静默覆盖后值 → 记 warning 提示消费方
            使用烘焙参数的唯一因子名（MA_5/MA_20）。
          - #R36：因子返回序列与 data.index 异索引时，pandas 按标签对齐会静默填 NaN；
            此处显式 reindex 并对齐校验，错位可见而非静默。
        """
        result_df = pd.DataFrame(index=data.index)

        for config in factor_configs:
            factor_name = config.get("name")
            params = config.get("params", {})

            if factor_name in result_df.columns:
                logger.warning(
                    f"因子名重复，后值将覆盖前值: {factor_name} (params={params})")
            factor_series = self.calculate_single_factor(data, factor_name, **params)
            if factor_series is not None:
                # #R36：按 data.index 对齐——异索引时 reindex 产生 NaN 行并告警
                if not factor_series.index.equals(data.index):
                    missing = factor_series.index.difference(data.index)
                    logger.warning(
                        f"因子 {factor_name} 索引与 data 不一致（{len(missing)} 个标签对齐为 NaN），"
                        f"已 reindex 对齐")
                    factor_series = factor_series.reindex(data.index)
                result_df[factor_name] = factor_series

        return result_df

    def calculate_factor_combination(self, data: pd.DataFrame,
                                     factor_configs: List[Dict]) -> pd.Series:
        """
        计算因子加权组合
        factor_configs 格式: [{"name": "MA", "params": {}, "weight": 0.3}]

        501 #R53：本方法**全仓无调用方（死代码路径）**——登记待接线时修复；
        已顺手修权重分母错（仅统计实际参与因子）与全失败返回空。
        """
        factors_df = self.calculate_multiple_factors(data, factor_configs)

        if factors_df.empty:
            return pd.Series(dtype=float, index=data.index)

        # 501 #R53：权重分母仅统计实际参与计算的因子（原含失败/缺名因子 → 分母偏大）
        contributing = [c for c in factor_configs
                        if c.get("name") in factors_df.columns]
        total_weight = sum(c.get("weight", 1.0) for c in contributing)
        if not contributing or total_weight == 0:
            logger.warning("无可用因子或权重和为0，返回空序列")
            return pd.Series(dtype=float, index=data.index)

        # 加权平均
        result = pd.Series(0.0, index=data.index)
        for config in contributing:
            name = config.get("name")
            weight = config.get("weight", 1.0)
            result += factors_df[name] * (weight / total_weight)

        return result
