---
title: STG 存储层 OCR 核查与处置
type: 核查整改方案
date: 2026-09-30
version: v1.0
status: 🔍 只读核查完成（本档未改任何代码/配置；处置计划待拍板）
related:
  - 292-全局数据体系权威架构说明（2026-07-23版）
  - 356-第2层STG存储层分库实施方案与规则体系
  - 423-STG仓储环节中心化架构方案v2.0（替代398号）
  - 424-STG存储层原始数据存储全面核查与整改方案
  - 426-RAW预计算环节配置核查报告与分库入库整改方案（§0.1 分库复审 D1-D8）
  - 496-daemon日终效率OCR全面检查与处置
  - 498-COL采集层OCR核查与处置
  - 499-分库表走总库连接读取核查与修复方案
---

# 500号｜STG 存储层 OCR 核查与处置

**版本**：v2.0（2026-09-30；**只读核查 + 处置方案**；**批次1~8 全部实施完成**，代码/数据已改、未推送）
**v2.0 批次7 实施（2026-09-30）**：用户「继续」→ **死存储/死表/视图重复（C-7 #91~#99）**。**先只读复核库现状**得关键发现：**#93~#99 的库内容问题基本已由 426 清理落地**，故**无需删库表**；真正空间占用在**未跟踪的历史备份/沙箱**（经用户拍板删除）。
- **⚠️ 复核更正**：#93（总库空壳表）现仅 **11 表 / 4 空**（原 44 表 / 36 空，426 已清）；#94（`cache_metadata` 双份）已**单份**（总库 34 行，`system_cache.db` 无该表）；#95（视图重复）仅 `history_cache.db.adj_factor_view`（活视图，无重复）；#96/#97/#98/#99 属**设计登记项**（`_prefix_rules`/`_ensure_snapshot_indexes`/`market_snapshot.db` 路由均已按 426 落地），非缺陷 → **不删库表**。
- **#91/#92 已删除（经用户批准，约 222 GiB 释放：磁盘 548→326 GiB）**：`data/duckdb/*.bak*` **34 个备份 196 GiB**（426~486 迁移/重算前快照）+ 测试沙箱 `data_sandbox_test_20260913`(12G)/`data_virtual_test_20260912`(25G) + `backend/instance/duckdb`（旧 `stock_cache.db.backup`/6×corrupted/zombie，~1 GiB）+ `data/` 3 个 0 字节残留库 + root `factors_combos.db` + `backend/test.db`。**全部未被 git 跟踪**（`.gitignore` 含 `data/duckdb/*.db`/`*.db`/`*.bak.*`/`instance/`）。
- **保留（在用）**：`data/factors_combos.db`（`routes/factors.py`）+ `backend/strategy_templates.db`（`routes/strategy_templates.py`）——**非死库**，未删。
- **验证**：探针 `scripts/_500_batch7_probe.py` **全绿**（备份/沙箱/残留已清 / 总库 11 表 4 空 / cache_metadata 单份 / 仅活视图 / 路由登记 / 活跃库完整）；app + data_daemon **导入冒烟 OK**；定向回归 **73 passed**（423/426_phase5/428）；**活跃库完整**（`daily_cache` 6.49M 行 / `adj_factor_view` / `as_market_snapshot` 5226 行）；daemon 全程存活并继续写库。

**v1.9 批次6 实施（2026-09-30）**：用户「按 §九 开工批次6」→ **死模块处置（Q1=B，经复核收窄）**。
- **⚠️ 核查更正（v1.0 结论有误）**：`create_views.py` **并非死模块**——其 `create_adj_factor_view` 构建的 `adj_factor_view` 被 `enhanced_cache_manager.get_cached_adj_factor:2147` **生产读取**，且被 `tests/test_426_phase4_adj_factor.py` + `scripts/_426_phase4_adj_factor_repair.py` 引用。**故不删该模块**（经用户拍板：仅删 4 个死函数，保留模块与 `create_adj_factor_view`）。同时 `init_sharding.py`（**模块**）虽被 `tests/test_426_phase5_cleanup.py` 断言导入（非生产引用），按拍板「同步更新该测试、移除对本模块断言」处置。
- **删除 5 个死模块**（`git rm`）：`app/data/config_manager.py` / `migration.py` / `init_sharding.py`（模块，与 `sharding_manager.init_sharding` 同名不同物）/ `health_checker.py` / `data_inventory.py`（**生产全仓零引用**，`grep` + 动态 import 扫描确认）。
- **`create_views.py`**：删 4 个死函数（`create_daily_data_view`/`create_financial_data_view`/`create_all_views`/`drop_all_views`，零引用）；保留 `create_adj_factor_view`（模块瘦身，docstring 说明保留理由）。
- **测试同步**：`tests/test_426_phase5_cleanup.py::test_dead_table_refs_removed_from_config` 移除对 `app.data.init_sharding` 模块的 3 行断言（保留 `scripts/backfill_all.py` 断言）。
- **验证**：`py_compile` OK；ruff `create_views.py`+测试 **clean**；**app 导入冒烟 OK** + **data_daemon 导入冒烟 OK**；探针 `scripts/_500_batch6_probe.py` **全绿**（5 模块文件删除+不可 import / `create_adj_factor_view` 端到端建视图覆盖 3 年表 / 4 死函数删除 / ECM 活链保留 / 全仓无残留引用）；定向回归 **81 passed**（426_phase5/426_phase4_adj_factor/426_p0/491_3/428）。停 daemon+看守 → 跑 → **已重启**。

**v1.8 批次8 实施（2026-09-30）**：用户「按 §九 开工批次8」→ **#1 `ws_bridge` 死分支删除（Q2=A）**，改动 4 文件（`ws_bridge.py` 重写 / `mootdx_collector.py` / `akshare_collector.py` / `routes/realtime.py`）+ 探针 1 新增：
- **删除死路径**：`WsBridge` 的 `on_collect_complete` + 7 个 `_broadcast_*`（market_summary/indices/top_stocks/sectors/limit_pools/news/watchlist_quotes）+ `broadcast_quote_update` + `_try_emit`/`_try_emit_to_room` + `_api_push_active`（初始化即 `True`、全仓无第二处赋值 → 7 处短路使整链不可达）+ `_sio`/`_get_store` 惰性引用。
- **保留活路径**：`WsBridge` 现仅为**自选股推送注册表**（`update/remove/clear/get_watchlist_codes`），供 **API 进程 `push_service.push_watchlist_quotes`** 读取（`routes/realtime.py:76` 注册）+ 全局单例 `ws_bridge`。
- **采集侧死调用移除**：`mootdx_collector`（2 处 `on_collect_complete`）+ `akshare_collector`（1 处）删除。
- **端点处置（Q2=A 连带）**：删 `routes/realtime.py` 的 `trigger_publish` SocketIO 端点（调 `on_collect_complete('market_snapshot')` 静默无效）；顶部架构注释/日志改「push_service」。
- **归属说明**：真实推送方＝`app/services/push_service.py`（APScheduler 每 5s，`scheduler_manager` 注册 4 个 `push_*`），**未改动**；`market:indices`/`market:news`/`market:limit_pools` 事件本无前端消费方（前端目录不在本仓）→ 随死路径一并移除。
- **验证**：`py_compile` OK；ruff 4 文件 **clean**（`mootdx_collector` I001 + `akshare_collector` F841 与 HEAD 同＝零新增）；探针 `scripts/_500_batch8_probe.py` **全绿**（11 死方法删除 / 4 活方法保留+注册表读写 / 采集侧死调用 0 / 端点删除 / push_service 4 函数+scheduler 注册完整）；定向回归 **81 passed**（push_service/428/463/426_p0）。停 daemon+看守 → 跑 → **已重启**。

