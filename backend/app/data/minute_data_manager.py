"""
MinuteDataManager — 分钟级数据通道
====================================
实现 151-P1-1: 分钟级数据获取、缓存、降级
- Tushare Pro stk_mins / pro_bar 接口
- AKShare 分钟数据备用
- DuckDB 本地缓存加速
- 频率支持: 1min / 5min / 15min / 30min / 60min
"""

import logging
import pandas as pd
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from app.data.tushare_provider import TushareProvider
from app.data.akshare_provider import AkshareProvider
from app.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class MinuteDataManager:
    """分钟级数据管理器 — 多源路由 + 缓存"""

    FREQ_MAP = {'1min': 1, '5min': 5, '15min': 15, '30min': 30, '60min': 60}

    def __init__(self):
        self.tushare = TushareProvider()
        self.akshare = AkshareProvider()
        self.cache = CacheManager()
        self._has_tushare_high = self._check_tushare_permission()

    def _check_tushare_permission(self) -> bool:
        """检查 Tushare 是否有 stk_mins 权限（5000积分+）"""
        try:
            data = self.tushare.get_minute_data('000001.SZ', freq='5min', limit=1)
            return data is not None and len(data) > 0
        except Exception:
            return False

    def get_minute_data(self, ts_code: str, freq: str = '15min',
                        start: Optional[str] = None,
                        end: Optional[str] = None,
                        days_back: int = 30) -> List[Dict]:
        """
        获取分钟线数据，自动降级

        Args:
            ts_code: 股票代码
            freq: 频率 1min/5min/15min/30min/60min
            start: 起始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD
            days_back: 回溯天数（start 为空时使用）

        Returns:
            [{'trade_time': str, 'open': float, 'high': float, 'low': float,
              'close': float, 'vol': float, 'amount': float}, ...]
        """
        if freq not in self.FREQ_MAP:
            logger.warning(f"不支持的频率: {freq}，使用 15min")
            freq = '15min'

        cache_key = f"minute:{ts_code}:{freq}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # 尝试 Tushare → AKShare 降级
        data = []
        if self._has_tushare_high:
            try:
                raw = self.tushare.get_minute_data(
                    ts_code, freq=freq,
                    start_date=start, end_date=end
                )
                if raw and len(raw) > 0:
                    data = self._normalize_tushare(raw)
            except Exception as e:
                logger.warning(f"Tushare 分钟数据失败 ({ts_code}): {e}")

        if not data:
            try:
                raw = self.akshare.get_minute_data(ts_code, freq=freq)
                if raw and len(raw) > 0:
                    data = self._normalize_akshare(raw)
            except Exception as e:
                logger.warning(f"AKShare 分钟数据失败 ({ts_code}): {e}")

        if data:
            self.cache.set(cache_key, data, ttl=300)  # 5分钟缓存
        return data

    def _normalize_tushare(self, raw: List[Dict]) -> List[Dict]:
        """统一 Tushare 分钟数据格式"""
        result = []
        for r in raw:
            result.append({
                'trade_time': str(r.get('trade_time', r.get('ts_code', ''))),
                'open': float(r.get('open', 0)),
                'high': float(r.get('high', 0)),
                'low': float(r.get('low', 0)),
                'close': float(r.get('close', 0)),
                'vol': float(r.get('vol', r.get('volume', 0))),
                'amount': float(r.get('amount', 0)),
            })
        return result

    def _normalize_akshare(self, raw: List[Dict]) -> List[Dict]:
        """统一 AKShare 分钟数据格式"""
        result = []
        for r in raw:
            result.append({
                'trade_time': str(r.get('日期', r.get('trade_time', ''))),
                'open': float(r.get('开盘', r.get('open', 0))),
                'high': float(r.get('最高', r.get('high', 0))),
                'low': float(r.get('最低', r.get('low', 0))),
                'close': float(r.get('收盘', r.get('close', 0))),
                'vol': float(r.get('成交量', r.get('vol', 0))),
                'amount': float(r.get('成交额', r.get('amount', 0))),
            })
        return result

    def batch_get(self, ts_codes: List[str], freq: str = '15min',
                  days_back: int = 5) -> Dict[str, List[Dict]]:
        """批量获取多只股票的分钟数据"""
        result = {}
        for code in ts_codes:
            result[code] = self.get_minute_data(code, freq=freq, days_back=days_back)
        return result
