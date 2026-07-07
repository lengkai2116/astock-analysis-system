"""
MootdxCollector — mootdx(TCP) 盘中数据后台采集器
===============================================
替代 AkshareCollector 的 HTTP 采集，使用通达信 TCP 二进制协议获取 L1 实时行情。

架构：
  mootdx Collector (1 线程)
  ┌──────────────────────────────────────┐
  │ L1快照线程 (5s TCP直连)               │
  │ · quotes(全市场 A 股)                 │ ← TCP 二进制协议，无 WAF
  │ · 46字段 + 五档盘口                   │
  │ · 从快照自算涨跌榜/涨跌停池            │
  └──────────────┬───────────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────────┐
  │ InMemoryStateStore                    │ ← 与 AKShare 共用
  │ + WsBridge → SocketIO → 前端          │
  └──────────────────────────────────────┘

启动方式：
    from app.data.mootdx_collector import mootdx_collector
    mootdx_collector.start()   # 应用启动时调用
    mootdx_collector.stop()    # 应用关闭时调用
"""

import os
# 免发环境变量代理干扰：mootdx TCP 直连无需 HTTP_PROXY
for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_k, None)

import logging
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict
import requests

logger = logging.getLogger(__name__)

# ── mootdx 惰性初始化 ───────────────────────────────────

_client_instance = None
_client_lock = threading.Lock()
_stock_name_map: Dict[str, str] = {}
_stock_name_map_ts = 0.0


def _get_client():
    """惰性初始化 mootdx Quotes 客户端（线程安全，支持重连）"""
    global _client_instance
    if _client_instance is not None:
        return _client_instance
    with _client_lock:
        if _client_instance is not None:
            return _client_instance
        try:
            from mootdx.quotes import Quotes
            client = Quotes.factory()
            stocks = client.stocks()
            if stocks is None or stocks.empty:
                raise ConnectionError("stocks() 返回空")
            _client_instance = client
            logger.info(f"mootdx 客户端已创建（{len(stocks)} 只股票）")
            return client
        except Exception as e:
            logger.warning(f"mootdx 客户端创建失败: {e}")
            return None


def _refresh_stock_name_map():
    """刷新股票名称映射表（每小时最多一次）"""
    global _stock_name_map, _stock_name_map_ts
    now = time.time()
    if now - _stock_name_map_ts < 3600 and _stock_name_map:
        return _stock_name_map
    client = _get_client()
    if client is None:
        return {}
    try:
        stocks = client.stocks()
        if stocks is not None and not stocks.empty:
            _stock_name_map = dict(zip(stocks['code'], stocks['name']))
            _stock_name_map_ts = now
            logger.debug(f"股票名称映射已刷新 ({len(_stock_name_map)} 只)")
    except Exception:
        pass
    return _stock_name_map


# ── 盘中数据引用 ──────────────────────────────────────────

from app.data.in_memory_store import store as mem_store


# ── 分钟K线聚合 ───────────────────────────────────────────
# 252号方案 Phase 1：从 mootdx L1 快照自聚合 1min K线
# _minute_window: {ts_code: {'minute_key': str, 'open': float, 'high': float,
#                            'low': float, 'close': float, 'volume': int,
#                            'amount': float, 'count': int}}
_minute_window: dict = {}
_minute_window_lock = threading.Lock()
_MINUTE_AGG_FREQ = '1min'  # 聚合频率
_FLUSH_BATCH_SIZE = 200    # 每批写入ECM的股票数


