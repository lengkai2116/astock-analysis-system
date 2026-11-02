---
title: 554-日终终版与分钟兜底缺陷处置（FINAL重试上限+指数硬门禁+THS死路径下线）
type: 方案
date: 2026-11-02
status: 已实施并已提交（待推送；P1-1/P1-2/P1-3 三项；P2/P3 登记待后续）
depends:
  - 548（OUT-MARKET-FINAL 终版重建）
  - 552/553（日终按源就绪定序、COL 判据、552-E 截止告警）
  - 543（日终完成保障：重试超限→告警+标 done 的既有先例）
source:
  - 2026-11-01 OCR 复核 6ff8085（16 条）与 111356a（24 条）
  - 001-沟通记录/2026-11-01.md、2026-11-02.md
---

# 554｜日终终版与分钟兜底缺陷处置

## 一、背景

2026-11-01 用 OCR（OpenCodeReview）复核了近期两次 daemon 修正：

| 提交 | 内容 | OCR 条数 |
|---|---|---|
| `6ff8085`（2026-10-31） | 10-30 日终六项遗留（FINAL 入管道、指数兜底重试、新股元数据、QA 历史巡检、一致性过滤、噪声收敛） | 16（含 1 组 `review_limit_reached`） |
| `111356a`（2026-10-29） | 553 A/B/C + 552 A/B/C/E（按源就绪定序、COL 行数判据、THS 分钟兜底、RAW-2 多进程、截止告警） | 24（含 1 次 `git grep` 工具侧失败） |

逐条对照代码与库表实测后，确定 3 项 **P1**（本档处置范围），其余 P2/P3 登记于 §六。

## 二、P1-1 终版重建无重试上限（本提交引入的退化）

### 成因

`OUT-MARKET-FINAL` 于 `6ff8085` 登记进 `PIPELINE_STEPS`（18→19 步）后：

- `_is_pipeline_complete()` 必须等 FINAL `done`；
- `_drive_pipeline()` 在 QA `done` 后**不判 FINAL 状态**，直接 `_finalize_out_market_panel(today)`（`backend/data_daemon.py:8523`）；
- `_finalize_out_market_panel()` 只有一条护栏 `prev == 'done' → return`（:6933），异常被 `except` 吞成 warning，`errors` 非空只写 `failed`，**无 retry_count、无退避、无告警**。

改前 QA `done` 即视为完成、下一 tick 顶部早退，不存在循环；改后任一模块持续报错即 **每 30s 重建 17 个模块**（10-30 实测单次 10.7s，叠加指数 ensure 可达 ~20s），并持续占用 `snapshot_cache.db` 写。

配套偏差：`_EOD_STEP_BASELINE`（552-E ETA）仍 18 项、`_PIPELINE_STEP_TIMEOUT_MIN`（看门狗）也缺 FINAL；实测 FINAL 行 `completed_at` 为 NULL。

### 拍板口径（2026-11-02）

**有界 3 次 + 指数退避（120s/240s/…) 超限转 done 并告警**，沿用 543 号 QA-CHECK 既有先例（重试超限 → 告警 + 标 done + detail 留痕，避免死循环，缺口由次日/巡检兜底）。

### 实施（554-A）

1. 新增 `_FINAL_RETRY_MAX=3`、`_FINAL_RETRY_BASE=120`、`_FINAL_RETRY_CAP=1800`、`_FINAL_RETRY_STATE{'date','next_at'}`；
2. 新增 `_final_record_failure(pipeline_date, rc, reason, **meta)`：`rc+1`；未超限 → `failed` + 退避；超限 → `done` + `detail='终版重建重试超限(3次)，已告警: …'` + `_pipeline_alert('OUT_FINAL_FAILED')`；两条路径都写 `retry_count` 与 `completed_at`；
3. `_finalize_out_market_panel()` 改为返回 `'done'|'failed'|'skipped'`，退避期内直接 `skipped`；成功路径写 `completed_at`；
4. `_PIPELINE_STEP_TIMEOUT_MIN` 增 `'OUT-MARKET-FINAL': 15`（分钟）；`_EOD_STEP_BASELINE` 增 `'OUT-MARKET-FINAL': 12`（秒）；
5. `_drive_pipeline` 末尾按返回值打印「全链路完成」或「主链路完成、终版待重试」，不再无条件宣称完成。

