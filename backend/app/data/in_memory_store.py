"""
InMemoryStateStore — 盘中数据线程安全内存状态存储器
===================================================
239号方案盘中数据核心：所有 AkshareCollector 采集结果先写内存，Flask 路由从内存读取。

替代方案（按优先级）：
  盘中（新品）：InMemoryStateStore → O(1) 读取，零 IO，零 DB 连接
  盘后（已有）：DuckDB *_cache → Tushare 日终同步后读取
  归档（异步）：内存数据每 15-30s 批量写 DuckDB as_*（可选，非阻塞）

设计原则：
  - 单进程多线程环境，threading.RLock 保护批量操作
  - 单字段赋值（dict.__setitem__）由 Python GIL 保证原子性
  - 所有读方法返回浅拷贝副本，防止外部引用污染内部状态
  - 数据不存在时返回 None / []，绝不抛异常
"""

import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class InMemoryStateStore:
    """线程安全盘中数据内存存储器"""

    def __init__(self):
        self._lock = threading.RLock()
        # 全市场快照（覆盖式）：{ts_code: {field: value}}
        self._snapshot: Dict[str, Dict] = {}
        # 板块排行（覆盖式）
        self._sectors: List[Dict] = []
        # 概念排行（覆盖式）
        self._concepts: List[Dict] = []
        # 涨跌榜（覆盖式）：{'up': [...], 'down': [...]}
        self._top_stocks: Dict[str, List[Dict]] = {'up': [], 'down': []}
        # 涨跌停池（覆盖式）：{'up': [...], 'down': [...]}
        self._limit_pools: Dict[str, List[Dict]] = {'up': [], 'down': []}
        # 分钟K线（追加式）：[record, ...]，盘后清理
        self._minute_kline: List[Dict] = []
        # 龙虎榜（覆盖式）
        self._lhb: List[Dict] = []
        # 席位级龙虎榜详情（覆盖式）：{ts_code: [seat_records]}
        self._lhb_detail: Dict[str, List[Dict]] = {}
        # 新闻（按需缓存）
        self._news: List[Dict] = []
        # 元信息：{topic_name: datetime}
        self._meta: Dict[str, datetime] = {}

    # ── 元信息 ─────────────────────────────────────────────

    def _touch(self, topic: str):
        """标记主题为"刚刚更新"（线程安全）"""
        with self._lock:
            self._meta[topic] = datetime.now()

    def get_meta(self, topic: str) -> Optional[datetime]:
        """获取某主题的最后更新时间"""
        with self._lock:
            return self._meta.get(topic)

    def age_seconds(self, topic: str) -> Optional[float]:
        """获取某主题距今的秒数"""
        t = self.get_meta(topic)
        if t is None:
            return None
        return (datetime.now() - t).total_seconds()

    def is_stale(self, topic: str, max_age_sec: int = 300) -> bool:
        """检查某主题是否过时（默认 5 分钟）"""
        age = self.age_seconds(topic)
        if age is None:
            return True
        return age > max_age_sec

    # ── 全市场快照（覆盖式，15s 刷新）──────────────────────

    def update_snapshot(self, records: List[Dict]):
        """全量更新市场快照（覆盖式，同代码覆盖）"""
        with self._lock:
            for r in records:
                code = r.get('ts_code', r.get('code', ''))
                if code:
                    self._snapshot[code] = dict(r)
            self._touch('snapshot')

    def get_snapshot(self) -> List[Dict]:
        """获取全市场快照（所有股票）"""
        with self._lock:
            return list(self._snapshot.values())

    def get_by_code(self, ts_code: str) -> Optional[Dict]:
        """按代码查询单只股票"""
        with self._lock:
            r = self._snapshot.get(ts_code)
            return dict(r) if r else None

    def batch_get(self, ts_codes: List[str]) -> List[Dict]:
        """批量查询指定股票列表"""
        with self._lock:
            result = []
            for code in ts_codes:
                r = self._snapshot.get(code)
                if r:
                    result.append(dict(r))
            return result

    # ── 板块排行（覆盖式，5min 刷新）────────────────────────

    def update_sectors(self, records: List[Dict]):
        """全量更新行业板块排行"""
        with self._lock:
            self._sectors = [dict(r) for r in records]
            self._touch('sectors')

    def get_sectors(self) -> List[Dict]:
        """获取行业板块排行"""
        with self._lock:
            return [dict(r) for r in self._sectors]

    def update_concepts(self, records: List[Dict]):
        """全量更新概念板块排行"""
        with self._lock:
            self._concepts = [dict(r) for r in records]
            self._touch('concepts')

    def get_concepts(self) -> List[Dict]:
        """获取概念板块排行"""
        with self._lock:
            return [dict(r) for r in self._concepts]

    # ── 涨跌榜（覆盖式，30s 刷新）───────────────────────────

    def update_top_stocks(self, rank_type: str, records: List[Dict]):
        """全量更新涨跌榜（'up' 或 'down'）"""
        with self._lock:
            self._top_stocks[rank_type] = [dict(r) for r in records]
            self._touch(f'top_stocks:{rank_type}')

    def get_top_stocks(self, rank_type: str) -> List[Dict]:
        """获取涨跌榜"""
        with self._lock:
            return [dict(r) for r in self._top_stocks.get(rank_type, [])]

    # ── 涨跌停池（覆盖式，5min 刷新）────────────────────────

    def update_limit_pool(self, limit_type: str, records: List[Dict]):
        """全量更新涨跌停池（'up' 或 'down'）"""
        with self._lock:
            self._limit_pools[limit_type] = [dict(r) for r in records]
            self._touch(f'limit_pool:{limit_type}')

    def get_limit_pool(self, limit_type: str) -> List[Dict]:
        """获取涨跌停池"""
        with self._lock:
            return [dict(r) for r in self._limit_pools.get(limit_type, [])]

    # ── 分钟K线（追加式，5min 采集，盘后清理）─────────────

    def append_minute_kline(self, records: List[Dict]):
        """追加分钟K线数据（盘后需调用 clear_minute_kline 清理）"""
        if not records:
            return
        with self._lock:
            self._minute_kline.extend(dict(r) for r in records)
            self._touch('minute_kline')

    def get_minute_kline(self, ts_code: str = None) -> List[Dict]:
        """获取分钟K线，可过滤指定股票"""
        with self._lock:
            if ts_code:
                return [dict(r) for r in self._minute_kline if r.get('ts_code') == ts_code]
            return [dict(r) for r in self._minute_kline]

    def clear_minute_kline(self):
        """盘后清理分钟K线（由 scheduler 日终调用）"""
        with self._lock:
            self._minute_kline.clear()
            self._meta.pop('minute_kline', None)

    def clear_lhb_detail(self):
        """盘后清理席位级龙虎榜（由 scheduler 日终调用）"""
        with self._lock:
            self._lhb_detail.clear()
            self._meta.pop('lhb_detail', None)

    # ── 龙虎榜（覆盖式，30min 刷新）─────────────────────────

    def update_lhb(self, records: List[Dict]):
        with self._lock:
            self._lhb = [dict(r) for r in records]
            self._touch('lhb')

    def get_lhb(self) -> List[Dict]:
        with self._lock:
            return [dict(r) for r in self._lhb]

    # ── 龙虎榜席位级详情（覆盖式，30min 刷新）────────────────

    def update_lhb_detail(self, records: List[Dict]):
        """更新席位级龙虎榜数据（覆盖式，按 ts_code 索引）"""
        with self._lock:
            self._lhb_detail.clear()
            for r in records:
                ts = r.get('ts_code', '')
                if ts:
                    self._lhb_detail.setdefault(ts, []).append(dict(r))
            self._touch('lhb_detail')

    def get_lhb_detail(self, ts_code: str = None) -> List[Dict]:
        """获取席位级龙虎榜数据"""
        with self._lock:
            if ts_code:
                return [dict(r) for r in self._lhb_detail.get(ts_code, [])]
            # 全量展平
            result = []
            for records in self._lhb_detail.values():
                result.extend(dict(r) for r in records)
            return result

    # ── 新闻（按需缓存，30min 刷新）─────────────────────────

    def update_news(self, records: List[Dict]):
        with self._lock:
            self._news = [dict(r) for r in records]
            self._touch('news')

    def get_news(self) -> List[Dict]:
        with self._lock:
            return [dict(r) for r in self._news]

    # ── 维护 ───────────────────────────────────────────────

    def clear_all(self):
        """清空全部状态（供测试或盘后重置用）"""
        with self._lock:
            self._snapshot.clear()
            self._sectors.clear()
            self._concepts.clear()
            self._top_stocks['up'].clear()
            self._top_stocks['down'].clear()
            self._limit_pools['up'].clear()
            self._limit_pools['down'].clear()
            self._minute_kline.clear()
            self._lhb.clear()
            self._news.clear()
            self._meta.clear()

    def stats(self) -> Dict[str, Any]:
        """统计信息（状态监控用）"""
        with self._lock:
            return {
                'snapshot_count': len(self._snapshot),
                'sector_count': len(self._sectors),
                'concept_count': len(self._concepts),
                'top_stocks_up': len(self._top_stocks.get('up', [])),
                'top_stocks_down': len(self._top_stocks.get('down', [])),
                'limit_pool_up': len(self._limit_pools.get('up', [])),
                'limit_pool_down': len(self._limit_pools.get('down', [])),
                'minute_kline': len(self._minute_kline),
                'lhb': len(self._lhb),
                'news': len(self._news),
                'meta': {k: v.isoformat() for k, v in self._meta.items()},
            }


# 全局单例
store = InMemoryStateStore()