**v1.7 批次5 实施（2026-09-30）**：用户「按 §九 开工批次5」→ **源管理/缓存/ECM/观测**，改动 6 文件（`data_source_manager.py` / `memory_cache.py` / `monitor.py` / `stg_quality.py` / `enhanced_cache_manager.py` / `ws_bridge.py`）+ 探针 1 新增：
- **#20（并发无锁）** `DataSourceManager` 新增 `_lock`（`RLock`），守护 `_update_active_source`/`get_data` 的 `active_source` 检查-赋值、`check_health` 的 `_last_health_check`、`reset_source`、`get_status_snapshot`（原非原子 RMW，多 Flask 请求共享单例 → 丢计数/竞态）。
- **#21（reset 不复位延迟量）** `reset_source` 一并复位 `avg_latency_ms`/`consecutive_successes`（原因延迟降级的源重置后立即被 `_evaluate_status` 重判 DEGRADED）。
- **#22（空结果判据）** 新增模块级 `_is_empty_result`（含 pandas 空 `DataFrame/Series`），`get_data`/`get_data_time_aware` 均改用（原判据仅识 `list/dict` → 空 DataFrame 被记 success 并当有效数据返回）。
- **#23（invalidate KeyError）** `memory_cache.invalidate` 非法 level 加容错（与 `get/set` 一致，原直接 `self._caches[level]` 抛 KeyError）。
- **#24（stats 不计过期）** `get_stats` 读前 `cache.expire()`；docstring 「必须可 pickle」修正。
- **#25（close 漏连接）** `ECM.close()` 关**全部 5 连接**（`conn/read_conn/snapshot_conn/compute_conn/compute_read_conn`，原仅 2 个 → 句柄泄漏）。
- **#26（裸名 NameError）** `_query_shard`/`_exec_shard` 预初始化 `sharding_manager = None`（原 else 分支在 import 失败后引用未绑定名）。
- **#27（假 commit）** 删 `cache_indicators` 末尾 `self.conn.commit()`（三张 indicator_* 在分库、`_insert_from_df` 已各自提交；对总库 commit 为 no-op）。
- **#28（告警 ID 碰撞）** `monitor` 告警 ID 改**单调计数器** `_alert_seq`（原 `len(_alerts)+1`，裁剪至 100 后与存活告警碰撞）。
- **#29（读方法无锁）** `get_metric_stats`/`get_alerts`/`acknowledge_alert`/`register_alert_callback` + 回调迭代均持 `_lock`。
- **#30（级别静默降级）** 未知/`None` 级别回退 `warning`（原 `getattr(logger, level.lower(), logger.info)` 静默降 INFO）。
- **#31（计数非原子）** `stg_quality._record_write_lock`/`get_write_lock_conflicts` 加 `_write_lock_conflicts_lock`。
- **#32（归因错误）** `validate_signal_rows` 顶层 `json.loads` 结果显式 `isinstance(dict)` 校验（原对 list/str/数字调 `.items()/set()` 抛异常被吞成「seven_dim_json 非法」）。
- **#33（浮点集脆弱）** `constant_guard` 判定改 `_all_constant_fallback`（`math.isclose` 容差 + 补兜底集，原精确 `set(row) <= {0.1,0.5,1.0}`）。
- **#34（吞异常无日志）** `daily_base`/`_count_null_fields` 补 `warning`（原静默 return 0 → 故障与「数据未就绪」不可区分）。
- **#35（死参数 + 弱校验）** `write_batch` 的 `expected_ratio` **接线**（严格模式升级告警）+ 从 `insert_sql` 占位符数推导 `expected_cols` 做**列数校验**（原仅校验行类型）。
- **#55（指数短码碰撞）** `ws_bridge` 指数匹配改**按市场限定**（`000001.SZ` 与上证 `1.000001` 短码同 → 原误标；现归一为 `market.code` 形态精确匹配）。
- **#56（降级重选同源）** 随 #20 持锁一并处理（`_update_active_source` 原子化），登记说明。
- **验证**：`py_compile` OK；ruff 6 文件 **clean**（`enhanced_cache_manager` 3 error 与 HEAD 同＝零新增）；探针 `scripts/_500_batch5_probe.py` **全绿**（空结果判据 / 持锁计数 16000 / reset 复位 / invalidate / close 5 连接 / 预初始化 / 告警 ID 单调 / 读锁 / 级别回退 / 常量容差 / expected_ratio / em_code）；定向回归 **89 passed, 2 skipped**（423/426_p0/425/services/483/436_b3）。停 daemon+看守 → 跑 → **已重启**。

**v1.6 批次4 实施（2026-09-30）**：用户「按 §九 开工批次4」→ **内存与分钟/重采样**，改动 3 文件（`in_memory_store.py` / `minute_backfill.py` / `kline_resampler.py`）+ 探针 1 新增：
- **#13（reset 漏清）** `InMemoryStateStore.clear_all` 补清 `_lhb_detail`（原遗漏 → 席位级龙虎榜跨交易日残留，读路径内存优先于缓存时被当「当日」数据）；`stats` 顺带加 `lhb_detail_codes`。
- **#14（浅拷贝）** 全部写/读方法由 `dict(r)` 改 `copy.deepcopy(r)`（原仅拷顶层，嵌套 dict/list 仍别名内部状态，违反类契约）。
- **#15（无界增长 + O(n)）** 分钟 K 线新增 `_minute_index`（按 `ts_code` 索引，单只读 O(k) 不再全量扫描）+ `_MINUTE_MAX_BARS=200 万` FIFO 裁剪（`_trim_minute_kline`，`append` 时触发）。
- **#16（分钟时间基准）** `_get_mootdx_minutes_safe`：(a) `enumerate` 取**位置索引**（不再 `int(idx)` 假设 0 基连续）；(b) 单日 **240 根上限**（超 240 跳过，避免生成 15:00 后不存在时间）；(c) `_cache_to_ecm` 的 `trade_date` 改 `pd.to_datetime` 归一（原 `str[:10]` 对紧凑串失配）。
- **#17（全历史重读）** `backfill_1min` 聚合改读 **`date_list` 窗口内**记录（原全量读 O(history)，可能用旧全量覆盖新聚合）。
- **#18（未排序 + 静默兜底）** `kline_resampler` 三个聚合函数**组内按时间排序**（原取 `bars[0]/bars[-1]` 从不排序 → Open/Close 可能颠倒）；`_parse_time/_parse_date` 解析失败 `warning`（不再静默 `now()`）。
- **#19（周键/跳过归一）** `FREQ_AGG_MAP['weekly']` 文档格式改 **ISO `%G-W%V`**（与实际 `isocalendar()` 一致）；同/粗频直返改走 `_normalize_bars`（排序归一，不静默跳过）。
- **#50（inf 低值）** `_resample_minute` 的 `low` 过滤 `None/缺失` 后取 min（原缺键即整组 `inf` 流入缓存）；全缺回退 0。
- **#51（连接泄漏）** `get_watchlist_stocks` SQLite 回退改 `with sqlite3.connect(...)`。
- **#52（静默吞错）** `minute_backfill` 三处 `_query_shard`（`aggregate_1min_to_60min` 交易日窗 / `ensure_minute_data` 覆盖计数 + 交易日窗）加 `warning`（原宽 except 静默 → 分库映射变化时不可区分）。**注**：`_check_watchlist_minute` 本体实为 `data_daemon._shard_fetchall`（公开分库读），OCR 归属有偏，按「可见告警」方向在 `minute_backfill` 侧处置。
- **#53（频串漂移）** `kline_resampler` 新增 `MINUTE_FREQS` 共享常量（`60min` 原仅现于分支元组）。
- **#54（元素未校验）** `resample` 过滤非 dict 元素（`data` 直取请求 body；原 `bar.get` 抛 `AttributeError`）。
- **验证**：`py_compile` OK；ruff 3 文件 **clean**（`minute_backfill` 1 error 与 HEAD 同＝零新增）；探针 `scripts/_500_batch4_probe.py` **全绿**（深拷贝 / 索引裁剪 / 位置索引+240 / 窗口聚合 / 乱序排序 / ISO 周键 / 非 dict 过滤 / inf 防护 / with 连接）；定向回归 **106 passed**（483/428/464_17/463）。停 daemon+看守 → 跑 → **已重启**。

**v1.5 批次3 实施（2026-09-30）**：用户「按 §九 开工批次3」→ **DataManager 读口径**，改动 `backend/app/data/__init__.py`（+ 测试 1 处日期脆性修正 + 探针 1 新增）：
- **#2 日期归一** 新增 `DataManager._normalize_date`（`YYYYMMDD`→`YYYY-MM-DD`），`get_cached_daily_data` 入口统一归一 → 分库分支与 ECM 回退**口径一致**（原分库分支原样绑定，紧凑格式静默不命中）。
- **#8 实例统一** 分库分支改走 `self._sharding_manager`（原裸 `from … import sharding_manager` → 分支判定可能与实际读路径不同实例）。
- **#9 降级可见** 分库读失败 `logger.debug` → `warning`。
- **#10 复权守卫**：`adj_factor` 先 `to_numeric` + `where(>0)`（零/负值视为缺失）再 ffill → 消除 0 因子产生的 `inf`；**基准因子非零/非 NaN 守卫**（原 `base_adj=0` → 全列 inf/NaN）；价格与量同源（因子已保证 >0）。
- **#11 行业排名**：显式按指数码聚合、取**最新交易日**记录（原 `seen[code]=r` 后覆盖保留的是最后插入项，非日期最新）。
- **#12 每股计数**：`sync_all_daily_data` 新增 `stock_done`，`max_stocks`/进度改按**股票数**（原按记录数，单只可贡献 >100 记录 → 边界非确定）。
- **#57 列名**：分库读改走 ECM **`_query_shard`**（`pd.read_sql` 带游标列名），删除硬编码列序假设（原 `execute_query` 返回元组后 `pd.DataFrame(rows, columns=[硬编码])`）。
- **#58 daily_basic 口径**：逐日回填分支归一 `trade_date` + 仅取白名单列（与 `sync_daily_basic_data` 一致）。
- **#59** `tushare.pro` 守卫：经核实 `get_daily_data` 等在 **provider 层**已有 `if not self.pro: return []` 守卫 → **不新增重复守卫**（原描述前提部分不成立，登记）。
- **附带（测试脆性，与批次3 无关但影响运行）**：`tests/test_464_17.py` 三处硬编码日期（`2026-08-25`/`2026-09-18`/`2026-05-20`）改**相对今天**——原值在今天（2026-09-30）已滑出 30 日窗口（cutoff=08-31）致 `test_margin_risk_30d_window` 恒失败；生产逻辑本身正确。
- **验证**：`py_compile` OK；ruff `__init__.py`+探针 **clean**；探针 `scripts/_500_batch3_probe.py` **全绿**（日期归一 / 分库走 _query_shard 保列名 / 降级 warning / 0 因子不产 NaN·基准 0 回退 / 行业取最新日 / 按股票数 / 白名单列）；定向回归 **138 passed**（463/462/464_17/464_dim4_batch1/2/457/419/323）。停 daemon+看守 → 跑 → **已重启**。

