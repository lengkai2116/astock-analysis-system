"""548 号：统一市场数据日解析器。

把原先散落在 DashboardService 各方法里的「today 之前最近完整交易日」收敛为
一处判定，按「交易日历 + 当前时段 + 数据就绪度」输出应展示的数据日。

data_status 取值：
  live              交易日盘中，实时字段可用；EOD 模块仍锚定上一完整交易日
  eod_partial       当日 EOD 原料与 SIG/JUD/OUT 已就绪，QA 未完成（当日收盘后可用）
  eod_final         当日 QA-CHECK 已完成，可全量展示
  previous_complete 当日不可用，展示上一完整交易日
  missing           无任何可用数据

设计约束：
- 纯函数 resolve_from_inputs() 便于单测；DB 版本只负责取输入。
- 结果缓存 30s，避免 dashboard/full 每模块都查库。
- 不在这里触发任何采集/计算，只读。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

REQUIRED_EOD_STEPS = ('SIG', 'JUD', 'OUT')
QA_STEP = 'QA-CHECK'
MIN_DAILY_ROWS = 1000
_CACHE_TTL = 30.0
_CACHE: dict = {'at': 0.0, 'ctx': None}
_LOCK = threading.Lock()

STATUS_LIVE = 'live'
STATUS_EOD_PARTIAL = 'eod_partial'
STATUS_EOD_FINAL = 'eod_final'
STATUS_PREVIOUS = 'previous_complete'
STATUS_MISSING = 'missing'

_FINAL_STATUSES = (STATUS_EOD_FINAL, STATUS_EOD_PARTIAL)
_TRADING_SESSIONS = ('pre_open', 'pre_market', 'morning', 'noon', 'afternoon')
_AFTER_CLOSE_SESSIONS = ('close', 'post_market', 'night')


def norm_date(value) -> Optional[str]:
    """归一为 YYYY-MM-DD；无法识别返回 None。"""
    if not value:
        return None
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    return None


def compact_date(value) -> Optional[str]:
    d = norm_date(value)
    return d.replace('-', '') if d else None


def _pipeline_ready(status_map: dict, steps: Iterable[str]) -> bool:
    return all(str(status_map.get(s) or '') == 'done' for s in steps)


def resolve_from_inputs(
    now: datetime,
    is_trading_day: bool,
    session: str,
    dates_desc: list[str],
    pipeline_by_date: dict[str, dict],
    daily_rows_by_date: dict[str, int],
    live_available: bool = False,
    min_rows: int = MIN_DAILY_ROWS,
) -> dict:
    """纯函数：根据已取得的输入解析数据上下文。

    dates_desc 需按日期倒序，且只含「有数据」的交易日。
    """
    today = now.strftime('%Y-%m-%d')
    dates = [d for d in (norm_date(x) for x in dates_desc) if d]
    dates = sorted(set(dates), reverse=True)
    if not dates:
        return {
            'today': today, 'is_trading_day': is_trading_day, 'session': session,
            'view_date': None, 'last_complete_date': None,
            'data_status': STATUS_MISSING, 'reason': 'no daily data',
        }

    last_complete = None
    for d in dates:
        if _pipeline_ready(pipeline_by_date.get(d, {}), REQUIRED_EOD_STEPS + (QA_STEP,)):
            last_complete = d
            break

    def _today_eod_ready() -> bool:
        if not is_trading_day:
            return False
        if today not in dates:
            return False
        if int(daily_rows_by_date.get(today, 0) or 0) < min_rows:
            return False
        return _pipeline_ready(pipeline_by_date.get(today, {}), REQUIRED_EOD_STEPS)

    def _today_qa_done() -> bool:
        return _pipeline_ready(pipeline_by_date.get(today, {}), (QA_STEP,))

    view_date: Optional[str]
    status: str
    reason: str

    if not is_trading_day:
        view_date = last_complete or dates[0]
        if last_complete and view_date == last_complete:
            status, reason = STATUS_EOD_FINAL, 'non-trading day, last complete session'
        else:
            status, reason = STATUS_PREVIOUS, 'non-trading day, no QA-complete date'
    elif session in _TRADING_SESSIONS:
        if live_available:
            view_date, status, reason = today, STATUS_LIVE, 'trading session live fields'
        else:
            view_date = last_complete or dates[0]
            status, reason = STATUS_PREVIOUS, 'trading session without live snapshot'
    elif session in _AFTER_CLOSE_SESSIONS:
        if _today_eod_ready():
            view_date = today
            if _today_qa_done():
                status, reason = STATUS_EOD_FINAL, 'same-day EOD finished (QA done)'
            else:
                status, reason = STATUS_EOD_PARTIAL, 'same-day EOD computed, QA pending'
        else:
            view_date = last_complete or dates[0]
            status, reason = STATUS_PREVIOUS, 'same-day EOD not ready'
    else:  # 未知时段按盘后处理，保守回退
        view_date = last_complete or dates[0]
        status, reason = STATUS_PREVIOUS, f'unknown session {session}'

    return {
        'today': today,
        'is_trading_day': bool(is_trading_day),
        'session': session,
        'view_date': view_date,
        'last_complete_date': last_complete,
        'data_status': status,
        'reason': reason,
    }


class DbLookup:
    """从 ECM 读取解析输入（只读）。"""

    @staticmethod
    def _ecm():
        from app.data.enhanced_cache_manager import get_ecm_instance
        return get_ecm_instance()

    def load(self) -> tuple[list[str], dict[str, dict], dict[str, int]]:
        ecm = self._ecm()
        df = ecm._query_shard(
            'daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache "
            "ORDER BY trade_date DESC LIMIT 12",
        )
        dates = [norm_date(x) for x in (df['trade_date'].tolist() if df is not None and not df.empty else [])]
        dates = [d for d in dates if d]
        if not dates:
            return [], {}, {}

        placeholders = ','.join('?' * len(dates))
        rows = ecm._query_shard(
            'daily_cache',
            f"SELECT trade_date, COUNT(*) AS cnt FROM daily_cache "
            f"WHERE trade_date IN ({placeholders}) GROUP BY trade_date",
            dates,
        )
        counts = {}
        if rows is not None and not rows.empty:
            for _, r in rows.iterrows():
                d = norm_date(r.get('trade_date'))
                if d:
                    counts[d] = int(r.get('cnt') or 0)

        placeholders = ','.join('?' * len(dates))
        st = ecm._query_shard(
            'pipeline_status',
            f"SELECT pipeline_date, step_id, status FROM pipeline_status "
            f"WHERE pipeline_date IN ({placeholders})",
            [d.replace('-', '') for d in dates],
        )
        pipeline: dict[str, dict] = {}
        if st is not None and not st.empty:
            for _, r in st.iterrows():
                d = norm_date(r.get('pipeline_date'))
                if d:
                    pipeline.setdefault(d, {})[str(r.get('step_id'))] = str(r.get('status'))
        return dates, pipeline, counts


def _live_available(session: str) -> bool:
    if session not in _TRADING_SESSIONS:
        return False
    try:
        from app.data.in_memory_store import store as mem_store
        if mem_store.get_snapshot():
            return True
    except Exception:
        pass
    try:
        from app.data.sharding_manager import sharding_manager
        conn = sharding_manager.get_read_connection('market_snapshot.db')
        row = conn.execute(
            "SELECT MAX(cached_at) FROM as_market_snapshot").fetchone()
        if row and row[0]:
            ts = str(row[0])
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    return (datetime.now() - datetime.strptime(ts[:19], fmt)).total_seconds() < 600
                except ValueError:
                    continue
    except Exception:
        pass
    return False


def resolve_context(now: datetime | None = None, refresh: bool = False,
                    lookup: DbLookup | None = None) -> dict:
    """带 30s 缓存的 DB 版本。失败时返回保守的 missing/previous 结构。"""
    now = now or datetime.now()
    if not refresh:
        with _LOCK:
            if _CACHE['ctx'] and time.time() - _CACHE['at'] < _CACHE_TTL:
                return dict(_CACHE['ctx'])

    try:
        from app.utils.trading_hours import get_current_session, is_holiday
        is_trading_day = not is_holiday(now)
        session = get_current_session(now)
    except Exception:
        is_trading_day = now.weekday() < 5
        session = 'night'

    try:
        dates, pipeline, counts = (lookup or DbLookup()).load()
        ctx = resolve_from_inputs(
            now=now,
            is_trading_day=is_trading_day,
            session=session,
            dates_desc=dates,
            pipeline_by_date=pipeline,
            daily_rows_by_date=counts,
            live_available=_live_available(session),
        )
    except Exception as exc:
        logger.warning(f"市场数据日解析失败，回退保守口径: {exc}")
        ctx = {
            'today': now.strftime('%Y-%m-%d'),
            'is_trading_day': is_trading_day,
            'session': session,
            'view_date': None,
            'last_complete_date': None,
            'data_status': STATUS_MISSING,
            'reason': f'resolver error: {type(exc).__name__}',
        }

    with _LOCK:
        _CACHE['at'] = time.time()
        _CACHE['ctx'] = dict(ctx)
    return dict(ctx)


def eod_date(now: datetime | None = None) -> Optional[str]:
    """EOD 类模块应锚定的数据日。

    盘中 → 上一完整交易日；同日 snapshot/final → 当日；非交易日 → 最近完整日。
    """
    ctx = resolve_context(now)
    if ctx.get('data_status') in _FINAL_STATUSES:
        return ctx.get('view_date')
    return ctx.get('last_complete_date') or ctx.get('view_date')


def expected_panel_date(now: datetime | None = None) -> Optional[str]:
    d = eod_date(now)
    return d.replace('-', '') if d else None


def clear_cache() -> None:
    with _LOCK:
        _CACHE['at'] = 0.0
        _CACHE['ctx'] = None
