"""
交易时段工具类 — A 股交易时间判断
===================================
提供交易时段判断函数，用于数据源时间感知路由。

A 股交易时段：
  开盘前：  09:00-09:15
  集合竞价：09:15-09:25
  上午盘：  09:30-11:30
  中午休市：11:30-13:00
  下午盘：  13:00-15:00
  收盘处理：15:00-15:30
  日终处理：15:30-16:00
  夜间维护：16:00-09:00

节假日跳过周末（周六/周日），法定节假日通过 .env 配置。
"""

import logging
import os
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

# 默认时区偏移（北京时间 UTC+8）
TIMEZONE_OFFSET = int(os.getenv('TZ_OFFSET', '8'))

# 交易时段常量（355号方案规则11：时段划分细化）
PRE_OPEN_START = time(9, 0)      # 开盘前开始
PRE_MARKET_START = time(9, 15)   # 集合竞价开始
PRE_MARKET_END = time(9, 25)     # 集合竞价结束
MORNING_START = time(9, 30)      # 上午盘开始
MORNING_END = time(11, 30)       # 上午盘结束
AFTERNOON_START = time(13, 0)    # 下午盘开始
AFTERNOON_END = time(15, 0)      # 下午盘结束
CLOSE_END = time(15, 30)         # 收盘处理结束
POST_MARKET_END = time(16, 0)    # 日终处理结束

# 法定节假日（快速判断，精确列表由外部配置）
# 2026 年安排依据《国务院办公厅关于2026年部分节假日安排的通知》（gov.cn content_7047090）：
#   元旦 1/1-1/3；春节 2/15-2/23（共9天）；清明 4/4-4/6；劳动节 5/1-5/5；
#   端午 6/19-6/21；中秋 9/25-9/27；国庆 10/1-10/7。
# 注：周末由 is_holiday 的 weekday 规则兜底，此处含周末日期仅为完整记录（冗余无害）。
_DEFAULT_HOLIDAYS = frozenset({
    # 元旦（1/1-1/3）
    '2026-01-01', '2026-01-02', '2026-01-03',
    # 春节（2/15-2/23，除夕 2/16、正月初一 2/17）
    '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19',
    '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
    # 清明节（4/4-4/6）
    '2026-04-04', '2026-04-05', '2026-04-06',
    # 劳动节（5/1-5/5）
    '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
    # 端午节（6/19-6/21）
    '2026-06-19', '2026-06-20', '2026-06-21',
    # 中秋节（9/25-9/27）
    '2026-09-25', '2026-09-26', '2026-09-27',
    # 国庆节（10/1-10/7；10/8 为正常工作日，非假期）
    '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05',
    '2026-10-06', '2026-10-07',
})

# 调休上班的周末（法定节假日调休安排中，这些周六/周日为工作日、股市照常开市，
# is_holiday 须对其返回 False——否则采集/巡检会把调休上班日当节假日跳过）
#
# 483号（2026-09-26）交叉审计：原列 6 条（01-04/02-14/02-28/05-09/09-20/10-10）。
# 用权威行情源逐条验证发现——**已过的 5 条当日行情均为 0 行**（实际休市）：
#   Tushare daily 01-04/02-14/02-28/05-09/09-20 全 0；对照 09-18=5553、09-21=5553；
#   且 `daily_cache` 全历史 1268 个交易日内**无任何周末有行情**（反向核对）。
# 用户 2026-09-26 拍板删除这 5 条（它们按周末规则回归非交易日）。
# `2026-10-10` 为未来日期、当前无法验证，**暂留待节后用审计脚本复核**：
#   `scripts/_483_trading_calendar_audit.py`（正向：逐条用行情验证；反向：扫描库里
#   有行情的周末 = 漏登记的调休交易日）。修改本表后务必重跑该脚本。
_WORKDAY_WEEKENDS = frozenset({
    '2026-10-10',   # 国庆调休（10/10 周六上班）——⚠️ 待 2026-10-10 后用审计脚本验证
})


def _now() -> datetime:
    """获取当前时间（北京时间，UTC+8）"""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


def is_holiday(d: datetime) -> bool:
    """判断是否为法定节假日或周末（调休上班的周末除外——股市照常开市）"""
    ds = d.strftime('%Y-%m-%d')
    if ds in _WORKDAY_WEEKENDS:
        return False
    if d.weekday() >= 5:  # 周六(5)/周日(6)
        return True
    return ds in _DEFAULT_HOLIDAYS


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
    """获取当前交易时段（355号方案规则11：时段划分细化）

    Returns:
        'pre_open'   — 开盘前     (09:00-09:15)
        'pre_market' — 集合竞价   (09:15-09:25)
        'morning'    — 上午盘     (09:30-11:30)
        'noon'       — 中午休市   (11:30-13:00)
        'afternoon'  — 下午盘     (13:00-15:00)
        'close'      — 收盘处理   (15:00-15:30)
        'post_market'— 日终处理   (15:30-16:00)
        'night'      — 夜间维护   (16:00-09:00)
        'off'        — 非交易时间（含节假日/周末）
    """
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return 'off'
    t = dt.time()
    if PRE_OPEN_START <= t < PRE_MARKET_START:
        return 'pre_open'
    if PRE_MARKET_START <= t <= PRE_MARKET_END:
        return 'pre_market'
    if MORNING_START <= t <= MORNING_END:
        return 'morning'
    if MORNING_END < t < AFTERNOON_START:
        return 'noon'
    if AFTERNOON_START <= t <= AFTERNOON_END:
        return 'afternoon'
    if AFTERNOON_END < t <= CLOSE_END:
        return 'close'
    if CLOSE_END < t <= POST_MARKET_END:
        return 'post_market'
    return 'night'


def is_pre_open(dt: datetime = None) -> bool:
    """判断是否为开盘前时段（09:00-09:15）"""
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return False
    return PRE_OPEN_START <= dt.time() < PRE_MARKET_START


def is_post_market(dt: datetime = None) -> bool:
    """判断是否为日终处理时段（15:30-16:00）"""
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return False
    return CLOSE_END < dt.time() <= POST_MARKET_END


def is_night_maintenance(dt: datetime = None) -> bool:
    """判断是否为夜间维护时段（16:00-09:00）"""
    if dt is None:
        dt = _now()
    if is_holiday(dt):
        return True  # 非交易日全天都是维护时段
    t = dt.time()
    return t > POST_MARKET_END or t < PRE_OPEN_START


def get_session_for_collection(dt: datetime = None) -> str:
    """获取适合数据采集的时段分类（355号方案规则11）

    用于确定当前时段应该执行哪些采集任务：
    - 'trading': 交易时段，执行盘中实时采集
    - 'preparing': 准备时段，执行数据准备和系统检查
    - 'settlement': 结算时段，执行日终数据采集
    - 'maintenance': 维护时段，执行数据维护和备份
    """
    session = get_current_session(dt)
    if session in ('morning', 'afternoon', 'pre_market'):
        return 'trading'
    elif session in ('pre_open',):
        return 'preparing'
    elif session in ('close', 'post_market'):
        return 'settlement'
    else:  # 'night', 'off', 'noon'
        return 'maintenance'
