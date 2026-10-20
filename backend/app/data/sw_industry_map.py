"""股票 → 申万一级行业（SW2021，31 类）映射（530号 第二轮修正）

背景：`stocks.industry` 为东财二级行业（110 类，电器连锁/公路/林业等碎行业
成分股仅 2~10 只），板块资金占比与近20日涨跌折线在该粒度下仍受小基数干扰。
用户拍板统一改申万一级 31 类（SW2021），板块热度与折线共用同一套粒度。

数据源（akshare）：
  - `sw_index_first_info()` → 31 个申万一级行业（行业代码/名称/成份个数）
  - `index_component_sw(symbol='801xxx')` → 各行业成分股（6 位证券代码）

映射持久化到 compute_cache.db 的 `stock_sw_industry`（月度新鲜度刷新），
daemon 侧 RAW-2D 预计算与 API 侧仪表盘共读同一份，避免进程内各自拉取。
成分股以 6 位代码存储，查询侧用 `normalize_code()` 去交易所后缀对齐。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TABLE = 'stock_sw_industry'
_TTL_SECONDS = 3600
_MIN_ROWS = 3000          # 低于该值视为映射不完整（SW2021 全市场约 5000+ 只）
_DEFAULT_MAX_AGE_DAYS = 30

_cache: dict = {'at': None, 'map': {}}


def normalize_code(code) -> str:
    """ts_code（600000.SH）/ 6 位代码 → 6 位代码（申万成分股按 6 位返回）"""
    return str(code or '').strip().upper().split('.')[0]


def _ecm(ecm=None):
    if ecm is not None:
        return ecm
    from app.data import get_ecm_instance
    return get_ecm_instance()


def _query_rows(ecm, sql: str, params=None):
    try:
        return ecm._query_shard(TABLE, sql, params or [])
    except Exception as e:
        logger.debug(f"申万一级映射查询失败: {e}")
        return None


def get_sw_industry_map(ecm=None, use_cache: bool = True) -> dict[str, str]:
    """读取映射 {6位代码: 申万一级行业名}；表空/异常返回空 dict。

    进程内缓存 1 小时（映射月度级变化，无需每次查库）。
    """
    now = datetime.now()
    if use_cache and _cache['at'] and (now - _cache['at']).total_seconds() < _TTL_SECONDS:
        return dict(_cache['map'])
    df = _query_rows(_ecm(ecm), "SELECT ts_code, industry FROM " + TABLE)
    if df is None or df.empty:
        return {}
    mapping = {}
    for _, r in df.iterrows():
        code = normalize_code(r.get('ts_code'))
        ind = str(r.get('industry') or '').strip()
        if code and ind and ind.lower() not in ('nan', 'none'):
            mapping[code] = ind
    _cache['at'] = now
    _cache['map'] = mapping
    return dict(mapping)


def get_sw_industry_status(ecm=None) -> tuple[int, str | None]:
    """返回 (行数, 最近更新时间)；表不存在/异常返回 (0, None)。"""
    df = _query_rows(_ecm(ecm),
                     "SELECT COUNT(*) AS n, MAX(updated_at) AS ts FROM " + TABLE)
    if df is None or df.empty:
        return 0, None
    try:
        n = int(df['n'].iloc[0] or 0)
        ts = df['ts'].iloc[0]
        return n, (str(ts) if ts else None)
    except Exception:
        return 0, None


def _is_fresh(ecm, max_age_days: int) -> bool:
    n, ts = get_sw_industry_status(ecm)
    if n < _MIN_ROWS or not ts:
        return False
    try:
        updated = datetime.fromisoformat(str(ts))
    except Exception:
        return False
    return datetime.now() - updated < timedelta(days=max_age_days)


def _invalidate_cache():
    _cache['at'] = None
    _cache['map'] = {}


def _ak_call(fn, *args, retries: int = 3, **kwargs):
    """akshare 单请求重试（外部接口偶发空返回/HTML 导致 JSON 解析失败）"""
    last = None
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            if i + 1 < retries:
                time.sleep(0.8 * (i + 1))
    raise last


def _write_rows(ecm, rows: list[tuple]) -> None:
    from app.data.sharding_manager import sharding_manager

    db_name = sharding_manager.get_db_for_table(TABLE)
    conn = sharding_manager.get_connection(db_name)
    lock = sharding_manager.get_write_lock(db_name)
    with lock:
        conn.execute("DELETE FROM " + TABLE)
        conn.executemany(
            "INSERT INTO " + TABLE + " (ts_code, industry, industry_code, updated_at) "
            "VALUES (?, ?, ?, ?)", rows)
        conn.commit()
    logger.info(f"申万一级映射写盘完成: {len(rows)} 只 (db={db_name})")


def refresh_sw_industry_map(ecm=None, force: bool = False,
                            max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> int:
    """拉取并持久化申万一级映射，返回写入行数（未过期/失败返回现有行数或 0）。

    仅 daemon 侧（RAW-2D）调用；akshare 31 次成分股请求约 1~4 分钟，故按月刷新。
    拉取失败不覆盖既有映射（保留旧表继续可用）。
    """
    ecm = _ecm(ecm)
    if not force and _is_fresh(ecm, max_age_days):
        n, _ = get_sw_industry_status(ecm)
        return n
    try:
        import akshare as ak
    except Exception as e:
        logger.warning(f"申万一级映射: akshare 不可用，保留旧表: {e}")
        return get_sw_industry_status(ecm)[0]

    try:
        info = _ak_call(ak.sw_index_first_info)
        now = datetime.now().isoformat(timespec='seconds')
        mapping: dict[str, tuple[str, str]] = {}
        failed = []
        for _, r in info.iterrows():
            ind_code = str(r.get('行业代码') or '').strip()
            ind_name = str(r.get('行业名称') or '').strip()
            if not ind_code or not ind_name:
                continue
            try:
                comp = _ak_call(ak.index_component_sw,
                                symbol=normalize_code(ind_code))
            except Exception as e:
                # 单行业接口偶发空返回：跳过该行业，其余仍落库（避免整表回滚）
                failed.append(ind_name)
                logger.warning(f"申万一级成分股拉取失败，跳过 {ind_name}"
                               f"({ind_code}): {e}")
                continue
            for _, c in comp.iterrows():
                code = normalize_code(c.get('证券代码'))
                if code:
                    mapping[code] = (ind_name, ind_code)
            time.sleep(0.15)
        rows = [(code, name, icode, now) for code, (name, icode) in mapping.items()]
        if len(rows) < _MIN_ROWS:
            raise RuntimeError(f"映射行数不足（{len(rows)} < {_MIN_ROWS}）")
        _write_rows(ecm, rows)
        _invalidate_cache()
        if failed:
            logger.warning(f"申万一级映射刷新完成（{len(failed)} 个行业缺成分股: "
                           f"{', '.join(failed)}）")
        return len(rows)
    except Exception as e:
        logger.warning(f"申万一级映射刷新失败，保留旧表: {e}")
        return get_sw_industry_status(ecm)[0]
