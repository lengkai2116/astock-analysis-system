# 全局数据系统重构：盘中介入 InMemoryStateStore + 盘后保持 DuckDB

## 背景

239号方案的"CQRS 化全局数据体系"设计中，盘中实时数据（15s~5min刷新）和盘后历史数据（日终Tushare同步写入）被混在一个DuckDB文件里，由5个采集线程和N个Flask请求同时读写。DuckDB的单写锁 + 不同连接配置冲突 → 进程启动后连接立即降级到内存空库，as_*表从未真正写入过数据 → 所有依赖盘中数据的接口返回503。

## 核心思路

**盘中实时数据和盘后历史数据用完全独立的管道处理，物理隔离。**

**盘中（交易日9:30-15:00）**：
- AkshareCollector 5个线程采集结果 → 写入 `InMemoryStateStore`（线程安全的内存字典）
- Flask 路由直接从内存读取 → O(1)，零IO，零DB连接
- 异步归档线程每15-30秒把内存快照写一次DuckDB as_*表（纯存档，不作为主要数据源）

**盘后（15:30以后）**：
- SchedulerManager → Tushare API → DuckDB daily_cache / moneyflow_cache（保持不变）
- Flask 路由读 DuckDB（无需单例解决冲突，因为写入者只有SchedulerManager一个人）

## 变更清单（5个文件，~200行核心代码）

### 文件1：新增 `backend/app/data/in_memory_store.py`

**What**: 120行。线程安全的全内存状态存储器。

**核心数据结构**：
```python
class InMemoryStateStore:
    """线程安全的盘中数据内存存储器"""
    
    def __init__(self):
        self._data = {}           # 主快照: {ts_code: {field: value}}
        self._sectors = []        # 板块排行
        self._concepts = []       # 概念排行
        self._top_stocks = {'up': [], 'down': []}  # 涨跌榜
        self._limit_pools = {'up': [], 'down': []} # 涨跌停池
        self._watchlist_kline = []   # 自选股分钟K线（当日累积）
        self._lhb = []            # 龙虎榜
        self._news = []           # 新闻
        self._meta = {}           # {topic: last_updated_timestamp}
        self._lock = threading.RLock()
```

**方法**（全是对应写/读）：
- 写：`update_snapshot(records)` / `update_sectors(records)` / `update_top_stocks(type, records)` / `append_minute_kline(records)` 等
- 读：`get(ts_code)` / `batch_get(codes)` / `get_sectors()` / `get_top_stocks(type)` / `get_all_snapshot()` / `get_meta(topic)`（返回最后更新时间）
- 检查：`is_stale(topic, max_age_sec=300)` / `age_seconds(topic)`

**设计决策**：
- 使用 `threading.RLock` 保护每次读写操作，粒度为整个操作（批量写/读时获取一次锁，非字段级别锁）
- Python GIL 保证单个 `dict.__setitem__` 是原子的，但批量操作需要锁
- `get_all_snapshot()` 返回的是 dict 的快照副本（浅拷贝），防止外部引用修改内部状态
- 分钟K线积累盘中5小时×12条/小时=60条/股×200股=12,000条，盘后通过 `clear_minute_kline()` 清理
- 所有读方法在 key 不存在时返回 `None` 或 `[]`，绝不抛异常

### 文件2：`backend/app/data/akshare_collector.py`

**What**: 改造5个采集函数，写入目的地改为 InMemoryStateStore（优先）+ DuckDB（异步归档/保留）。

**变更点**（5处`_get_ecm().write_*()` → 先写store再写DB）：

```python
from app.data.akshare_reader import store  # 全局内存状态

def _collect_market_snapshot():
    # ... 采集逻辑不变 ...
    # 1. 写内存（盘中主数据源）
    store.update_snapshot(records)
    # 2. 写DuckDB（异步归档，失败不阻塞）
    try:
        _get_ecm().write_as_market_snapshot(records)
    except Exception:
        pass  # 盘中归档不重要
```

