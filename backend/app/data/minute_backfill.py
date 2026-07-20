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
from datetime import datetime, timedelta, date
from typing import List, Optional

import pandas as pd
from app.data.enhanced_cache_manager import get_ecm_instance, EnhancedCacheManager

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
        import sqlite3
        import os
        data_dir = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data'))
        db_path = os.path.join(data_dir, 'app.db')
        if os.path.isfile(db_path):
            conn = sqlite3.connect(db_path)
            cur = conn.execute('SELECT ts_code FROM watchlist ORDER BY sort_order')
            codes = [r[0] for r in cur.fetchall()]
            conn.close()
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
            for idx, r in raw.iterrows():
                hour = 9 + (idx + 30) // 60
                minute = (idx + 30) % 60
                trade_time = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]} {hour:02d}:{minute:02d}:00"
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
        if 'vol' in df_copy.columns and 'volume' not in df_copy.columns:
            df_copy = df_copy.rename(columns={'vol': 'volume'})
        ecm.cache_minute_kline(df_copy)
    except Exception as e:
        logger.warning(f"缓存分钟K线失败 ({ts_code}/{freq}): {e}")


def _resample_minute(records: list, from_freq: str, to_freq: str) -> list:
    """分钟线频率转换（复用 MinuteDataManager._resample_minute 逻辑）"""
    from collections import defaultdict
    if not records:
        return []
    total_min = int(to_freq.replace('min', ''))
    base_min = int(from_freq.replace('min', ''))
    group_size = total_min // base_min
    if group_size <= 1:
        return records
    groups = defaultdict(list)
    for r in records:
        tt = r.get('trade_time', '')
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
    for (d, slot), bars in sorted(groups.items()):
        o = bars[0].get('open', 0)
        c = bars[-1].get('close', 0)
        h = max(b.get('high', 0) for b in bars)
        lv = min(b.get('low', float('inf')) for b in bars)
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
            # 跳过已有数据的股票
            existing = ecm.get_cached_minute_kline(ts_code, freq='5min')
            if existing is not None and not existing.empty:
                logger.debug(f"[5min] 跳过已有数据: {ts_code} ({len(existing)} 行)")
                ok += 1
                continue
            
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
    for ts_code in ts_codes:
        try:
            for target_date in date_list:
                # 跳过已有数据的日期
                existing = ecm.get_cached_minute_kline(ts_code, trade_date=target_date, freq='1min')
                if existing is not None and not existing.empty:
                    continue
                
                df = _get_mootdx_minutes_safe(ts_code, target_date)
                if not df.empty:
                    _cache_to_ecm(df, ts_code, '1min', ecm)
            
            # 聚合1min→5min→15m/30m/60m
            df_1min = ecm.get_cached_minute_kline(ts_code, freq='1min')
            if df_1min is not None and not df_1min.empty:
                records = df_1min.to_dict('records')
                agg5 = _resample_minute(records, '1min', '5min')
                if agg5:
                    _cache_to_ecm(pd.DataFrame(agg5), ts_code, '5min', ecm)
                    for freq in ['15min', '30min', '60min']:
                        agg = _resample_minute(agg5, '5min', freq)
                        if agg:
                            _cache_to_ecm(pd.DataFrame(agg), ts_code, freq, ecm)
            
            ok += 1
            if ok % 10 == 0:
                logger.info(f"[1min] 进度: {ok}/{len(ts_codes)} 只")
            
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
    from collections import defaultdict
    from datetime import date, timedelta
    ecm_local = get_ecm_instance()
    
    # 只处理缺失5min数据的股票
    missing = []
    for code in ts_codes:
        c = ecm_local.conn.execute(
            'SELECT COUNT(*) FROM minute_kline_cache WHERE ts_code=? AND freq="5min"',
            [code]
        ).fetchone()[0]
        if c == 0:
            missing.append(code)
    
    if not missing:
        return 0
    
    # 真实交易日列表
    trade_dates = [r[0] for r in ecm_local.conn.execute(
        'SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT ?',
        [days_back]
    ).fetchall()]
    
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
