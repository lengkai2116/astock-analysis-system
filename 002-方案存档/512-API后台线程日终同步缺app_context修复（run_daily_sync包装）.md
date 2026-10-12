# 512号｜API 后台线程/APScheduler 任务缺 app_context 全量修复

> **版本**：v1.1（2026-10-12 开号拍板 + 全量 8 处修复 + 验证通过）
> **v1.1 补充**：实测发现 `run_daily_sync` 只是冰山一角——**另有 7 个 APScheduler 后台任务长期静默失败**（10-04 周度报告已实证「Working outside of application context」；周度赢率/策略健康/月度 Stock/月度参数同型，用 `current_app.app_context()` 的错误模式——`current_app` 在无 context 线程解析即抛）。用户拍板：**512 + 全量同类修复**（统一 `self._app.app_context()` 模式）、标准模式重启观察验证。
> **前置**：511号 附带发现（`scheduler_manager.py:425` "日终同步失败: Working outside of application context"）
> **性质**：后台线程/调度任务上下文修复（非「果」层判定语义）

---

## 一、缘起与拍板记录（2026-10-12）

511号 实施后核查附带发现 → 只读核查确认 `run_daily_sync` 三入口缺 context → 用户「开号实施」→ 实施中实测暴露更大的 7 处同类缺陷 → 拍板扩大：

| 拍板 | 决策 | 实质 |
|------|------|------|
| 修复范围 | **512 + 全量同类修复** | 8 个后台任务统一 `self._app.app_context()`：`run_daily_sync`（3 入口）+ 周度赢率/策略健康/周度报告/月度参数/月度 Stock（5 无条件注册）+ 信号回算/盘中推送 5s/30s（仅单 API 部署注册） |
| 验证方式 | **标准模式重启观察** | `DATA_DAEMON_RUNNING=1` 下观察 5 个无条件任务不再报错；定向线程验证 context 内 db 查询成功 |

## 二、根因与现状核查（2026-10-12 代码实证）

### 根因：APScheduler 后台线程无 Flask app context

`APScheduler BackgroundScheduler` 的 job 在线程池执行，**不继承 Flask app context**。凡后台任务内部访问 Flask-SQLAlchemy（`db.session`/`Model.query`）或 `current_app` 均抛 `RuntimeError: Working outside of application context`。

### 关键模式错误：`current_app.app_context()` 是错误模式

最小实验证实：**无 app context 的线程中访问 `current_app` 本身（LocalProxy 解析）即抛错**，故 `with current_app.app_context():` 永远进不去、任务必失败。正确模式 = `with self._app.app_context():`（`scheduler_manager` 持有 `self._app`）。

### 8 处缺陷清单（全已修复）

| # | 任务 | 注册条件 | 修复前 | 修复 |
|---|------|---------|--------|------|
| 1 | `run_daily_sync`（日终） | 3 入口（APScheduler+catch_up×2） | 无 context | `_run_daily_sync_in_context` 包装 |
| 2 | `_run_weekly_eval`（周度赢率） | 无条件 | 无 context → `run_weekly_batch_eval`→`SignalRecord.query` 抛 | `self._app.app_context()` |
| 3 | `_run_health_check`（策略健康） | 无条件 | 同上 | `self._app.app_context()` |
| 4 | `_run_weekly_report`（周度报告） | 无条件 | 同上（10-04 已实证失败） | `self._app.app_context()` |
| 5 | `_run_param_plateau_check`（月度参数） | 无条件 | 无 context | `self._app.app_context()` |
| 6 | `_run_stock_sync`（月度 Stock） | 无条件 | `current_app.app_context()` 错误模式 | `self._app.app_context()` |
| 7 | `_run_signal_checkpoint`（信号回算） | 无 daemon 才注册 | `current_app.app_context()` 错误模式 | `self._app.app_context()` |
| 8 | `_market_snapshot_push_wrapper_5s/30s`（盘中推送） | 无 daemon 才注册 | `current_app.app_context()` 错误模式 | `self._app.app_context()` |

### 关键环境事实（避免误判）

- **标准双进程模式**（`start.command` 设 `DATA_DAEMON_RUNNING=1`）：日终/信号回算/盘中推送**不注册**（daemon 独立管理，`data_daemon.py:7618 _run_signal_checkpoint` 有 daemon 版）；**5 个无条件任务仍注册**（周度/月度/Stock）——即 #2~#6 是标准模式真实缺陷。
- **先前直启刷屏**（511/512 验证早期用 `run.py` 无 `DATA_DAEMON_RUNNING`）导致盘中推送被注册并刷错——**验证方式错误，非生产问题**；已恢复标准模式。

## 三、修复设计

### ① `run_daily_sync` 三入口（512 v1.0 已实施）

新增 `_run_daily_sync_in_context`（`with self._app.app_context(): return self.run_daily_sync()`）；APScheduler `:141`、catch_up 两线程 `:466/:474` 改调包装。

### ② 其余 7 处（512 v1.1 扩展）

每个任务函数体内部包 `with self._app.app_context():`（`_run_stock_sync`/信号回算/推送从 `current_app.app_context()` 改 `self._app.app_context()`，删除 `from flask import current_app` 死导入）。

## 四、验证口径（v1.1 已执行）

- **静态**：`py_compile` 通过；ruff 零错误；`test_320_l4_push_guard.py` 2 passed。
- **定向线程验证**（独立线程模拟 APScheduler）：
  - `param_plateau: OK`（512 修复后任务线程内成功）
  - `db_query: OK`（`self._app.app_context()` 下 `SignalRecord.query` 成功）
  - `db_query_NO_context: RuntimeError`（对照实证：无 context 必抛——修复必要性成立）
- **标准模式重启观察**（`DATA_DAEMON_RUNNING=1` 重启 API）：health 200、0 条 `Working outside`/`database is locked`/`Traceback`、5 个无条件任务正常注册、catch_up 线程无异常、写锁仍空闲（511 修复保持）。
- **全量回归**：本次盘中未做；后续按 `full-regression-daemon-must-stop.md` 约定择机补跑。
