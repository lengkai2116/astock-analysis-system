#!/usr/bin/env python3
"""
backfill_minute_kline.py — 分钟K线全量补齐脚本

用途：利用 Tushare 5000积分，在周末非交易时段补齐全部 A 股分钟K线数据。
执行方式： python scripts/backfill_minute_kline.py

并行策略：
  - ThreadPoolExecutor 并行调用 pro_bar(freq='1min')
  - 共享限流器确保 ≤500次/分钟（Tushare 5000积分限制）
  - 批量化写入 ECM（每收集100只股票的数据集中写入）

输出日志文件： backend/logs/backfill_minute_kline.log
"""

import os, sys, time, logging, threading
from datetime import datetime, timedelta

# ── 路径设置 ──
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DATA_DIR', os.path.join(os.path.dirname(BACKEND_DIR), 'data'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(BACKEND_DIR, 'logs', 'backfill_minute_kline.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('backfill')

# ── ECM 初始化 ──
from app.data.enhanced_cache_manager import EnhancedCacheManager
_ecm = EnhancedCacheManager()

# ── 限流器（stk_mins 限制 200次/分钟，设120次/分钟=500ms间隔） ──
_lock = threading.Lock()
_last_call = [0.0]
_MIN_INTERVAL = 0.5  # 500ms = 120次/分钟（远低于200上限，防触发惩罚）

def _rate_limit():
    with _lock:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()

# ── 批量写入缓冲区 ──
_write_buffer = []
_write_buffer_lock = threading.Lock()
_WRITE_BATCH_SIZE = 50  # 每50只股票批量写入ECM一次

def _flush_buffer():
    """将缓冲区中的分钟K线数据写入ECM"""
    global _write_buffer
    with _write_buffer_lock:
        if not _write_buffer:
            return 0
        import pandas as pd
        batch = _write_buffer
        _write_buffer = []
    try:
        for df in batch:
            if df is not None and not df.empty:
                _ecm.cache_minute_kline(df)
        return len(batch)
    except Exception as e:
        logger.warning(f"  ECM写入失败: {e}")
        return 0

def _push_to_buffer(df):
    """将单只股票的分钟数据加入缓冲区"""
    global _write_buffer
    with _write_buffer_lock:
        _write_buffer.append(df)
    if len(_write_buffer) >= _WRITE_BATCH_SIZE:
        _flush_buffer()


def fetch_and_cache(code: str, batch_size: int = 30) -> int:
    """获取并缓存单只股票的分钟K线数据
    
    尝试批量获取（逗号分隔多只），失败则回落单只。
    Returns: 获取的数据行数
    """
    import tushare as ts
    import pandas as pd
    _rate_limit()

    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=batch_size)).strftime('%Y%m%d')

    try:
        raw = ts.pro_bar(ts_code=code, freq='1min',
                         start_date=start_date, end_date=end_date, adj='qfq')
        if raw is None or raw.empty:
            return 0

        df = raw.copy()
        # 列映射：trade_time → trade_date + trade_time
        if 'trade_time' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_time']).dt.date
        elif 'trade_date' in df.columns:
            df['trade_time'] = df['trade_date']
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date

        # 列重命名：vol → volume
        if 'vol' in df.columns and 'volume' not in df.columns:
            df['volume'] = df['vol']
            df = df.drop(columns=['vol'])

        # 设置频率
        df['freq'] = '1min'

        # 确保所有列存在
        for col in ['ts_code', 'trade_date', 'trade_time', 'freq',
                     'open', 'high', 'low', 'close', 'volume', 'amount']:
            if col not in df.columns:
                df[col] = 0 if col in ('open', 'high', 'low', 'close', 'volume', 'amount') else ''

        # 只保留需要的列
        keep = ['ts_code', 'trade_date', 'trade_time', 'freq',
                'open', 'high', 'low', 'close', 'volume', 'amount']
        df = df[[c for c in keep if c in df.columns]]

        _push_to_buffer(df)
        return len(df)

    except Exception as e:
        logger.debug(f"  {code} 失败: {str(e)[:80]}")
        return 0


def get_stock_list() -> list:
    """获取全部股票列表，以及已有分钟数据的股票"""
    # 全部股票
    all_stocks = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache ORDER BY ts_code"
    ).fetchall()
    all_stocks = [r[0] for r in all_stocks]

    # 已有分钟数据的股票（最近30天）
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    have_minute = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE trade_date >= ?",
        [cutoff]
    ).fetchall()
    have_minute = set(r[0] for r in have_minute)

    # 已有1min频率数据的股票
    have_1min = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE freq='1min' AND trade_date >= ?",
        [cutoff]
    ).fetchall() if have_minute else []
    have_1min = set(r[0] for r in have_1min)

    return all_stocks, have_minute, have_1min