## 三、P1-2 指数晚到的重置窗口不完整（10-30 场景仍会漏）

### 成因

`_refresh_out_final_if_index_late()`（:895）只在 `run_integrity_check` 的 `for idx_date in idx_checks:`（:2800）内调用，而 `idx_checks` 只收「本次巡检当场发现有缺口」的日期。

10-30 实测：面板 18:40 建、指数 19:01 发布 → 19:00 巡检仍缺、20:00 巡检已齐 ⇒ **该函数一次都不触发**。更关键的是缺指数时 `get_market_volume()` 用历史序列静默拼接（`dashboard_service.py:2666-2680`），`errors=[]` → FINAL 记 `done`；次日 `_check_eod_completion()` 见 done 直接返回（:8806）⇒ 当日指数永久缺失。

### 拍板口径（2026-11-02）

**指数未齐不建终版（构建前硬门禁）**；`_ensure_index_daily` 先做 3×10s 有界重试，仍缺则按 P1-1 计为失败并退避（detail 带 `index_missing=N`）。同时把重置触发扩展为「任意巡检发现 FINAL `done` 且 detail 含 `index_missing`、且该日指数现已齐」→ 重置 pending 重建。

### 实施（554-B）

1. `_finalize_out_market_panel()`：`_ensure_index_daily()` 后查 `_missing_index_codes()`，非空 → **不调用** `_build_out_market_panel`，直接 `_final_record_failure(..., 'index_missing=N（代码…）')`；
2. `_refresh_out_final_if_index_late()` 兼容两种触发：①本次巡检当场补齐（原逻辑，`missing_before` 非空）；②巡检补偿（`missing_before` 为空但 FINAL detail 含 `index_missing` 且现已补齐）；重置时清 `retry_count` 并复位退避状态；
3. `run_integrity_check()` 指数循环之后，对 `_get_latest_data_date()` 无条件再调一次上述函数（不再依赖当场观测到缺口）。

## 四、P1-3 同花顺分钟兜底是死路径（且接线会写脏行）

### 成因

- 553-C 的 THS `time` 分时兜底写在 `_batch_backfill_minute_kline()` 内（:9240-9256），但该函数唯一入口 `_run_minute_backfill()` 已在日终同步处**被注释**（:3272，414号 R20「移除 v1 Tushare 回填，仅保留 v2 mootdx」），调度器也未注册 ⇒ 兜底永不执行；
- 即便接线也会写脏行：`fetch_intraday_minutes()` 返回列**不含 `ts_code`**（调用方只补 `freq='1min'`），`cache_minute_kline()` → `_insert_from_df('minute_kline_cache', df)` 会以 `ts_code=NULL` 落库；PK `(ts_code, trade_date, trade_time, freq)`、读取恒 `WHERE ts_code=?` ⇒ 写入即不可读；
- `mootdx_collector.py:1400` 注释仍宣称「非交易时段分钟线完整性由日终 Tushare pro_bar 回填兜底（`_batch_backfill_minute_kline`）」，与实现不符；
- 另：`fetch_intraday_minutes` 对 3 位 `HHMM`（如 `930`）会生成非法 `trade_time`；`date_str` 传 `date/pd.Timestamp` 时 `replace('-','')` 恒不匹配；`_load_jsonp` 的 `json.loads` 无保护（截断响应抛到调用方）。

### 拍板口径（2026-11-02）

**下线并修正注释；provider 补 `ts_code`/`freq` 与入参校验以防将来误用，不接线。**如需分钟兜底，另开号接入 mootdx v2 缺口路径。

### 实施（554-C）

