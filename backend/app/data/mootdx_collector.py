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
from typing import Dict, List

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
        except NotImplementedError:
            logger.warning("mootdx Quotes.factory() 不支持当前协议版本（协议可能已变更）")
            return None
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


# ── D3: 盘中实时字段计算 ─────────────────────────────────

def _calc_commission(row) -> float:
    """从五档盘口计算委比 (%)"""
    bid_sum = sum(
        int(_safe_float(row.get(f'bid_vol{i}', 0)))
        for i in range(1, 6)
    )
    ask_sum = sum(
        int(_safe_float(row.get(f'ask_vol{i}', 0)))
        for i in range(1, 6)
    )
    total = bid_sum + ask_sum
    if total == 0:
        return 0.0
    return round((bid_sum - ask_sum) / total * 100, 2)


def _calc_speed(code: str, price: float) -> float:
    """计算涨速 (%) — 基于相邻两次采集的价格变化"""
    global _prev_prices
    prev = _prev_prices.get(code, 0.0)
    _prev_prices[code] = price
    if prev == 0 or price == 0:
        return 0.0
    return round((price - prev) / prev * 100, 2)


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
# D3: 上一轮采集价格，用于计算涨速（盘后重置）
_prev_prices: Dict[str, float] = {}


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
    """获取所有 A 股代码列表（沪深主板/中小板/创业板/科创板）"""
    name_map = _refresh_stock_name_map()
    return [
        c for c in name_map
        if isinstance(c, str) and len(c) == 6 and c[0] in ('0', '2', '3', '6')
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
    """全市场快照采集（东财 HTTP 主源，Sina/Tencent 降级）

    mootdx TCP 协议自 2026-07-20 起因通达信服务端更新而断裂，
    quotes() 返回空。按 289号方案，实时快照改用以下优先级：
      东财 HTTP (主) → 新浪 HTTP (备1) → 腾讯 HTTP (备2)

    Returns:
        采集的有效股票数量
    """
    # mootdx quotes() 已断裂，快照直接走 HTTP 降级（东财主源 → 新浪 → 腾讯）
    return _collect_dual_source_fallback()


# ══════════════════════════════════════════════════════════
# 双源热备 HTTP 实时行情降级（东财主 + Sina备 + Tencent备）
# ══════════════════════════════════════════════════════════

# ── 源健康统计 ──
_source_stats = {
    'mootdx':  {'ok': 0, 'fail': 0},
    'eastmoney': {'ok': 0, 'fail': 0},
    'sina':    {'ok': 0, 'fail': 0},
    'tencent': {'ok': 0, 'fail': 0},
}
_active_source = 'eastmoney'  # 当前活跃源


def get_source_stats() -> dict:
    """返回采集源健康统计（供健康检查端点使用）"""
    global _active_source
    rates = {}
    for name, st in _source_stats.items():
        total = st['ok'] + st['fail']
        rates[name] = {
            'ok': st['ok'],
            'fail': st['fail'],
            'rate': f'{st["ok"] / total * 100:.1f}%' if total > 0 else 'N/A',
        }
    return {
        'active_source': _active_source,
        'sources': rates,
    }


def _record_source_result(source: str, success: bool):
    """记录单次采集结果到统计"""
    global _source_stats
    _source_stats.setdefault(source, {'ok': 0, 'fail': 0})
    if success:
        _source_stats[source]['ok'] += 1
    else:
        _source_stats[source]['fail'] += 1


# ── 双源热备管理器 ─────────────────────────────────────


class _SnapshotSourceManager:
    """三源热备管理器：东财主 / Sina备 / Tencent备，自动切换与恢复探测"""

    FAILOVER_THRESHOLD = 3    # 主源连续失败 N 次后切换到备用源
    RECOVERY_THRESHOLD = 2    # 备用源连续成功 N 次后更新主源（更稳定者上位）
    RECOVERY_PROBE_INTERVAL = 10  # 降级到备用源后，每 N 次周期探测一次东财是否恢复

    def __init__(self):
        self._primary = 'eastmoney'  # 东财主源，Sina/Tencent 备源
        self._consecutive_failures = 0
        self._recovery_successes = 0
        self._backup_streak = 0       # 备用源连续成功次数（用于周期探测东财）

    @property
    def active_source(self) -> str:
        return self._primary

    def fetch(self, codes: list, name_map: dict) -> list:
        """按主备顺序获取行情，返回 records 列表（空列表=双源均失败）
        
        自动恢复策略：
        - 降级到备用源后，每 RECOVERY_PROBE_INTERVAL 次成功采集，
          主动探测东财一次，恢复后自动切回。
        """
        global _active_source

        # Phase 1: 主源（降级后周期探测东财恢复）
        probe_source = self._primary
        if self._primary != 'eastmoney':
            self._backup_streak += 1
            if self._backup_streak >= self.RECOVERY_PROBE_INTERVAL:
                probe_source = 'eastmoney'  # 周期探测东财

        result = self._fetch_source(probe_source, codes, name_map)
        if result:
            _record_source_result(probe_source, True)
            self._consecutive_failures = 0
            self._recovery_successes = 0
            if probe_source == 'eastmoney' and self._primary != 'eastmoney':
                # 东财已恢复，切回主源
                self._primary = 'eastmoney'
                self._backup_streak = 0
                _active_source = 'eastmoney'
                return result
            if probe_source == self._primary:
                self._backup_streak = 0
                _active_source = self._primary
                return result
            # 探测到东财恢复 → 上面已处理；探测但东财非当前主源且返回了数据→继续用当前主源
            self._backup_streak = 0
            _active_source = self._primary
            return result

        _record_source_result(probe_source, False)
        self._consecutive_failures += 1

        # Phase 2: 备用源（主源失败时自动尝试）
        backup = 'tencent' if self._primary == 'sina' else 'sina'
        result = self._fetch_source(backup, codes, name_map)
        if result:
            _record_source_result(backup, True)
            self._recovery_successes += 1
            _active_source = backup

            # 备用源连续成功后切换主源（更稳定者上位）
            if self._recovery_successes >= self.RECOVERY_THRESHOLD:
                self._primary = backup
                self._consecutive_failures = 0
                self._recovery_successes = 0
                self._backup_streak = 0
            return result

        _record_source_result(backup, False)
        self._recovery_successes = 0
        return []

    def _fetch_source(self, source: str, codes: list, name_map: dict) -> list:
        if source == 'eastmoney':
            return _fetch_eastmoney(codes, name_map)
        if source == 'sina':
            return _fetch_sina(codes, name_map)
        return _fetch_tencent(codes, name_map)


# ── Sina 解析器 ─────────────────────────────────────────


def _fetch_sina(codes: list, name_map: dict) -> list:
    """从 hq.sinajs.cn 获取实时行情（并行4线程，全量覆盖）

    旧版限 `min(len(codes), 2000)` 导致 SH 代码（索引 12000+）永不触达。
    改为并行全量：147 批 × 4 线程 ≈ 3-5s 覆盖全部 A 股。
    """
    import urllib.request
    import concurrent.futures
    all_records = []
    batch_size = 100
    max_workers = 4

    def _fetch_one(batch: list) -> list:
        sina_codes = [f"{'sh' if c.startswith(('6','9')) else 'sz'}{c}" for c in batch]
        url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
        req = urllib.request.Request(url, headers={
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        })
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode('gbk')
        except Exception:
            return []
        records = []
        for line in raw.strip().split('\n'):
            if not line.strip():
                continue
            try:
                parts = line.split('="')
                if len(parts) < 2:
                    continue
                values = parts[1].rstrip('";').split(',')
                if len(values) < 32:
                    continue
                code_str = parts[0].split('_')[-1] if '_' in parts[0] else ''
                code = code_str[2:] if code_str.startswith(('sh', 'sz')) else code_str
                name = values[0]
                open_p = _safe_float(values[1])
                close_p = _safe_float(values[2])
                price = _safe_float(values[3])
                if price == 0 or close_p == 0:
                    continue
                market = 0 if code.startswith(('6', '9')) else 1
                ts_code = f'{code}.SH' if market == 0 else f'{code}.SZ'
                change = round(price - close_p, 2)
                change_pct = round(change / close_p * 100, 2) if close_p else 0.0
                records.append({
                    'ts_code': ts_code, 'code': code,
                    'name': name_map.get(code, name),
                    'price': price, 'change': change, 'change_pct': change_pct,
                    'open': open_p, 'high': _safe_float(values[4]),
                    'low': _safe_float(values[5]), 'prev_close': close_p,
                    'volume': int(_safe_float(values[8]) * 100) if _safe_float(values[8]) else 0,
                    'amount': _safe_float(values[9]),
                    'bid1': 0.0, 'ask1': 0.0, 'bid_vol1': 0, 'ask_vol1': 0,
                    'bid2': 0.0, 'ask2': 0.0, 'bid_vol2': 0, 'ask_vol2': 0,
                    'bid3': 0.0, 'ask3': 0.0, 'bid_vol3': 0, 'ask_vol3': 0,
                    'bid4': 0.0, 'ask4': 0.0, 'bid_vol4': 0, 'ask_vol4': 0,
                    'bid5': 0.0, 'ask5': 0.0, 'bid_vol5': 0, 'ask_vol5': 0,
                    'commission': 0.0, 'speed': 0.0,
                    'timestamp': datetime.now().isoformat(),
                    'source': 'sina',
                })
            except Exception:
                continue
        return records

    # 全量分批并行（不限2000，覆盖SH 2311只）
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_one, b) for b in batches]
        for f in concurrent.futures.as_completed(futures):
            try:
                result = f.result()
                if result:
                    all_records.extend(result)
            except Exception:
                continue
    return all_records


