"""
KlineResampler — K线重采样管道
===============================
实现 151-P3-3: 分钟 → 日 → 周自动重采样

从分钟数据按指定频率聚合为更长时间周期的K线，
使用 OHLC 规则: Open=首条, High=最高, Low=最低, Close=末条, Volume=合计
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Callable
from collections import OrderedDict

logger = logging.getLogger(__name__)


class KlineResampler:
    """
    K线重采样管道

    支持:
    - 分钟→日线: 聚合同一天的分钟数据
    - 日线→周线: 按自然周聚合
    - 日线→月线: 按自然月聚合
    - 自定义频率: 任意时间窗口聚合
    """

    FREQ_AGG_MAP = {
        'daily':   {'unit': 'day',  'format': '%Y%m%d'},
        'weekly':  {'unit': 'week', 'format': '%Y-W%W'},
        'monthly': {'unit': 'month','format': '%Y-%m'},
    }

    def resample(self, data: List[Dict], source_freq: str, target_freq: str,
                 time_key: str = 'trade_time') -> List[Dict]:
        """
        重采样K线数据

        Args:
            data: 源K线数据列表
            source_freq: 源频率 ('1min', '5min', '15min', 'daily', 'weekly')
            target_freq: 目标频率 ('daily', 'weekly', 'monthly')
            time_key: 时间字段名

        Returns:
            重采样后的K线列表
        """
        if not data:
            return []

        # 判断是否需要聚合
        if target_freq == 'daily' and source_freq in ('daily', 'weekly', 'monthly'):
            return data  # 已经是日线或更高
        if target_freq == 'weekly' and source_freq in ('weekly', 'monthly'):
            return data

        if source_freq in ('1min', '5min', '15min', '30min', '60min'):
            if target_freq == 'daily':
                return self._minute_to_daily(data, time_key)
            elif target_freq in ('weekly', 'monthly'):
                daily = self._minute_to_daily(data, time_key)
                return self._daily_to_weekly(daily) if target_freq == 'weekly' \
                    else self._daily_to_monthly(daily)
        elif source_freq == 'daily':
            if target_freq == 'weekly':
                return self._daily_to_weekly(data)
            elif target_freq == 'monthly':
                return self._daily_to_monthly(data)

        logger.warning(f"不支持的重采样: {source_freq} → {target_freq}")
        return data

    def _minute_to_daily(self, data: List[Dict], time_key: str = 'trade_time') -> List[Dict]:
        """分钟→日线"""
        from collections import defaultdict
        groups = defaultdict(list)

        for bar in data:
            ts = self._parse_time(bar.get(time_key, ''))
            day_key = ts.strftime('%Y%m%d')
            groups[day_key].append(bar)

        result = []
        for day_key in sorted(groups.keys()):
            bars = groups[day_key]
            result.append({
                'trade_date': day_key,
                'open': float(bars[0].get('open', 0)),
                'high': max(float(b.get('high', 0)) for b in bars),
                'low': min(float(b.get('low', 0)) for b in bars),
                'close': float(bars[-1].get('close', 0)),
                'vol': sum(float(b.get('vol', 0)) for b in bars),
                'amount': sum(float(b.get('amount', 0)) for b in bars),
            })
        return result

    def _daily_to_weekly(self, daily_data: List[Dict]) -> List[Dict]:
        """日线→周线"""
        from collections import defaultdict
        groups = defaultdict(list)

        for bar in daily_data:
            d = self._parse_date(bar.get('trade_date', ''))
            iso = d.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
            groups[week_key].append(bar)

        result = []
        for week_key in sorted(groups.keys()):
            bars = groups[week_key]
            result.append({
                'trade_date': week_key,
                'open': float(bars[0].get('open', 0)),
                'high': max(float(b.get('high', 0)) for b in bars),
                'low': min(float(b.get('low', 0)) for b in bars),
                'close': float(bars[-1].get('close', 0)),
                'vol': sum(float(b.get('vol', 0)) for b in bars),
                'amount': sum(float(b.get('amount', 0)) for b in bars),
            })
        return result

    def _daily_to_monthly(self, daily_data: List[Dict]) -> List[Dict]:
        """日线→月线"""
        from collections import defaultdict
        groups = defaultdict(list)

        for bar in daily_data:
            d = self._parse_date(bar.get('trade_date', ''))
            month_key = d.strftime('%Y-%m')
            groups[month_key].append(bar)

        result = []
        for month_key in sorted(groups.keys()):
            bars = groups[month_key]
            result.append({
                'trade_date': month_key,
                'open': float(bars[0].get('open', 0)),
                'high': max(float(b.get('high', 0)) for b in bars),
                'low': min(float(b.get('low', 0)) for b in bars),
                'close': float(bars[-1].get('close', 0)),
                'vol': sum(float(b.get('vol', 0)) for b in bars),
                'amount': sum(float(b.get('amount', 0)) for b in bars),
            })
        return result

    # ── 辅助 ──

    def _parse_time(self, s: str) -> datetime:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S',
                     '%Y%m%d %H%M%S', '%Y%m%d'):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return datetime.now()

    def _parse_date(self, s: str) -> datetime:
        for fmt in ('%Y%m%d', '%Y-%m-%d'):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return datetime.now()


# 快捷函数
def resample(data: List[Dict], source_freq: str, target_freq: str) -> List[Dict]:
    return KlineResampler().resample(data, source_freq, target_freq)
