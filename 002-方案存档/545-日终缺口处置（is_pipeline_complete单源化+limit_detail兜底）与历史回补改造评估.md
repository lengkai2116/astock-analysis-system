---
title: 545-日终缺口处置（is_pipeline_complete 单源化 + limit_detail 兜底）与历史回补改造评估
type: 实施+评估
date: 2026-10-23
status: ③②已实施；①评估完成，改造待实施（用户拍板：改造后正式回补 10-20/10-21）
---

# 545｜日终缺口处置与历史回补评估

## 一、背景与拍板

2026-10-23 接续 542~544-C 后核查 P2 三项，实测结果与交接记录有差异：

- 历史缺口不止 10-21：**10-20 与 10-21 两天都停在 `RAW-2C`**（RAW-2D/2E 当时未注册、无记录），SIG/JUD/OUT/QA-CHECK 全 `pending`；10-22 已由 542 续跑补完（19 环节全 done）。
- `limit_detail_cache` 最新为 10-21（69 行），10-22 = 0；同期 `stk_limit_cache` 10-22 有 5,655 行。
- `_is_pipeline_complete` 仍是 16 项硬编码，与 `PIPELINE_STEPS`（18 项）双源。

用户拍板：

| 项 | 口径 |
|---|---|
| ③ 单源化 | 现在实施 |
| ② limit_detail | 现在补采 10-22，并接入完整性检查兜底 |
| ① 历史回补 | 本轮只出评估方案不改码；**最终口径＝改造后正式回补 10-20/10-21** |
| 18:00 验证 | 挂后台监控并自动汇报 |

## 二、③ `_is_pipeline_complete` 单源化（已实施）

**改动**（`backend/data_daemon.py:7000-7014`）：

- 环节清单改为 `from app.data.enhanced_cache_manager import PIPELINE_STEPS` 派生，IN 占位符动态生成，判据 `count >= len(step_ids)`。
- 消除 532 批次2 新增 RAW-2D/RAW-2E 后「新增环节漏登记 → 完成判定漏判」的同类隐患（与 542 同源）。

**调用面**：仅 3 处（`data_daemon.py:7309`、`7313`、`8917`），均以「最新数据日」或「今日」为参数，历史日退回不触发重跑（管道只推进最新数据日）。

**验证**：`test_545_pipeline_gaps.py::test_pipeline_complete_requires_all_registered_steps` —— 旧 16 项全 done 判 False，补齐 2D/2E 后判 True。

## 三、② limit_detail 兜底（已实施 + 已补采）

**根因**：`_batch_limit_detail` 只挂在 `run_daily_sync()`（`data_daemon.py:2919`，15:30 一次性任务）；接口当日尚未发布时返回空 → 写 0 行，而 `run_integrity_check` 清单不含该表 → 整点巡检永不重试。10-22 日终为次日早上续跑，也未经过 15:30 钩子。

**改动**：

- 新增 `_check_limit_detail_completeness(backfill_days)`（`data_daemon.py:892`）：按 `backfill_days` 逐交易日检查，「`stk_limit_cache` ≥ `LIMIT_THRESHOLD` 且 `limit_detail_cache` 当日为 0」→ 调 `_batch_limit_detail(YYYYMMDD)` 幂等补采；非交易日与当日 18:00 前跳过。
- `run_integrity_check` 内新增一行调用（`data_daemon.py:2371`），随启动/整点巡检自动重试。

**补采结果**（`_537_backfill_p1_sources.py --date 20261022 --only limit`）：

| 日期 | U（涨停） | Z（炸板） | 合计 |
|---|---:|---:|---:|
| 2026-10-20 | 54 | 29 | 83 |
| 2026-10-21 | 50 | 19 | 69 |
| **2026-10-22** | **33** | **23** | **56**（本次补采） |

**测试**：`test_545_pipeline_gaps.py` 3 项（空明细补采且传 YYYYMMDD、有明细跳过、基础表不足跳过）。

## 四、① 历史回补：为什么不能直接重跑

SIG 全链的日期口径是「最新交易日」，重跑只会写入最新日：