def _feed_minute_aggregator(records: List[Dict]):
    """将快照数据送入分钟K线聚合窗口

    每5秒调用一次，按分钟窗口聚合 OHLC。
    在分钟切换时自动 flush 已完成窗口到存储层。
    """
    global _minute_window
    now = datetime.now()
    minute_key = now.strftime('%Y-%m-%d %H:%M')  # 精确到分

    with _minute_window_lock:
        for r in records:
            code = r.get('ts_code', '')
            price = r.get('price', 0)
            vol = r.get('volume', 0)
            amt = r.get('amount', 0)
            if not code or price == 0:
                continue

            if code not in _minute_window:
                _minute_window[code] = {
                    'minute_key': minute_key,
                    'open': price, 'high': price, 'low': price,
                    'close': price, 'volume': vol, 'amount': amt,
                    'count': 1,
                }
            else:
                w = _minute_window[code]
                if w['minute_key'] != minute_key:
                    # 分钟切换：flush旧窗口，start新窗口
                    _do_flush_one(code, w, now)
                    _minute_window[code] = {
                        'minute_key': minute_key,
                        'open': price, 'high': price, 'low': price,
                        'close': price, 'volume': vol, 'amount': amt,
                        'count': 1,
                    }
                else:
                    w['high'] = max(w['high'], price)
                    w['low'] = min(w['low'], price) if w['low'] > 0 else price
                    w['close'] = price
                    w['volume'] += vol
                    w['amount'] += amt
                    w['count'] += 1


def _do_flush_one(code: str, window: dict, now: datetime):
    """flush 单只股票的已完成分钟K线到 InMemoryStore + ECM"""
    trade_date = now.strftime('%Y-%m-%d')
    trade_time = f"{window['minute_key']}:00"

    bar = {
        'ts_code': code,
        'trade_date': trade_date,
        'trade_time': trade_time,
        'freq': _MINUTE_AGG_FREQ,
        'open': window['open'],
        'high': window['high'],
        'low': window['low'],
        'close': window['close'],
        'volume': window['volume'],
        'amount': window['amount'],
    }

    # 写入 InMemoryStateStore（盘中推送用）
    try:
        mem_store.append_minute_kline([bar])
    except Exception:
        pass

    # 写入 ECM minute_kline_cache（持久化）
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        import pandas as pd
        ecm._insert_from_df('minute_kline_cache', pd.DataFrame([bar]))
    except Exception:
        pass


def _flush_all_pending():
    """强制 flush 所有未完成的窗口（应用关闭/日终时调用）"""
    global _minute_window
    now = datetime.now()
    with _minute_window_lock:
        for code, window in list(_minute_window.items()):
            if window['count'] > 0:
                _do_flush_one(code, window, now)
        _minute_window.clear()


# ── 交易时段判断 ──────────────────────────────────────────

def _is_trading_time() -> bool:
    try:
        from app.utils.trading_hours import is_trading_time
        return is_trading_time()
    except ImportError:
        return True


# ── 工具函数 ──────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        v = float(val)
        return v if v == v else 0.0  # NaN → 0
    except (TypeError, ValueError):
        return 0.0


def _ts_code(code: str, market: int) -> str:
    suffix = 'SH' if market == 1 else 'SZ'
    return f"{code}.{suffix}"


def _get_a_share_codes() -> List[str]:
    """获取所有 A 股代码列表（沪深主板/创业板/科创板）"""
    name_map = _refresh_stock_name_map()
    return [
        c for c in name_map
        if isinstance(c, str) and len(c) == 6 and c[0] in ('0', '3', '6')
    ]


# ══════════════════════════════════════════════════════════
# 采集阈值 & 指数配置
# ══════════════════════════════════════════════════════════

_LIMIT_UP_THRESHOLD = 9.8
_LIMIT_DOWN_THRESHOLD = -9.8

# 五大指数配置：mootdx code → (ts_code_suffix, ws_name)
INDEX_CONFIG = {
    '000001': ('SH', '上证指数'),
    '399001': ('SZ', '深证成指'),
    '000300': ('SH', '沪深300'),
    '000016': ('SH', '上证50'),
    '399006': ('SZ', '创业板指'),
}

# ══════════════════════════════════════════════════════════
# 采集函数
# ══════════════════════════════════════════════════════════


