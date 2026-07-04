"""
AkshareCollector — AKShare 盘中数据后台采集器
=============================================
独立的后台线程管理器，按固定频次采集 AKShare 数据并写入 DuckDB as_* 表。
所有模块通过 AkshareDataReader 读取，不直接调用本采集器。

设计原则：
- 5 个独立线程，互不等待
- 每个线程固定间隔轮询，间隔包含采集耗时
- 仅在 A 股交易时段运行（非交易日/非交易时段休眠）
- 采集失败记录日志，不影响其他线程
- 每轮采集完成后经由 WsBridge 通过 WebSocket 推送到前端

启动方式：
    from app.data.akshare_collector import akshare_collector
    akshare_collector.start()   # 应用启动时调用
    akshare_collector.stop()    # 应用关闭时调用
"""

import os
# 免发环境变量代理干扰：AKShare 直连东方财富 API，不走 HTTP_PROXY/ALL_PROXY
for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_k, None)

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


# ── DuckDB 写入代理（模块级单例，避免每次创建新连接） ────────────

_ecm_instance = None


def _get_ecm():
    """获取全局共享的 ECM 单例（复用 app.data.enhanced_cache_manager 全局单例）"""
    global _ecm_instance
    if _ecm_instance is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm_instance = get_ecm_instance()
    return _ecm_instance


# 盘中数据内存状态（优先写入，Flask 路由从此读取）
from app.data.in_memory_store import store as mem_store

# ── PostgreSQL 持久化写入（惰性单例，避免循环导入） ──────────

_pg_instance = None


def _get_pg():
    """获取 PostgreSQL 盘中实时写入单例"""
    global _pg_instance
    if _pg_instance is None:
        try:
            from app.data.realtime_pg import (
                upsert_snapshot, upsert_top_stocks, upsert_sectors,
                upsert_concepts, upsert_limit_pool, upsert_minute_kline,
                upsert_lhb, upsert_news,
            )
            _pg_instance = {
                'snapshot': upsert_snapshot,
                'top_stocks': upsert_top_stocks,
                'sectors': upsert_sectors,
                'concepts': upsert_concepts,
                'limit_pool': upsert_limit_pool,
                'minute_kline': upsert_minute_kline,
                'lhb': upsert_lhb,
                'news': upsert_news,
            }
        except Exception as e:
            logger.warning(f"realtime_pg 不可用（盘中数据不会写入 PG）: {e}")
            _pg_instance = {}
    return _pg_instance


# ── 交易时段判断 ─────────────────────────────────────────

def _is_trading_time() -> bool:
    """判断当前是否为 A 股交易时段"""
    try:
        from app.utils.trading_hours import is_trading_time
        return is_trading_time()
    except ImportError:
        # 交易时段判断不可用时默认返回 True（全天运行）
        return True


# ══════════════════════════════════════════════════════════
# 采集线程基类
# ══════════════════════════════════════════════════════════

class _CollectThread(threading.Thread):
    """采集线程基类 — 固定间隔轮询，仅在交易时段工作"""

    def __init__(self, name: str, interval_sec: int, collect_func,
                 check_trading_time: bool = True):
        super().__init__(name=name, daemon=True)
        self.interval = interval_sec
        self.collect = collect_func
        self.check_trading = check_trading_time
        self._stop_event = threading.Event()
        self._collect_count = 0
        self._error_count = 0

    def run(self):
        logger.info(f"[{self.name}] 线程启动，间隔={self.interval}s")
        # 首次采集前等待 5s，给系统初始化留时间
        time.sleep(5)
        while not self._stop_event.is_set():
            try:
                # 是否检查交易时段
                if self.check_trading and not _is_trading_time():
                    self._stop_event.wait(60)  # 非交易时段每分钟检查一次
                    continue

                # 执行采集
                t0 = time.time()
                self.collect()
                elapsed = time.time() - t0
                self._collect_count += 1
                logger.debug(f"[{self.name}] 采集完成 ({elapsed:.1f}s)")

                # 采集完成后通过 WebSocket 推送最新数据到前端
                try:
                    from app.data.ws_bridge import ws_bridge
                    ws_bridge.on_collect_complete(self.name)
                except Exception:
                    pass

                # 等待剩余间隔时间
                wait = max(1, self.interval - elapsed)
                self._stop_event.wait(wait)

            except Exception as e:
                self._error_count += 1
                logger.error(f"[{self.name}] 采集异常: {e}", exc_info=True)
                self._stop_event.wait(self.interval)  # 异常后等待一个完整间隔

        logger.info(f"[{self.name}] 线程停止 (采集{self._collect_count}次, 错误{self._error_count}次)")

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════
# 5 个采集线程的具体实现
# ══════════════════════════════════════════════════════════

