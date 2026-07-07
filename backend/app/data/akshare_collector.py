"""
AkshareCollector — AKShare 盘中数据低频补充采集器（248号方案瘦身版）
=============================================================
L1 实时行情/涨跌榜/涨跌停池已由 mootdx_collector.py TCP 直连替代。
本采集器仅保留 AKShare 特有且 mootdx 不提供的数据：
  - Thread 3: 行业板块排行 + 概念板块排行 (30min)
  - Thread 4: 分钟 K 线 (5min, 自选股)
  - Thread 5: 龙虎榜 + 新闻 (30min)

设计原则：
  - 3 个独立线程，互不等待
  - 仅在 A 股交易时段运行
  - 采集结果写入 InMemoryStateStore（与 mootdx 共享）
  - 写入 DuckDB as_* 表归档（保留历史）
  - 每轮采集完成后经由 WsBridge 推送

启动方式：
    from app.data.akshare_collector import akshare_collector
    akshare_collector.start()
    akshare_collector.stop()
"""

import os
# 免发环境变量代理干扰
for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_k, None)
_no_proxy_domains = 'eastmoney.com,push2.eastmoney.com,em.com'
os.environ.setdefault('NO_PROXY', _no_proxy_domains)
os.environ.setdefault('no_proxy', _no_proxy_domains)

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── AKShare 惰性导入 ──────────────────────────────────────

_ak = None


def _get_ak():
    global _ak
    if _ak is None:
        try:
            import akshare as ak
            _ak = ak
        except ImportError:
            logger.warning("akshare 未安装，采集器无法启动")
            return None
    return _ak


# ── DuckDB ECM 单例 ───────────────────────────────────────

_ecm_instance = None


def _get_ecm():
    global _ecm_instance
    if _ecm_instance is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm_instance = get_ecm_instance()
    return _ecm_instance


# 盘中数据内存状态（与 mootdx 共享）
from app.data.in_memory_store import store as mem_store


# ── 分钟 K 线关注列表 ─────────────────────────────────────

_minute_watchlist: list = []
_minute_watchlist_lock = threading.Lock()


def update_watchlist(ts_codes: list):
    """更新分钟 K 线关注列表（外部调用，如自选监控模块）"""
    global _minute_watchlist
    with _minute_watchlist_lock:
        _minute_watchlist = list(ts_codes)
    logger.info(f"[watchlist] 已更新，共 {len(_minute_watchlist)} 只")


# ── 交易时段判断 ─────────────────────────────────────────

def _is_trading_time() -> bool:
    try:
        from app.utils.trading_hours import is_trading_time
        return is_trading_time()
    except ImportError:
        return True


# ══════════════════════════════════════════════════════════
# 采集线程基类
# ══════════════════════════════════════════════════════════

class _CollectThread(threading.Thread):
    """采集线程基类 — 固定间隔轮询，仅在交易时段工作"""

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
        self._last_logged_failure = 0
        self._initial_delay = initial_delay

    def run(self):
        logger.info(f"[{self.name}] 线程启动，间隔={self.interval}s，初始延迟={self._initial_delay}s")
        time.sleep(self._initial_delay)
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
                logger.debug(f"[{self.name}] 采集完成 ({elapsed:.1f}s)")

                try:
                    from app.data.ws_bridge import ws_bridge
                    ws_bridge.on_collect_complete(self.name)
                except Exception:
                    pass

                wait = max(1, self.interval - elapsed)
                self._stop_event.wait(wait)

            except Exception as e:
                self._error_count += 1
                self._consecutive_failures += 1
                self._log_error_throttled(e)
                backoff_idx = min(self._consecutive_failures - 1,
                                  len(self._BACKOFF_STEPS) - 1)
                backoff_sec = min(self._BACKOFF_STEPS[backoff_idx] * self.interval,
                                  self._MAX_BACKOFF)
                self._stop_event.wait(backoff_sec)

        logger.info(f"[{self.name}] 线程停止 (采集{self._collect_count}次, 错误{self._error_count}次)")

    def _log_error_throttled(self, e):
        n = self._consecutive_failures
        if n <= 3 or n == 10 or n == 100 or n % 100 == 0:
            logger.warning(f"[{self.name}] 采集失败(第{n}次连续): {e}")
            self._last_logged_failure = n
        elif n == self._last_logged_failure + 1 and n <= 5:
            logger.warning(f"[{self.name}] 采集失败: {e}")
            self._last_logged_failure = n
        else:
            logger.debug(f"[{self.name}] 采集失败(第{n}次连续): {e}")

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════
# 3 个采集线程的具体实现
# ══════════════════════════════════════════════════════════