1. `_batch_backfill_minute_kline()` 删除 THS 兜底分支（死路径内不再保留会产生 NULL `ts_code` 的调用）；
2. `ths_provider.fetch_intraday_minutes()`：返回列补 `ts_code` 与 `freq='1min'`；`HHMM` 必须 4 位且时分合法，否则跳过；`date_str` 统一归一（支持 `date/datetime/pd.Timestamp/YYYY-MM-DD/YYYYMMDD`）；
3. `_load_jsonp()`：`json.loads` 失败返回 `{}`（与"无数据"同义，不向上抛）；
4. 模块 docstring 标注「当前未接线」；`mootdx_collector.py:1400` 注释改为「非交易时段由 mootdx `minute_full` + `minute_backfill v2` 覆盖；v1 Tushare 全市场回填已停用」。

## 五、验证

- 新增 `backend/tests/test_554a_final_retry.py`（重试计数/退避/超限转 done+告警/幂等/`completed_at`）；
- 新增 `backend/tests/test_554b_index_gate.py`（指数未齐不建终版、`index_missing` 标记、巡检补偿重置、历史日不重置）；
- 新增 `backend/tests/test_554c_ths_contract.py`（`ts_code`/`freq` 列、`HHMM` 校验、日期归一、JSONP 截断）；同步更新 `test_553c_ths_provider.py` 列断言；

### 实际验证结果（2026-11-02）

| 项 | 结果 |
|---|---|
| 新增单测 | `test_554a_final_retry.py` 5 + `test_554b_index_gate.py` 7 + `test_554c_ths_contract.py` 5 = **17 passed**；`test_553c_ths_provider.py` 4（列断言已按新契约更新） |
| 相邻回归 | `test_542/543/552/553b×2/555/428` = **77 passed** |
| 编译 | `py_compile` 通过（`data_daemon.py` / `ths_provider.py` / `mootdx_collector.py`）；`ruff` 本机未安装（`.venv/bin/ruff` 不存在），未执行 |
| live 重启 | 杀 PID 1290 → `start_daemon.sh` 看守 10s 后拉起（PID 9404，08:11:51 启动、08:12:50 进主循环）；启动期无 `Traceback`、无「终版补偿检查失败」 |
| live 终版重建 | 将 `pipeline_status(20261030/OUT-MARKET-FINAL)` 置 pending（retry_count=0）→ 08:14:27 重建 `written=17 errors=[]`，状态回 done；**`completed_at` 由 NULL 变为 `2026-11-02 08:14:27`**（原实现不写） |
| live 幂等 | 再等 1 个 tick，`OUT成品仓终版重建` 日志条数仍为 **1**，未重复重建 |
| 日志口径 | 仅当终版 done 才打印「今日全链路完成 ✅」 |

未做 live 的项（原因）：指数未齐→`failed+退避` 需源侧故障才可复现，且删指数行会扰动基准库（078 已做过同类验证），故该分支由 `test_554b` 覆盖（含 `index_missing` 标记、补偿重置、非指数失败不重置）。

## 六、登记（本次不处置）

| 级别 | 项 | 位置 |
|---|---|---|
| P2 | 日历日 vs 数据日口径不统一（非关键源重试、截止告警、`idx_checks`、一致性检查、分钟回填入口） | `_maybe_retry_noncritical_cols` / `_check_eod_deadline_warning` / `run_integrity_check` / `_check_data_consistency` |
| P2 | `p.join()` 无超时，子进程挂死阻塞 RAW-2 | `_run_raw2_in_processes` |
| P2 | 552-B 财务后台线程与主循环共用 `_ecm.conn`（`check_same_thread=False`） | `_financial_sync_one_day` |
| P2 | COL 冷却固定 300s，源晚发布日全市场重采次数偏多 | `_col_retry_due` / `_COL_RETRY_INTERVAL` |
| P2 | 新股元数据补采失败不可见；`ts.pro_api()` 未走 provider | `_backfill_missing_stock_metadata` |
| P2 | `_sync_treemap_stock_meta` 写 snapshot_cache 未取写锁 | 同名函数 |
| P3 | AKShare 龙虎榜双层 DEBUG（源故障零日志）；`quiet` 未覆盖 provider 异常分支；归档表按 trade_date 双计风险；`extract_dates` 只扫前 20 项；`_COL_RETRY_AT` 无界增长等 | 见 2026-11-01 OCR 报告 |