def collect_market_snapshot() -> int:
    """全市场 L1 快照采集（mootdx TCP，分批）

    mootdx server 单次 quotes() 最多返回 ~80 只，将全市场代码分批查询后合并。
    从快照自算涨跌榜 + 涨跌停池，无需独立 HTTP 采集。

    Returns:
        采集的有效股票数量
    """
    global _client_instance
    client = _get_client()
    if client is None:
        logger.warning("[mootdx] 客户端不可用，跳过快照采集")
        return 0

    codes = _get_a_share_codes()
    if not codes:
        return 0

    name_map = _stock_name_map
    _BATCH_SIZE = 100
    all_records = []

    try:
        t_start = time.time()
        for batch_start in range(0, len(codes), _BATCH_SIZE):
            batch = codes[batch_start:batch_start + _BATCH_SIZE]
            try:
                df = client.quotes(batch)
            except Exception as e:
                logger.debug(f"[mootdx] batch {batch_start} 请求失败: {e}")
                continue

            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                code = str(row.get('code', ''))
                market = int(row.get('market', 0))
                price = _safe_float(row.get('price'))
                last_close = _safe_float(row.get('last_close'))

                if price == 0 or last_close == 0:
                    continue

                change = round(price - last_close, 2)
                change_pct = round(change / last_close * 100, 2) if last_close else 0.0

                record = {
                    'ts_code': _ts_code(code, market),
                    'code': code,
                    'name': name_map.get(code, ''),
                    'price': price,
                    'change': change,
                    'change_pct': change_pct,
                    'open': _safe_float(row.get('open')),
                    'high': _safe_float(row.get('high')),
                    'low': _safe_float(row.get('low')),
                    'prev_close': last_close,
                    'volume': int(_safe_float(row.get('volume', row.get('vol', 0)))),
                    'amount': _safe_float(row.get('amount')),
                    'bid1': _safe_float(row.get('bid1')),
                    'ask1': _safe_float(row.get('ask1')),
                    'bid_vol1': int(_safe_float(row.get('bid_vol1', 0))),
                    'ask_vol1': int(_safe_float(row.get('ask_vol1', 0))),
                    'bid2': _safe_float(row.get('bid2')),
                    'ask2': _safe_float(row.get('ask2')),
                    'bid_vol2': int(_safe_float(row.get('bid_vol2', 0))),
                    'ask_vol2': int(_safe_float(row.get('ask_vol2', 0))),
                    'bid3': _safe_float(row.get('bid3')),
                    'ask3': _safe_float(row.get('ask3')),
                    'bid_vol3': int(_safe_float(row.get('bid_vol3', 0))),
                    'ask_vol3': int(_safe_float(row.get('ask_vol3', 0))),
                    'bid4': _safe_float(row.get('bid4')),
                    'ask4': _safe_float(row.get('ask4')),
                    'bid_vol4': int(_safe_float(row.get('bid_vol4', 0))),
                    'ask_vol4': int(_safe_float(row.get('ask_vol4', 0))),
                    'bid5': _safe_float(row.get('bid5')),
                    'ask5': _safe_float(row.get('ask5')),
                    'bid_vol5': int(_safe_float(row.get('bid_vol5', 0))),
                    'ask_vol5': int(_safe_float(row.get('ask_vol5', 0))),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'mootdx_collector',
                }
                all_records.append(record)

        elapsed = time.time() - t_start

        if not all_records:
            logger.warning(f"[mootdx] 快照采集完成，但无有效数据 ({elapsed:.1f}s)")
            return 0

        mem_store.update_snapshot(all_records)
        logger.info(f"[mootdx] 快照采集完成: {len(all_records)} 只 ({elapsed:.1f}s, {len(codes)} 批)")

        # 252号方案 Phase 1：分钟K线聚合
        _feed_minute_aggregator(all_records)

        _compute_top_stocks(all_records)
        _compute_limit_pools(all_records)
        _collect_indices()         # 指数数据（修复SH/SZ标记）
        _compute_sector_rankings()  # 板块排行（替代AKShare）
        _collect_bse_quotes()       # 北交所行情（腾讯API补充）

        return len(all_records)

    except Exception as e:
        logger.warning(f"[mootdx] 快照采集失败: {e}")
        # 连接失败时重置客户端，下次采集自动重连
        global _client_instance
        _client_instance = None
        return 0