def _collect_sector_and_limit():
    """Thread 3: 行业板块排行 + 概念板块排行（覆盖式，30min，通过 AKShare）

    涨跌停池已由 mootdx_collector 从全量快照自算，本函数不再采集。
    """
    ak = _get_ak()
    if ak is None:
        return

    ecm = _get_ecm()

    # 行业板块排行
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            records = []
            for rank, (_, row) in enumerate(df.iterrows(), 1):
                records.append({
                    'sector_code': str(row.get('板块代码', '')),
                    'sector_name': str(row.get('板块名称', '')),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'price': _safe_float(row.get('最新价', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'up_count': int(row.get('上涨家数', 0)),
                    'down_count': int(row.get('下跌家数', 0)),
                    'rank': rank,
                })
            mem_store.update_sectors(records)
            try:
                ecm.write_as_sector_ranking(records)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[sector_ranking] 采集失败: {e}")

    # 概念板块排行
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty:
            records = []
            for rank, (_, row) in enumerate(df.iterrows(), 1):
                records.append({
                    'concept_code': str(row.get('板块代码', '')),
                    'concept_name': str(row.get('板块名称', '')),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'price': _safe_float(row.get('最新价', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'up_count': int(row.get('上涨家数', 0)),
                    'down_count': int(row.get('下跌家数', 0)),
                    'rank': rank,
                })
            mem_store.update_concepts(records)
            try:
                ecm.write_as_concept_ranking(records)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[concept_ranking] 采集失败: {e}")


def _collect_minute_kline():
    """Thread 4: 分钟K线（追加式，5min，通过 AKShare）"""
    ak = _get_ak()
    if ak is None:
        return

    with _minute_watchlist_lock:
        watchlist = list(_minute_watchlist)
    if not watchlist:
        return

    today = datetime.now().strftime('%Y-%m-%d')
    ecm = _get_ecm()
    for ts_code in watchlist:
        try:
            from app.data.akshare_provider import _parse_ts_code
            symbol, _, _ = _parse_ts_code(ts_code)
            df = ak.stock_zh_a_hist_min_em(symbol=symbol, period='5min',
                                            start_date=today, end_date=today)
            if df is None or df.empty:
                continue
            records = []
            for _, row in df.iterrows():
                time_str = str(row.get('时间', ''))
                if len(time_str) >= 5:
                    time_str = time_str[-5:]
                records.append({
                    'ts_code': ts_code,
                    'trade_date': today,
                    'trade_time': time_str,
                    'freq': '5min',
                    'open': _safe_float(row.get('开盘', 0)),
                    'high': _safe_float(row.get('最高', 0)),
                    'low': _safe_float(row.get('最低', 0)),
                    'close': _safe_float(row.get('收盘', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                })
            mem_store.append_minute_kline(records)
            try:
                ecm.append_as_minute_kline(records)
            except Exception:
                pass
            logger.debug(f"[minute_kline] {ts_code}: {len(records)} 条")
            time.sleep(0.1)
        except Exception as e:
            logger.debug(f"[minute_kline] {ts_code} 跳过: {e}")


def _collect_lhb_and_news():
    """Thread 5: 龙虎榜 + 新闻（覆盖式，30min，通过 AKShare）"""
    ak = _get_ak()
    if ak is None:
        return

    ecm = _get_ecm()

    # 龙虎榜
    try:
        today = datetime.now().strftime('%Y%m%d')
        df = ak.stock_lhb_detail_em(start_date=today, end_date=today)
        if df is not None and not df.empty:
            records = []
            for _, row in df.iterrows():
                records.append({
                    'ts_code': str(row.get('代码', '')),
                    'trade_date': today,
                    'name': str(row.get('名称', '')),
                    'reason_category': str(row.get('上榜原因', '')),
                    'total_amount': _safe_float(row.get('龙虎榜成交额', 0)),
                    'net_amount': _safe_float(row.get('龙虎榜净买额', 0)),
                    'buy_amount': _safe_float(row.get('龙虎榜买入额', 0)),
                    'sell_amount': _safe_float(row.get('龙虎榜卖出额', 0)),
                })
            mem_store.update_lhb(records)
            try:
                ecm.write_as_lhb_detail(records)
            except Exception:
                pass
            logger.info(f"[lhb_detail] {len(records)} 条")
    except Exception as e:
        logger.warning(f"[lhb_detail] 采集失败: {e}")

    # 新闻（用标题hash去重）
    try:
        df = ak.stock_news_em()
        if df is not None and not df.empty:
            records = []
            seen_ids = set()
            import hashlib
            for _, row in df.iterrows():
                title = str(row.get('新闻标题', ''))
                h = int(hashlib.md5(title.encode('utf-8'), usedforsecurity=False).hexdigest()[:8], 16)
                if h in seen_ids:
                    continue
                seen_ids.add(h)
                records.append({
                    'id': h,
                    'ts_code': str(row.get('股票代码', '') or ''),
                    'title': title,
                    'content': str(row.get('新闻内容', '') or ''),
                    'publish_time': str(row.get('发布时间', '') or ''),
                    'source': str(row.get('文章来源', '') or 'akshare'),
                })
            mem_store.update_news(records)
            try:
                ecm.write_as_news(records)
            except Exception:
                pass
            logger.info(f"[news] {len(records)} 条")
    except Exception as e:
        logger.warning(f"[news] 采集失败: {e}")


# ══════════════════════════════════════════════════════════
# Collector 管理器
# ══════════════════════════════════════════════════════════

class AkshareCollector:
    """AKShare 盘中数据低频补充采集器管理器

    管理 3 个独立采集线程的启动/停止。
    L1 行情/涨跌榜/涨跌停池已由 mootdx_collector 替代。
    """

    def __init__(self):
        self._threads: list[_CollectThread] = []

    def start(self):
        if self._threads:
            logger.warning("采集器已在运行，先 stop() 再重启")
            return

        self._threads = [
            _CollectThread('sector_and_limit', 1800, _collect_sector_and_limit, initial_delay=15),
            _CollectThread('minute_kline', 300, _collect_minute_kline, initial_delay=20),
            _CollectThread('lhb_and_news', 1800, _collect_lhb_and_news, initial_delay=25),
        ]

        for t in self._threads:
            t.start()

        logger.info(f"AkshareCollector 已启动 ({len(self._threads)} 线程, 低频补充)")

    def stop(self):
        for t in self._threads:
            t.stop()
        for t in self._threads:
            t.join(timeout=5)
        logger.info(f"AkshareCollector 已停止 ({len(self._threads)} 线程)")
        self._threads = []

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

    def clear_watchlist(self):
        """清空分钟k线关注列表（盘后清理链调用）"""
        global _minute_watchlist
        with _minute_watchlist_lock:
            _minute_watchlist.clear()
        logger.debug("AkshareCollector 分钟关注列表已清空")


# ── 工具函数 ─────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ── 全局单例 ─────────────────────────────────────────────

akshare_collector = AkshareCollector()