def try_batch_fetch(codes: list, batch_size: int = 30) -> tuple:
    """尝试批量获取多只股票的分钟数据（逗号分隔）
    
    Returns: (成功股票数, 总行数, 失败股票列表)
    """
    import tushare as ts
    import pandas as pd
    _rate_limit()

    if len(codes) > 10:
        return 0, 0, codes  # 批次不要太大

    code_str = ','.join(codes)
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=batch_size)).strftime('%Y%m%d')

    try:
        raw = ts.pro_bar(ts_code=code_str, freq='1min',
                         start_date=start_date, end_date=end_date, adj='qfq')
        if raw is None or raw.empty:
            return 0, 0, codes

        # pro_bar 批量返回的列与单只相同，ts_code区分股票
        df = raw.copy()
        if 'trade_time' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_time']).dt.date
        if 'vol' in df.columns and 'volume' not in df.columns:
            df['volume'] = df['vol']
            df = df.drop(columns=['vol'])
        df['freq'] = '1min'

        # 按股票拆分后写入
        success_codes = []
        total_rows = 0
        for code in codes:
            sub = df[df['ts_code'] == code]
            if not sub.empty:
                keep = ['ts_code', 'trade_date', 'trade_time', 'freq',
                        'open', 'high', 'low', 'close', 'volume', 'amount']
                sub = sub[[c for c in keep if c in sub.columns]]
                _push_to_buffer(sub)
                success_codes.append(code)
                total_rows += len(sub)

        failed = [c for c in codes if c not in success_codes]
        return len(success_codes), total_rows, failed
    except Exception as e:
        logger.debug(f"  批量获取失败 ({len(codes)}只): {str(e)[:80]}")
        return 0, 0, codes


def main():
    logger.info("=" * 60)
    logger.info("分钟K线全量补齐脚本启动")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    import concurrent.futures

    # ── Step 1: 获取股票列表 ──
    all_stocks, have_minute, have_1min = get_stock_list()
    logger.info(f"全部股票: {len(all_stocks)} 只")
    logger.info(f"已有分钟数据(30日内): {len(have_minute)} 只")
    logger.info(f"已有1min数据(30日内): {len(have_1min)} 只")

    # 需要补齐的股票：全部股票 - 已有1min完整数据的
    need_backfill = [s for s in all_stocks if s not in have_1min]
    logger.info(f"需补齐: {len(need_backfill)} 只")

    if not need_backfill:
        logger.info("所有股票分钟数据已完整，无需补齐")
        return

    # ── Step 2: 分批处理（每批10只，用ThreadPoolExecutor并行获取） ──
    batch_size = 10
    total_ok = 0
    total_rows = 0
    t_start = time.time()

    for i in range(0, len(need_backfill), batch_size):
        batch_codes = need_backfill[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(need_backfill) + batch_size - 1) // batch_size

        # 先尝试批量获取（逗号分隔）
        ok, rows, failed = try_batch_fetch(batch_codes)
        if ok == len(batch_codes):
            total_ok += ok
            total_rows += rows
            elapsed = time.time() - t_start
            rate = total_ok / (elapsed / 60) if elapsed > 0 else 0
            logger.info(f"  [批{batch_num}/{total_batches}✅] {ok}/{len(batch_codes)}只, {rows}行, "
                        f"累计{total_ok}只, {total_rows}行, {rate:.0f}只/分")
            continue

        # 批量失败，回落单只并行
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_and_cache, code): code for code in failed}
            for future in concurrent.futures.as_completed(futures):
                code = futures[future]
                try:
                    rows = future.result()
                    if rows > 0:
                        total_ok += 1
                        total_rows += rows
                except Exception as e:
                    logger.debug(f"  {code} 异常: {e}")

        elapsed = time.time() - t_start
        rate = total_ok / (elapsed / 60) if elapsed > 0 else 0
        logger.info(f"  [批{batch_num}/{total_batches}] {len(batch_codes)}只完成, "
                    f"累计{total_ok}只, {total_rows}行, {rate:.0f}只/分")

        # 每10批写一次进度+刷新缓冲区
        if batch_num % 10 == 0:
            flushed = _flush_buffer()
            if flushed:
                logger.info(f"  缓冲区写入ECM: {flushed} 批")
            remaining = len(need_backfill) - total_ok
            eta_min = remaining / rate if rate > 0 else 0
            logger.info(f"  预估剩余: {remaining}只, {eta_min:.0f}分钟")

    # ── 最终刷新 ──
    flushed = _flush_buffer()
    t_total = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"补齐完成!")
    logger.info(f"成功: {total_ok}/{len(need_backfill)} 只, 共 {total_rows} 行")
    logger.info(f"耗时: {t_total:.0f}秒 ({t_total/60:.1f}分钟)")
    logger.info(f"速率: {total_ok/(t_total/60):.0f} 只/分钟")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
