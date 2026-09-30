"""
WsBridge — 自选股推送注册表（采集侧推送已废止）
================================================
历史用途：采集线程每轮采集完成后从 InMemoryStateStore 读取数据、经 SocketIO 推送。

**500号#1（2026-09-30）**：采集侧推送链路事实上已废止——`_api_push_active` 初始化即
`True` 且全仓无第二处赋值（原 7 处 `_broadcast_*` 均被其短路），真实实时推送由
**API 进程** `app/services/push_service.py`（APScheduler 每 5s）承担。故删除该死路径
（`on_collect_complete` + 7 个 `_broadcast_*` + `broadcast_quote_update` + `_try_emit*`）。

本模块现仅保留**自选股推送注册表**：收集/维护需要实时推送的自选股代码，供
`push_service.push_watchlist_quotes` 读取（`get_watchlist_codes`）。

事件归属（现网，均由 push_service 产出）：
    market:summary / market:top_stocks / market:sectors / stock:quotes

设计原则：
    - 线程安全（threading.Lock 守护自选股集合）
    - 不持有 DuckDB / Redis 连接
"""

import logging
import threading
from typing import List

logger = logging.getLogger(__name__)


class WsBridge:
    """自选股推送注册表（采集侧推送已废止，见模块 docstring）"""

    def __init__(self):
        self._watchlist_codes: set = set()
        self._watchlist_lock = threading.Lock()

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

    def get_watchlist_codes(self) -> list:
        """获取当前注册的自选股代码列表（供 push_service 读取）"""
        with self._watchlist_lock:
            return list(self._watchlist_codes)


# 全局单例
ws_bridge = WsBridge()
