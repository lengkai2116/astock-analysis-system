---
title: 544-RAW-2 与 SIG 只读 profiling（FCF 基准 N+1 + 单只耗时拆分）
type: 核查档
date: 2026-10-23
status: 已完成（只读，未改代码）
---

# 544｜RAW-2 与 SIG 只读 profiling

## 一、方法

- 探针：`.qwen/tmp/profile_raw2_sig.py`，样本 10 只主板股票（000001.SZ、000002.SZ、000858.SZ、002415.SZ、300750.SZ、600000.SH、600036.SH、600519.SH、601318.SH、688981.SH）。
- 只读约束：停 daemon 后运行；`DATA_DIR` 指向项目根 `data`；预置 `_tables_initialized_paths` 跳过 ECM 建表；`cache_pre_feat` / `_batch_write_signal_detail` / `_prewarm_weekly_cache` 全部替换为计数 no-op；dim1 `_notify_missing_data` 替换为计数；SQL trace 统计 SELECT/INSERT/UPDATE/DELETE。
- 为完整捕获调用栈，`ThreadPoolExecutor` 替换为同步执行器（因此 wall 时间不等于生产并行 wall，单只 CPU 拆分仍有效）；`create_app` 替换为轻量 Flask 上下文。
- cProfile 按 cumulative 排序。

## 二、结果

### 2.1 RAW-2（10 只）

- wall **42.045s**；函数内部日志「10/10 只，耗时 4.1s」⇒ **固定成本约 37.9s（90%）**。
- SQL：**SELECT 11,905 次**，INSERT/UPDATE/DELETE **0**。

| 函数 | cumtime | 说明 |
|---|---:|---|
| `build_fcf_percentile` | **36.894s** | 固定成本，占 87.8% |
| `get_cached_daily_basic` | 32.531s | **5,589 次**调用（N+1） |
| `get_cached_cashflow` | 2.689s | **5,599 次**调用 |
| `_raw2_one`（10 只） | 4.146s | 单只 **0.415s** |
| └ 缠论 `analyze` | 1.690s | 0.169s/只 |
| └ 筹码 `estimate` | 1.053s | 0.105s/只 |
| └ 事件 `compute_tags` | 0.627s | 0.063s/只 |

**FCF 基准是最大单点**：`build_fcf_percentile` 对全市场逐股调用 `get_cached_daily_basic` + `get_cached_cashflow`（各约 5,589 次），只为取 `total_mv` 最新值与 `free_cashflow` 首值。

### 2.2 SIG（10 只）

- wall **50.246s**；SQL **SELECT 11,680 次**，写操作 0。
- dim1 通知 **10 次/10 只**（每只 1 次 `sync_requests`）。

| 函数 | cumtime | 说明 |
|---|---:|---|
| `_build_dim_engine_results` | **47.653s** | 占 94.8% |
| └ dim7 `evaluate` | 31.807s | 含 `build_fcf_percentile` 30.405s（固定一次） |
| └ **dim1 `evaluate`** | **7.880s** | **0.788s/只** |
| └ dim2 `evaluate` | 5.395s | 0.540s/只 |
| └ dim4 `evaluate` | 2.432s | 0.243s/只 |
| └ 缠论 `analyze` | 5.268s | 70 次 / 10 只 |
| `get_cached_minute_kline` | 6.968s | 20 次（2 次/只，0.348s/次） |
| `_get_weekly_data` | 6.753s | 10 次（0.675s/只） |
| `get_cached_daily_basic` | 25.911s | 5,605 次（几乎全来自 FCF 基准） |

**SIG 的单只成本**主要是 dim1（0.788s）+ dim2（0.540s）+ 缠论（0.527s）+ 分钟线（约 0.696s）+ 周线（0.675s）；FCF 基准为一次性固定成本（30.4s）。

## 三、关键结论

