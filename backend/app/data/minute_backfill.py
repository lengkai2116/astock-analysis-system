"""
分钟K线数据补采模块
用于自选股分钟数据的闲时补采（日终或低负载时运行）。

功能：
1. 自选股5分钟历史数据采集（mootdx bars(freq=2)）
2. 自选股1分钟历史数据采集（mootdx minutes(YYYYMMDD)）
3. 5min → 15min/30min/60min 聚合

采集策略：
- 自选股优先（从 DB Watchlist 表读取）
- 每只股票0.5秒间隔，避免 mootdx 限流
- 已存在数据跳过（幂等）
"""
import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd

from app.data.enhanced_cache_manager import EnhancedCacheManager, get_ecm_instance

logger = logging.getLogger(__name__)

# 频率映射
FREQ_MAP = {'1m': '1min', '5m': '5min', '15m': '15min', '30m': '30min', '60m': '60min'}
FREQ_MAP_REV = {'1min': '1m', '5min': '5m', '15min': '15m', '30min': '30m', '60min': '60m'}


def get_watchlist_stocks() -> List[str]:
    """从 DB Watchlist 表获取自选股列表

    优先级：
    1. Flask-SQLAlchemy ORM（APP上下文）
    2. PostgreSQL 直连（data_daemon 环境）
    3. SQLite 直连（开发环境回退）
    """
    try:
        from app.models import Watchlist
        stocks = Watchlist.query.all()
        return [w.ts_code for w in stocks if w.ts_code]
    except Exception:
        pass

    # 回退1: PostgreSQL 直连（data_daemon 通过 .env 加载 DATABASE_URL）
    try:
        import os
        db_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql' in db_url:
            import sqlalchemy as sa
            engine = sa.create_engine(db_url)
            with engine.connect() as conn:
                rows = conn.execute(sa.text('SELECT ts_code FROM watchlist ORDER BY id')).fetchall()
                return [r[0] for r in rows]
    except Exception:
        pass

    # 回退2: SQLite 直连（开发环境）
    try:
        import os
        import sqlite3
        data_dir = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data'))
        db_path = os.path.join(data_dir, 'app.db')
        if os.path.isfile(db_path):
            # 500号#51：改 with 上下文管理（原正常路径 close，但 fetchall 抛错即泄漏）
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute('SELECT ts_code FROM watchlist ORDER BY sort_order')
                codes = [r[0] for r in cur.fetchall()]
            return codes
    except Exception as e:
        logger.warning(f"读取自选股列表全部失败: {e}")
    return []


def _get_mootdx_bars_safe(ts_code: str, freq: int = 2, start: int = 0, offset: int = 800) -> pd.DataFrame:
    """带超时和重试的 mootdx bars 调用"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        raw = client.bars(symbol=symbol, frequency=freq, start=start, offset=offset)
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        if 'volume' in df.columns and 'vol' not in df.columns:
            df = df.rename(columns={'volume': 'vol'})
        elif 'vol' in raw.columns:
            df = raw.copy()
            if 'volume' in raw.columns:
                df = df.drop(columns=['volume'])
        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        elif 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'trade_time'})
        return df
    except Exception as e:
        logger.warning(f"mootdx bars 失败 ({ts_code}): {e}")
        return pd.DataFrame()


def _get_mootdx_minutes_safe(ts_code: str, target_date: str) -> pd.DataFrame:
    """获取指定日期的1分钟K线数据"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        raw = client.minutes(symbol=symbol, date=target_date)
        if raw is not None and not raw.empty:
            rows = []
            # 498号#4：A 股交易时段为 09:30-11:30 + 13:00-15:00（各 120 根），原
            # `hour = 9 + (idx+30)//60` 未跳午休 ⇒ 第 120+ 根穿过 11:30-13:00 不存在的
            # 区间、下午时间/日期全错位。按 idx 分段映射（上午/下午各 120 根）。
            def _bar_time(i: int) -> str:
                if i < 120:          # 上午 09:30-11:29
                    h, m = 9 + (30 + i) // 60, (30 + i) % 60
                else:                # 下午 13:00-14:59（跳过 11:30-13:00）
                    j = i - 120
                    h, m = 13 + j // 60, j % 60
                return (f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]} "
                        f"{h:02d}:{m:02d}:00")
            # 500号#16：(a) 用 enumerate 取**位置索引**，不假设 DataFrame 索引为 0 基连续
            # 整数（mootdx 若返回字符串/非 0 基索引 → `int(idx)` 抛错或时间整体错位）。
            for pos, r in enumerate(raw.to_dict('records')):
                # 500号#16：(b) 单日有效 bar 上限 240（上午/下午各 120）——超出则跳过，
                # 避免对非交易日/超长序列生成 15:00 以后不存在的时间。
                if pos >= 240:
                    break
                trade_time = _bar_time(pos)
                price = float(r.get('price', 0))
                if price == 0:
                    continue
                rows.append({
                    'trade_time': trade_time,
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'vol': int(r.get('vol', 0)),
                })
            return pd.DataFrame(rows)
    except Exception as e:
        logger.debug(f"mootdx minutes 失败 ({ts_code}/{target_date}): {e}")
    return pd.DataFrame()