# ── Tencent 解析器 ──────────────────────────────────────


def _fetch_tencent(codes: list, name_map: dict) -> list:
    """从 qt.gtimg.cn 获取实时行情（含完整五档盘口）

    Tencent 格式:
      v_sh600519="1~贵州茅台~600519~30.88~30.72~30.90~...~date;time"

    字段位置:
      3=当前价, 4=昨收, 5=今开, 6=成交量(手), 7=成交额
      8=买一量, 9=买一价, 10=买二量, 11=买二价, ...(至买五)
      20=卖一量, 21=卖一价, 22=卖二量, 23=卖二价, ...(至卖五)
      33=最高, 34=最低
    """
    import urllib.request
    all_records = []
    batch_size = 100

    for batch_start in range(0, min(len(codes), 2000), batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        tencent_codes = []
        for c in batch:
            m = 0 if c.startswith(('6', '9')) else 1
            prefix = 'sh' if m == 0 else 'sz'
            tencent_codes.append(f'{prefix}{c}')

        url = 'https://qt.gtimg.cn/q=' + ','.join(tencent_codes)
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
        })
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode('gbk')
        except Exception:
            continue

        for line in raw.strip().split('\n'):
            if not line.strip():
                continue
            try:
                eq_pos = line.index('="')
                values = line[eq_pos + 2:line.rindex('";')].split('~')
                if len(values) < 40:
                    continue

                code_str = line.split('=')[0].lstrip('v_')
                code = code_str[2:]
                price = _safe_float(values[3])
                close_p = _safe_float(values[4])
                if price == 0 or close_p == 0:
                    continue

                market = 0 if code.startswith(('6', '9')) else 1
                ts_code = f'{code}.SH' if market == 0 else f'{code}.SZ'
                change = round(price - close_p, 2)
                change_pct = round(change / close_p * 100, 2) if close_p else 0.0

                record = {
                    'ts_code': ts_code, 'code': code,
                    'name': name_map.get(code, values[1]),
                    'price': price, 'change': change, 'change_pct': change_pct,
                    'open': _safe_float(values[5]),
                    'high': _safe_float(values[33]),
                    'low': _safe_float(values[34]),
                    'prev_close': close_p,
                    'volume': int(_safe_float(values[6]) * 100),
                    'amount': _safe_float(values[7]),
                    # 五档盘口：(量,价) 交替
                    'bid1': _safe_float(values[9]),
                    'bid_vol1': int(_safe_float(values[8])),
                    'ask1': _safe_float(values[21]),
                    'ask_vol1': int(_safe_float(values[20])),
                    'bid2': _safe_float(values[11]),
                    'bid_vol2': int(_safe_float(values[10])),
                    'ask2': _safe_float(values[23]),
                    'ask_vol2': int(_safe_float(values[22])),
                    'bid3': _safe_float(values[13]),
                    'bid_vol3': int(_safe_float(values[12])),
                    'ask3': _safe_float(values[25]),
                    'ask_vol3': int(_safe_float(values[24])),
                    'bid4': _safe_float(values[15]),
                    'bid_vol4': int(_safe_float(values[14])),
                    'ask4': _safe_float(values[27]),
                    'ask_vol4': int(_safe_float(values[26])),
                    'bid5': _safe_float(values[17]),
                    'bid_vol5': int(_safe_float(values[16])),
                    'ask5': _safe_float(values[29]),
                    'ask_vol5': int(_safe_float(values[28])),
                    # 委比 = (∑买量-∑卖量)/(∑买量+∑卖量)*100
                    'commission': 0.0, 'speed': 0.0,
                    'timestamp': datetime.now().isoformat(),
                    'source': 'tencent',
                }
                all_records.append(record)
            except Exception:
                continue

    return all_records


