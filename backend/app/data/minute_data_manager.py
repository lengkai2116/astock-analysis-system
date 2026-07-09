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
from app.data.memory_cache import TieredMemoryCache

logger = logging.getLogger(__name__)


class MinuteDataManager:
    """分钟级数据管理器 — 多源路由 + 缓存"""

    FREQ_MAP = {'1min': 1, '5min': 5, '15min': 15, '30min': 30, '60min': 60}

    def __init__(self):
        self.tushare = TushareProvider()
        self.cache = TieredMemoryCache()
        self._has_tushare_high = None  # 惰性检测，首次 get_minute_data 时获取

    def _check_tushare_permission(self) -> bool:
        """惰性检查 Tushare 分钟数据权限（只在首次 get_minute_data 时触发）"""
        if self._has_tushare_high is not None:
            return self._has_tushare_high
        try:
            data = self.tushare.get_minute_data('000001.SZ', freq='5min')
            self._has_tushare_high = data is not None and len(data) > 0
            return self._has_tushare_high
        except Exception:
            self._has_tushare_high = False
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
        cached = self.cache.get(cache_key, level='intraday')
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
                from app.data.akshare_provider import AkshareProvider
                ak = AkshareProvider()
                ak_data = ak.get_minute_data(ts_code, freq=freq, start_date=start, end_date=end)
                if ak_data:
                    data = ak_data  # AKShare 返回格式与 _normalize_tushare 兼容
                    logger.info(f"AKShare 分钟数据降级成功 ({ts_code})")
            except Exception as e:
                logger.debug(f"AKShare 分钟数据降级也失败 ({ts_code}): {e}")

        if data:
            self.cache.set(cache_key, data, level='intraday')  # 5分钟缓存
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


    def batch_get(self, ts_codes: List[str], freq: str = '15min',
                  days_back: int = 5) -> Dict[str, List[Dict]]:
        """批量获取多只股票的分钟数据"""
        result = {}
        for code in ts_codes:
            result[code] = self.get_minute_data(code, freq=freq, days_back=days_back)
        return result

    # ══════════════════════════════════════════════
    # 252号方案：从 ECM minute_kline_cache 读取
    # ══════════════════════════════════════════════

    def get_cached_minute(self, ts_code: str, freq: str = '1min') -> Optional[List[Dict]]:
        """优先从 ECM minute_kline_cache 读取分钟线数据"""
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            trade_date = datetime.now().strftime('%Y-%m-%d')

            # Step 1: 尝试精确freq匹配
            for try_freq in [freq, '5min', '1min']:
                df = ecm.get_cached_minute_kline(ts_code, trade_date=trade_date, freq=try_freq)
                if df is not None and not df.empty:
                    records = df.to_dict('records')
                    for r in records:
                        if 'trade_time' not in r:
                            r['trade_time'] = str(r.get('datetime', ''))
                    # 如果请求的freq与实际获取的不一致，做重采样
                    if try_freq != freq:
                        records = self._resample_minute(records, try_freq, freq)
                    return records

            # Step 2: 尝试跨日期读取（盘后数据）
            for try_freq in [freq, '5min', '1min']:
                df = ecm.get_cached_minute_kline(ts_code, freq=try_freq)
                if df is not None and not df.empty:
                    records = df.to_dict('records')
                    cutoff = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
                    records = [r for r in records if str(r.get('trade_date', '')) >= cutoff]
                    for r in records:
                        if 'trade_time' not in r:
                            r['trade_time'] = str(r.get('datetime', ''))
                    if try_freq != freq:
                        records = self._resample_minute(records, try_freq, freq)
                    return records
        except Exception as e:
            logger.debug(f"ECM 分钟数据读取失败: {e}")
        return None

    def _resample_minute(self, records: list, from_freq: str, to_freq: str) -> list:
        """分钟线频率转换（如 1min → 15min）"""
        from collections import defaultdict
        if not records:
            return []
        total_min = int(to_freq.replace('min', ''))
        base_min = int(from_freq.replace('min', ''))
        group_size = total_min // base_min
        if group_size <= 1:
            return records
        # 按日期+时间片分组聚合
        groups = defaultdict(list)
        for r in records:
            tt = r.get('trade_time', '')
            # 取时间部分 "2026-07-07 10:08:00" → 取分钟
            try:
                ts = tt.split(' ')[1] if ' ' in tt else tt
                parts = ts.split(':')
                minute_slot = int(parts[0]) * 60 + int(parts[1])
                slot = minute_slot // total_min
                key = (tt[:10] if len(tt) > 10 else tt.split(' ')[0], slot)
            except Exception:
                key = (tt, 0)
            groups[key].append(r)

        result = []
        for (date, slot), bars in sorted(groups.items()):
            o = bars[0].get('open', 0)
            c = bars[-1].get('close', 0)
            h = max(b.get('high', 0) for b in bars)
            lv = min(b.get('low', float('inf')) for b in bars)
            v = sum(b.get('volume', 0) or b.get('vol', 0) for b in bars)
            a = sum(b.get('amount', 0) for b in bars)
            first_tt = bars[0].get('trade_time', '')
            result.append({
                'trade_time': first_tt,
                'open': float(o), 'high': float(h), 'low': float(lv), 'close': float(c),
                'vol': float(v), 'amount': float(a),
            })
        return result