def _cache_to_ecm(df: pd.DataFrame, ts_code: str, freq: str, ecm: EnhancedCacheManager):
    """将 DataFrame 写入 minute_kline_cache"""
    if df.empty:
        return
    try:
        df_copy = df.copy()
        df_copy['ts_code'] = ts_code
        df_copy['freq'] = freq
        if 'trade_time' not in df_copy.columns:
            if 'trade_date' in df_copy.columns:
                df_copy['trade_time'] = df_copy['trade_date'].astype(str)
            else:
                df_copy['trade_time'] = ''
        if 'trade_date' not in df_copy.columns:
            # 483号 ②：聚合结果（_resample_minute）只带 trade_time，须补 trade_date ——
            # minute_kline_cache PK 含 trade_date，缺失会落 NULL（既有 5/15/30min 即此问题）
            # 致按日检索/完整性核对失效；从 trade_time 前 10 位取日期。
            # 500号#16(c)：归一为 YYYY-MM-DD——原 `str[:10]` 对紧凑 `'20260929'` 会原样截成
            # `'20260929'`（分库读的字符串范围比较失配）。先转 datetime 再格式化，失败留空。
            _tt = df_copy['trade_time'].astype(str)
            _dt = pd.to_datetime(_tt, errors='coerce')
            df_copy['trade_date'] = _dt.dt.strftime('%Y-%m-%d')
            _bad = df_copy['trade_date'].isna().sum()
            if _bad:
                logger.warning(f"分钟K线 trade_date 解析失败 {_bad} 行（{ts_code}/{freq}），已置空")
        if 'vol' in df_copy.columns and 'volume' not in df_copy.columns:
            df_copy = df_copy.rename(columns={'vol': 'volume'})
        ecm.cache_minute_kline(df_copy)
    except Exception as e:
        logger.warning(f"缓存分钟K线失败 ({ts_code}/{freq}): {e}")


