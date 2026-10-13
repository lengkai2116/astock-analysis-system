# 518号｜10-13 日终 RAW 写 compute_cache.db 全量锁失败核查与处置（分库共享连接读写并发疑似根因）

> **版本**：v1.0（2026-10-13 只读核查，待拍板）
> **性质**：数据管道阻塞（RAW-1/RAW-3 写 `compute_cache.db` 全量失败 → 10-13 EOD 不推进 → 快照停 10-12 → 全量回归 2 项快照测试失败）
> **触发**：2026-10-13 全量回归复核时发现 `data_daemon.log` 大量 `compute_cache.db ... database is locked`
> **关联**：517（WAL 维护重启，时间相邻但根因不同）；511（总库写锁，同为锁议题、库不同）；499/510（分库读路径）
> **核查时刻**：2026-10-13 20:3x（只读）

---

## 一、现象（实证）

- **写失败量**：`backend/logs/data_daemon.log` 中，2026-10-13 当日 `compute_cache.db` 写失败 **61105 次**（首条 **18:45:44**，末条 **20:32:30**）；累计（含历史）**75432 次**。
- **失败表**：`indicator_ma` / `indicator_macd` / `indicator_other`（RAW-1）＋ `factor_cache`（RAW-3）。
- **错误类型（两种）**：
  - `分库写入失败: {table} on compute_cache.db, OperationalError: database is locked`
  - `factor_cache 分库写入失败: compute_cache.db, database is locked`
  - 另有 `another row available`（`DatabaseError` / `OperationalError`；经全仓检索**非本仓自定义文本**，属库层错误）
- **失败节奏**：**~0.1s/次**（**非 30s 级**——关键定性依据，见 §三）。
- **管道状态**（`data/duckdb/stock_cache.db` 的 `pipeline_status`）：`20261013` 的 COL-1~COL-7 全 `done`，**RAW-1/2/3 及后续全 `pending`**（未推进）。
- **数据日期错位**（下游表现）：`market_cache.db.daily_cache` / `daily_basic_cache` 的 `max(trade_date)` = **2026-10-13**，而 `snapshot_cache.db.treemap_snapshot` = **2026-10-12** ⇒ 全量回归两项快照测试失败（`test_t14_pe_pb`/`test_t25_f4_ohl`，**非代码回归**）。
- **锁持有者**（`lsof compute_cache.db`）：仅 **daemon 与 API**（WAL 守护无）。
- **时机**：首现于 **18:45:10**（daemon 初始化中：APScheduler/数据源注册）与 **18:45:44**（`[RAW-3] 断点续算: 跳过已完成 185 只，待算 5375 只`）——恰在 **18:43 WAL 维护重启**之后。
- **当前态**：核查后重启的 daemon（20:34 起）暂 **0 锁错**（尚未重入 RAW）。

## 二、代码机制（实证）

`backend/app/data/sharding_manager.py`：

- `get_connection(db_name)`（`:173`）：**每个分库缓存单条 `sqlite3.Connection`**（`check_same_thread=False`），**全线程共享**；连接 `PRAGMA busy_timeout=30000`（`:183`）。
- **写**路径：`execute_batch_insert`（`:339`）/`execute_insert`/`create_table`/ECM `_exec_shard` —— 均持**库级 `threading.RLock`**（`get_write_lock`，`:234`）。
- **读**路径：`execute_query` —— **不持锁**，直接用**同一共享连接**游标查询。

`backend/app/data/enhanced_cache_manager.py`：

- ECM 自身读路径用独立连接 `read_conn`（`:164`，总库）/`compute_read_conn`（`:202`，compute_cache.db）。
- **但 `_query_shard`（分库路由读，`:528`）用 `sharding_manager.get_connection(db)` 的共享连接**（`pd.read_sql(sql, conn)`），**不持写锁**——`get_cached_factor(s)`（`:3171`/`:3183` → `:3174`/`:3185` 读 `factor_cache`）、`indicator_ma/macd/other`（`:1509/1513/1516/1819/3833`）等均走此路。
- 失败日志来源：`:369`（`分库写入失败`）/ `:3162`（`factor_cache 分库写入失败`）。

## 三、疑似根因（待验证）

**分库共享连接被「读（不持锁）」与「写（持锁）」并发使用** —— 同一 SQLite 连接无法同时服务读写（`check_same_thread=False` 仅关掉 Python 线程检查，不保证线程安全）：

- `another row available` ＝ 同一连接/游标被并发使用（游标结果未取尽又执行新语句）的典型特征；
- **关键推理**：`compute_cache.db` 为 **WAL 模式** ⇒ **普通读者不阻塞写者**，故 `database is locked` **不可能**来自「外部读者持锁」；又若为**外部写者**（如 API）持写锁，`busy_timeout=30000` 会令 daemon 等待 **30s** ⇒ 失败节奏应为 **30s 级**——实测 **0.1s 级** ⇒ **非外部锁**。
- ⇒ **锁「持有者」是 daemon 自身的共享连接**：读线程（`_query_shard`）与写线程（`execute_batch_insert`）落在**同一连接**上，写升级/游标冲突**立即**报错（`busy_timeout` 对「连接自身」冲突不生效）。

**触发时机**：自 18:43 WAL 维护重启后，daemon（18:45 起）读写重叠持续命中 ⇒ 近乎**每次**写失败（非偶发竞态）。

## 四、待核 / 待验

1. **精确定位并发读点**：RAW-1/RAW-3 写 `compute_cache.db` 时，哪条读路径（RAW-2 因子读取？daemon 巡检？）在读 `factor_cache`/`indicator_*`（均在共享连接上）。
2. **为何自 18:45 起持续**（此前无）：是否近期改动/线程时序放大重叠，或与 WAL 维护重启残留相关。
3. **复现**：让 daemon 重入 10-13 RAW，观察是否复发（判定必现/偶发）。
4. **API 角色**：确认 API 是否写 `compute_cache.db`（若写，属跨进程写者；与 §三 0.1s 节奏矛盾，需排除）。

## 五、处置候选（待拍板）

| Q | 议题 | 候选 |
|---|---|---|
| **Q1** | 分库读写连接 | **A. 分库读写分离**（读用独立连接，对齐 ECM `read_conn`/`compute_read_conn` 先例，彻底） / B. 读路径亦持库级锁（最简，读写互斥） / C. 维持 |
| **Q2** | 共享连接线程安全 | A. `execute_query`/`_query_shard` 复用共享连接前加锁或改独立只读连接 / B. 维持 |
| **Q3** | 复现判定 | A. 待 10-13 RAW 重入观察是否复发（定必现/偶发）再定处置范围 / B. 直接按 Q1 处置 |
| **Q4** | 卡死现状 | A. 待 Q1/Q2 修复后重跑 10-13 EOD / B. 先人工清障让 EOD 推进（评估） |

## 附：核对命令（只读）

- 锁错计数：`grep -c "compute_cache.db, database is locked" backend/logs/data_daemon.log`
- 持有者：`lsof "<项目根>/data/duckdb/compute_cache.db"`
- 日期错位：`SELECT MAX(trade_date) FROM daily_cache / daily_basic_cache / treemap_snapshot`
- 管道：`SELECT stage, status FROM pipeline_status WHERE data_date='20261013'`
- 代码：`sharding_manager.py:173`（`get_connection`）/`:234`（`get_write_lock`）/`:339`（`execute_batch_insert`）/`execute_query`（读，无锁）；`enhanced_cache_manager.py:528`（`_query_shard`）/`:369`/`:3162`