# ── East Money 解析器（289号方案：主源替代 mootdx） ──────


def _fetch_eastmoney(codes: list, name_map: dict) -> list:
    """从 push2.eastmoney.com 获取实时行情（主源）

    使用 ulist.np 批量端点，fltt=2 自动缩放，60只/批，
    并行4线程采集，全市场5000只约5s（经289号方案实测验证）。

    东财字段 → 内部标准字段:
      f2=price, f3=change_pct, f4=change, f5=volume(手),
      f6=amount, f12=6位代码, f14=name,
      f15=high, f16=low, f17=open, f18=prev_close,
      f20=总市值, f21=流通市值, f57=ts_code, f60=昨收
    """
    import concurrent.futures
    import json
    import urllib.request

    all_records = []
    batch_size = 60
    max_workers = 4
    field_str = 'f2,f3,f4,f5,f6,f7,f10,f12,f14,f15,f16,f17,f18,f20,f21,f57,f60'

    def _fetch_batch(code_batch: list) -> list:
        secids = ','.join(
            f"1.{c}" if c.startswith(('6', '9')) else f"0.{c}"
            for c in code_batch
        )
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&fields={field_str}&secids={secids}")
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://www.eastmoney.com/',
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8')
                data = json.loads(raw)
                diff = data.get('data', {}).get('diff', [])
        except Exception:
            return []

        records = []
        for s in diff:
            if not s or not s.get('f12'):
                continue
            code = str(s.get('f12', ''))
            price = _safe_float(s.get('f2'))
            prev_close = _safe_float(s.get('f18'))
            if price == 0 or prev_close == 0:
                continue

            change = round(price - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
            market = 0 if code.startswith(('6', '9')) else 1
            ts_code = f'{code}.SH' if market == 0 else f'{code}.SZ'

            records.append({
                'ts_code': ts_code,
                'code': code,
                'name': s.get('f14', '') or name_map.get(code, ''),
                'price': price,
                'change': change,
                'change_pct': change_pct,
                'open': _safe_float(s.get('f17')),
                'high': _safe_float(s.get('f15')),
                'low': _safe_float(s.get('f16')),
                'prev_close': prev_close,
                'volume': int(_safe_float(s.get('f5', 0))),
                'amount': _safe_float(s.get('f6')),
                'bid1': 0.0, 'ask1': 0.0,
                'bid_vol1': 0, 'ask_vol1': 0,
                'bid2': 0.0, 'ask2': 0.0,
                'bid_vol2': 0, 'ask_vol2': 0,
                'bid3': 0.0, 'ask3': 0.0,
                'bid_vol3': 0, 'ask_vol3': 0,
                'bid4': 0.0, 'ask4': 0.0,
                'bid_vol4': 0, 'ask_vol4': 0,
                'bid5': 0.0, 'ask5': 0.0,
                'bid_vol5': 0, 'ask_vol5': 0,
                'commission': 0.0,
                'speed': _calc_speed(code, price),
                'timestamp': datetime.now().isoformat(),
                'source': 'eastmoney',
            })
        return records

    # 分批并行采集
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_batch, b) for b in batches]
        for f in concurrent.futures.as_completed(futures):
            try:
                result = f.result()
                if result:
                    all_records.extend(result)
            except Exception:
                continue

    return all_records


