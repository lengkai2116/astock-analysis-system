# 全局数据体系五层架构修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有三层架构修复为五层流水线架构（采集层→存储层→计算层→调用层→使用层），解决盘中盘口为空、实时推送失效、API 直调数据源、空表缺失、日期格式混乱等 7 个数据层问题。

**Architecture:** 增量式修复，7 个迭代独立可部署可回滚。采集层只管写存储，不关心谁读；调用层只从存储层读，不关心数据来源；计算层在存储层内部完成预计算。新增独立快照库（market_snapshot.db）分离实时数据与持久数据。

**Tech Stack:** Python 3.11+, Flask/SocketIO, SQLite (WAL mode), APScheduler, mootdx (TCP), Tushare Pro API, launchd (macOS)

**参考文档:** `002-方案存档/260-全局数据体系全面诊断与优化方案.md`（§1-§11，含 §10/§11 补充修正）

## 全局约束

- 路径始终用 `pathlib.Path`，禁止 `os.path`、硬编码 `/` 或 `\`
- 文件读写始终指定 `encoding='utf-8'`
- 生产环境禁止模拟数据（Mock）作为数据源降级方案，允许的降级优先级：缓存数据 → 空结构 → 明确错误（HTTP 503）
- API 层"只读不计算"原则：数据从 ECM SQLite 读取，不直调外部 API（TPT 规则）
- 所有 SQLite 使用 WAL 模式 + `BUSY_TIMEOUT=5000`
- `indicator_cache` / `factor_cache` 有数据无消费问题本次不处理
- 每个迭代独立可回滚（见 260 §8.4）

---

## 迭代 1: 实时快照入库（P0-1 盘口为空）

**Covers:** [260 §8.2, §11.2 V3]

**目标:** mootdx TCP 采集的盘中快照写入独立快照库 `market_snapshot.db`，替代当前的 InMemoryStateStore 独占模式。同时修复 `market.py:orderbook` 端点的 route 层直调 mootdx 违规（§11 V3）。

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`
- Modify: `backend/app/data/collector/mootdx_collector.py`
- Modify: `backend/app/routes/market.py`（第473-517行）
- Create: `backend/app/data/market_snapshot_db.py`（快照库管理器，可选——也可扩展 ECM）

**ECM 变更：** `enhanced_cache_manager.py` 新增 `market_snapshot_db` 属性（指向 `DATA_DIR/duckdb/market_snapshot.db`）+ 快照写入/读取方法

**mootdx_collector 变更：** `collect_market_snapshot()` 末尾增加 ECM 快照写入（`INSERT OR REPLACE` 批量覆盖），写入完成后依然更新 InMemoryStateStore（为兼容过渡期）

**market.py 变更：** `GET /api/v3/stock/<ts_code>/orderbook` 第473-517行，优先读快照库，降级读 InMemoryStateStore，移除 route 层直调 mootdx

---

## 迭代 2: API 定时推送（P0-2 WsBridge 失效）

**Covers:** [260 §5.2, §8.3]

**目标:** API 进程通过 APScheduler 定时（每 5s，仅交易时段）读取快照库，计算涨跌分布/板块排行/自选股行情后通过 SocketIO 推送到前端，完全替代 data_daemon 进程中的 WsBridge。

**Files:**
- Modify: `backend/app/__init__.py`（注册 APScheduler 任务）
- Create: `backend/app/services/push_service.py`（推送逻辑：读快照库 → 计算 → SocketIO emit）
- Modify: `backend/app/data/collector/ws_bridge.py`（确认旧 WsBridge 推送已禁用，避免双推）

**推送任务清单：**
1. `push_market_summary()` — 涨跌分布（每 5s）
2. `push_top_stocks()` — 涨幅榜/跌幅榜（每 5s）
3. `push_sector_rankings()` — 板块排行（每 30s）
4. `push_watchlist_quotes()` — 自选股行情（每 5s，匹配已注册自选代码）