| 锚点 | 位置 | 现状 |
|---|---|---|
| SIG 结果 trade_date | `backend/app/engine/unified_core.py:120-130` | `SELECT MAX(trade_date) FROM daily_cache`，无参数 |
| 单只计算入口 | `backend/app/services/signal_computation_service.py:46-68` | `get_cached_daily_data(ts_code, adj='qfq')` 不传 `end_date`，读全历史 |
| 批量入口 | `backend/app/engine/unified_core.py:78-99` | `compute_batch(codes, period, max_workers)` 无 as_of |
| dim1 门禁 | `backend/app/opportunity_atlas/status_engine.py:261,280,301` | `evaluate(asof_date=...)` **已支持**，但 SIG 预计算未传 |
| dim2-dim7 调度 | 同上 `448-500` | `_build_dim_engine_results(...)` 无 asof_date → dim1 取 None |
| JUD 产物表 | `status_snapshot`（`trade_date`/`snapshot_date`）、`treemap_snapshot`（`trade_date`/`snapshot_date`） | 有日期列，可按日写入 |
| OUT 成品仓 | `out_market_panel` 主键 `(module, asof_date)` | 天然支持历史 asof |

**核心风险＝后视偏差（look-ahead）**：若只改 trade_date 而不截断行情视窗，10-20 的信号会用 10-21/10-22 的 K 线计算；因此必须让「取数视窗」与「落库日期」同时锚定 as_of。

## 五、改造方案对比

| 方案 | 做法 | 优点 | 代价/风险 |
|---|---|---|---|
| **A 显式 as_of 贯穿**（推荐） | `compute_batch/compute_for_stock` 增 `as_of`；`get_cached_daily_data` 传 `end_date=as_of`；dim1/dim2-dim7 经 `_build_dim_engine_results(asof_date=...)` 透传；SIG/JUD/OUT 写库用同一 as_of | 无副作用、可复用（回测/重放）、路径单一 | 改动跨 4~5 个文件；需逐项排查隐藏的 `MAX(trade_date)`/`datetime.now()` 取数点；需回归 |
| B 影子库截断重放 | 克隆基准库，删除 > as_of 的行后重跑 | 代码零改动 | 破坏性重放、需双份 13GB+ 库、与 daemon 争锁；已明确不做（开发期隔离红线） |
| C 接受缺口 | 只保证 10-22 起完整 | 零成本 | 10-20/10-21 的个股页/历史面板永久缺失 |

用户已排除 C；采用 **A**。

## 六、A 方案实施拆解（待实施）

前置：**必须避开 15:00–18:00 数据窗口与日终运行**。建议 10-24（周六）执行，回补两日各约 SIG 0.7~1.2h + JUD 0.7h + OUT 秒级，合计约 3~4h。

| 批次 | 内容 | 验证 |
|---|---|---|
| A1 | `compute_for_stock/compute_batch` 增 `as_of: Optional[str]`；`get_cached_daily_data(end_date=as_of)`；`_to_standardized` 用 as_of 而非 `MAX()` | 单只 10-21 重算 trade_date=2026-10-21；K 线末根 ≤ as_of |
| A2 | `_build_dim_engine_results` / dim1 `evaluate` 透传 `asof_date`；确认 dim2-dim7 只从 `data_context` 读原料 | 抽样 10 只：dim_results 非空、无「数据缺失」通知 |
| A3 | JUD 三个产物写入带 as_of（`_build_status_snapshot`/`_jud_enrich_with_meta`/`_build_treemap_snapshot`），禁止覆盖最新日 | 10-22 产物行数前后不变 |
| A4 | 新增回补脚本 `_545_backfill_sig_jud_out.py --date`（只写目标日；默认 dry-run） | 先 1 只 → 10 只 → 全市场 |
| A5 | 回补 10-20、10-21；重跑 QA-CHECK 并核对覆盖 | `strategy_signal_detail` 两日各 ≥5,500；`out_market_panel` 出现 20261020/20261021 |

**回归清单**：`test_544a/544c`、`test_542/543/545` 定向；API `/diagnose` 与个股策略页抽样；确认最新日（10-22）产物零变化。

## 七、验证记录

| 项 | 结果 |
|---|---|
| 定向测试 | `test_545_pipeline_gaps.py` + `test_542_*` 共 **6 passed** |
| py_compile | `backend/data_daemon.py` OK |
| 补采实机 | 10-22 limit_detail 0 → **56 行（U33/Z23）** |
| API 重启 | 旧 1334（07:30，旧代码）→ 新 **26101**，`health/live=200`（12:48） |

## 八、遗留

1. ① 的 A1~A5 未实施（本档只评估）；实施前须确认 545 号 A 方案无遗漏锚点（重点：`_load_market_context`、指标宽表读取、`pre_feat` 读取是否按日切片）。
2. 回补窗口不得与日终重叠；建议周末执行并在执行前停 daemon。
3. `strategy_signal_detail` 10-21 的 2 行影子行（519 号）在回补时须先清理，避免 `MAX(trade_date)` 与覆盖写冲突。
4. 545 号改动需 daemon 重启后生效（当前 daemon 21345 为 11:47 启动，未含本档代码）。
