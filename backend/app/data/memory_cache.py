"""
TieredMemoryCache — 三级 TTL 内存缓存层
========================================
提供实时/盘中/分析三级粒度的内存缓存，使用 cachetools.TTLCache 实现。
纯内存操作，不依赖 DuckDB/Redis，用于盘中快速查询的本地缓存。

缓存级别：
  realtime  — 3s  TTL, 100 条目 — 实时行情（28字段/盘口）
  intraday  — 5min TTL, 200 条目 — 盘中数据（日线/分钟线）
  analysis  — 30min TTL, 100 条目 — 分析数据（资金流向/板块/概念）

线程安全：使用 threading.RLock()
"""

import logging
import threading
from typing import Any, Dict, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# 缓存级别配置
CACHE_LEVELS = {
    'realtime': {'ttl': 3, 'maxsize': 200},         # 实时行情，3s 刷新（原100→200）
    'intraday': {'ttl': 300, 'maxsize': 500},        # 盘中数据，5min 过期（原200→500）
    'analysis': {'ttl': 1800, 'maxsize': 300},       # 分析数据，30min 过期（原100→300）
    'dashboard': {'ttl': 60, 'maxsize': 500},        # 仪表盘响应，60s 过期（新增）
}

VALID_LEVELS = set(CACHE_LEVELS.keys())


class TieredMemoryCache:
    """三级 TTL 内存缓存 — 纯内存，无外部依赖"""

    def __init__(self):
        self._lock = threading.RLock()
        self._caches: Dict[str, TTLCache] = {
            level: TTLCache(maxsize=cfg['maxsize'], ttl=cfg['ttl'])
            for level, cfg in CACHE_LEVELS.items()
        }
        self._hits = {level: 0 for level in CACHE_LEVELS}
        self._misses = {level: 0 for level in CACHE_LEVELS}

    def get(self, key: str, level: str = 'realtime') -> Optional[Any]:
        """从指定级别缓存读取

        Args:
            key: 缓存键
            level: 缓存级别 (realtime/intraday/analysis)

        Returns:
            缓存的值，未命中时返回 None
        """
        if level not in VALID_LEVELS:
            logger.warning(f"无效缓存级别: {level}，使用 realtime")
            level = 'realtime'

        with self._lock:
            cache = self._caches[level]
            if key in cache:
                self._hits[level] += 1
                return cache[key]
            self._misses[level] += 1
            return None

    def set(self, key: str, value: Any, level: str = 'realtime') -> None:
        """写入指定级别缓存

        Args:
            key: 缓存键
            value: 缓存值（必须可 pickle 序列化，TTLCache 无此限制）
            level: 缓存级别
        """
        if level not in VALID_LEVELS:
            logger.warning(f"无效缓存级别: {level}，使用 realtime")
            level = 'realtime'

        with self._lock:
            self._caches[level][key] = value

    def clear(self, level: Optional[str] = None) -> None:
        """清空缓存

        Args:
            level: 指定级别，为 None 时清空全部
        """
        with self._lock:
            if level:
                if level in self._caches:
                    self._caches[level].clear()
                    self._hits[level] = 0
                    self._misses[level] = 0
            else:
                for lvl in self._caches:
                    self._caches[lvl].clear()
                    self._hits[lvl] = 0
                    self._misses[lvl] = 0

    def invalidate(self, key: str, level: Optional[str] = None) -> None:
        """驱逐指定键的缓存（不报错）

        Args:
            key: 缓存键
            level: 指定级别，为 None 时从所有级别驱逐
        """
        with self._lock:
            if level:
                self._caches[level].pop(key, None)
            else:
                for cache in self._caches.values():
                    cache.pop(key, None)

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取各级缓存统计信息

        Returns:
            {
                'realtime': {'size': int, 'maxsize': int, 'hits': int, 'misses': int, 'hit_rate': float, 'ttl': int},
                ...
            }
        """
        with self._lock:
            stats = {}
            for level, cache in self._caches.items():
                hits = self._hits[level]
                misses = self._misses[level]
                total = hits + misses
                stats[level] = {
                    'size': len(cache),
                    'maxsize': cache.maxsize,
                    'ttl': cache.ttl,
                    'hits': hits,
                    'misses': misses,
                    'hit_rate': round(hits / total, 4) if total > 0 else 0.0,
                }
            return stats