**冷启动保护：** 首次推送延迟 10s 启动（给采集层一个采集周期），推送内容携带 `cached_at` 时间戳

**陈旧数据检测：** 检查 `cached_at` 与当前时间差值 > 30s 推送 `staleness_warning`，> 5min 推送 `data_offline`

---

## 迭代 3: data_daemon launchd 加固（P0-3）

**Covers:** [260 §6.1 迭代3]

**目标:** 确保 data_daemon 进程崩溃后自动重启，开机自启可靠。

**Files:**
- Modify: `~/Library/LaunchAgents/com.stock.data-daemon.plist`
- Modify: `backend/data_daemon.py`（wrapper 脚本，增加看门狗逻辑）

**plist 加固要点：**
- `KeepAlive` → `true`
- `ThrottleInterval` → 10（秒）
- `StandardOutPath` / `StandardErrorPath` 指向固定日志文件
- `RunAtLoad` → `true`

**wrapper 脚本：**
- 检测 `DATA_DAEMON_RUNNING` 环境变量防重复启动
- 启动时清除 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`（参考 run.py 第8行）
- 异常退出时记录最后 50 行日志到 crash report

---

## 迭代 4: 补齐空表同步（P1-4）

**Covers:** [260 §6.1 迭代4, §9]

**目标:** 补齐 `margin_cache`、`concept_cache`、`index_member_cache`、`win_rate_cache` 四个空表的数据同步任务。

**Files:**
- Modify: `backend/app/data/collector/data_daemon.py`（日终同步方法新增）

**新增同步任务（data_daemon 日终流程中注册）：**

| 方法 | Tushare 调用 | 预估耗时 |
|:-----|:-------------|:--------:|
| `_sync_margin()` | `margin(ts_code)` 或 `margin_all()` | ~3s |
| `_sync_concept()` | `concept()` + `concept_detail()` | ~10s |
| `_sync_index_member()` | `index_member(ts_code)` | ~5s |
| `_sync_win_rate()` | 不调外部 API，从历史信号计算 | ~2s |

---

## 迭代 5: 统一日期格式 + 存储清理（P1-5）

**Covers:** [260 §6.1 迭代5]

**目标:** 统一所有 ECM 表的日期字段为 `YYYYMMDD` 格式，建立定期清理策略。

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`
- Modify: `backend/app/data/collector/data_daemon.py`（增加清理定时任务）

### 5a: 工具函数

`enhanced_cache_manager.py` 新增 `_fmt_date(date_val)` 类方法，统一将所有日期转换为 `YYYYMMDD`（字符串）：

```python
@staticmethod
def _fmt_date(date_val) -> str:
    """归一化日期格式为 YYYYMMDD 字符串"""
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        return date_val.strftime('%Y%m%d')
    if isinstance(date_val, date):
        return date_val.strftime('%Y%mDD')
    s = str(date_val).replace('-', '').replace('/', '').strip()
    if len(s) == 8 and s.isdigit():
        return s
    raise ValueError(f'无法解析日期: {date_val}')
```

### 5b: 清理策略实现

| 表 | 保留期限 | 清理时机 | 清理方式 |
|:---|:---------|:---------|:---------|
| `stk_limit_cache` | 近 1 年 | 每月 1 日 00:30 | `DELETE WHERE trade_date < cutoff` |
| `lhb_cache` | 近 1 年 | 每月 1 日 00:30 | 同上 |
| `fina_indicator_cache` | 近 3 年 | 每季度末 00:30 | 同上 |
| `minute_cache` | 近 30 日 | 每日 00:30 | 同上 |
| `as_*` 快照表 | 永不持久 | 日终同步后 | `DROP`/重建 |

### 5c: 数据迁移

`stk_limit_cache` 当前日期为 `YYYYMMDD`（整数），需确认无格式问题（§9 标记 ⚠️），如有则执行一次 `UPDATE` 转换。