**v1.4 批次1 实施（2026-09-30）**：用户「按 §九 开工批次1」→ **预计算/因子正确性**，改动 4 文件（`precompute_indicator_manager.py` / `factor_precompute.py` / `market_universe.py` / `factors/calculator.py`）+ 探针 1 新增：
- **A#3（真多周期）** `compute_win_rates` 重构：`_WIN_HORIZONS=(5,10,20)` 各窗口**独立实算** `win_rate_*/avg_return_*`（原 10d/20d 与 5d **完全相同**＝假多周期）；移除旧 `lookahead` 形参。
- **#36（消除 N+1）** 原循环内每信号行 2 次 `_query_shard`（入场/出场价）→ 改**一次性批量载入** `[最早信号日, 今]` 的 `(ts_code,trade_date)->close` 映射后内存索引（实测查询 3 次）。
- **#37（双侧守卫）** entry/exit 价均做**非空 + 数值 + NaN** 校验（原仅守 entry，exit 为 NULL/NaN 时 `(exit-entry)` 抛 `TypeError`）。
- **#38（Sharpe 实算）** `_period_stats` 新增：`mean/std(ddof=1)*sqrt(252)`（年化，**对齐 `strategy_health_monitor`**），n≥5 且 std>0 才给值（原 sharpe_5d/20d 硬编码 `0.0`）。
- **#39（吞异常可见）** `except` 改 `logger.warning(..., exc_info=True)`。
- **#40（死参数）** `precompute_all_indicators` 删 `force`（无缓存分支、全仓零传参）。
- **#41（脏键）** `_batch_cache_factor_series` 日期映射改为「整数索引仅在有 `data.trade_date` 时映射、否则**跳过**」（原写 `"0"/"1"`…；并避免 `pd.to_datetime(0)→1970-01-01`）。
- **#42（死分支）** 删永不可达的重复 `pd.Timestamp` 分支。
- **#43（归一）** 新增 `_normalize_trade_date`（`pd.to_datetime(errors='coerce')` 严格解析 → `YYYY-MM-DD`，失败跳过）。
- **#44（缓存键/参数语义）** `factor_precompute.precompute_factor` docstring 明确「因子身份只由 `factor_name` 承载、kwargs 不入缓存键」；`factors/calculator.calculate_single_factor` **有 kwargs 时跳过缓存直算**（防命中另一套参数序列）。
- **#45（冗余 try）** `precompute_all_factors` 删永不触发的 `try/except`。
- **#46（索引对齐）** `get_cached_factors` 改显式 **outer join**（原 `result[name]=series` 遇异构索引产生 NaN 行/重复索引 `ValueError`）。
- **#47（吞错可见）** `get_cache_stats` 空结果补 warning（区分真空缓存/分库读失败）。
- **#48/#49** `market_universe`：`399` 段规则加注释说明（D4 更正：方向正确）；`stock_only_sql` 占位符/参数改**模块级预计算 + 长度断言**。
- **验证**：`py_compile` OK；ruff 4 文件 **clean**；探针 `scripts/_500_batch1_probe.py` **全绿**（多周期非恒等 / N+1→3 次 / NaN 守卫 / 脏键跳过 / 外连接）；**端到端真实库** `compute_win_rates` 10.4s、**6/6 策略行多周期非恒等**、Sharpe 非 0；定向回归 **51 passed, 4 xfailed**。停 daemon+看守 → 跑 → **已重启**。

**v1.3 批次2 实施（2026-09-30）**：用户「按 §九 开工批次2」→ **分库路由收口**，改动 `backend/app/data/sharding_manager.py`（+ 测试断言同步 + 探针 1 新增）：
- **#4 `get_write_lock` 原子化** — 新增 `_write_locks_lock`，`get_write_lock` 改「快路径 get + 双检锁建锁」（原裸 `if db_name not in self._write_locks: … = RLock()` 在并发首次使用同一分库时两线程各建一把锁 → 后者覆盖前者 → 该分库写不再互斥）。
- **#5 `get_connection` 错误路径不泄漏** — PRAGMA / `_ensure_snapshot_indexes` 包入 `try`；失败时 `conn.close()` 且**不入缓存**、异常上抛（原「先入缓存后初始化」→ 异常后既不关闭也不回滚 = 句柄泄漏 + 半初始化连接被复用）。
- **#6 `get_table_row_count` 前缀路由一致** — 白名单判据 `not in self._table_to_db` → **`is_registered(table_name)`**（含前缀规则，与 `get_db_for_table` 契约一致；原实现使动态表 `adj_factor_cache_YYYY` 恒返 0，属 426 D8 收口残留）；并补 **`_is_valid_identifier` 标识符纵深防御**（新模块级正则）。
- **#7**（`init_sharding` close_all 在途线程）**按计划仅登记**（窄窗口，不改）。
- **验证**：`py_compile` OK；ruff `sharding_manager.py`+探针 **clean**（`test_428` 30→30 零新增）；探针 `scripts/_500_batch2_probe.py` **全绿**（#4 8 线程并发同锁 / #5 失败关闭且不入缓存 / #6 前缀表计数=2、非法标识符被拒）；定向回归 **155 passed**（426/428/458/436/491/321/447 等 12 文件）。停 daemon+看守 → 跑 → **已重启**。

**v1.2 拍板回填（2026-09-30）**：四项口径经用户**逐项选定**——**Q1 = B**（删除六模块群）/ **Q2 = A**（删 `ws_bridge` 死分支 + 删 `_broadcast_limit_pools`）/ **Q3 = A**（各周期按各自 lookahead 实算）/ **Q4 = 全部批次纳入**。据此 **§九 八批次全部纳入实施范围**（开工顺序见 §九「依赖顺序」）。
**v1.1 修订说明（2026-09-30）**：经用户要求「核对 500 号方案与对话内容，如有遗漏和错误进行修订」，回核 OCR 原始输出（`/tmp/stg_ocr_20260930/seg1~seg6`，**逐条比对 6 段全部条目头**）后订正：
1. **计数订正（原为实质性错误）**：v1.0 §一/§二 将 B 类标为 **18**、C 类标为 **23**、总数标 **~44**，均与正文实际编号不符。实际 v1.0 正文编号已是 **B 类 #4~#35（32 项）、C 类 #36~#66（31 项）** ⇒ 原文档自相矛盾。本版统一为 **A3 + B56 + C40 = 99 项**（C 类重编号 #60~#99）。
2. **遗漏补录（原为遗漏）**：v1.0 漏计 **seg6 预计算段 7 条**（`compute_win_rates` N+1/exit_price/吞异常、`precompute_all_indicators` 死参数 `force`、`factor_precompute` 冗余 try/索引对齐/stats 吞错）→ 补 **B 类 #36~#40、#45~#47**；另补 seg5/seg4 3 条（`__init__` 位置列/重复路径格式/pro 守卫 → **#57~#59**）、#48~#56（宇宙/分钟/重采样/推送/源管理）→ **B 类共 56 项**；并新增 **C-7 死存储/死表/视图重复 9 项（#91~#99，与 426 D4~D7 同源）**。
3. **职责切分**：A#3 收敛为「多周期恒等」单一数据正确性缺陷；Sharpe 恒 0 等移入 B#38。
4. **交叉引用订正**：`health_checker` 引用「498#7/#9」→ **498#7**（#9 属 `minute_data_manager`）；「见 §七 D2」→ **§六 D2**；D 类补 1 项（`market_universe` 399）→ **4 项**。
**来源**：2026-09-30 用户要求「调用 OCR 对系统的 STG 整体实际代码配置进行检查，相关检查的问题请在对话框内进行说明，不要修改方案和代码」→ 对话框内出具核查报告 → 用户要求「落成 500-STG存储层OCR核查与处置.md」。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek `deepseek-chat`）按功能拆 **6 段**全量扫描 STG 层，共 **106 条**原始发现，**逐条人工核实**（OCR 按文件/片段审查，存在上下文误报，全部对照真实代码核对；误报/需更正单列 §六）。
**范围（STG＝第 2 层存储层）**：`backend/app/data/` 全部存储相关模块——ECM 缓存管理器、分库路由/规则/迁移、仓储质量/健康/监控/盘点、内存态存储、DataManager 网关、预计算/分钟/宇宙。
**侧重**：分库路由与读写口径一致性 × 与 356（分库设计）/423（仓储中心化）/424/426（核查整改）的一致性 + 存储正确性/健壮性 + 死模块与零消费方识别。
**基线**：HEAD `4113946`（= origin/main；工作树含 497 遗留登记 4 项未推送改动）；daemon 运行中（看守 `start_daemon.sh`）。
**边界（2026-09-30 订正）**：原「445 引擎锁定」的**果层限制（判定阈值/权重/方向语义须独立号 + 依据 + 验证）源于「修正 SIG 对应 dim8 输出股票现状」阶段，现已失效** ⇒ **现阶段检查出的错误，凡对系统运行有影响均须修正，不再区分因/果、不必独立号拍板**（历史档案见记忆 `445-freeze-vs-fact-layer.md`；现行口径 `engine-lock-stage-scope.md`）。**改动的编号文档记录与验证口径（`py_compile`+ruff+回归+探针）保留，属质量流程而非「能不能改」的门槛**。