1. **最大固定成本是 FCF 截面基准，两处重复实现**：`valuation_estimator.build_fcf_percentile` 与 `dim7_valuation_engine.build_fcf_percentile` 都逐股 N+1 查询；RAW-2 与 SIG 各构建一次，日终合计约 **60–67s、约 2.2 万次 SQL**。
2. **RAW-2 单只 CPU 0.415s**（缠论/筹码/事件为主），但生产 wall 约 1.35s/只（2h05m/5569）⇒ **约 2/3 时间不在纯计算**，指向 DB I/O、8 线程争抢/锁等待或固定成本叠加；需要生产态采样（py-spy/sample）进一步确认。
3. **SIG 单只受数据加载影响明显**：分钟线 0.35s×2、周线 0.675s/只；dim1 0.788s/只 是最大计算项。
4. **dim1 通知逐只写**：全市场约 5,569 次/日，可批量合并。
5. 探针本身零写（INSERT/UPDATE/DELETE=0）。

## 四、只读副作用披露

- 数据可见性预检脚本（独立进程构造 ECM，未预置 `_tables_initialized_paths`）触发了一次「总库空壳表自清理：DROP 37 张」。这 37 张是 `stock_cache.db` 中分库表的**空壳副本**，非业务数据；复核分库：`daily_cache` 8,492,266 行、`pre_feat_cache` 215,101 行、最新交易日 2026-10-22，均完好。daemon 已重启（PID 13131 / 看守 13116），`stock_cache.db` 现有 12 表，分库 9/16/8 表正常。
- 除上述 DDL 外，探针运行期间无 INSERT/UPDATE/DELETE；daemon 已恢复。

## 五、优化候选（未实施，按收益排序）

| 优先级 | 对象 | 方案 | 预期 |
|---|---|---|---|
| P0 | FCF 基准（两处） | 改为一次批量 SQL：最新交易日 `daily_basic_cache(ts_code,total_mv)` + `cashflow_cache(ts_code,free_cashflow)`，内存 JOIN；抽公共函数 | 30–37s → <1s/次；日终省 ≈60s；SQL 从 ≈2.2 万降到个位数 |
| P1 | SIG 数据加载 | 分钟线/周线批量预取或进程内缓存；`_get_weekly_data` 复用预热结果 | 单只省 ≈0.5–1.0s |
| P1 | dim1 通知 | 每 100 只或 60s 合并写 `sync_requests` | 5,569 次写 → 约 56 次 |
| P1 | RAW-2 单只 | 批量预取当日 daily_basic/moneyflow/limit；复核 8 线程下 DB 锁/连接竞争；再评估 E5-a 进程池 | 先定位生产 1.35s/只 中 2/3 的非计算时间 |
| P2 | JUD | 逐股 ORM/DB 往返改批量查询 | 42min → 15–20min 候选 |

**建议顺序**：先做 P0（低风险、口径可验证、收益确定），再做 P1 数据加载/通知批量；进程池放到生产态采样确认 I/O 等待占比之后，避免盲目多进程。

## 六、待拍板

1. P0 是否开号实施（544-A：FCF 基准批量查询 + 两处实现收敛）。
2. 生产态 1.35s/只 的非计算时间是否需要用 py-spy/sample 再采一轮（需短暂停 daemon）。
3. SIG/RAW-2 进程池是否列入候选（依赖写回单点化改造）。

## 七、544-A 实施记录（2026-10-23）

**用户拍板**：开 544-A，先做 FCF 基准批量查询。

**实现**：
- 新增 `backend/app/opportunity_atlas/fcf_percentile.py`：公共 `build_fcf_percentile(cache, codes=None, min_samples=200)`。
- `valuation_estimator.ValuationEngine.build_fcf_percentile` 与 `dim7_valuation_engine.Dim7ValuationEngine.build_fcf_percentile` 收敛为调用公共函数（保留各自 codes 来源：`treemap_snapshot` / `daily_cache` 最新日）。
- SQL 优化：`daily_basic_cache` 660 万行全表窗口/分组实测 15–17s → 改为「最新交易日批量（0.01s，5,570 行）+ 缺失股票 IN 补查」；`cashflow_cache` 仅 7.7 万行，保留窗口查询（0.03s）。

**验证**：
- 单元测试 `test_544a_fcf_percentile_batch.py`：**6 passed**。
- 实机只读对比 100 只：逐股 vs 批量 **diffs=0**；批量 0.035s。
- 真实 ECM（`codes=None`，全市场候选 5,570）：**0.142s**（旧逐股 32.5s，约 229×）；pct 返回正常。