---

## 迭代 6: 消除 API 直调 Tushare（P2-6 + §11 V1/V2/V4）

**Covers:** [260 §5.1, §11.6.1]

**目标:** 消除调用层全部 4 处违规直调，全改为 DataManager → ECM 路径。

**Files:**
- Modify: `backend/app/data/__init__.py`（DataManager）
- Modify: `backend/app/routes/watchlist.py`（第240行附近）
- Modify: `backend/app/services/dashboard_service.py`（第430-457行）
- Modify: `backend/app/data/collector/data_daemon.py`（补齐 `fina_indicator` 日终同步）

### 6a: 修复 V1 — `watchlist/quotes` 直调 Tushare（红线）

**当前**（`watchlist.py:240` → `DataManager.__init__.py:940`）：
```python
# DataManager.get_fina_indicator() 直调 TushareProvider
def get_fina_indicator(self, ts_code, trade_date=None):
    return TushareProvider.get_fina_indicator(ts_code)  # ❌ 违规
```

**改造方案：**
1. `data_daemon.py` 日终同步增加 `_sync_fina_indicator()`，确保 `fina_indicator_cache` 有数据
2. DataManager 新增 `get_cached_fina_indicator()` 方法，读取 ECM `fina_indicator_cache`
3. `watchlist.py:240` 调用路径改为 `dm.get_cached_fina_indicator(ts_code)`（读 ECM）
4. 保留 Tushare 降级路径（当 ECM 无数据时），但必须经过 DataManager 封装

### 6b: 修复 V2 — `sector-sector` 三级降级含直调

**当前**（`dashboard_service.py:430-457`）：
```python
# 三级降级：Stock.industry → DataManager → Tushare stock_basic()
```

**改造方案：**
1. 消除最后一级直调 Tushare `stock_basic()`：当 Stock 表无行业数据时，返回空结果而非降级到 Tushare
2. ECM 补充 `stock_basic_cache` 表（或复用 Stock ORM），由 data_daemon 日终同步

### 6c: 修复 V4 — `factor-combinations` 直连 SQLite

**当前**（`screener.py:774`）：
```python
conn = sqlite3.connect('factor_combinations.db')  # ❌ 绕过 DataManager
```

**改造方案：**
1. 将 `factor_combinations` 数据迁移到 ECM（新增 `factor_combinations_cache` 表）或通过 DataManager 管理连接
2. `screener.py` 改为通过 DataManager 读取

### 6d: 补充 §5.1 中已文档化的 6 处直调

260 §5.1 列表中的 6 处（watchlist.py:114,251,335 / benchmark_service.py:41 / backtest.py:87 / sandbox_service.py:35）全部改为 DataManager 路径：
- 已受 244 号方案约束的部分（watchlist.py:114,251,335）确认改造状态
- `benchmark_service.py:41` → 改用 `DataManager.get_cached_daily_data(ts_code=index_code)`
- `backtest.py:87` → 改用 `DataManager.get_cached_daily_data()`
- `sandbox_service.py:35` → 改用 `DataManager.get_cached_daily_data()`

---

## 迭代 7: 计算层落地（P2-7）

**Covers:** [260 §4, §10.3.1]