**OCR 会话（6 段）**：`80e75202…`（ECM，5 条）/ `a5a5af0a…`（分库/规则/迁移，27 条）/ `2dd82dba…`（质量/健康/监控/盘点，23 条）/ `9b9496e4…`（内存/网关，19 条）/ `fe7107dd…`（DataManager，10 条）/ `946e398c…`（预计算/分钟/宇宙，22 条）。原始输出：`/tmp/stg_ocr_20260930/seg1~seg6_*.md`。

---

## 一、核查背景与总体结论

- STG 是「写入网关 → 分库路由 → 质量校验 → 读取分发」的第 2 层；356（分库设计）/423（仓储中心化）/424（存储核查）为既有治理依据，426 §0.1 已复审分库设计与存储管理（D1-D8 主要项已落地）。
- 本次 OCR 全量扫 + 人工核实结论：
  - **106 条原始发现 → 归并 99 项**（A 3 / B 56 / C 40；其中 **C-7 #91~#99 为本次回核新补、非 OCR 原始条目**）；另 **D 类 4 条**误报·更正。
  - **当前生效路径上的高优先缺陷 3 项**：`ws_bridge` 推送链路整体失效（#1）、`DataManager.get_cached_daily_data` 分库读日期格式不归一（#2）、`compute_win_rates` 产出恒等多周期指标（#3）。
  - **生效路径上的中低项 56 项**（预计算/因子缓存键正确性、并发无锁、错误路径资源泄漏、静默兜底、口径分叉、重采样顺序脆弱等）。
  - **死模块 / 零消费方 40 项**（`config_manager` / `migration` / `init_sharding` / `health_checker` / `data_inventory` / `create_views` 六模块群**生产全仓零引用** + 死存储/死表 9 项；其代码问题成立，但**当前不影响运行**）。
  - **OCR 误报/需更正 4 项**（§六）。
  - **未计入的 OCR 条目**：ECM `get_market_ma20_ratio` / `get_market_limit_ratio` 两处 `close`/`change_pct` 列名错（`indicator_ma` 无 `close`、`daily_cache` 用 `pct_chg`）——经调用图核实**仅 `get_market_ma20_ratio` 一处被 `status_engine.py:178` 经 `getattr` 调用（市场级温度兜底路径，异常被吞 → 静默返 0.5），`get_market_limit_ratio` 等其余同族方法全仓无调用方（休眠）**；该缺陷属实但**当前影响面窄**，随 #3 同批或单列（登记，不计入 A/B）。
  - 与 496/498/499 重叠项（daemon 效率、分库读错库、连接缓存锁、未登记告警等）**已实施，不重复计入**；与 426 D1-D8 已落地项的关系见 §七。
  - **本档归并口径**：分级统计见 §二；逐项见 §三（A）/§四（B）/§五（C）；**同一处代码可能同时被多条 OCR 命中**（如 `compute_win_rates` 被 6 条命中 → A#3 + B#36~#39；monitor 锁 4 条 → #29；`split_table_by_year` 2 条 → #70），故项数少于 OCR 原始 106 条。

---

## 二、发现总览

| 级别 | 项数 | 主题 |
|------|------|------|
| 🔴 A 类（生效路径·高优先） | 3 | 推送链路整体失效、分库读日期格式不归一、预计算多周期指标恒等（假多周期） |
| 🟠 B 类（生效路径·中低） | 56 | **预计算**（N+1 查询、exit_price 无守卫、Sharpe 恒 0、吞异常、死参数 force）· **因子**（trade_date 脏键、死分支、日期归一窄、缓存键缺参数、冗余 try、索引对齐、stats 吞错）· **宇宙**（399 前缀、占位符断言）· **分钟**（`inf` 低值、连接泄漏、私有 API+吞错）· **重采样**（60min 不一致、元素未校验）· **推送**（短码碰撞）· **源管理**（重选同源）· **DataManager**（位置列、重复路径格式、pro 守卫）· **分库路由**（写锁竞态、连接泄漏、前缀路由）· **网关/内存/观测**（日期口径、裸名实例、debug 静默、复权基准、行业排名、每股计数、漏清 lhb_detail、浅拷贝、O(n) 拷贝、单例无锁、延迟量、空结果判据、invalidate、expire、close 漏连接、假 commit、monitor ID/锁/级别、质量归因/死参数） |
| ⚪ C 类（死模块/零消费） | 40 | `config_manager`/`migration`/`init_sharding`/`health_checker`/`data_inventory`/`create_views` 六模块群（#60~#90）＋ 死存储/死表/视图重复（#91~#99） |
| 🟡 D 类（误报/需更正） | 4 | 分库分支「忽略 adj」（误报）、`health_checker`「忽略 elapsed」（需更正）、`monitor` 单位（信息类）、`market_universe` 399（需更正） |

> 「实证」＝本次已对照真实代码/DB schema/调用图确认。**本档 A/B/C 类均经逐条代码核验**（无「OCR-only」未核项）。

---

## 三、A 类：生效路径高优先（3 项，已实证）

> ✅ **A#3 已于批次1 实施**（真多周期 + Sharpe 实算）；✅ **A#2 已于批次3 实施**（日期归一）；✅ **A#1 已于批次8 实施**（死分支删除，Q2=A）。以下为原始核查记录。

### #1 `ws_bridge.py` 推送链路整体失效（`_api_push_active=True` 恒真）
- **位置**：`backend/app/data/ws_bridge.py:41`（初始化 `self._api_push_active = True`）→ 7 处 `if self._api_push_active: return`（:116/:139/:178/:191/:203/:217/:245）。
- **现象**：全仓仅 `:41` 一处赋值（`grep _api_push_active` 确认），故**所有 `_broadcast_*` 方法立即返回** → 采集线程推送路径**不可达**；`routes/realtime.py:364` 的 `trigger_publish` 端点调用 `on_collect_complete('market_snapshot')` **静默无效果**（注释却写「手动触发 WsBridge 推送」）。
- **实证**：真实推送由 **API 进程** `services/push_service.py`（`sio.emit('market:summary')` 等，事件名与 ws_bridge 相同）承担 → **非线上故障**，但该模块＝**失效死代码 + 误导性端点**。
- **附带**：`_broadcast_limit_pools`（:201）**无任何调用方**（`sector_and_limit` 分支只调 `_broadcast_sectors`）→ `market:limit_pools` 事件**永不产出**。
- **方向**：A 删死分支（保留 `_api_push_active` 语义注释 + 删 `_broadcast_limit_pools`）；或 B 将开关改为构造参数/env，使 API 进程可真正启用（需先确认 API 进程是否复用该模块）。

### #2 `DataManager.get_cached_daily_data` 分库读日期格式不归一（静默空/截断）
- **位置**：`backend/app/data/__init__.py:193-200`。
- **现象**：分库分支把 `start_date/end_date` **原样**绑定到 `daily_cache.trade_date`（存 `YYYY-MM-DD`）；而 ECM 回退 `get_cached_daily`（`enhanced_cache_manager.py:1401-1412`）**显式把 `YYYYMMDD` 归一为 `YYYY-MM-DD`**。→ 调用方传紧凑格式时，分库路径**静默返回空/截断**（不报错），**两条读路径口径分叉**。
- **实证**：`app/data/chip_distribution_service.py:229` 的 `start_date/ref_date` 来自上游、格式不定 → 有命中风险；`ECM.get_cached_daily` 归一逻辑已核（对）。
- **方向**：分库分支与 ECM 同口径归一（或统一在入口归一）。

### #3 `compute_win_rates` 产出「同名恒等」的多周期指标（数据正确性）
- **位置**：`backend/app/data/precompute_indicator_manager.py:167-171`。
- **现象**：`win_rate_5d/10d/20d` 与 `avg_return_5d/20d` **全部由同一个 `lookahead=5` 的 `returns` 计算**（10d/20d 列与 5d **完全相同**），与 `win_rate_cache` 表结构与函数契约矛盾 → 下游任何消费方读到的都是**假多周期**。
- **实证**：DB 实查 `win_rate_cache` 列 = `win_rate_5d/10d/20d + avg_return_5d/20d + sharpe_5d/20d`（表结构与「多周期」语义一致，实现未兑现）；落库链 `data_daemon.py:1184 manager.compute_win_rates()` → `cache_win_rates`。
- **性质**：属 RAW 预计算产出正确性（写入 STG 表），非 STG 存储本身。
- **方向**：各周期按各自 lookahead 计算（或删 10d/20d 列）。
- **同函数其余子项**（性能/健壮性，列 B 类）：N+1 查询（#36）、exit_price 无守卫（#37）、Sharpe 恒 0（#38）、吞异常（#39）。