**效果**：RAW-2 固定成本 36.9s + SIG 固定成本 30.4s → 各约 0.15s，日终合计省约 **60–67s**，SQL 从约 2.2 万次降到约 4 次/次构建。

**状态**：代码已实施，已随 `f459a22` 提交；daemon 已重启加载。

**注意**：`codes=None` 时补查候选来自 `daily_cache` 最新日；两处生产调用均传 codes。

## 八、544-B：cost_ext 生产导入路径修复（2026-10-23）

**P1 核查发现**：2026-10-22 的 `pre_feat_cache` 抽样 200 只中 `cost_ext` **100% 为 `{}`**，其余 7 个 ext 组 100% 非空。dim1 `_validate` 因此对全市场每只判 `cost_ext` 缺失 → 生产日志 **5,628 次/日** `precompute_raw` 通知。

**根因**：`data_daemon.py` 的 RAW-2 第 17 段从 `app.opportunity_atlas.dimensions.dim4_chip_fund_engine` 导入 `MainForceScorer`，但该类 508 批次1 已收敛到 `app.engine.framework.chip_strategy`，dim4 不再导出 → 每次 `ImportError` 被 debug 吞掉 → `_cost_feat={}`。

**修复**：导入改为 `from app.engine.framework.chip_strategy import MainForceScorer`。

**验证**：
- 新增 `test_544b_cost_ext_import.py`：**3 passed**（framework 导出、dim4 不导出、daemon 源码使用正确导入）。
- 模拟 RAW-2 成本段：`cost_ext` 返回非空（`main_force_cost` + `margin_cost_price`）。

**状态**：代码已修复，daemon 已重启（PID 17269/看守 17253）；10-22 历史 pre_feat 已定向回填。

**定向回填（2026-10-23，用户选 B）**：新增 `backend/scripts/_544b_backfill_cost_ext.py`，只更新 `features_json.cost_ext`，保留其余键。dry-run 20 只通过；`--apply` 全量 **5,567/5,567，failed=0，18.52s**；回填后 `cost_ext` 非空 **5,567/5,567（100%）**。

**遗留**：`margin_cost_price` 在 10-22 仍为 `None`（两融 T+1，属正常）；dim1 通知应随 cost_ext 恢复而消失（下次 SIG 验证）。

## 九、544-C：SIG 60m 分钟线批量预取（2026-10-23）

**问题**：SIG 的 dim1 每只调用 `dm.get_kline_data(ts_code, '60m')`；原 `get_cached_minute_kline` 的 `sharding_manager.execute_query` 返回 **list**，旧代码 `df.empty` 抛异常 → 静默降级到 pandas `_query_shard`，单只约 **0.35s**，全市场约 **32min**。

**实现**：
- ECM 新增 `_minute_cache`（键 `(ts_code, freq)`）、`prime_minute_cache(codes, freq='60min', ttl_sec=7200)`、`clear_minute_cache()`。
- `get_cached_minute_kline` 优先命中缓存（返回 copy）；未命中统一走 `_query_shard`（pandas 带列名），移除 list 异常分支。
- SIG 入口 `_precompute_strategy_signals` 在 `_prewarm_weekly_cache` 后调用 `_prewarm_minute_cache(codes)`；批量读取用 `pd.read_sql_query` + 分库只读连接，按 ts_code 分组缓存。

**实测（2026-10-23，5,605 只）**：
- 批量预取 **5,217 只 / 711,538 行：28.6s**（固定成本）；
- 缓存命中 100 只：**0.002s（0.02ms/只）**；
- 未命中单只 `_query_shard`：**40.6ms/只**（全市场约 227.7s）；
- 对比原路径（约 0.35s/只，全市场约 32min）：单只路径修复 + 批量预取后，60m 加载降到约 **29s + 命中近零**，预计 SIG 减少约 **30min**（下次 SIG 实测确认）。

**测试**：`test_544c_minute_cache.py` **3 passed**；py_compile 通过。

**状态**：代码已实施；daemon 需重启加载；下次 SIG 观察 `[SIG] 60min 分钟线缓存预热` 与 SIG 耗时。

**遗留**：28.6s 预取可继续优化（仅 SELECT 必要列/日期范围/避免 5,227 个 group DataFrame），当前收益已足够。