# ── 双源热备采集入口 ─────────────────────────────────────


_http_source_mgr = _SnapshotSourceManager()


def _collect_dual_source_fallback() -> int:
    """HTTP 双源热备采集：Sina 主 / Tencent 备，自动切换

    由 collect_market_snapshot() 在 mootdx 不可用时调用。
    将采集结果写入 InMemoryStateStore 并计算涨跌榜/涨跌停池。
    """
    from app.data.in_memory_store import store as mem_store

    codes = _get_a_share_codes()
    if not codes:
        return 0

    t_start = time.time()
    name_map = _stock_name_map

    all_records = _http_source_mgr.fetch(codes, name_map)
    if not all_records:
        return 0

    elapsed = time.time() - t_start
    source = _http_source_mgr.active_source

    mem_store.update_snapshot(all_records)
    _compute_top_stocks(all_records)
    _compute_limit_pools(all_records)

    # 分钟K线聚合（从5s快照自聚合1min OHLC，写入ECM持久化）
    try:
        _feed_minute_aggregator(all_records)
    except Exception as e:
        logger.debug(f"[{source}] 分钟聚合异常（非关键）: {e}")

    # 持久化到 ECM market_snapshot.db（供 API 进程读取）
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        ecm.cache_market_snapshot_data(all_records)
    except Exception:
        logger.debug("[http] 快照数据库写入失败（非关键）")

    logger.info(f"[{source}] 实时行情降级完成: {len(all_records)} 只 ({elapsed:.1f}s)")
    return len(all_records)