# ── 指数数据采集 ───────────────────────────────────────────

# 上次采集成功的时间戳，用于降频（指数数据不需要每轮都刷新）
_last_index_ts = 0.0


def _collect_indices():
    """采集五大指数行情数据（使用 mootdx index()，修复 SH/SZ 市场标记）

    client.index() 返回正确的市场归属（上证→SH，深证→SZ），
    替代 quotes() 中因前缀规则误分的市场标记。
    同时提供 up_count/down_count（涨跌家数）用于市场广度指标。
    """
    global _last_index_ts
    now = time.time()
    # 每 30s 刷新一次指数即可
    if now - _last_index_ts < 30 and _last_index_ts > 0:
        return
    _last_index_ts = now

    client = _get_client()
    if client is None:
        return

    now_dt = datetime.now()
    records = []

    for code, (suffix, name) in INDEX_CONFIG.items():
        try:
            df = client.index(code)
            if df is None or df.empty:
                logger.debug(f"[mootdx] index('{code}') 返回空")
                continue

            # 取最新一行
            df = df.sort_index()
            latest = df.iloc[-1]
            price = _safe_float(latest.get('close'))
            last_close_idx = df.iloc[-2]['close'] if len(df) > 1 else price
            change = round(price - last_close_idx, 2) if last_close_idx else 0.0
            change_pct = round(change / last_close_idx * 100, 2) if last_close_idx else 0.0

            records.append({
                'ts_code': f"{code}.{suffix}",
                'code': code,
                'name': name,
                'price': price,
                'change': change,
                'change_pct': change_pct,
                'open': _safe_float(latest.get('open')),
                'high': _safe_float(latest.get('high')),
                'low': _safe_float(latest.get('low')),
                'prev_close': last_close_idx,
                'volume': int(_safe_float(latest.get('vol', 0))),
                'amount': _safe_float(latest.get('amount')),
                'up_count': int(_safe_float(latest.get('up_count', 0))),
                'down_count': int(_safe_float(latest.get('down_count', 0))),
                'timestamp': now_dt.isoformat(),
                'source': 'mootdx_index',
            })
        except Exception as e:
            logger.debug(f"[mootdx] 采集指数 {code}({name}) 失败: {e}")

    if records:
        # 写入 store，覆盖 quotes() 中可能错误的市场标记
        mem_store.update_snapshot(records)
        logger.debug(f"[mootdx] 指数采集完成: {len(records)} 个指数")


# ── 行业板块排行（从快照自算，替代 AKShare） ─────────────

# 行业映射缓存：{ts_code: industry_name}
# 来源：Tushare stock_basic（110 个行业分类）
_industry_map: Dict[str, str] = {}
_industry_map_ts = 0.0


def _init_industry_map():
    """初始化行业映射（从 Tushare stock_basic，每日最多刷新一次）"""
    global _industry_map, _industry_map_ts
    now = time.time()
    if now - _industry_map_ts < 86400 and _industry_map:
        return
    try:
        import tushare as ts
        pro = ts.pro_api()
        df = pro.stock_basic(fields='ts_code,industry')
        if df is not None and not df.empty:
            _industry_map = {
                row['ts_code']: row['industry']
                for _, row in df.iterrows()
                if row.get('industry')
            }
            _industry_map_ts = now
            logger.info(f"[mootdx] 行业映射已初始化 ({len(_industry_map)} 只股票, "
                        f"{len(set(_industry_map.values()))} 个行业)")
    except Exception as e:
        logger.warning(f"[mootdx] 行业映射初始化失败: {e}")