**目标:** 将散落在 API 端点和 Service 中的计算前置到存储层，实现 Eager/Lazy/Realtime 三级计算策略。

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`（新增 `strategy_signals` 表）
- Modify: `backend/app/data/collector/data_daemon.py`（扩展 `_run_precompute()`）
- Modify: `backend/app/data/__init__.py`（DataManager 新增接口）
- Modify: `backend/app/services/signal_computation_service.py`（全市场批量模式）
- Modify: `backend/app/services/dashboard_service.py` 等（接入路径选择逻辑）

### 7a: 创建 `strategy_signals` 表 + 日终预计算

**ECM 新增表：**
```sql
CREATE TABLE IF NOT EXISTS strategy_signals (
    ts_code     TEXT NOT NULL,
    trade_date  TEXT NOT NULL,  -- YYYYMMDD
    signal_name TEXT NOT NULL,  -- 'chanlun', 'vp', 'factor', 'volume_price', 'bociasi'
    signal_value REAL,
    signal_level TEXT,          -- 'strong_buy', 'buy', 'neutral', 'sell', 'strong_sell'
    cached_at   TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (ts_code, trade_date, signal_name)
);
```

**data_daemon 新增预计算任务（日终 `_run_precompute()` 完成后执行）：**
1. 遍历全市场股票（或活跃股票列表）
2. 复用 `SignalComputationService.compute_for_stock()` 计算逻辑
3. 改为批量模式：先全量加载 `daily_cache`/`daily_basic_cache`/`moneyflow_cache` 到内存，再逐只计算
4. 结果写入 `strategy_signals` 表

### 7b: API 路径选择逻辑

**DataManager 新增方法 `select_data_source()`：**
```python
def select_data_source(self, data_type: str, ts_code: str = None) -> str:
    """
    根据当前时间和日终标志位，返回数据源选择：
    - 'eager': 使用预计算结果（日终后）
    - 'lazy': 实时计算 + 缓存（日终前）
    - 'realtime': 实时计算不缓存（仅盘中快照聚合）
    """
    if self._is_eod_completed() and self._is_after_eod_time():
        return 'eager'
    return 'lazy'
```

**接入点（改造后的 API 端点调用模式）：**
```python
source = dm.select_data_source('indicators')
if source == 'eager':
    data = dm.get_cached_indicators(ts_code)  # 读预计算结果
else:
    data = compute_realtime(ts_code)           # 实时计算 + 缓存
    dm.set_to_memory(f'indicators:{ts_code}', data, ttl=1800)
```

### 7c: DataManager 暴露预计算读取接口

**新增方法：**
- `get_cached_indicators(ts_code, start_date, end_date)` — 读取 `indicator_cache`
- `get_cached_factors(ts_code, factor_names=None)` — 读取 `factor_cache`
- `get_cached_signals(ts_code, signal_names=None)` — 读取 `strategy_signals`

**接口约定：**
- 返回 `pd.DataFrame` 格式，与实时计算输出的列名/结构一致
- 无数据时返回 `None`（调用方降级到实时计算）
- 所有数据以 ECM 行式存储读取后，转为调用方期望的列式结构

---

## 依赖关系

```
迭代1 ──→ 迭代2（迭代1提供快照库数据源）
  │
  ├──→ 迭代3（独立，可随时进行）
  ├──→ 迭代4（独立，可随时进行）
  ├──→ 迭代5（独立，可随时进行）
  │
  └──→ 迭代6 ──→ 迭代7（迭代6确保 ECM 数据完整，迭代7在此基础上预计算）
```

- 迭代1 与 迭代2 有前驱依赖（2 依赖 1 的快照库数据）
- 迭代3/4/5 完全独立，可并行
- 迭代6 与 迭代7 有前驱依赖（7 依赖 6 提供的完整 ECM 数据路径）
- 迭代1/2 与 迭代6/7 无直接依赖，可并行推进

---

## 回滚策略

| 迭代 | 回滚方式 |
|:-----|:---------|
| 1 | 删除 `cache_market_snapshot_data()` 调用，`orderbook` 回退到 InMemoryStateStore 路径 |
| 2 | 删除 APScheduler 推送任务注册 |
| 3 | 恢复旧 plist 文件 |
| 4 | 删除新增的 `_sync_*` 方法调用 |
| 5 | 移除清理定时任务；日期格式如无兼容问题可不回滚 |
| 6 | 逐个文件回退，改回直调 TushareProvider |
| 7 | 删除预计算定时任务 + DataManager 新增方法 |