# ── 分钟K线全覆盖采集 ─────────────────────────────────────

def collect_minute_full() -> int:
    """全市场分钟K线补齐（使用 mootdx minutes() API）

    quotes() 只返回有交易活动的股票(price≠0)，冷门股无数据。
    本函数用 minutes() 对缺失股票逐一补采 minutes tick 数据，
    转换为 1min OHLC 写入 ECM minute_kline_cache。

    运行频率：每 5 分钟 (300s)，每次限 200 只避免耗时过长。
    """
    client = _get_client()
    if client is None:
        return 0

    today = datetime.now().strftime('%Y-%m-%d')
    trade_date = datetime.now().strftime('%Y%m%d')
    codes = _get_a_share_codes()
    if not codes:
        return 0

    # 查询已有分钟数据的股票
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        minute_df = ecm.get_cached_minute_kline(trade_date=today)
        if minute_df is not None and not minute_df.empty:
            existing = set(minute_df['ts_code'].unique())
        else:
            existing = set()
    except Exception:
        existing = set()

    # 计算缺失股票，限 200 只
    missing = [c for c in codes if c not in existing][:200]
    if not missing:
        return 0

    total_ok = 0
    for code in missing:
        try:
            raw = client.minutes(symbol=code, dest='/tmp/min_backfill')
            if raw is None or raw.empty:
                continue
            # minutes 返回 price/vol/volume，构建 1min OHLC
            rows = []
            prev_price = None
            for _, r in raw.iterrows():
                price = float(r.get('price', 0))
                vol_val = int(r.get('vol', 0))
                if price == 0:
                    continue
                # 取 trade_time（分钟索引从 9:30 开始）
                idx = len(rows)
                hour = 9 + (idx + 30) // 60
                minute = (idx + 30) % 60
                trade_time = f"{today} {hour:02d}:{minute:02d}:00"
                # high/low 近似：从价格变动范围估算 ±0.1%
                spread = price * 0.001
                open_price = prev_price if prev_price else price
                high_price = max(price, open_price) + spread
                low_price = min(price, open_price) - spread
                rows.append({
                    'ts_code': code,
                    'trade_date': today,
                    'trade_time': trade_time,
                    'freq': '1min',
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(max(low_price, 0.01), 2),
                    'close': round(price, 2),
                    'volume': vol_val,
                    'amount': round(price * vol_val, 2),
                })
                prev_price = price

            if rows:
                import pandas as pd
                ecm._insert_from_df('minute_kline_cache', pd.DataFrame(rows))
                total_ok += 1

        except Exception as e:
            logger.debug(f"[minutes补齐] {code} 失败: {e}")
            continue

    if total_ok:
        logger.info(f"[minutes补齐] 完成: {total_ok} 只")
    return total_ok


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

        try:
            logger.info(f"[{self.name}] 线程停止 (采集{self._collect_count}次, 错误{self._error_count}次)")
        except ValueError:
            pass  # atexit 时 logger stream 已不可用

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

        # mootdx 不再作为快照采集的必需条件（289号：通达信协议断裂，改用东财HTTP）
        # 分钟数据仍尝试使用 mootdx（minutes() 尚可用）
        client = _get_client()
        if client is None:
            logger.info("mootdx 客户端不可用，快照使用 HTTP 降级（东财/新浪/腾讯）")
        else:
            logger.info("mootdx 客户端可用（stocks OK），分钟数据继续使用 mootdx")

        # 快照线程始终启动（走 HTTP 降级链：东财 → 新浪 → 腾讯）
        self._threads = [
            _MootdxThread('market_snapshot', 5, collect_market_snapshot, initial_delay=3),
        ]

        # 分钟数据线程：仅 mootdx 可用时启动（minutes() 尚可用）
        if client is not None:
            self._threads.append(
                _MootdxThread('minute_full', 300, collect_minute_full, initial_delay=60,
                              check_trading_time=False),
            )

        for t in self._threads:
            t.start()

        self._started = True
        if client is not None:
            logger.info(
                f"MootdxCollector 已启动 ({len(self._threads)} 线程, "
                "快照:东财HTTP, 分钟:mootdx)"
            )
        else:
            logger.info("MootdxCollector 已启动（降级模式, 快照:东财HTTP, 分钟:跳过）")
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
