# 518号｜10-13 日终 RAW 写 compute_cache.db 全量锁失败核查与处置（分库共享连接读写并发疑似根因）

> **版本**：v1.1（2026-10-13 只读核查 + 20:47 维护重启后**必现复发**确认；待拍板 Q1~Q4）
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
- **复发（必现，回答 Q3）**：20:47:53 WAL 守护维护周期重启 daemon（新 PID 42179，见 §六）后重入 RAW，锁错**照旧**——`compute_cache.db ... database is locked` 于 **20:56:21** 仍在刷，20:34 之后窗口计数 **5143** ⇒ **非一次性状态，属必现复发**（每次重入 RAW 即命中）。

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
3. ~~**复现**~~ **已复现（必现）**：20:47:53 WAL 守护维护周期重启 daemon（42179，见 §六）后重入 RAW，锁错照旧（20:34 后 5143 次、20:56 仍在刷）⇒ **非一次性状态**。
4. **API 角色**：确认 API 是否写 `compute_cache.db`（若写，属跨进程写者；与 §三 0.1s 节奏矛盾，需排除）。

## 五、处置候选（待拍板）

| Q | 议题 | 候选 |
|---|---|---|
| **Q1** | 分库读写连接 | **A. 分库读写分离**（读用独立连接，对齐 ECM `read_conn`/`compute_read_conn` 先例，彻底） / B. 读路径亦持库级锁（最简，读写互斥） / C. 维持 |
| **Q2** | 共享连接线程安全 | A. `execute_query`/`_query_shard` 复用共享连接前加锁或改独立只读连接 / B. 维持 |
| **Q3** | 复现判定 | A. 待 10-13 RAW 重入观察是否复发（定必现/偶发）再定处置范围 / B. 直接按 Q1 处置 |
| **Q4** | 卡死现状 | A. 待 Q1/Q2 修复后重跑 10-13 EOD / B. 先人工清障让 EOD 推进（评估） |

## 六、20:47 维护周期（复发佐证 + 517 野外验证）

2026-10-13 **20:47:53**，WAL 守护执行一次**真实维护周期**（`maintenance_once`），与 517 号原故障**同链路**（停 daemon+API → 收缩 → 重启）：

```text
20:47:52 收缩 compute_cache.db: 前 151.5MB → 后 0.0MB（PASSIVE busy=0 frames=38546）
20:47:53 ✅ 全部分库 WAL 收缩成功
20:47:53 daemon 已重启（无看守）          ← 新 PID 42179
20:47:54 API 已重启（health 校验通过）     ← 新 PID 42180
```

- **517 修复野外验证通过**：该周期重启后 API 恢复（`health 校验通过`）⇒ 517 号原「停后即时重启 API 静默不恢复」在**真实维护周期**下闭环（详见 517 档 §十）。
- **本号问题与 517 无关且必现**：daemon（42179）重入 RAW 后锁错照旧（§一末、§四-3）。

## 附：核对命令（只读）

- 锁错计数：`grep -c "compute_cache.db, database is locked" backend/logs/data_daemon.log`
- 持有者：`lsof "<项目根>/data/duckdb/compute_cache.db"`
- 日期错位：`SELECT MAX(trade_date) FROM daily_cache / daily_basic_cache / treemap_snapshot`
- 管道：`SELECT step_id, step_name, status FROM pipeline_status WHERE pipeline_date='20261013'`（实际列：`pipeline_date/step_id/step_name/status/started_at/completed_at/detail/retry_count`）
- 代码：`sharding_manager.py:173`（`get_connection`）/`:234`（`get_write_lock`）/`:339`（`execute_batch_insert`）/`execute_query`（读，无锁）；`enhanced_cache_manager.py:528`（`_query_shard`）/`:369`/`:3162`