def _compute_sector_rankings():
    """从快照自算行业板块排行

    使用 Tushare stock_basic 的行业分类 + mootdx L1 快照涨跌幅，
    按行业聚合计算平均涨跌幅，替代不可用的 AKShare stock_board_industry_name_em()。
    刷新频率跟随快照（~5s），但每 30s 才实际更新 store。
    """
    global _last_sector_ts
    now = time.time()
    # 每 30s 刷新一次板块排行
    if now - getattr(_compute_sector_rankings, '_last_ts', 0) < 30:
        return
    _compute_sector_rankings._last_ts = now

    _init_industry_map()
    if not _industry_map:
        return

    snapshot = mem_store.get_snapshot()
    if not snapshot:
        return

    # 按行业分组聚合
    from collections import defaultdict
    industry_data = defaultdict(list)

    for s in snapshot:
        ts_code = s.get('ts_code', '')
        industry = _industry_map.get(ts_code)
        if not industry:
            continue
        pct = s.get('change_pct')
        if pct is None:
            continue
        industry_data[industry].append(pct)

    if not industry_data:
        return

    # 计算每个行业的平均涨跌幅、涨跌家数
    records = []
    for industry, pcts in industry_data.items():
        avg_pct = round(sum(pcts) / len(pcts), 2)
        up = sum(1 for p in pcts if p > 0)
        down = sum(1 for p in pcts if p < 0)
        records.append({
            'industry': industry,
            'avg_change_pct': avg_pct,
            'up_count': up,
            'down_count': down,
            'total_count': len(pcts),
        })

    if not records:
        return

    # 按平均涨跌幅排序并写入 store
    records.sort(key=lambda r: r['avg_change_pct'], reverse=True)
    mem_store.update_sectors(records)
    logger.debug(f"[mootdx] 行业板块排行已更新: {len(records)} 个行业")


# ── 北交所行情采集（腾讯财经 HTTP API 补充） ────────────

# 北交所股票列表缓存：[{code, ts_code, name}]
_bse_stocks: List[Dict] = []
_bse_stocks_ts = 0.0
_bse_last_fetch_ts = 0.0


def _init_bse_stock_list():
    """初始化北交所股票列表（从 Tushare stock_basic，每日刷新一次）"""
    global _bse_stocks, _bse_stocks_ts
    now = time.time()
    if now - _bse_stocks_ts < 86400 and _bse_stocks:
        return
    try:
        import tushare as ts
        pro = ts.pro_api()
        df = pro.stock_basic(fields='ts_code,symbol,name')
        if df is not None and not df.empty:
            bse = df[df['ts_code'].str.endswith('.BJ')]
            _bse_stocks = [
                {'ts_code': row['ts_code'], 'symbol': str(row['symbol']), 'name': row['name']}
                for _, row in bse.iterrows()
            ]
            _bse_stocks_ts = now
            logger.info(f"[mootdx] 北交所股票列表已初始化: {len(_bse_stocks)} 只")
    except Exception as e:
        logger.warning(f"[mootdx] 北交所股票列表初始化失败: {e}")


