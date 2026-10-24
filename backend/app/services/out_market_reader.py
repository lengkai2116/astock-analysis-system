"""541号 B2：仪表盘 OUT 成品仓读取层。

- `OUT_MARKET_PANEL_MODE`：
  - `prefer`（默认）：有成品仓读成品仓；缺失时临时回退旧路径并标记 `panel_source=legacy/stale`；
  - `strict`：只读成品仓，缺失返回 None（路由 503）；
  - `off`：完全走旧路径（回滚开关）。
- 成品仓 payload 原样返回，附加 `panel_source/panel_date/panel_built_at/stale`；
  不覆盖各模块原有的 `source` 字段，避免破坏前端既有文案。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_MODES = {'off', 'prefer', 'strict'}
_WARNED_MISSING: set[str] = set()
_DM = None
_EXPECTED_CACHE = {'at': 0.0, 'value': None}
_EXPECTED_LOCK = threading.Lock()


def _data_manager():
    global _DM
    if _DM is None:
        from app.data import DataManager
        _DM = DataManager()
    return _DM


def _warn_missing(module: str, strict: bool = False) -> None:
    if module in _WARNED_MISSING:
        return
    _WARNED_MISSING.add(module)
    if strict:
        logger.warning(f"out_market_panel 缺失（strict）: {module}")
    else:
        logger.warning(f"out_market_panel 缺失，临时回退旧路径: {module}")


def panel_mode() -> str:
    mode = (os.getenv('OUT_MARKET_PANEL_MODE') or 'prefer').strip().lower()
    return mode if mode in _MODES else 'prefer'


def load_panel(module: str, asof_date: str | None = None) -> dict | None:
    try:
        return _data_manager().get_out_market_panel(module, asof_date=asof_date)
    except Exception as exc:
        logger.warning(f"out_market_panel 读取失败 [{module}]: {exc}")
        return None


def _expected_date() -> str | None:
    """当前成品应覆盖的数据日（treemap_snapshot.trade_date），60s 缓存。

    查询失败返回 None 且不写缓存，避免一次瞬时错误让后续 60s 全部判为不 stale。
    """
    now = time.time()
    with _EXPECTED_LOCK:
        cached = _EXPECTED_CACHE['value']
        if cached and now - _EXPECTED_CACHE['at'] < 60:
            return cached
    try:
        value = _data_manager().get_snapshot_data_date()
    except Exception:
        value = None
    if value:
        with _EXPECTED_LOCK:
            _EXPECTED_CACHE['at'] = now
            _EXPECTED_CACHE['value'] = value
    return value


def _max_data_date(data_dates: dict | None) -> str | None:
    """从 data_dates 中取最大可识别日期；忽略 08/20 这类无年份缩写。"""
    from app.services.market_date_resolver import norm_date
    vals = []
    for value in (data_dates or {}).values():
        if isinstance(value, str):
            d = norm_date(value)
            if d:
                vals.append(d)
    return max(vals) if vals else None


def attach_meta(payload, panel: dict, expected_date: str | None = None):
    """给成品 payload 附加 OUT 元信息；非 dict 原样返回。"""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    actual = str(panel.get('asof_date') or '')
    expected = expected_date if expected_date is not None else _expected_date()
    expected_norm = str(expected or '').replace('-', '')
    actual_norm = actual.replace('-', '')
    # 548：payload 内部数据日（data_dates_json 最大值）才是真实新鲜度。
    # 只看 asof 会把「10-23 面板里装 10-22 数据」判成最新。
    data_date = _max_data_date(panel.get('data_dates'))
    data_norm = data_date.replace('-', '') if data_date else ''
    out['panel_source'] = 'out'
    out['panel_date'] = actual or None
    out['panel_data_date'] = data_date
    out['panel_built_at'] = panel.get('built_at')
    out['stale'] = bool(
        (expected_norm and actual_norm and actual_norm < expected_norm)
        or (expected_norm and data_norm and data_norm < expected_norm)
    )
    return out


def _legacy(fallback: Callable | None):
    if fallback is None:
        return None
    data = fallback()
    if isinstance(data, dict):
        data = dict(data)
        data.setdefault('source', data.get('source') or 'legacy')
        data['panel_source'] = 'legacy'
        data['panel_missing'] = True
        data['stale'] = True
    return data


def get_out_or_legacy(module: str, fallback: Callable | None,
                      transform: Callable | None = None,
                      expected_date: str | None = None):
    """B2 统一入口：成品仓优先，按模式决定是否回退旧路径。"""
    mode = panel_mode()
    if mode == 'off':
        return _legacy(fallback)

    panel = load_panel(module)
    if panel and panel.get('payload') is not None:
        payload = panel['payload']
        if transform is not None:
            payload = transform(payload)
        return attach_meta(payload, panel, expected_date=expected_date)

    if mode == 'strict':
        _warn_missing(module, strict=True)
        return None

    _warn_missing(module)
    return _legacy(fallback)


# ── 请求参数切片（成品仓按全量构建，接口按请求参数裁剪） ──────────

def slice_index_daily(payload: dict, days: int | None) -> dict:
    out = dict(payload)
    rows = list(payload.get('days') or [])
    if days and len(rows) > days:
        out['days'] = rows[-days:]
    return out


def slice_moneyflow_summary(payload: dict, days: int | None) -> dict:
    out = dict(payload)
    rows = list(payload.get('days') or [])
    if days and len(rows) > days:
        out['days'] = rows[-days:]
    return out


def slice_daily_top(payload: dict, limit: int | None) -> dict:
    out = dict(payload)
    rows = list(payload.get('stocks') or [])
    if limit and len(rows) > limit:
        out['stocks'] = rows[:limit]
    return out


def slice_sector_changes(payload: dict, top_n: int | None) -> dict:
    out = dict(payload)
    if not top_n:
        return out
    for key in ('gainers', 'losers'):
        rows = list(payload.get(key) or [])
        if len(rows) > top_n:
            out[key] = rows[:top_n]
    return out


def _slice_sector_stocks(sectors: list, top_n: int | None,
                         stocks_per_sector: int | None) -> list:
    rows = list(sectors or [])
    if top_n and len(rows) > top_n:
        rows = rows[:top_n]
    if stocks_per_sector:
        rows = [
            {**row, 'stocks': list(row.get('stocks') or [])[:stocks_per_sector]}
            if isinstance(row, dict) else row
            for row in rows
        ]
    return rows


def slice_sector_moneyflow(payload: dict, top_n: int | None,
                           stocks_per_sector: int | None) -> dict:
    out = dict(payload)
    out['sectors'] = _slice_sector_stocks(
        payload.get('sectors') or [], top_n, stocks_per_sector)
    if 'out_sectors' in payload:
        out['out_sectors'] = _slice_sector_stocks(
            payload.get('out_sectors') or [], top_n, stocks_per_sector)
    return out


def slice_sector_heat(payload: dict, top_n: int | None) -> dict:
    out = dict(payload)
    rows = list(payload.get('sectors') or [])
    if top_n and len(rows) > top_n:
        out['sectors'] = rows[:top_n]
    return out