---

## 四、B 类：生效路径中低优先（56 项，已实证）

### 预计算指标（`precompute_indicator_manager.py`）
- **#36 `compute_win_rates` N+1 查询（:145-152）** — 循环内每信号行 2 次 `_query_shard`（入场/出场价），O(signals) 往返。**方向**：批量取入场/出场 close 后内存索引。
- **#37 `compute_win_rates` exit_price 无守卫（:155-158）** — `daily_cache.close` 为 NULL/NaN 时 `(exit_price - entry_price)` 抛 `TypeError`（仅 `entry_price>0` 已守）。**方向**：两值均需数值/非空校验。
- **#38 `compute_win_rates` Sharpe 恒 0（:172-173）** — `sharpe_5d/sharpe_20d` 硬编码 `0.0`，下游恒收常量假值。**注**：与 A 类 #3 同函数。**方向**：实算或显式登记缺省。
- **#39 `compute_win_rates` 吞异常（:178-180）** — `except Exception` 仅 warning + 返回空 DataFrame，DB/schema 故障与「合法空」不可区分。**方向**：收窄异常或 `exc_info=True`。
- **#40 `precompute_all_indicators` 死参数 `force`（:31）** — 形参 `force` 声明「忽略已有缓存」但函数体**无缓存查询/force 分支**，参数完全未用、docstring 失真。**方向**：实现或删参。

### 因子预计算（`factor_precompute.py`）
- **#41 `_batch_cache_factor_series` trade_date 兜底脏键（:74-75）** — `else: trade_date = str(idx)` 对越界/偏移索引（tail 切片、rolling/shifted 窗口）写入 `"0"`/`"1"`… 无意义键，永不匹配 `get_cached_factor` 的日期有序读，且与他处位置键碰撞。**方向**：无法映射时跳过/告警。
- **#42 `_batch_cache_factor_series` 死分支（:72-73）** — `elif isinstance(idx, (datetime, pd.Timestamp))` 已覆盖，紧随的 `elif isinstance(idx, pd.Timestamp)` **永不可达**。**方向**：删除。
- **#43 日期归一过窄（:83-85）** — 仅转换 8 位纯数字串，`'nan'`/`'2026-8-1'`/`'2026/08/01'`/因子名等原样入库 → `ORDER BY trade_date`/`< cutoff` 比较错乱。**方向**：`pd.to_datetime(errors='coerce')` 校验后跳过。
- **#44 因子缓存键缺参数（:94-97）** — 缓存记录 key 仅由 `factor_name` 构成，但 `**kwargs`（如 `period`）已转发 `calculate_single_factor` → 同名不同参因子**互相覆盖**、读方无法区分。**方向**：参数签名并入缓存键。
- **#45 `precompute_all_factors` 冗余 try/except（:168-173）** — `calculate_single_factor` 内部已吞异常返 None、`precompute_factor` 外层已 try/except 返 False ⇒ 此层异常处理器**永不触发**，仅增噪声且 `results[name]=False` 混淆「未满足数据要求」与「真失败」。**方向**：移除或返回富状态。
- **#46 `get_cached_factors` 索引对齐脆弱（:187-190）** — `result[name] = series` 按 index 对齐；各因子 series 日期索引不一致时引入 NaN 行，重复 trade_date 时抛 `ValueError`。**方向**：显式 outer join 或用长表。
- **#47 `get_cache_stats` 经 `_query_shard` 吞错（:200）** — `_query_shard` 任意失败返空 DataFrame ⇒ 瞬时 DB 错误与「真空缓存」不可区分、恒报 0。**方向**：公开 stats 方法或显式处理错误。

### 个股宇宙（`market_universe.py`）
- **#48 `399` 前缀忽略交易所后缀（:39-41）** — `startswith('399')`/`NOT LIKE '399%'` 仅按 6 位码前缀匹配、忽略 `.SZ/.SH` 后缀（docstring 自述后缀不可忽略）。**实测方向正确**（399xxx 均深市指数），属**理论风险**，见 §六 D4。**方向**：限定 `and code.endswith('.SZ')` 或注释说明。
- **#49 `stock_only_sql` 无长度断言 + 每次重建（:51-54）** — `sorted(_INDEX_CODE_SET)` 与占位符数若不等则参数错位；每次调用重建占位符串。**方向**：模块级预计算 + 长度断言。

### 分钟回填（`minute_backfill.py`）
- **#50 聚合 `inf` 低值（:211）** — `min(b.get('low', float('inf')) for b in bars)`：任一 bar 缺 `low` 键即整组得 `float('inf')` 并流入缓存 `low`（默认值仅逐元素生效）。**方向**：过滤有效 low / `min(..., default=0)`。
- **#51 `_get_watchlist_codes` 连接非上下文管理（:65-70）** — 正常路径 `conn.close()`，但 `fetchall()` 抛错即泄漏（外层宽 `except` 仅日志）。**方向**：`with sqlite3.connect(...)`。
- **#52 `_check_watchlist_minute` 调私有 `ecm._query_shard` + 宽 except（:493-497）** — 直调私有 API 且宽 except 吞错 → 分库映射/表位变化时**静默报 0 缺失股**（下游 60min 聚合静默 no-op）。**方向**：公开方法或 warning 日志。

### 重采样（`kline_resampler.py`）
- **#53 `60min` 支持不一致 + 频串重复（:57）** — `'60min'` 在分钟元组内，但对外 `source_freqs` 列表未含；频串多处硬编码易漂移。**方向**：共享常量。
- **#54 输入 `data` 未校验元素为 dict（:78-80）** — `data` 直取请求 body；非 mapping 元素 `bar.get(...)` 抛 `AttributeError`，缺 `open/high/low` 静默取 0 → 聚合失真。**方向**：逐 bar 类型校验。

### 推送桥接（`ws_bridge.py`）
- **#55 指数匹配用裸 6 位短码（:158-161）** — `code.split('.')[0]` 对 `000001.SZ` 得 `000001`，与上证指数 `1.000001` 的短码 `000001` 相等 → 无关个股被误标指数名混入 `market:indices`。**方向**：按市场限定码匹配。**注**：该路径本身已被 #1 屏蔽（不可达），与 #1 同批处置。

### 源管理（`data_source_manager.py`）
- **#56 降级递归可能重选同源（:309-312）** — `_update_active_source()` 纯按优先级/可用性重选，可再选中同一源（FALLBACK 但非 UNAVAILABLE）→ 「自动切换至备用数据源」日志失真，实际仅靠 `_retry` 深度上限终止。**方向**：记录已试源。

### DataManager 网关（`app/data/__init__.py`）
- **#57 位置列硬编码映射（:204-205）** — DataFrame 由固定列名列表切片至 `len(result[0])` 构建，假设物理列序与映射一致；列增/减/重排则截断或错标，且空/非序列行可能抛错 → 污染下游 OHLC/复权消费。**方向**：按游标描述构建或显式校验列数。
- **#58 重复路径 trade_date 格式不归一（:934-938）** — 逐日补 basic 分支 `self.tushare.get_daily_basic(trade_date=date_str)` 后**直接** `cache_daily_basic_data(df)`，既不归一 `trade_date` 也不过滤未知列（与 `sync_daily_basic_data` 不一致）→ 同列混入 `YYYYMMDD` 与 `.date()` 两种格式，破坏分库读的字符串范围比较。
- **#59 `self.tushare.pro` 守卫口径不一致（:75-77）** — 多个 `sync_*` 守卫检查 `not self.tushare.pro`，但 `sync_daily_data` 调 `get_daily_data(...)` 无此守卫，且 AKShare 回退仅在 `if not data and self._source_mgr` 时触发 → `pro` 为 None 时主同步的 AKShare 回退实际不可达。**方向**：统一守卫并显式路由回退。

### 分库路由（`sharding_manager.py`，续）
> 以下 #4~#7 为 v1.0 已编号项（保留原编号，便于与对话记录对照）；#8~#35 同见下节。
- **#4 `get_write_lock` 检查-建锁竞态（:211）** — `get_connection` 已在 498#20 加 `_conn_lock` 原子化，但 `get_write_lock` 仍是裸 `if db_name not in self._write_locks: … = RLock()`。并发首次使用同一分库时两线程可各持**不同** RLock → 该分库写不再互斥。**方向**：复用 `_conn_lock`。
- **#5 `get_connection` 错误路径连接泄漏（:166）** — `sqlite3.connect` 成功后若任一 PRAGMA / `_ensure_snapshot_indexes` 抛错，`conn` 既不关闭也不入缓存 → 句柄泄漏。**方向**：try/finally 关闭。
- **#6 `get_table_row_count` 白名单与路由契约不一致（:362）** — `if table_name not in self._table_to_db: return 0` **绕过前缀规则**：动态表 `adj_factor_cache_2026` 走 `get_db_for_table` 命中 `history_cache.db`，但此处返回 **0**。**方向**：改用 `is_registered`。
- **#7 `init_sharding` 关闭旧实例连接时在途线程（:402）** — `_old.close_all()` 时其他线程可能仍持旧 `sharding_manager` 连接 → 「Cannot operate on a closed database」。**窗口窄（daemon 启动/测试切沙盒）**，仅登记。