同样的模式应用到全部5个采集函数：
- `_collect_top_stocks()` → `store.update_top_stocks('up'/'down', records)`
- `_collect_sector_and_limit()` → `store.update_sectors(records)` / `store.update_concepts(records)` / `store.update_limit_pool(type, records)`
- `_collect_minute_kline()` → `store.append_minute_kline(records)`
- `_collect_lhb_and_news()` → `store.update_lhb(records)` / `store.update_news(records)`

### 文件3：`backend/app/data/akshare_reader.py`

**What**: AkshareDataReader 增加从 InMemoryStateStore 读取的方法（与现有 DuckDB 读取并存，盘中优先走内存）。

**变更点**：
```python
from .in_memory_store import InMemoryStateStore

class AkshareDataReader:
    def __init__(self):
        # ... 现有初始化 ...
        self._store = InMemoryStateStore()  # 内存状态引用

    def get_market_snapshot(self):
        """先试内存（盘中），失败再试 DuckDB（盘后归档）"""
        snapshot = self._store.get_all_snapshot()
        if snapshot:
            return snapshot
        # fallback: DuckDB as_* 归档
        return self._read_from_duckdb('as_market_snapshot')
    
    def get_batch_quotes(self, ts_codes):
        """批量查询走内存"""
        return self._store.batch_get(ts_codes)
```

这样现有用 `reader.get_batch_quotes()` 的代码（dashboard_service、realtime等）不需要改，内部自动走内存。

### 文件4：`backend/app/services/dashboard_service.py`

**What**: 盘中读 InMemoryStateStore（通过 AkshareDataReader），盘后读 DuckDB。

**变更点**：
- `get_index_summary()` / `get_market_volume()` / `get_moneyflow_summary()` / `get_sector_moneyflow()` 
  → 读内存而不是 DuckDB → 不再依赖 as_* 表是否有数据
- `_try_get_index_daily()` 保持盘后 DuckDB + AKShare API 降级不变（这条路是对的）

### 文件5：`backend/app/data/enhanced_cache_manager.py`

**What**: 清理遗留问题。最小的改动。

**变更点**：
- 所有 `as_*` 表的 DuckDB 读写方法保持不变
- `get_ecm_instance()` 单例机制保留（用于盘后 Tushare sync + 归档线程的写入）
- 全局 `_clean_stale_duckdb_locks()` 在启动时清理僵尸.wal/.tmp文件（已实现）

## 不需要改动的文件（保持现状）

| 文件 | 原因 |
|------|------|
| `scheduler_manager.py` | 盘后Tushare同步，不涉及盘中实时 |
| `run.py` / `__init__.py` | 启动流程不变，只是数据源内部切换 |
| `cache_manager.py`（旧） | 将被 `minute_data_manager.py` 逐渐弃用，不急于删除 |
| 前端文件 | 数据管道改好了前端自然通 |

## 盘中数据流验证方式

1. 启动后端后，查看日志确认 `AkshareCollector 5 线程启动`
2. 每15秒确认 `_collect_market_snapshot` 完成一次
3. `curl http://localhost:5001/api/v3/dashboard/summary` 应 < 200ms 返回真实数据
4. 盘中手动断开网络 → 内存中最后一次快照仍可返回（不返回503）
5. 盘后确认 as_* 归档表有几行数据（证明归档线程在工作）

## 盘后数据流验证方式（无变化）

1. 日终15:30确认 Tushare sync 完成
2. `curl http://localhost:5001/api/v.../market/moneyflow-summary` 返回缓存数据

## 实施顺序

| 步骤 | 内容 | 文件 | 行数 |
|------|------|------|------|
| 1 | 新建 InMemoryStateStore | `in_memory_store.py`（新增） | ~120行 |
| 2 | 改造 AkshareCollector 5个采集函数 | `akshare_collector.py` | ~30行 |
| 3 | 改造 AkshareDataReader 增加内存路径 | `akshare_reader.py` | ~30行 |
| 4 | 改造 DashboardService 盘中读内存 | `dashboard_service.py` | ~20行 |
| 5 | 验证：启动 → 采集 → 接口返回真数据 | 终端验证 | — |
