"""541号 B3：仪表盘混合模块的实时 overlay（白名单）。

只允许覆盖 COL 实时采集的原始字段：
- 指数实时价/涨跌幅；
- 涨跌平家数及直接比例；
- 涨停/跌停家数；
- 情绪指标中的涨停/跌停家数与直接比值。

OUT 的 EOD 序列、板块热度、资金流、阶段/温度、状态/预警等判定字段一律不覆盖。
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

INDEX_CODES = ('000001.SH', '399001.SZ', '899050.BJ', '399006.SZ')
_MIN_BREADTH_SAMPLE = 100
_BREADTH_MIN_COVERAGE = 0.8  # 实时样本相对 EOD 全市场的覆盖下限
_LIVE_MAX_AGE = 300  # 实时源超过 5 分钟不再冒充 live

# 文档/测试用白名单（模块 → 允许 overlay 的字段路径）
LIVE_WHITELIST = {
    'market_overview': (
        'indexes.price', 'indexes.change_pct', 'market_status', 'data_is_live',
    ),
    'market_breadth': (
        'count', 'up_count', 'down_count', 'flat_count', 'up_ratio', 'down_ratio',
    ),
    'market_limit_ecology': ('up.count', 'down.count', 'data_available'),
    'market_emotion': (
        'metrics.limit_up_count', 'metrics.limit_down_count', 'metrics.up_down_ratio',
    ),
}


def _store():
    from app.data.in_memory_store import store
    return store


def _fresh(topic: str, max_age: int = _LIVE_MAX_AGE) -> bool:
    try:
        meta = _store().get_meta(topic)
        if meta is None:
            return False
        return (datetime.now() - meta).total_seconds() <= max_age
    except Exception:
        return False


def _recent_text(value, max_age: int = _LIVE_MAX_AGE) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    for parser in (
        lambda s: datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S'),
        lambda s: datetime.fromisoformat(s.replace('Z', '')),
    ):
        try:
            return (datetime.now() - parser(text)).total_seconds() <= max_age
        except (TypeError, ValueError):
            continue
    return False


def _snapshot_records() -> tuple[list[dict], str]:
    """实时全市场快照：内存优先，as_market_snapshot 仅在足够新时兜底。"""
    try:
        records = _store().get_snapshot()
        if records and _fresh('snapshot'):
            return records, 'in_memory_store'
    except Exception as exc:
        logger.debug(f"in_memory_store 快照读取失败: {exc}")
    try:
        from app.data import DataManager
        records = DataManager().cache.get_all_market_snapshots()
        if records:
            latest = max(
                (str(r.get('updated_at') or r.get('cached_at') or '') for r in records),
                default='')
            if _recent_text(latest):
                return records, 'as_market_snapshot'
    except Exception as exc:
        logger.debug(f"as_market_snapshot 读取失败: {exc}")
    return [], ''


def _live_at() -> str:
    try:
        meta = _store().get_meta('snapshot')
        if meta:
            return meta.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _breadth_counts(records: list[dict]) -> dict | None:
    if not records:
        return None
    up = down = flat = 0
    valid = 0
    for rec in records:
        try:
            pct = float(rec.get('change_pct'))
        except (TypeError, ValueError):
            continue
        valid += 1
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1
    if valid < _MIN_BREADTH_SAMPLE:
        return None
    return {
        'count': valid,
        'up_count': up,
        'down_count': down,
        'flat_count': flat,
        'up_ratio': round(up / valid * 100, 1),
        'down_ratio': round(down / valid * 100, 1),
    }


def _limit_counts() -> tuple[dict | None, str]:
    try:
        if not (_fresh('limit_pool:up') or _fresh('limit_pool:down')):
            return None, ''
        up = _store().get_limit_pool('up')
        down = _store().get_limit_pool('down')
    except Exception as exc:
        logger.debug(f"涨跌停池读取失败: {exc}")
        return None, ''
    if not up and not down:
        return None, ''
    return {'up': len(up), 'down': len(down)}, 'in_memory_store'


def _index_quotes() -> tuple[dict, str]:
    quotes: dict[str, dict] = {}
    source = 'in_memory_store'
    try:
        for code in INDEX_CODES:
            rec = _store().get_by_code(code)
            if not rec:
                continue
            price = rec.get('price')
            if price is None:
                continue
            quotes[code] = {
                'price': float(price),
                'change_pct': float(rec.get('change_pct') or 0),
            }
    except Exception as exc:
        logger.debug(f"指数实时价读取失败: {exc}")
    if quotes:
        return quotes, source

    records, source = _snapshot_records()
    by_code = {str(r.get('ts_code') or ''): r for r in records}
    for code in INDEX_CODES:
        rec = by_code.get(code)
        if not rec or rec.get('price') is None:
            continue
        quotes[code] = {
            'price': float(rec.get('price')),
            'change_pct': float(rec.get('change_pct') or 0),
        }
    return quotes, source


def _market_status_now() -> str:
    try:
        from app.utils import trading_hours as th
        now = th._now()
        if th.is_trading_time(now):
            return 'trading'
        if th.is_holiday(now):
            return 'holiday'
        return 'closed'
    except Exception:
        return 'closed'


def get_live_overlay(module: str) -> dict | None:
    """按模块返回实时 overlay；无可用实时数据时返回 None。"""
    if module == 'market_overview':
        quotes, source = _index_quotes()
        if not quotes:
            return None
        return {
            'index_quotes': quotes,
            'market_status': _market_status_now(),
            'source': source,
            'at': _live_at(),
        }
    if module == 'market_breadth':
        records, source = _snapshot_records()
        counts = _breadth_counts(records)
        if not counts:
            return None
        return {'breadth': counts, 'source': source, 'at': _live_at()}
    if module in ('market_limit_ecology', 'market_emotion'):
        counts, source = _limit_counts()
        if not counts:
            return None
        return {'limits': counts, 'source': source, 'at': _live_at()}
    return None


def _merge_overview(payload: dict, live: dict) -> None:
    quotes = live.get('index_quotes') or {}
    indexes = [item for item in (payload.get('indexes') or [])
               if isinstance(item, dict)]
    merged = 0
    for item in indexes:
        quote = quotes.get(str(item.get('ts_code') or ''))
        if not quote:
            continue
        if quote.get('price') is not None:
            item['price'] = round(float(quote['price']), 2)
        if quote.get('change_pct') is not None:
            item['change_pct'] = round(float(quote['change_pct']), 2)
        merged += 1
    if live.get('market_status'):
        payload['market_status'] = live['market_status']
    # 仅全指数覆盖时才标记 live，避免 1/4 指数实时就盖掉 EOD 的 False
    if indexes and merged == len(indexes):
        payload['data_is_live'] = True


def _merge_breadth(payload: dict, live: dict) -> None:
    counts = live.get('breadth') or {}
    if not counts:
        return
    live_count = counts.get('count')
    eod_count = payload.get('count')
    if (isinstance(live_count, (int, float)) and isinstance(eod_count, (int, float))
            and eod_count > 0 and live_count < eod_count * _BREADTH_MIN_COVERAGE):
        # 盘中样本明显不足（如 3000/5500），保留 EOD 锚定，避免家数/比例大幅跳动
        return
    for key in ('count', 'up_count', 'down_count', 'flat_count',
                'up_ratio', 'down_ratio'):
        if key in counts:
            payload[key] = counts[key]


def _merge_limits(payload: dict, live: dict) -> None:
    counts = live.get('limits') or {}
    if 'up' in counts and isinstance(payload.get('up'), dict):
        payload['up']['count'] = counts['up']
    if 'down' in counts and isinstance(payload.get('down'), dict):
        payload['down']['count'] = counts['down']
    if counts:
        payload['data_available'] = True


def _merge_emotion(payload: dict, live: dict) -> None:
    counts = live.get('limits') or {}
    metrics = payload.get('metrics')
    if not isinstance(metrics, dict):
        metrics = {}
        payload['metrics'] = metrics
    if 'up' in counts:
        metrics['limit_up_count'] = counts['up']
    if 'down' in counts:
        metrics['limit_down_count'] = counts['down']
    if counts.get('up') is not None and counts.get('down') is not None:
        metrics['up_down_ratio'] = round(counts['up'] / max(counts['down'], 1), 2)


def apply_overlay(module: str, payload, live: dict | None = None):
    """把实时白名单字段合并进 OUT payload；非 dict/无实时数据原样返回。"""
    if not isinstance(payload, dict):
        return payload
    live = live if live is not None else get_live_overlay(module)
    if not live:
        return payload

    out = copy.deepcopy(payload)
    if module == 'market_overview':
        _merge_overview(out, live)
    elif module == 'market_breadth':
        _merge_breadth(out, live)
    elif module == 'market_limit_ecology':
        _merge_limits(out, live)
    elif module == 'market_emotion':
        _merge_emotion(out, live)
    else:
        return payload

    out['live_source'] = live.get('source')
    out['live_at'] = live.get('at')
    out['live_fields'] = list(LIVE_WHITELIST.get(module, ()))
    out.setdefault('panel_source', 'out')
    return out