### DataManager 网关（`app/data/__init__.py`，除 #2）
- **#8 分库分支用重导入的 `sharding_manager`（:189-191）** — `table_exists('daily_cache')` 用裸 `from app.data.sharding_manager import sharding_manager`，而回退与 `get_cached_daily_basic` 用 `self._sharding_manager` → 分支判定可能基于**不同实例**（`table_exists` 返 False 即全量走 ECM，即使 `self._sharding_manager` 可用）。**方向**：统一 `self._sharding_manager`。
- **#9 分库读失败仅 `logger.debug`（:209-213）** — 主读路径 schema/日期口径回归与「真无数据」**不可区分**。**方向**：升 warning。
- **#10 `_apply_adjust_factor` 基准/零因子无守卫（:236-237）** — 价格用**未替换** `adj_factor`、成交量用 `.replace(0,1)`；`base_adj = iloc[0]/iloc[-1]` 未校验非零/非 NaN → 基准为 0 时得 inf/全 NaN，且 `_valid_ratio<0.5` 只数非空、抓不到零因子。**方向**：单条 `f = adj_factor.where(>0, 1)` 同施价格/量 + 基准非零断言。
- **#11 `get_all_industry_rankings`「最新子行业」注释与实现不符（:1792）** — `seen[r['code']] = r` 迭代插入有序的 `SUB_INDUSTRY_TO_CODE.items()`，「后覆盖」保留**最后插入**而非**数据日期最新**，排名用 `pct` 实际任意。**方向**：显式按指数码聚合。
- **#12 `sync_all_daily_data` 按**记录数**而非股票数（:170-175）** — `max_stocks`/commit 以累计 `count`（记录）判定，单只股票可贡献 >100 记录 → 边界非确定、`resume_from` 仅能在股票边界续传。**方向**：分离每股计数。

### 内存态存储（`in_memory_store.py`）
- **#13 `clear_all` 漏清 `_lhb_detail`（:247）** — 日终 reset（`scheduler_manager.py:394` 调 `clear_all`）清快了 `_snapshot/_sectors/_top_stocks/_limit_pools/_minute_kline/_lhb/_news`，**唯独未清 `_lhb_detail`**（另有独立 `clear_lhb_detail` 存在）→ 席位级龙虎榜跨交易日残留；`data/__init__.py:1054` 读路径**内存优先于缓存**，可能被当「当日」数据。**方向**：补 `_lhb_detail.clear()`。
- **#14 读方法返回浅拷贝（:86 等）** — `dict(r)` 只拷顶层，嵌套 dict/list 仍别名内部状态；类契约声明「浅拷贝副本，防止外部引用污染」。**方向**：`copy.deepcopy` 或文档化扁平假设。
- **#15 `get_minute_kline` O(n) 全量拷 + 无界增长（:170）** — 盘中 `_minute_kline` 追加式无界增长，每次读取在全局 RLock 下全量拷贝（过滤分支 O(n)）→ 读写互相阻塞。**方向**：按 `ts_code` 索引/裁剪旧 bar。

### 分钟与重采样（`minute_backfill.py` / `kline_resampler.py`）
- **#16 `_get_mootdx_minutes_safe` 索引/240 根/日期截断（:115/:122/:156）** — (a) `i = int(idx)` 假设索引为 0 基连续整数（mootdx 若返回字符串/非 0 基索引 → 时间映射整体错位）；(b) `_bar_time` 假设每日恰 240 根（数据不足时下午时间整体前移）；(c) `_cache_to_ecm` `trade_date = trade_time.astype(str).str[:10]` 未校验格式（`'20260929'` 原样截成 `'20260929'`）。**注**：498 批次4 已修午休跳段（#4），此三点未覆盖。**方向**：`enumerate` 取位置索引 + 按实际根数推导 + `pd.to_datetime` 归一。
- **#17 `backfill_1min` 全历史重读重采样（:328）** — 每次重读该股**全部**缓存 1min 历史并重写 5/15/30/60min（O(history)），可能用旧全量覆盖新聚合。**注**：498#41 修的是 `aggregate_1min_to_60min`，此处是不同函数。**方向**：限 `date_list` 窗口。
- **#18 `kline_resampler` OHLC 未排序 + 时间静默兜底（:84-88/:149-155）** — 聚合取 `bars[0]` 作 Open、`bars[-1]` 作 Close（**从不排序**）；`_parse_time/_parse_date` 解析失败**静默回退 `datetime.now()`** → 错分桶。该模块经 `routes/kline_resampler_api.py` **对外可用**（POST body 传 `data`）。**方向**：组内按时间排序 + 解析失败告警/拒绝。
- **#19 `kline_resampler` 周键不一致 + 快捷返回跳过归一（:30/:52-55）** — 文档格式 `%Y-W%W`（周一起算，含 00 周）与实际分组 `isocalendar()` 不一致；`resample` 同/粗频直接 return 跳过逐 bar 归一。**方向**：统一 ISO 周键 + 归一后返回。

### 源管理与内存缓存（`data_source_manager.py` / `memory_cache.py`）
- **#20 `data_source_manager` 单例并发无锁（:130）** — `active_source` 检查-赋值、`consecutive_failures/successes +=`、`avg_latency_ms = …*0.7+…` 均为非原子 RMW，被多 Flask 请求共享。**方向**：`threading.Lock` 守护可变共享态。
- **#21 `reset_source` 未复位延迟量（:418）** — 重置 `status/consecutive_failures/failures`，但**未复位 `avg_latency_ms`/`consecutive_successes`** → 因延迟降级的源重置后立即被 `_evaluate_status` 重判 DEGRADED。**方向**：一并复位。
- **#22 空结果判据仅识 `list/dict`（:363）** — 空 `DataFrame`/`Series`（非 list/dict）被**记为 success 并当有效数据返回**。**方向**：按 `len()==0`/`.empty` 归一判定。
- **#23 `memory_cache.invalidate` 非法 level 抛 KeyError（:110）** — `get/set` 回退 `'realtime'`、`clear` 检查成员，唯 `invalidate` 直接 `self._caches[level]`。**方向**：`get(level)` 容错。
- **#24 `memory_cache.get_stats` 不 `expire()` + docstring 矛盾（:127/:74）** — `len(cache)` 计入已过期项；docstring 声称「必须可 pickle」与 TTLCache 实际无此限制矛盾。**方向**：读前 `cache.expire()` + 更正文档。

### ECM 与观测（`enhanced_cache_manager.py` / `monitor.py` / `stg_quality.py`）
- **#25 `ECM.close()` 只关 `conn`/`snapshot_conn`（:1855）** — 漏 `read_conn`/`compute_conn`/`compute_read_conn`（均 `__init__` 打开）。**方向**：`hasattr` 守护逐个关闭。
- **#26 `_query_shard` else 分支裸用 `sharding_manager`（:534）** — 名字仅在 `try: from … import sharding_manager` 内绑定；导入失败（`db_name=None`）时该分支 `NameError`（被上层吞）。**方向**：`try` 前初始化 `sharding_manager = None`。
- **#27 `_insert_from_df` 后 `self.conn.commit()` 对分库写为 no-op（:1486）** — 指标表经路由落分库、`_insert_from_df` 已各自 commit；末尾 commit 仅提交总库连接 → **假原子性 + 噪声**。**方向**：移除或加注。
- **#28 `monitor` 告警 ID 用 `len(self._alerts)+1`（:81）** — `_alerts` 裁剪至 100 条后新 ID 与存活告警**碰撞** → `acknowledge_alert(id)` 可能确认**无关**告警。**方向**：单调计数器。**注**：`get_alerts`/`acknowledge_alert` 目前**无生产读取方**（`monitor` 仅 `record_metric`/`create_alert` 被 daemon 消费）。
- **#29 `monitor` 读方法未持锁（:112/:130/:137/:108）** — `get_metric_stats`/`get_alerts`/`acknowledge_alert`/`register_alert_callback` 未持 `self._lock`，而 `create_alert`/`record_metric` 持锁并**整体替换**列表 → 并发读者可见不一致/`RuntimeError`。
- **#30 `monitor` 日志级别回退到 INFO（:98）** — `getattr(logger, level.lower(), logger.info)` 对未知/`None` 级别**静默降为 INFO**（CRITICAL 可能被记成 INFO）。**方向**：校验级别 + 回退 warning。
- **#31 `stg_quality._record_write_lock` 全局无锁（:129）** — `_write_lock_conflicts` get-then-set 非原子（daemon 多线程写）→ 计数丢失。**方向**：`Counter` + 锁。
- **#32 `stg_quality.validate_signal_rows` 非 dict 归因错误（:520）** — `json.loads` 得 list/str/数字时 `.items()`/`set()` 抛异常被吞成**「seven_dim_json 非法」**（原因不符）。**方向**：显式 `isinstance(sd_obj, dict)`。
- **#33 `stg_quality.constant_guard` 精确浮点集判定脆弱（:428）** — `set(row) <= {0.1, 0.5, 1.0}` 精确浮点比较脆弱、兜底集不全。**方向**：`math.isclose`/取整比较。
- **#34 `stg_quality.daily_base/_baseline_rows/_count_null_fields` 吞异常无日志（:332/:335）** — 持久 DB 故障与「数据未就绪」不可区分。**方向**：warning 日志。
- **#35 `stg_quality.write_batch` 死参数 + 写前校验弱（:224/:190）** — `expected_ratio` 完全未使用；`validate_before_write` 只校验行是 list/tuple、不校验列数。**方向**：接线或删参；补列数校验。

