"""
AkshareDataReader — AKShare 盘中数据全局读取接口
=================================================
所有模块通过此接口读取 AKShare 盘中数据，不直接调用 AkshareProvider 或 AKShare API。

读取来源（优先级）：
  1. InMemoryStateStore（内存，盘中主数据源，O(1) 读取）
  2. DuckDB as_* 表（归档，盘后或内存无数据时回退）

设计原则：
  - 全局单例，每个模块只引用此单例
  - 只读不写（写入由 AkshareCollector 负责）
  - 返回统一格式（list[dict] 或 pd.DataFrame）
  - 数据不存在时返回空列表/None（不抛异常）
"""

import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any

import pandas as pd

logger = logging.getLogger(__name__)


# 盘中内存状态（惰性导入避免循环引用）
_mem_store = None


def _get_mem_store():
    global _mem_store
    if _mem_store is None:
        from app.data.in_memory_store import store
        _mem_store = store
    return _mem_store


class AkshareDataReader:
    """AKShare 盘中数据全局只读接口（内存优先 → DuckDB 归档回退）

    用法：
        from app.data.akshare_reader import reader
        snapshot = reader.get_market_snapshot()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cache = None  # lazy init
        self._stale_threshold_sec = 300  # 5 分钟数据过期告警

    @property
    def _ecm(self):
        """惰性初始化 EnhancedCacheManager（全局单例）"""
        if self._cache is None:
            from app.data.enhanced_cache_manager import get_ecm_instance
            self._cache = get_ecm_instance()
        return self._cache

    # ── 实时快照 ─────────────────────────────────────────────

    def get_market_snapshot(self) -> List[Dict]:
        """获取全市场实时行情快照

        读取顺序：内存（盘中）→ DuckDB as_*（归档）
        """
        # 1. 尝试内存（盘中主数据源）
        store = _get_mem_store()
        if not store.is_stale('snapshot', max_age_sec=600):
            snapshot = store.get_snapshot()
            if snapshot:
                return snapshot
            logger.debug("内存快照为空，尝试 DuckDB 归档")
        # 2. 回退 DuckDB 归档
        try:
            df = self._ecm.read_as_market_snapshot()
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_market_snapshot 归档回退失败: {e}")
            return []

    def get_batch_quotes(self, ts_codes: List[str]) -> List[Dict]:
        """批量获取指定股票列表的实时行情

        Args:
            ts_codes: 股票代码列表，如 ['600519.SH', '000001.SZ']

        Returns:
            list[dict]: 包含指定股票的行情数据
        """
        if not ts_codes:
            return []
        # 1. 尝试内存（盘中主数据源）
        store = _get_mem_store()
        if not store.is_stale('snapshot', max_age_sec=600):
            records = store.batch_get(ts_codes)
            if records:
                return records
        # 2. 回退 DuckDB 归档
        try:
            df = self._ecm.read_as_market_snapshot_by_codes(ts_codes)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_batch_quotes 归档回退失败: {e}")
            return []

    def get_realtime_spot(self, ts_code: str) -> Optional[Dict]:
        """获取单只股票实时行情

        Args:
            ts_code: 股票代码

        Returns:
            dict 或 None
        """
        if not ts_code:
            return None
        # 1. 尝试内存
        store = _get_mem_store()
        if not store.is_stale('snapshot', max_age_sec=600):
            r = store.get_by_code(ts_code)
            if r:
                return r
        # 2. 回退 DuckDB
        try:
            records = self.get_batch_quotes([ts_code])
            return records[0] if records else None
        except Exception:
            return None

    # ── 涨跌榜 ───────────────────────────────────────────────

    def get_top_stocks(self, type: str = 'up', limit: int = 10) -> List[Dict]:
        """获取涨幅/跌幅榜

        Args:
            type: 'up' 涨幅榜 / 'down' 跌幅榜
            limit: 返回数量
        """
        store = _get_mem_store()
        records = store.get_top_stocks(type)
        if records:
            return records[:limit]
        # 回退 DuckDB
        try:
            df = self._ecm.read_as_top_stocks(type)
            records = df.to_dict('records') if not df.empty else []
            for r in records:
                r.pop('updated_at', None)
            return records[:limit]
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_top_stocks 回退失败: {e}")
            return []

    # ── 板块排行 ─────────────────────────────────────────────

    def get_sector_rankings(self, top_n: int = 20) -> List[Dict]:
        """获取行业板块涨跌排行"""
        store = _get_mem_store()
        records = store.get_sectors()
        if records:
            return records[:top_n]
        try:
            df = self._ecm.read_as_sector_ranking(top_n)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_sector_rankings 回退失败: {e}")
            return []

    def get_concept_rankings(self, top_n: int = 20) -> List[Dict]:
        """获取概念板块涨跌排行"""
        store = _get_mem_store()
        records = store.get_concepts()
        if records:
            return records[:top_n]
        try:
            df = self._ecm.read_as_concept_ranking(top_n)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_concept_rankings 回退失败: {e}")
            return []

    # ── 涨跌停池 ─────────────────────────────────────────────

    def get_limit_pool(self, limit_type: str = None) -> Dict[str, List[Dict]]:
        """获取涨跌停股票列表

        Args:
            limit_type: 'up' 涨停 / 'down' 跌停 / None 返回全部

        Returns:
            {'up': [...], 'down': [...]}
        """
        result = {'up': [], 'down': []}
        store = _get_mem_store()
        if limit_type in ('up', None):
            result['up'] = store.get_limit_pool('up')
        if limit_type in ('down', None):
            result['down'] = store.get_limit_pool('down')
        if result['up'] or result['down']:
            return result
        # 回退 DuckDB
        try:
            df = self._ecm.read_as_limit_pool(limit_type)
            if not df.empty:
                for _, row in df.iterrows():
                    record = {
                        'ts_code': row.get('ts_code'),
                        'name': row.get('name'),
                        'price': float(row.get('price', 0)),
                        'change_pct': float(row.get('change_pct', 0)),
                    }
                    lt = row.get('limit_type', '')
                    if lt == 'up':
                        result['up'].append(record)
                    else:
                        result['down'].append(record)
            return result
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_limit_pool 回退失败: {e}")
            return result

    # ── 分钟K线 ──────────────────────────────────────────────

    def get_minute_kline(self, ts_code: str, trade_date: str = None,
                         freq: str = '5min') -> List[Dict]:
        """获取个股分钟K线

        Args:
            ts_code: 股票代码
            trade_date: 交易日，默认今天
            freq: 1min/5min/15min/30min/60min
        """
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        # 仅当日数据走内存
        if trade_date == today:
            store = _get_mem_store()
            records = store.get_minute_kline(ts_code)
            if records:
                return records
        try:
            df = self._ecm.read_as_minute_kline(ts_code, trade_date, freq)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_minute_kline 回退失败: {e}")
            return []

    # ── 龙虎榜 ───────────────────────────────────────────────

    def get_lhb_detail(self, trade_date: str = None) -> List[Dict]:
        """获取龙虎榜数据"""
        today = datetime.now().strftime('%Y%m%d')
        if trade_date in (None, today):
            store = _get_mem_store()
            records = store.get_lhb()
            if records:
                return records
        try:
            df = self._ecm.read_as_lhb_detail(trade_date)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_lhb_detail 回退失败: {e}")
            return []

    # ── 新闻 ──────────────────────────────────────────────────

    def get_news(self, limit: int = 50) -> List[Dict]:
        """获取最新财经新闻"""
        store = _get_mem_store()
        records = store.get_news()
        if records:
            return records[:limit]
        try:
            df = self._ecm.read_as_news(limit)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.debug(f"AkshareDataReader.get_news 回退失败: {e}")
            return []

    # ── 个股盘口 ─────────────────────────────────────────────

    def get_quote_cache(self, ts_code: str) -> Dict:
        """获取个股盘口缓存（373号§9.3：as_quote_cache 已废弃，始终返回空）"""
        return {}

    # ── 健康检查 ──────────────────────────────────────────────

    def get_last_updated(self) -> Optional[datetime]:
        """获取盘中数据最近更新时间（从 InMemoryStateStore 获取）"""
        store = _get_mem_store()
        t = store.get_meta('snapshot')
        return t

    def is_data_stale(self, max_age_sec: int = 300) -> bool:
        """判断盘中数据是否过期"""
        store = _get_mem_store()
        return store.is_stale('snapshot', max_age_sec)

    def stats(self) -> Dict[str, Any]:
        """内存状态快照（调试用）"""
        store = _get_mem_store()
        return store.stats()


# 全局单例 — 所有模块引用此实例
reader = AkshareDataReader()
