"""
交易时段工具类 — A 股交易时间判断
===================================
提供交易时段判断函数，用于数据源时间感知路由。

A 股交易时段：
  集合竞价：09:15-09:25
  上午盘：  09:30-11:30
  中午休市：11:30-13:00
  下午盘：  13:00-15:00
  收盘处理：15:00-15:30

节假日跳过周末（周六/周日），法定节假日通过 .env 配置。
"""

import logging
import os
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

# 默认时区偏移（北京时间 UTC+8）
TIMEZONE_OFFSET = int(os.getenv('TZ_OFFSET', '8'))

# 交易时段常量
PRE_MARKET_START = time(9, 15)
PRE_MARKET_END = time(9, 25)
MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)
CLOSE_END = time(15, 30)

# 法定节假日（快速判断，精确列表由外部配置）
_DEFAULT_HOLIDAYS = frozenset({
    '2026-01-01', '2026-01-28', '2026-01-29', '2026-01-30', '2026-01-31',
    '2026-02-01', '2026-02-02', '2026-02-03', '2026-04-04', '2026-04-05',
    '2026-04-06', '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04',
    '2026-05-05', '2026-06-12', '2026-06-13', '2026-06-14',
    '2026-09-15', '2026-09-16', '2026-09-17',
    '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04',
    '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08',
})


def _now() -> datetime:
    """获取当前时间（北京时间，UTC+8）"""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


def is_holiday(d: datetime) -> bool:
    """判断是否为法定节假日或周末"""
    if d.weekday() >= 5:  # 周六(5)/周日(6)
        return True
    return d.strftime('%Y-%m-%d') in _DEFAULT_HOLIDAYS


def is_trading_time(dt: datetime = None) -> bool:
    """判断当前是否为 A 股交易时段（上午 9:30-11:30 + 下午 13:00-15:00）

    Args:
        dt: 指定时间（默认当前北京时间）

    Returns:
        True 如果在交易时段
    """
    dt = dt or _now()
    if is_holiday(dt):
        return False
    t = dt.time()
    in_morning = MORNING_START <= t <= MORNING_END
    in_afternoon = AFTERNOON_START <= t <= AFTERNOON_END
    return in_morning or in_afternoon


def is_pre_market(dt: datetime = None) -> bool:
    """判断是否为集合竞价时段（09:15-09:25）"""
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return False
    return PRE_MARKET_START <= dt.time() <= PRE_MARKET_END


def is_close_time(dt: datetime = None) -> bool:
    """判断是否为收盘处理期（15:00-15:30）"""
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return False
    return AFTERNOON_END <= dt.time() <= CLOSE_END


def get_current_session(dt: datetime = None) -> str:
    """获取当前交易时段

    Returns:
        'pre'      — 集合竞价 (09:15-09:25)
        'morning'  — 上午盘   (09:30-11:30)
        'noon'     — 中午休市 (11:30-13:00)
        'afternoon'— 下午盘   (13:00-15:00)
        'close'    — 收盘处理 (15:00-15:30)
        'off'      — 非交易时间（含节假日/周末）
    """
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return 'off'
    t = dt.time()
    if PRE_MARKET_START <= t <= PRE_MARKET_END:
        return 'pre'
    if MORNING_START <= t <= MORNING_END:
        return 'morning'
    if AFTERNOON_START <= t <= AFTERNOON_END:
        return 'afternoon'
    if AFTERNOON_END <= t <= CLOSE_END:
        return 'close'
    return 'off'