> 说明：B 类影响最直接的三项为 **#13（日终 reset 漏字段）**、**#4（写锁竞态）**、**#2（日期口径）**；其余多为健壮性/一致性边界。

---

## 五、C 类：死模块 / 零消费方（40 项，代码问题成立但不影响运行）

> 以下 **6 个模块群**在生产全仓**零引用**（`grep` 已核）；其 OCR 问题多为高/中危，但**当前无运行影响**，仅作档案登记。**实施前须再核引用状态**（避免遗漏动态 import）。编号 **#60~#90** 为六模块群；**#91~#99** 为本次回核新补的死存储/死表项（与 426 §0.1 D6/D7 同源，属未随 426 收口的残留，见 §七）。
>
> **✅ 批次6 已处置（2026-09-30，Q1=B 经复核收窄）**：**C-1~C-5 五模块已 `git rm` 删除**（`config_manager` / `migration` / `init_sharding`模块 / `health_checker` / `data_inventory`）；**C-6 `create_views.py` 经复核更正——非死模块**（`create_adj_factor_view` 活代码），仅删 4 个死函数、保留模块。故 C-1~C-6 条目现为**历史核查记录**（代码已删/瘦身）。

### C-1 `app/data/config_manager.py`（**零引用**；生产用 `app.services.runtime_config`）
- **#60 `save_config` 非原子写 + 失败不还原（:92）** — 直接截断原文件写入，中途中断即损坏；`except` 记日志但**不还原刚做的备份**。**方向**：临时文件 + `os.replace`。
- **#61 备份秒级时间戳碰撞（:88）** — `%Y%m%d%H%M%S` 同秒两次保存覆盖同一 `.bak` → 回滚保真度丢失。
- **#62 `set_config` 中间键非 dict 崩溃（:162）** — 中间节点是标量/list 时 `current[k]` 抛 `TypeError`/错嵌。
- **#63 `_validate` 不校验列表元素 + 非 dict 子 schema（:196）** — 列表元素任意通过；`sub_schema.get(...)` 对非 dict schema 抛 `AttributeError`。
- **#64 `safe_load` 空/异常混同（:69）** — 空文档与解析失败均返回 `{}`，损坏文件留存、无失败信号。
- **#65 模块级单例无锁（:31）** — `_configs`/`_config_history` 并发改无锁。

### C-2 `app/data/migration.py`（**零引用**）
- **#66 SQL 标识符拼接注入面（:86 等多处）** — `table_name`/`date_column`/列名/列型直插 SQL。**方向**：白名单/`^[A-Za-z_][A-Za-z0-9_]*$`。
- **#67 `restore_database` 未校验即覆盖库（:62）** — 任意路径直接 `copy2` 覆盖活库，无存在/有效/目录校验，无路径约束、无先备份。
- **#68 `convert_date_format` 静默丢行（:132）** — 无法解析的行 `except: pass`，但仍报 `converted_count`。
- **#69 `create_sql.replace` 非锚定替换（:159）** — 表名子串出现在列名/默认值/约束中亦被改写。
- **#70 `split_table_by_year` 跨连接事务交织（:196）** + **LIKE 前缀匹配（:200）** — 委托建表另开连接并发写同一库；`LIKE '{year}%'` 模糊匹配。
- **#71 `migrate_to_sharding` 失败不回滚（:261）** — 部分失败仅日志、未 `rollback` 即关连接。
- **#72 `get_table_stats` 返回全库尺寸（:279）** — 无表/页过滤，键名 `db_size` 误导。
- **#73 冗余局部 import（:123）** — `convert_date_format` 内重复 `import datetime`。

### C-3 `app/data/init_sharding.py`（**零引用**；daemon 用的是 `sharding_manager.init_sharding`，同名不同物）
- **#74 迁移非幂等（:158）** — 建表 `IF NOT EXISTS` 后**无条件** `INSERT`，二次运行重复/主键冲突。**方向**：`INSERT OR IGNORE`/跳过已填表。
- **#75 `fetchall` 整表入内存（:148）** — `daily_cache`/`minute_kline_cache` 可致内存爆。**方向**：游标迭代/分批。
- **#76 静默 `except: continue`（:101）** — 源库发现错误全丢，无日志。
- **#77 主流程忽略返回值（:289）** — `create_adj_factor_year_tables` 在 `init_sharding_databases` 失败时仍继续。
- **#78 冗余内层 `import sqlite3`（:91）**。

### C-4 `app/data/health_checker.py`（**零引用**；**498#7** 已删其唯一 vestigial 写入）
- **#79 `time.time()` 非单调（:40）** — NTP 调整可致 `elapsed` 负/失真。**方向**：`time.monotonic()`。
- **#80 `_health_scores` 无锁（:45）** — 周期线程写、调用方并发读。
- **#81 延迟分未与 `is_healthy` 联动（:76）** — 见 §六 D2（真问题＝失败源仍得延迟分）。
- **#82 `stop_periodic_check` 不复位 `_thread`（:140）** — join 后未置 None → 之后无法重启；自 join 风险。

### C-5 `app/data/data_inventory.py`（**零引用**）
- **#83 `_inventory_database` 连接泄漏（:91）** — `conn.close()` 仅在成功路径。
- **#84 `check_data_timeliness` 同类泄漏（:150）**。
- **#85 目录缺失即崩溃（:232）** — `os.listdir(self.db_dir)` 无 `isdir` 守卫。
- **#86 `strptime('%Y-%m-%d')` 静默丢表（:160）** — `YYYYMMDD` 格式抛错仅 debug 记录。
- **#87 `table_name` 拼接注入面（:198）** — 公开 API 参数直插 SQL。

### C-6 `app/data/create_views.py`（**⚠️ 更正：非死模块**；`create_all_views/drop_all_views` 零引用已删；`create_adj_factor_view` **活代码**保留）
- **#88 `DROP VIEW` 先于存在性检查（:42）** — 无年表时**永久移除**可用视图。**方向**：先查后删/兜底重建。
- **#89 `drop_all_views` 连接仅成功路径关闭（:190）**。
- **#90 失败仅 `return False` + 聚合只数成功（:158）** — 部分视图缺失被静默。

### C-7 死存储 / 死表 / 视图重复（本次回核新补，与 426 §0.1 D6/D7 同源）

> **✅ 批次7 已处置（2026-09-30）**：**#91/#92（死备份库/散落空库）已删**（34 备份 196 GiB + 2 测试沙箱 37 GiB + instance 残留 + 0 字节库，共释放 222 GiB）；**#93/#94/#95 经复核为「426 已清理落地」**（总库仅 11 表/4 空、`cache_metadata` 单份、无重复视图）→ 库表**不删**；**#96~#99 属设计登记项**（非缺陷）。以下为原始核查记录。
- **#91 死备份库占空间（未随 426 清）** — `stock_cache_backup_20260818.db`（≈15.5 GiB）+ `stock_cache.db.bak_424_20260910`（≈8.75 GiB）；426 D6 已识别，**需复核是否已清**。**方向**：确认后 `git rm`/删除。
- **#92 散落空库 / 陈旧库** — 根目录 `market_cache.db`、`data/stock_cache.db`、`backend/financial_cache.db`、`backend/instance/*.db`、`instance/test.db`（≈295 MiB）等；426 D6 已识别，**需复核**。
- **#93 总库空壳表未清（36 张 0 行）** — 426 D4/D7 已识别；总库 `stock_cache.db` 44 表中 36 张 0 行空壳（未随 426 全清）。**方向**：按白名单清理或标注。
- **#94 `cache_metadata` 双份（主库 29 / system 3）** — 426 D4 已识别；`cache_metadata` 在总库与 `system_cache.db` 双份不一致。**方向**：单源化。
- **#95 视图重复 `daily_data_view`/`adj_factor_view`** — `create_views.create_daily_data_view` 建 `daily_data_view`（`market_cache.db`）、`create_adj_factor_view` 建 `adj_factor_view`（`history_cache.db`）；与数据侧既有同名视图并存 → 需复核是否重复/陈旧。
- **#96 `init_sharding.SHARDING_CONFIG` 与路由表漂移** — 该常量的表清单（含 `cache_metadata` 等）与 `sharding_manager._table_to_db` 实际路由**不一致**（模块零引用，故仅登记）。
- **#97 `_ensure_snapshot_indexes` 建索引为一次性副作用** — 连接首次建立时建 5 个索引 + 2 列迁移，属**连接创建副作用**而非集中迁移（虽幂等 `IF NOT EXISTS`，但耦合在 `get_connection` 中）。**方向**：迁至显式迁移步骤。
- **#98 动态前缀表路由仅 `adj_factor_cache_`** — `_prefix_rules` 仅一条；`daily_/indicator_/minute_` 按设计拆分未落地（426 D3 半成品），其余动态年表无路由。**登记**。
- **#99 `market_snapshot.db` 第 7 库与设计/路由漂移** — 426 D5 已识别（`as_market_snapshot`/`as_sector_ranking` 走独立库 + ECM `snapshot_conn` 直连，已在 `_table_to_db` 补登但库不在 356 设计）。**登记**。