def _resample_minute(records: list, from_freq: str, to_freq: str) -> list:
    """分钟线频率转换（414号P1.3: 修正60min对齐A股交易时段边界）"""
    from collections import defaultdict
    if not records:
        return []
    total_min = int(to_freq.replace('min', ''))
    base_min = int(from_freq.replace('min', ''))
    group_size = total_min // base_min
    if group_size <= 1:
        return records

    # 414号P1.3: A股交易时段边界（分钟数 from midnight）
    SESSIONS = [
        (570, 690),   # 09:30-11:30 上午场
        (780, 900),   # 13:00-15:00 下午场
    ]

    def _assign_slot(minute_of_day: int) -> tuple:
        """按交易时段边界分配(slot_index)，非交易时段归入最近有效slot"""
        for sess_idx, (sess_start, sess_end) in enumerate(SESSIONS):
            if sess_start <= minute_of_day < sess_end:
                return (sess_idx, (minute_of_day - sess_start) // total_min)
        # 非交易时段：盘前/午休归上午slot0，盘后归下午最后一slot
        if minute_of_day < 570:
            return (0, 0)
        elif minute_of_day < 780:
            return (0, (690 - 570) // total_min - 1)  # 上午最后slot
        else:
            return (1, (900 - 780) // total_min - 1)  # 下午最后slot

    groups = defaultdict(list)
    for r in records:
        tt = r.get('trade_time', '')
        try:
            ts = tt.split(' ')[1] if ' ' in tt else tt
            parts = ts.split(':')
            minute_slot = int(parts[0]) * 60 + int(parts[1])
            sess_idx, slot = _assign_slot(minute_slot)
            key = (tt[:10] if len(tt) > 10 else tt.split(' ')[0], sess_idx, slot)
        except Exception:
            key = (tt, 0, 0)
        groups[key].append(r)
    result = []
    for (d, sess, slot), bars in sorted(groups.items()):
        o = bars[0].get('open', 0)
        c = bars[-1].get('close', 0)
        h = max(b.get('high', 0) for b in bars)
        # 500号#50：low 过滤 None/缺失后再取 min（原 `min(b.get('low', float('inf')) …)`：
        # 任一 bar 缺 low 键即整组得 inf，且 inf 会流入缓存 low）。全缺失时回退 0。
        _lows = [b.get('low') for b in bars if b.get('low') is not None]
        lv = min(_lows) if _lows else 0
        v = sum(b.get('volume', 0) or b.get('vol', 0) for b in bars)
        a = sum(b.get('amount', 0) for b in bars)
        result.append({
            'trade_time': bars[0].get('trade_time', ''),
            'open': float(o), 'high': float(h), 'low': float(lv), 'close': float(c),
            'vol': float(v), 'amount': float(a),
        })
    return result


def backfill_5min(ts_codes: List[str], days_back: int = 90,
                  ecm: Optional[EnhancedCacheManager] = None) -> int:
    """补采5分钟K线历史数据

    Args:
        ts_codes: 股票代码列表
        days_back: 回溯天数
        ecm: ECM实例（可选）

    Returns:
        成功写入的股票数
    """
    if ecm is None:
        ecm = get_ecm_instance()

    ok = 0
    for i, ts_code in enumerate(ts_codes):
        try:
            # 414号R17: 检查已有数据是否覆盖最近交易日，而非简单跳过有数据的股票
            existing = ecm.get_cached_minute_kline(ts_code, freq='5min')
            if existing is not None and not existing.empty:
                # 498号#40：原按日历日 `days_since<=5` 判「最近」，长假前后会误判过旧/过新；
                # 改按**交易日**（交易日历）判：latest 距今超过 3 个交易日才认为过旧。
                # 交易日历不可用时回退原日历日阈值（保证不因日历缺失而过度重采）。
                if 'trade_date' in existing.columns:
                    latest = existing['trade_date'].max()
                    if isinstance(latest, str):
                        latest_dt = datetime.strptime(latest[:10], '%Y-%m-%d')
                    else:
                        latest_dt = pd.to_datetime(latest).to_pydatetime()
                    stale = None
                    try:
                        from datetime import timedelta as _td
                        from app.utils.trading_hours import is_holiday
                        cur = datetime.now().date()
                        probe, days = latest_dt.date() + _td(days=1), 0
                        # 自 latest 次日起数「经过的交易日」（跳过周末与节假日）
                        while probe <= cur and days < 30:
                            if probe.weekday() < 5 and not is_holiday(datetime(probe.year, probe.month, probe.day)):
                                days += 1
                            probe += _td(days=1)
                        stale = days > 3
                    except Exception:
                        stale = (datetime.now() - latest_dt).days > 5
                    if not stale:  # 已有最近交易日数据，跳过
                        logger.debug(f"[5min] 跳过已有数据: {ts_code} ({len(existing)} 行, 最新 {latest})")
                        ok += 1
                        continue
                    else:
                        logger.info(f"[5min] 数据过旧, 重新采集: {ts_code}")

            df = _get_mootdx_bars_safe(ts_code, freq=2)
            if not df.empty:
                _cache_to_ecm(df, ts_code, '5min', ecm)
                logger.info(f"[5min] √ {ts_code}: {len(df)} 行")
                ok += 1
            else:
                logger.debug(f"[5min] × {ts_code}: mootdx 无数据")

            if (i + 1) % 10 == 0:
                logger.info(f"[5min] 进度: {i+1}/{len(ts_codes)}, 成功 {ok}")

            time.sleep(0.3)  # 避免限流
        except Exception as e:
            logger.warning(f"[5min] 失败 {ts_code}: {e}")
            continue

    logger.info(f"[5min] 采集完成: 成功 {ok}/{len(ts_codes)} 只")
    return ok


def backfill_1min(ts_codes: List[str], days_back: int = 30,
                  ecm: Optional[EnhancedCacheManager] = None) -> int:
    """补采1分钟K线历史数据（利用 mootdx minutes(YYYYMMDD) 支持任意历史日）

    Args:
        ts_codes: 股票代码列表
        days_back: 回溯天数
        ecm: ECM实例（可选）

    Returns:
        成功写入的股票数
    """
    if ecm is None:
        ecm = get_ecm_instance()

    today = date.today()
    date_list = [(today - timedelta(days=d)).strftime('%Y%m%d')
                 for d in range(days_back + 1)]
    # 过滤周末（粗略判断）
    date_list = [d for d in date_list if datetime.strptime(d, '%Y%m%d').weekday() < 5]

    ok = 0
    # 500号#17：改为读 `date_list` 窗口内的 1min 记录用于聚合（原 `ts_code` 全量读 →
    # O(history) 内存/耗时随历史线性增长，且可能用旧全量覆盖新聚合）。窗口内已落库的
    # 更早日期聚合结果保持不动（幂等 REPLACE 只更新窗口内日期）。
    for ts_code in ts_codes:
        try:
            window_records = []
            for target_date in date_list:
                # 跳过已有数据的日期（但窗口内已有记录仍需纳入聚合）
                existing = ecm.get_cached_minute_kline(ts_code, trade_date=target_date, freq='1min')
                if existing is not None and not existing.empty:
                    window_records.extend(existing.to_dict('records'))
                    continue

                df = _get_mootdx_minutes_safe(ts_code, target_date)
                if not df.empty:
                    _cache_to_ecm(df, ts_code, '1min', ecm)
                    window_records.extend(df.to_dict('records'))

            # 聚合1min→5min→15m/30m/60m（仅窗口内记录）
            got_data = bool(window_records)
            if got_data:
                agg5 = _resample_minute(window_records, '1min', '5min')
                if agg5:
                    _cache_to_ecm(pd.DataFrame(agg5), ts_code, '5min', ecm)
                    for freq in ['15min', '30min', '60min']:
                        agg = _resample_minute(agg5, '5min', freq)
                        if agg:
                            _cache_to_ecm(pd.DataFrame(agg), ts_code, freq, ecm)

            # 498号#42：原无条件 `ok += 1`（取到 0 行亦计成功）→ ok 虚增、系统性故障与
            # 「该股无数据」不可区分；改为仅在有 1min 数据时计成功。
            if got_data:
                ok += 1
                if ok % 10 == 0:
                    logger.info(f"[1min] 进度: {ok}/{len(ts_codes)} 只")
            else:
                logger.debug(f"[1min] 无数据: {ts_code}")

            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"[1min] 失败 {ts_code}: {e}")
            continue

    logger.info(f"[1min] 采集完成: {ok}/{len(ts_codes)} 只")
    return ok


def aggregate_minute(ts_codes: List[str],
                     target_freqs: Optional[List[str]] = None,
                     ecm: Optional[EnhancedCacheManager] = None) -> int:
    """从5min数据聚合为15m/30m/60m

    Args:
        ts_codes: 股票代码列表
        target_freqs: 目标频率列表，默认 ['15min', '30min', '60min']
        ecm: ECM实例（可选）

    Returns:
        处理的股票数
    """
    if target_freqs is None:
        target_freqs = ['15min', '30min', '60min']
    if ecm is None:
        ecm = get_ecm_instance()

    ok = 0
    for ts_code in ts_codes:
        try:
            df_5min = ecm.get_cached_minute_kline(ts_code, freq='5min')
            if df_5min is None or df_5min.empty:
                continue

            records = df_5min.to_dict('records')
            for freq in target_freqs:
                # 跳过已有聚合数据
                existing = ecm.get_cached_minute_kline(ts_code, freq=freq)
                if existing is not None and not existing.empty:
                    continue

                agg = _resample_minute(records, '5min', freq)
                if agg:
                    df_agg = pd.DataFrame(agg)
                    _cache_to_ecm(df_agg, ts_code, freq, ecm)

            ok += 1
            if ok % 50 == 0:
                logger.info(f"[聚合] 进度: {ok}/{len(ts_codes)} 只")
        except Exception as e:
            logger.warning(f"[聚合] 失败 {ts_code}: {e}")
            continue

    logger.info(f"[聚合] 完成: {ok}/{len(ts_codes)} 只, 目标频率: {target_freqs}")
    return ok


def aggregate_1min_to_60min(ts_codes: List[str],
                            ecm: Optional[EnhancedCacheManager] = None,
                            target_freq: str = '60min',
                            days_back: int = 5) -> int:
    """483号 ②：把 minute_kline_cache 的 1min 本地聚合为目标频率（默认 60min）落库。

    全市场维度、**零 API**（CPU-only）、幂等（PK = ts_code+trade_date+trade_time+freq，
    INSERT OR REPLACE）。原「5/15/30/60min 聚合」只在 run_backfill_all（自选股补采）内，
    watchlist 实测仅 1 只 → 全市场 60min 无生产链路，dim2 457 多周期级联退化为 W+D。

    498号#41：按最近 `days_back` 个交易日**窗口**读 1min（原读全量历史 → O(history) 内存/
    耗时随历史线性增长）。默认 5 日窗口足够覆盖 60min 日终聚合的日更需求。

    Returns:
        成功聚合写库的股票数
    """
    if ecm is None:
        ecm = get_ecm_instance()
    # 最近 N 个 1min 交易日（升序），限定读取窗口（内存可控）
    try:
        _td_df = ecm._query_shard(
            'minute_kline_cache',
            "SELECT DISTINCT trade_date FROM minute_kline_cache "
            "WHERE freq='1min' ORDER BY trade_date DESC LIMIT ?", [days_back])
        trade_dates = set(_td_df['trade_date'].tolist()) if _td_df is not None and not _td_df.empty else set()
    except Exception as e:
        # 500号#52：原宽 except 静默置空 → 分库映射/表位变化时下游静默 no-op（不可区分）
        logger.warning(f"[1min聚合{target_freq}] 读取交易日窗失败，退化为全量读取: {e}")
        trade_dates = set()
    ok = 0
    for ts_code in ts_codes:
        try:
            df_1min = ecm.get_cached_minute_kline(ts_code, freq='1min')
            if df_1min is None or df_1min.empty:
                continue
            # 498号#41：仅保留窗口内交易日（无 trade_date 列时不裁剪，保守全量）
            if trade_dates and 'trade_date' in df_1min.columns:
                df_1min = df_1min[df_1min['trade_date'].isin(trade_dates)]
                if df_1min.empty:
                    continue
            agg = _resample_minute(df_1min.to_dict('records'), '1min', target_freq)
            if agg:
                _cache_to_ecm(pd.DataFrame(agg), ts_code, target_freq, ecm)
                ok += 1
        except Exception as e:
            logger.debug(f"[1min聚合{target_freq}] {ts_code} 失败: {e}")
            continue
    logger.info(f"[1min聚合{target_freq}] 完成 {ok}/{len(ts_codes)} 只")
    return ok


def run_backfill_all(ts_codes: Optional[List[str]] = None) -> dict:
    """运行完整分钟数据补采流程

    Args:
        ts_codes: 股票代码列表（None则从自选股读取）

    Returns:
        执行结果统计
    """
    if ts_codes is None:
        ts_codes = get_watchlist_stocks()

    if not ts_codes:
        logger.warning("自选股列表为空，跳过分钟数据补采")
        return {'5min': 0, '1min': 0, 'aggregate': 0}

    ecm = get_ecm_instance()
    logger.info(f"分钟数据补采开始: {len(ts_codes)} 只自选股")

    n_5min = backfill_5min(ts_codes, ecm=ecm)
    n_1min = backfill_1min(ts_codes, ecm=ecm)
    n_agg = aggregate_minute(ts_codes, ecm=ecm)

    logger.info(f"分钟数据补采完成: 5min={n_5min}, 1min={n_1min}, 聚合={n_agg}")
    return {'5min': n_5min, '1min': n_1min, 'aggregate': n_agg}


def ensure_minute_data(ts_codes: List[str], days_back: int = 20) -> int:
    """快速确保股票具有分钟数据（供选股系统L3调用）"""

    import pandas as pd
    ecm_local = get_ecm_instance()

    # 只处理缺失5min数据的股票
    # 498号#2：minute_kline_cache 属 market_cache.db 分库，原直读 ecm_local.conn（总库，
    # 该库无此表）致 COUNT 恒 0/抛错；改分库读（_query_shard）。
    missing = []
    for code in ts_codes:
        try:
            _cnt_df = ecm_local._query_shard(
                'minute_kline_cache',
                'SELECT COUNT(*) AS n FROM minute_kline_cache WHERE ts_code=? AND freq="5min"',
                [code]
            )
            c = int(_cnt_df.iloc[0]['n']) if _cnt_df is not None and not _cnt_df.empty else 0
        except Exception as e:
            # 500号#52：原无包裹 → 分库读失败致整函数抛错被上层吞（不可区分）；按缺失处理并告警
            logger.warning(f"ensure_minute_data: 查询分钟覆盖失败({code})，按缺失处理: {e}")
            c = 0
        if c == 0:
            missing.append(code)

    if not missing:
        return 0

    # 真实交易日列表（498号#2：daily_cache 同属 market_cache.db 分库）
    try:
        _td_df = ecm_local._query_shard(
            'daily_cache',
            'SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT ?',
            [days_back]
        )
        trade_dates = _td_df['trade_date'].tolist() if _td_df is not None and not _td_df.empty else []
    except Exception as e:
        # 500号#52：交易日窗读取失败 → 无目标日，直接返回（可见告警，不静默 no-op）
        logger.warning(f"ensure_minute_data: 读取交易日窗失败，跳过补采: {e}")
        return 0

    ok = 0
    for ts_code in missing:
        try:
            all_1min = []
            for td in trade_dates:
                td_str = str(td) if not isinstance(td, str) else td
                td_fmt = td_str.replace('-', '')
                existing = ecm_local.get_cached_minute_kline(ts_code, trade_date=td_str, freq='1min')
                if existing is not None and not existing.empty:
                    continue
                raw = _get_mootdx_minutes_safe(ts_code, td_fmt)
                if raw is not None and not raw.empty:
                    _cache_to_ecm(raw, ts_code, '1min', ecm_local)
                    all_1min.extend(raw.to_dict('records'))

            if not all_1min:
                exist = ecm_local.get_cached_minute_kline(ts_code, freq='1min')
                if exist is not None and not exist.empty:
                    all_1min = exist.to_dict('records')
            if not all_1min:
                continue

            agg5 = _resample_minute(all_1min, '1min', '5min')
            if agg5:
                _cache_to_ecm(pd.DataFrame(agg5), ts_code, '5min', ecm_local)
                for freq in ['15min', '30min', '60min']:
                    agg = _resample_minute(agg5, '5min', freq)
                    if agg:
                        _cache_to_ecm(pd.DataFrame(agg), ts_code, freq, ecm_local)
            ok += 1
            time.sleep(0.15)
        except Exception as e:
            logger.debug(f"ensure_minute_data 失败 {ts_code}: {e}")
            continue

    if ok:
        logger.info(f"分钟数据快速补足: {ok}/{len(missing)} 只 (回溯{days_back}天)")
    return ok
