"""
AnalysisCache — 日内分析结果缓存

消除缠论和量价在"个股分析"和"筛选批量"双路径间的重复计算。
以 (ts_code, data_length) 为 key 缓存分析器输出，TTL=1 交易日。
"""

import logging
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AnalysisCache:
    """日内分析结果缓存。

    用法:
        cache = AnalysisCache()
        result = cache.get("chanlun:000001.SZ:120")
        if result is None:
            result = analyzer.analyze(df)
            cache.set("chanlun:000001.SZ:120", result)
    """

    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._today: date = date.today()

    def _check_date(self) -> None:
        today = date.today()
        if today != self._today:
            self._cache.clear()
            self._today = today

    def get(self, key: str) -> Optional[Dict]:
        self._check_date()
        return self._cache.get(key)

    def set(self, key: str, result: Dict) -> None:
        self._check_date()
        self._cache[key] = result

    def clear(self) -> None:
        self._cache.clear()
        self._today = date.today()

    @property
    def size(self) -> int:
        return len(self._cache)


# 模块级单例
_analysis_cache: Optional[AnalysisCache] = None


def get_analysis_cache() -> AnalysisCache:
    """获取全局 AnalysisCache 单例。"""
    global _analysis_cache
    if _analysis_cache is None:
        _analysis_cache = AnalysisCache()
    return _analysis_cache