---

## 六、D 类：OCR 误报 / 需更正（4 项）

1. **D1（误报）「分库分支忽略 `adj` 参数」** — OCR seg5 头号结论。**实为错误**：`app/data/__init__.py:193-205` 分库分支在 `adj is None` 时 return，否则 `return self._apply_adjust_factor(df, adj)`，**复权已应用**。OCR 未读到该 return 分支。
2. **D2（需更正）`health_checker._calculate_health_score`「忽略 elapsed」** — 实为参数改名（形参 `response_time` 接收 `elapsed`）。OCR 的**真问题**是「延迟分未与 `is_healthy` 联动」（失败源仍得 +0.4）＝见 #81，非「忽略 elapsed」。
3. **D3（信息类）`monitor.check_wal_size` `threshold_mb` 单位** — 现有调用方（daemon `wal_size_mb`）以 MB 传入，单位一致，非缺陷。
4. **D4（需更正）`market_universe` `399` 前缀规则** — OCR 判为「与别所 399 开头正股混淆」。**实为深市指数段**（`399001.SZ` 等），剔除方向正确；属**理论风险**（无现实 399 开头非深市码），非缺陷 ＝ 见 #48。

---

## 七、与既有方案的关系（避免重复处置）

| 既有方案 | 已落地内容 | 与本次关系 |
|---|---|---|
| **426 §0.1（D1-D8）** | 保留期规则、每库 PRAGMA、adj_factor 拆分、总库归属、market_snapshot 路由、路由二义性（`is_registered`）等**主要项已落地** | 本次 **#6**（`get_table_row_count` 未随 D8 统一）＝D8 收口残留；**#91~#99**（死备份/空壳表/双份 metadata/视图重复/库漂移）＝D4/D5/D6/D7 未完全收口，**实施前须复核现状** |
| **498 #2/#21/#22/#23/#24/#26** | 分库读错库、未登记读/写告警、迁移失败 debug→warning、连接缓存双检锁、`init_sharding` close_all | 本次 **#4**（`get_write_lock` 未同步加锁）、**#5**（连接错误路径泄漏）、**#7** 为其邻域 |
| **499（全 12 处）** | 分库表走总库连接读取 | 本次 **#2**＝**同型**（DataManager 分库读 vs ECM 归一），但为**格式口径**而非「走错库」 |
| **496（daemon 效率）** | `_query_table` 吞异常、分钟回填增量、pct_chg 板块、treemap guard | **不重复计入** |
| **498 批次4/8** | `_get_mootdx_minutes_safe` 午休跳段（#4 时间基准）、`aggregate_1min_to_60min` 窗口读（#41） | 本次 **#16/#50** 为其**未覆盖的三点**（索引假设/240 根/日期截断）与**不同函数**（`backfill_1min`/`_resample_minute` 低值） |

---

## 八、口径拍板结果（Q1~Q4，2026-09-30 已决）

> 依项目惯例，涉及「**范围取舍 / 是否删除 / 接线方向**」的分歧可先确认再实施（属范围问题，非「果层」限制——后者已失效，见 §边界）。**四项已由用户逐项选定（v1.2）**：

- **Q1 = B（删除六模块群）** — `config_manager` / `migration` / `init_sharding`（模块） / `health_checker` / `data_inventory` / `create_views`（除 `create_adj_factor_view`）**`git rm` 删除**（随 498#Q3 先例）。**注意**：`create_views.create_adj_factor_view` 有唯一调用方 `scripts/_426_phase4_adj_factor_repair.py` → 删模块前须先迁移/内联该函数（或一并处置该脚本），否则脚本失效。
- **Q2 = A（删死分支）** — 删 `ws_bridge` 死分支（`_api_push_active` 恒真 + 7 处 `_broadcast_*` 短路）**+ 删 `_broadcast_limit_pools`**；承认推送由 `services/push_service.py` 承担。**连带的 `routes/realtime.py:364` `trigger_publish` 端点**需同步处置（删端点或改注释为“已由 push_service 承担”）。
- **Q3 = A（各周期各自 lookahead 实算）** — `compute_win_rates` 的 `win_rate_5d/10d/20d`、`avg_return_5d/20d` **按各自前瞻窗口实算**（真多周期）；Sharpe（#38）随本次一并实算或显式登记缺省。
- **Q4 = 全部批次纳入** — §九 批次1~8 **全部纳入实施范围**（含 C-7 死存储/死表）。

---

## 九、分批实施计划（八批次全部纳入，2026-09-30 拍板）

> 原则：**零行为变更优先**、**同因同批**、**死模块与生效路径分开**、**每批 `py_compile` + ruff + 定向回归 + 探针**，涉 daemon 停启按 498 惯例（停看守）。

| 批次 | 范围 | 项 | 风险 |
|---|---|---|---|
| **批次1** ✅ | 预计算/因子正确性（A#3[Q3=A 实算] + B#36~#49） | 15 | **已实施（2026-09-30）**；端到端 6/6 非恒等、51 passed |
| **批次2** ✅ | 分库路由收口（#4/#5/#6 + #7 登记） | 4 | **已实施（2026-09-30）**；155 passed、探针全绿 |
| **批次3** ✅ | DataManager 读口径（#2/#8~#12 + #57~#59） | 9 | **已实施（2026-09-30）**；138 passed、探针全绿 |
| **批次4** ✅ | 内存与分钟/重采样（#13~#19 + #50~#54） | 12 | **已实施（2026-09-30）**；106 passed、探针全绿 |
| **批次5** ✅ | 源管理/缓存/ECM/观测（#20~#35 + #55/#56） | 18 | **已实施（2026-09-30）**；89 passed、探针全绿 |
| **批次6** ✅ | 死模块处置（Q1=B 经复核收窄：删 C-1~C-5 五模块 + C-6 4 死函数） | 5 模块 + 4 函数 | **已实施（2026-09-30）**；81 passed、导入冒烟 OK（`create_views` 更正为非死模块） |
| **批次7** ✅ | 死存储/死表/视图重复（C-7 #91~#99） | 9 | **已实施（2026-09-30）**；删 34 备份+2 沙箱+残留（释放 222 GiB）；库内容 426 已落地（非缺陷）；73 passed |
| **批次8** ✅ | #1 `ws_bridge`（Q2=A 删死分支+端点） | 1 | **已实施（2026-09-30）**；81 passed、探针全绿（#55 已在批次5 处理） |

> **依赖顺序（开工建议）**：批次2（低风险、对齐既有模式）→ 批次1（Q3=A 实算）→ 批次3/4/5（互相无耦合，可并行）→ 批次8（Q2=A）→ 批次6/7（删除/清库，**须先复核库现状 + 迁移 `create_adj_factor_view` 调用方**）。
> **实施前须知**：批次7 涉及 DB 文件删除，须先按 `data/duckdb/` 现状复核（#91~#99 为 426 D4~D7 残留，部分可能已清）；批次6 删除前须 `grep` 复核零引用（防动态 import）。

---

## 十、核查证据锚点（复现入口）

- **schema 实证**（只读直查 `data/duckdb/`）：
  - `daily_cache` 列 = `ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, cached_at`（**无 `change_pct`** → 该列名错属 §一「未计入条」）；
  - `indicator_ma` 列 = `…, ma5..ma250, vol_ma5, vol_ma10,…`（**无 `close`** → `get_market_ma20_ratio` 的 SQL 实际会失败，见 §一）；
  - `win_rate_cache` 列 = `win_rate_5d/10d/20d, avg_return_5d/20d, sharpe_5d/20d` 等。
- **调用图实证**：`_api_push_active`（仅 :41 赋值）；`get_market_ma20_ratio`（仅 `status_engine.py:178`，经 `getattr` 兜底）；`get_market_limit_ratio`（**零调用方**）；`monitor`（daemon 6 处写）；`config_manager`/`migration`/`DataInventory`/`HealthChecker`（生产零引用）。
- **OCR 原始输出**：`/tmp/stg_ocr_20260930/seg1_ecm.md` ~ `seg6_precompute.md`（106 条原始发现，6 会话）。

---

## 十一、落档登记（本次）

- **本档创建**＝`002-方案存档/500-STG存储层OCR核查与处置.md`（v1.0 → **v1.1**，**未改任何代码/配置**）。
- 已更新 `002-方案存档/001-目录索引.md` §二十 500 行。
- 已追加 `001-沟通记录/2026-09-30.md` + `沟通索引.md`。
- **下一步**：待用户对 §八 Q1~Q4 拍板后，按 §九 逐批实施。

---

## 维护规则

1. 本档为 STG 层 OCR 核查的**唯一权威归档**；后续 STG 相关修订在此追加（`v1.x`）。
2. 批次实施后，在 §九 表格追加实施记录 + commit，并同步 `001-目录索引.md` 状态列。
3. 与 356/423/424/426 冲突时，以本档为准（更晚）+ 回填既有文档。
