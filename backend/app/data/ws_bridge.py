"""
WsBridge — 采集器 → WebSocket 桥接器
====================================
在每个采集线程完成一轮采集后，从 InMemoryStateStore 读取最新数据，
通过 Flask-SocketIO 推送到对应房间。不阻塞采集器，不持有 DB 连接。

使用方式（在 akshare_collector.py 的 _CollectThread.run 中调用）：
    from app.data.ws_bridge import ws_bridge
    ws_bridge.on_collect_complete(self.name)

前端监听事件：
    market:summary      — 市场概况统计（涨跌比/总数）
    market:top_stocks   — 涨幅榜/跌幅榜 Top10
    market:sectors      — 板块排行 + 涨跌停池
    stock:quotes        — 自选股行情更新
    market:news         — 新闻头条

设计原则：
    - 所有 emit 通过 try/except 容错，不抛异常
    - 不持有 DuckDB / Redis 连接
    - 惰性导入 socketio 实例，避免循环依赖
"""

import logging
import threading
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


class WsBridge:
    """采集器 → WebSocket 桥接器"""

    def __init__(self):
        self._socketio = None
        self._store = None
        self._watchlist_codes: set = set()
        self._watchlist_lock = threading.Lock()

    # ── 惰性引用 ─────────────────────────────────────────────

    def _sio(self):
        if self._socketio is None:
            try:
                from app import socketio as sio
                self._socketio = sio
            except Exception as e:
                logger.debug(f"[WsBridge] socketio 引用失败: {e}")
                return None
        return self._socketio

    def _get_store(self):
        if self._store is None:
            try:
                from app.data.in_memory_store import store
                self._store = store
            except Exception as e:
                logger.debug(f"[WsBridge] InMemoryStateStore 引用失败: {e}")
                return None
        return self._store

    # ── 自选股推送管理 ─────────────────────────────────────

    def update_watchlist_codes(self, codes: List[str]):
        """注册需要实时推送的自选股代码（由 subscribe_watchlist 调用）"""
        with self._watchlist_lock:
            self._watchlist_codes.update(codes)

    def remove_watchlist_codes(self, codes: List[str]):
        """移除自选股代码推送"""
        with self._watchlist_lock:
            self._watchlist_codes.difference_update(codes)

    def clear_watchlist_codes(self):
        """清空全部自选股推送注册"""
        with self._watchlist_lock:
            self._watchlist_codes.clear()

    # ── 统一入口（由 _CollectThread.run 调用） ──────────────

    def on_collect_complete(self, thread_name: str):
        """采集线程完成后推送对应通知"""
        sio = self._sio()
        if sio is None:
            return  # SocketIO 未就绪，静默跳过

        if thread_name == 'market_snapshot':
            self._broadcast_market_summary(sio)
            self._broadcast_market_indices(sio)
            self._broadcast_watchlist_quotes(sio)

        elif thread_name == 'top_stocks':
            self._broadcast_top_stocks(sio)

        elif thread_name == 'sector_and_limit':
            self._broadcast_sectors(sio)

        elif thread_name == 'lhb_and_news':
            self._broadcast_news(sio)

        elif thread_name == 'minute_kline':
            pass  # 分钟K线数据量大，不主动推送，前端按需拉取

    # ── 具体推送方法 ─────────────────────────────────────────

    def _broadcast_market_summary(self, sio):
        """推送市场概况（涨跌比、总数）"""
        store = self._get_store()
        if store is None:
            return
        snapshot = store.get_snapshot()
        up = sum(1 for s in snapshot if s.get('change_pct', 0) > 0)
        down = sum(1 for s in snapshot if s.get('change_pct', 0) < 0)
        self._try_emit(sio, 'market:summary', {
            'total_count': len(snapshot),
            'up_ratio': round(up / max(len(snapshot), 1), 4),
            'up_count': up,
            'down_count': down,
            'flat_count': len(snapshot) - up - down,
            'timestamp': datetime.now().isoformat(),
        })

    def _broadcast_market_indices(self, sio):
        """推送四大指数实时行情（market:indices）

        从 InMemoryStateStore 快照中查找四大指数代码，提取实时行情。
        前端收到后更新 marketIndexes，与 REST /market/overview 互补。
        """
        store = self._get_store()
        if store is None:
            return
        # 四大指数的东方财富行情代码映射
        index_codes = {
            '1.000001': '上证指数',
            '0.399001': '深证成指',
            '0.399300': '沪深300',
            '1.000016': '上证50',
            '0.399006': '创业板指',
        }
        snapshot = store.get_snapshot()
        indices = []
        for s in snapshot:
            code = str(s.get('ts_code', ''))
            # 东方财富实时快照使用纯数字代码（无后缀）
            # 兼容 ts_code=000001.SH 或代码=1.000001
            short_code = code.split('.')[0]
            for ec_code, name in index_codes.items():
                ec_short = ec_code.split('.')[-1]
                if short_code == ec_short or code.startswith(ec_code):
                    indices.append({
                        'ts_code': code,
                        'name': name,
                        'price': float(s.get('price', 0)),
                        'change_pct': float(s.get('change_pct', 0)),
                        'change': float(s.get('change', 0)),
                    })
                    break
        if indices:
            self._try_emit(sio, 'market:indices', {
                'indices': indices,
                'timestamp': datetime.now().isoformat(),
            })

    def _broadcast_top_stocks(self, sio):
        """推送涨幅榜/跌幅榜 Top10"""
        store = self._get_store()
        if store is None:
            return
        self._try_emit(sio, 'market:top_stocks', {
            'up': store.get_top_stocks('up')[:10],
            'down': store.get_top_stocks('down')[:10],
            'timestamp': datetime.now().isoformat(),
        })

    def _broadcast_sectors(self, sio):
        """推送行业板块排行 + 涨跌停池"""
        store = self._get_store()
        if store is None:
            return
        self._try_emit(sio, 'market:sectors', {
            'sectors': store.get_sectors()[:20],
            'timestamp': datetime.now().isoformat(),
        })

    def _broadcast_limit_pools(self, sio):
        """推送涨跌停池"""
        store = self._get_store()
        if store is None:
            return
        pool = store.get_limit_pool('up')[:10], store.get_limit_pool('down')[:10]
        self._try_emit(sio, 'market:limit_pools', {
            'up': pool[0],
            'down': pool[1],
            'timestamp': datetime.now().isoformat(),
        })

    def _broadcast_news(self, sio):
        """推送新闻头条"""
        store = self._get_store()
        if store is None:
            return
        news = store.get_news()
        self._try_emit(sio, 'market:news', {
            'headlines': news[:5],
            'total': len(news),
            'timestamp': datetime.now().isoformat(),
        })

    def broadcast_quote_update(self, ts_codes: List[str]):
        """推送指定股票的行情更新（外部调用，如自选监控）"""
        sio = self._sio()
        store = self._get_store()
        if sio is None or store is None:
            return
        quotes = store.batch_get(ts_codes)
        if quotes:
            self._try_emit(sio, 'stock:quotes', {
                'quotes': quotes,
                'ts_codes': ts_codes,
                'timestamp': datetime.now().isoformat(),
            })

    def _broadcast_watchlist_quotes(self, sio):
        """推送自选股实时行情到 watchlist 房间（每5s采集后自动触发）"""
        store = self._get_store()
        if store is None:
            return
        with self._watchlist_lock:
            codes = list(self._watchlist_codes)
        if not codes:
            return
        quotes = store.batch_get(codes)
        if quotes:
            self._try_emit_to_room(sio, 'watchlist', 'stock:quotes', {
                'quotes': quotes,
                'ts_codes': codes,
                'timestamp': datetime.now().isoformat(),
            })

    # ── 内部辅助 ─────────────────────────────────────────────

    def _try_emit(self, sio, event: str, data: dict):
        """容错 emit（广播到所有客户端）"""
        try:
            sio.emit(event, data)
        except Exception as e:
            logger.debug(f"[WsBridge] emit {event} 失败: {e}")

    def _try_emit_to_room(self, sio, room: str, event: str, data: dict):
        """容错 emit 到指定房间"""
        try:
            sio.emit(event, data, room=room)
        except Exception as e:
            logger.debug(f"[WsBridge] emit {event} → room {room} 失败: {e}")


# 全局单例
ws_bridge = WsBridge()