def _collect_market_snapshot():
    """Thread 1: 全市场快照（覆盖式，15s）"""
    ak = _get_ak()
    if ak is None:
        return
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return
        records = []
        for _, row in df.iterrows():
            records.append({
                'ts_code': str(row.get('代码', '')),
                'name': str(row.get('名称', '')),
                'price': _safe_float(row.get('最新价', 0)),
                'change': _safe_float(row.get('涨跌额', 0)),
                'change_pct': _safe_float(row.get('涨跌幅', 0)),
                'open': _safe_float(row.get('今开', 0)),
                'high': _safe_float(row.get('最高', 0)),
                'low': _safe_float(row.get('最低', 0)),
                'prev_close': _safe_float(row.get('昨收', 0)),
                'volume': _safe_float(row.get('成交量', 0)),
                'amount': _safe_float(row.get('成交额', 0)),
                'turnover_rate': _safe_float(row.get('换手率', 0)),
                'pe': _safe_float(row.get('市盈率-动态', 0)),
                'pb': _safe_float(row.get('市净率', 0)),
                'amplitude': _safe_float(row.get('振幅', 0)),
                'circ_mv': _safe_float(row.get('流通市值', 0)),
                'total_mv': _safe_float(row.get('总市值', 0)),
                'volume_ratio': _safe_float(row.get('量比', 0)),
                'timestamp': datetime.now().isoformat(),
                'source': 'akshare_collector',
            })
        # 盘中：先写内存（主数据源）
        mem_store.update_snapshot(records)
        # 归档：再写 DuckDB（非阻塞，失败不影响）
        try:
            _get_ecm().write_as_market_snapshot(records)
        except Exception:
            pass
        # 持久化：再写 PostgreSQL（L2 持久，跨 worker 共享）
        pg = _get_pg()
        snapshot_fn = pg.get('snapshot')
        if snapshot_fn:
            try:
                snapshot_fn(records)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[market_snapshot] 采集失败: {e}")