def _collect_bse_quotes():
    """采集北交所实时行情（腾讯财经 HTTP API）

    每 10s 轮询一次，通过 qt.gtimg.cn HTTP API 获取 324 只北交所股票行情。
    写入 InMemoryStateStore，与沪深数据合并。
    """
    global _bse_last_fetch_ts
    now = time.time()
    if now - _bse_last_fetch_ts < 10 and _bse_last_fetch_ts > 0:
        return
    _bse_last_fetch_ts = now

    _init_bse_stock_list()
    if not _bse_stocks:
        return

    # 分批查询（腾讯API单次可处理约 50 个代码）
    records = []
    _BATCH = 50
    for batch_start in range(0, len(_bse_stocks), _BATCH):
        batch = _bse_stocks[batch_start:batch_start + _BATCH]
        codes_q = ','.join(f"bj{s['symbol']}" for s in batch)
        try:
            resp = requests.get(f"https://qt.gtimg.cn/q={codes_q}",
                           timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code != 200 or not resp.text:
                continue
            for line in resp.text.strip().split('\n'):
                if '=' not in line or not line.strip():
                    continue
                parts = line.split('~')
                if len(parts) < 35:
                    continue
                code = parts[2] if len(parts) > 2 else ''
                name = parts[1] if len(parts) > 1 else ''
                price = _safe_float(parts[3]) if len(parts) > 3 else 0.0
                prev_close = _safe_float(parts[4]) if len(parts) > 4 else 0.0
                if price == 0:
                    continue
                records.append({
                    'ts_code': f"{code}.BJ",
                    'code': code,
                    'name': name,
                    'price': price,
                    'change': round(price - prev_close, 2) if prev_close else 0.0,
                    'change_pct': round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
                    'open': _safe_float(parts[5]) if len(parts) > 5 else 0.0,
                    'high': _safe_float(parts[33]) if len(parts) > 33 else 0.0,
                    'low': _safe_float(parts[34]) if len(parts) > 34 else 0.0,
                    'prev_close': prev_close,
                    'volume': int(_safe_float(parts[6])) if len(parts) > 6 else 0,
                    'amount': 0.0,
                    'bid1': _safe_float(parts[9]) if len(parts) > 9 else 0.0,
                    'ask1': _safe_float(parts[10]) if len(parts) > 10 else 0.0,
                    'timestamp': datetime.now().isoformat(),
                    'source': 'bse_tencent',
                })
        except Exception as e:
            logger.debug(f"[mootdx] BSE batch {batch_start} 失败: {e}")
            continue

    if records:
        mem_store.update_snapshot(records)
        logger.debug(f"[mootdx] 北交所采集完成: {len(records)} 只")


def _compute_top_stocks(records: List[Dict]):
    """从快照自算涨跌榜（Top 20）"""
    if not records:
        return
    sorted_r = sorted(records, key=lambda r: r.get('change_pct', 0), reverse=True)
    up = [
        {'ts_code': r['ts_code'], 'name': r.get('name', ''), 'price': r.get('price', 0),
         'change': r.get('change', 0), 'change_pct': r.get('change_pct', 0)}
        for r in sorted_r[:20] if r.get('change_pct', 0) > 0
    ]
    down = [
        {'ts_code': r['ts_code'], 'name': r.get('name', ''), 'price': r.get('price', 0),
         'change': r.get('change', 0), 'change_pct': r.get('change_pct', 0)}
        for r in reversed(sorted_r[-20:]) if r.get('change_pct', 0) < 0
    ]
    mem_store.update_top_stocks('up', up)
    mem_store.update_top_stocks('down', down)


def _compute_limit_pools(records: List[Dict]):
    """从快照自算涨跌停池（含近涨/跌停标记）"""
    if not records:
        return
    up = []
    down = []
    for r in records:
        pct = r.get('change_pct', 0)
        if pct >= _LIMIT_UP_THRESHOLD:
            up.append({'ts_code': r['ts_code'], 'name': r.get('name', ''),
                       'price': r.get('price', 0), 'change_pct': pct})
        elif pct <= _LIMIT_DOWN_THRESHOLD:
            down.append({'ts_code': r['ts_code'], 'name': r.get('name', ''),
                         'price': r.get('price', 0), 'change_pct': pct})
    mem_store.update_limit_pool('up', up)
    mem_store.update_limit_pool('down', down)


# ══════════════════════════════════════════════════════════
# 采集线程
# ══════════════════════════════════════════════════════════

class _MootdxThread(threading.Thread):
    """mootdx 采集线程 — 固定间隔轮询，仅在交易时段工作"""

    _BACKOFF_STEPS = [1, 2, 4, 8, 15, 30, 60, 120]
    _MAX_BACKOFF = 300

    def __init__(self, name: str, interval_sec: int, collect_func,
                 check_trading_time: bool = True,
                 initial_delay: int = 5):
        super().__init__(name=name, daemon=True)
        self.interval = interval_sec
        self.collect = collect_func
        self.check_trading = check_trading_time
        self._stop_event = threading.Event()
        self._collect_count = 0
        self._error_count = 0
        self._consecutive_failures = 0
        self._initial_delay = initial_delay

    def run(self):
        logger.info(f"[{self.name}] 线程启动，间隔={self.interval}s，初始延迟={self._initial_delay}s")
        time.sleep(self._initial_delay)
        # 首次采集：无论是否交易时段都执行一次，确保盘后也有缓存数据
        try:
            self.collect()
            self._collect_count += 1
            self._consecutive_failures = 0
        except Exception:
            pass
        # 之后的采集仅在交易时段执行
        while not self._stop_event.is_set():
            try:
                if self.check_trading and not _is_trading_time():
                    self._stop_event.wait(60)
                    continue

                t0 = time.time()
                self.collect()
                elapsed = time.time() - t0
                self._collect_count += 1
                self._consecutive_failures = 0

                try:
                    from app.data.ws_bridge import ws_bridge
                    ws_bridge.on_collect_complete(self.name)
                    # 板块排行也被 mootdx 计算，触发推送
                    ws_bridge.on_collect_complete('sector_and_limit')
                except Exception:
                    pass

                wait = max(1, self.interval - elapsed)
                self._stop_event.wait(wait)

            except Exception as e:
                self._error_count += 1
                self._consecutive_failures += 1
                n = self._consecutive_failures
                if n <= 3 or n == 10 or n == 100 or n % 100 == 0:
                    logger.warning(f"[{self.name}] 采集失败(第{n}次连续): {e}")

                backoff_idx = min(self._consecutive_failures - 1,
                                  len(self._BACKOFF_STEPS) - 1)
                backoff_sec = min(self._BACKOFF_STEPS[backoff_idx] * self.interval,
                                  self._MAX_BACKOFF)
                self._stop_event.wait(backoff_sec)

        logger.info(f"[{self.name}] 线程停止 (采集{self._collect_count}次, 错误{self._error_count}次)")

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════
# 采集器管理器
# ══════════════════════════════════════════════════════════

class MootdxCollector:
    """mootdx 盘中数据采集器管理器

    管理 mootdx TCP 采集线程的启动/停止/状态查询。
    """

    def __init__(self):
        self._threads: list[_MootdxThread] = []
        self._started = False

    def start(self):
        """启动 mootdx 采集线程

        Returns:
            True 已启动, False 不可用
        """
        if self._started:
            logger.warning("MootdxCollector 已在运行，跳过")
            return True

        # 延迟初始化：仅当 mootdx 可用时启动
        client = _get_client()
        if client is None:
            logger.warning("mootdx 不可用，MootdxCollector 未启动")
            return False

        self._threads = [
            _MootdxThread('market_snapshot', 5, collect_market_snapshot, initial_delay=3),
        ]

        for t in self._threads:
            t.start()

        self._started = True
        logger.info(f"MootdxCollector 已启动 ({len(self._threads)} 线程, TCP 直连)")
        return True

    def stop(self):
        """停止所有采集线程"""
        # 252号方案：flush 未完成的分钟K线
        _flush_all_pending()
        for t in self._threads:
            t.stop()
        for t in self._threads:
            t.join(timeout=5)
        logger.info(f"MootdxCollector 已停止 ({len(self._threads)} 线程)")
        self._threads.clear()
        self._started = False

    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def get_stats(self) -> dict:
        stats = {'active': 0, 'total': len(self._threads)}
        for t in self._threads:
            stats[t.name] = {
                'alive': t.is_alive(),
                'collect_count': t._collect_count,
                'error_count': t._error_count,
            }
            if t.is_alive():
                stats['active'] += 1
        return stats


# ── 全局单例 ─────────────────────────────────────────────

mootdx_collector = MootdxCollector()
