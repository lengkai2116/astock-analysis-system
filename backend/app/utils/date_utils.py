"""
日期格式统一工具函数
将项目范围内混用的 %Y%m%d / %Y-%m-%d 格式归一到 `-` 分隔格式

使用原则：
  - API 输入/缓存查询：统一转为 %Y-%m-%d
  - 外部数据源（Tushare / AKShare）需要 %Y%m%d 的，在 provider 层保留
  - dashboard_service.py、screener.py 中混用的地方优先使用本工具
"""
from datetime import datetime, date
from typing import Optional


def normalize_date(d, fmt: str = '%Y-%m-%d') -> Optional[str]:
    """
    统一日期格式，输入支持 str / datetime / date / None

    Args:
        d: 输入的日期值
        fmt: 输出格式（默认 %Y-%m-%d）

    Returns:
        格式化日期字符串，或 None（输入为 None 时）

    Examples:
        >>> normalize_date('20260703')
        '2026-07-03'
        >>> normalize_date('2026-07-03')
        '2026-07-03'
        >>> normalize_date(None)
        >>> normalize_date(datetime(2026, 7, 3))
        '2026-07-03'
    """
    if d is None:
        return None
    if isinstance(d, str):
        # 已经是目标格式 → 直接返回
        if fmt == '%Y-%m-%d' and '-' in d:
            return d
        if fmt == '%Y%m%d' and '-' not in d and len(d) == 8:
            return d
        # 统一转换
        cleaned = d.replace('-', '').replace('/', '').replace(' ', '').strip()[:8]
        if len(cleaned) == 8 and cleaned.isdigit():
            return f'{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}' if fmt == '%Y-%m-%d' else cleaned
        return d[:10] if len(d) >= 10 else d
    if isinstance(d, (datetime, date)):
        return d.strftime(fmt)
    return str(d)