def _collect_top_stocks():
    """Thread 2: 涨跌榜（覆盖式，30s）"""
    try:
        import requests
        for rank_type in ('up', 'down'):
            po = 1 if rank_type == 'up' else 0
            url = "https://82.push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": "1", "pz": "20",
                "po": str(po), "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2",
                "fid": "f3",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f2,f3,f4,f12,f14",
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('data', {}).get('diff', [])
            records = []
            for item in items:
                records.append({
                    'ts_code': str(item.get('f12', '')),
                    'name': str(item.get('f14', '')),
                    'price': round(float(item.get('f2', 0)), 2),
                    'change': _safe_float(item.get('f4', 0)),
                    'change_pct': _safe_float(item.get('f3', 0)),
                })
            # 盘中：先写内存
            mem_store.update_top_stocks(rank_type, records)
            # 归档：再写 DuckDB（非阻塞）
            try:
                _get_ecm().write_as_top_stocks(rank_type, records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            ts_fn = pg.get('top_stocks')
            if ts_fn:
                try:
                    ts_fn(rank_type, records)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[top_stocks] 采集失败: {e}")


def _collect_sector_and_limit():
    """Thread 3: 板块排行 + 涨跌停池（覆盖式，5min）"""
    ak = _get_ak()
    if ak is None:
        return

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
            # 盘中：先写内存
            mem_store.update_sectors(records)
            # 归档：再写 DuckDB
            try:
                _get_ecm().write_as_sector_ranking(records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            sec_fn = pg.get('sectors')
            if sec_fn:
                try:
                    sec_fn(records)
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
            # 盘中：先写内存
            mem_store.update_concepts(records)
            # 归档：再写 DuckDB
            try:
                _get_ecm().write_as_concept_ranking(records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            con_fn = pg.get('concepts')
            if con_fn:
                try:
                    con_fn(records)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[concept_ranking] 采集失败: {e}")

    # 涨停池 + 跌停池
    for limit_type, symbol in [('up', '涨停'), ('down', '跌停')]:
        try:
            df = ak.stock_zt_pool_em(symbol=symbol)
            if df is not None and not df.empty:
                records = []
                for _, row in df.iterrows():
                    records.append({
                        'ts_code': str(row.get('代码', '')),
                        'name': str(row.get('名称', '')),
                        'price': _safe_float(row.get('最新价', 0)),
                        'change_pct': _safe_float(row.get('涨跌幅', 0)),
                        'force_amount': _safe_float(row.get('封单资金', row.get('封单额', 0))),
                        'turn_over': _safe_float(row.get('换手率', row.get('换手', 0))),
                        'limit_count': int(row.get('封板次数', row.get('连板数', 1))),
                    })
                # 盘中：先写内存
                mem_store.update_limit_pool(limit_type, records)
                # 归档：再写 DuckDB
                try:
                    _get_ecm().write_as_limit_pool(records, limit_type)
                except Exception:
                    pass
                # 持久化：再写 PostgreSQL
                pg = _get_pg()
                lp_fn = pg.get('limit_pool')
                if lp_fn:
                    try:
                        lp_fn(records, limit_type)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[limit_pool:{limit_type}] 采集失败: {e}")


# 关注股票列表（盘前配置，盘中可动态更新）
_watchlist = []  # ['600519.SH', '000001.SZ', ...]
_watchlist_lock = threading.Lock()


def update_watchlist(ts_codes: list):
    """更新关注股票列表（供外部调用，如自选监控模块），线程安全"""
    global _watchlist
    with _watchlist_lock:
        _watchlist = list(ts_codes)
    logger.info(f"[watchlist] 已更新，共 {len(_watchlist)} 只")


def _collect_minute_kline():
    """Thread 4: 分钟K线（追加式，5min）"""
    ak = _get_ak()
    if ak is None:
        return
    with _watchlist_lock:
        watchlist_snapshot = list(_watchlist)
    if not watchlist_snapshot:
        return
    today = datetime.now().strftime('%Y-%m-%d')
    ecm = _get_ecm()
    for ts_code in watchlist_snapshot:
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
                    time_str = time_str[-5:]  # 确保 HH:MM 格式
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
            # 归档：再写 DuckDB（非阻塞）
            try:
                ecm.append_as_minute_kline(records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            mk_fn = pg.get('minute_kline')
            if mk_fn:
                try:
                    mk_fn(records)
                except Exception:
                    pass
            logger.debug(f"[minute_kline] {ts_code}: {len(records)} 条追加")
            time.sleep(0.1)  # 轻微节流避免触发频次限制
        except Exception as e:
            logger.debug(f"[minute_kline] {ts_code} 跳过: {e}")


def _collect_lhb_and_news():
    """Thread 5: 龙虎榜 + 新闻（覆盖式，30min）"""
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
            # 盘中：先写内存
            mem_store.update_lhb(records)
            # 归档：再写 DuckDB
            try:
                ecm.write_as_lhb_detail(records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            lhb_fn = pg.get('lhb')
            if lhb_fn:
                try:
                    lhb_fn(records)
                except Exception:
                    pass
            logger.info(f"[lhb_detail] {len(records)} 条")
    except Exception as e:
        logger.warning(f"[lhb_detail] 采集失败: {e}")

    # 新闻（用标题hash作为id去重）
    try:
        df = ak.stock_news_em()
        if df is not None and not df.empty:
            records = []
            seen_ids = set()
            for _, row in df.iterrows():
                title = str(row.get('新闻标题', ''))
                # 用标题哈希作为稳定 ID 以避免跨周期覆盖
                import hashlib
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
            # 盘中：先写内存
            mem_store.update_news(records)
            # 归档：再写 DuckDB
            try:
                ecm.write_as_news(records)
            except Exception:
                pass
            # 持久化：再写 PostgreSQL
            pg = _get_pg()
            news_fn = pg.get('news')
            if news_fn:
                try:
                    news_fn(records)
                except Exception:
                    pass
            logger.info(f"[news] {len(records)} 条")
    except Exception as e:
        logger.warning(f"[news] 采集失败: {e}")


# ══════════════════════════════════════════════════════════
# Collector 管理器
# ══════════════════════════════════════════════════════════

class AkshareCollector:
    """AKShare 盘中数据采集器管理器

    管理 5 个独立采集线程的启动/停止/状态查询。
    应用启动时调用 start()，关闭时调用 stop()。
    """

    def __init__(self):
        self._threads: list[_CollectThread] = []

    def start(self):
        """启动所有采集线程"""
        if self._threads:
            logger.warning("采集器已在运行，先 stop() 再重启")
            return

        self._threads = [
            _CollectThread('market_snapshot', 15, _collect_market_snapshot),
            _CollectThread('top_stocks', 30, _collect_top_stocks),
            _CollectThread('sector_and_limit', 300, _collect_sector_and_limit),
            _CollectThread('minute_kline', 300, _collect_minute_kline),
            _CollectThread('lhb_and_news', 1800, _collect_lhb_and_news),
        ]

        for t in self._threads:
            t.start()

        logger.info(f"AkshareCollector 已启动 ({len(self._threads)} 线程)")

    def stop(self):
        """停止所有采集线程"""
        for t in self._threads:
            t.stop()
        for t in self._threads:
            t.join(timeout=5)
        logger.info(f"AkshareCollector 已停止 ({len(self._threads)} 线程)")
        self._threads = []

    def is_running(self) -> bool:
        """是否有线程在运行"""
        return any(t.is_alive() for t in self._threads)

    def get_stats(self) -> dict:
        """获取采集统计"""
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


# ── 工具函数 ─────────────────────────────────────────────

def _safe_float(val) -> float:
    """安全转 float，失败返回 0.0"""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ── 全局单例 ─────────────────────────────────────────────

akshare_collector = AkshareCollector()
