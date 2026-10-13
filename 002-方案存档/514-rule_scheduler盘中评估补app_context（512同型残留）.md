# 514号｜rule_scheduler 盘中评估任务补 app_context（512 同型残留）

> **版本**：v1.0（2026-10-13 开号 + 实施 + 定向验证通过）
> **性质**：后台 APScheduler 任务上下文修复（**非**「果」层判定语义）
> **前置**：**513 号 #R2**（2026-10-13 仪表盘核查的附带发现）＝512 号「全量 8 处」的**同型遗漏点**
> **关联**：512 号（`_market_snapshot_push_wrapper_5s/30s` 等 8 处统一 `self._app.app_context()`）；511 号已修

---

## 一、缘起与拍板（2026-10-13）

2026-10-13 仪表盘核查（513 号）过程中，`app.log` / `data_daemon.log` 于 `09:34:32` 各出现 1 次：

```
[ERROR] app.services.rule_scheduler: 盘中评估异常: Working outside of application context.
```

只读核查 `app/services/rule_scheduler.py` 确认：**`register_intraday_eval` 的任务体是 5 个通知任务中唯一未包 app_context 者**（其余 `register_daily_eval:156` / `register_dormancy_check:191` / `register_weekly_health_report:225` / `register_retry_check:275` 均已 `with scheduler_manager._app.app_context():`）。用户拍板：**单开 514 号**按 512 模式统一修。

**影响面：API 与 daemon 双进程（2026-10-13 重启复核时确认）** —— `data_daemon.py` 多处调用 `create_app()`（`:3117/3273/3697/5537/5649/6213`），而 `create_app`（`app/__init__.py:324`）会 `RuleScheduler.register_all()` → **daemon 进程亦注册并执行 `notification_intraday_eval_15m`**（09:34 那条报错即来自 daemon 日志，daemon 的日志名被 `basicConfig` 硬编码为 `data_daemon`）。故本修复对两进程均有效，但**各自必须重启**才能加载新代码。另注：`create_app` 会把 `app.*` 日志写入 `app.log`，因此 daemon 的注册/执行行**也会出现在 `app.log`**（易被误判为 API 单进程所为）。

## 二、根因（与 512 同型）

`APScheduler BackgroundScheduler` 的 job 在线程池执行，**不继承 Flask app context**。凡任务体内访问 Flask-SQLAlchemy（`db.session` / `Model.query`）或 `current_app` 均抛 `RuntimeError: Working outside of application context`。`run_evaluation(mode='intraday')` 内部访问 db → 必抛。

**唯一缺口的证据**：

| 任务 | 任务体 app_context | 状态 |
|---|---|---|
| `register_intraday_eval` | ❌ 无 | **本号修复** |
| `register_daily_eval` | ✅ `:156` | 512 期已具备 |
| `register_dormancy_check` | ✅ `:191` | 512 期已具备 |
| `register_weekly_health_report` | ✅ `:225` | 512 期已具备 |
| `register_retry_check` | ✅ `:275` | 512 期已具备 |

## 三、修复（1 处）

`app/services/rule_scheduler.py` `register_intraday_eval.intraday_eval_job`：

```python
                try:
                    # 514号（512 同型残留）：APScheduler 线程无 app context，须显式建上下文，
                    # 否则 run_evaluation 内 db 访问抛 "Working outside of application context"
                    with scheduler_manager._app.app_context():
                        from app.services.notification_service import run_evaluation
                        result = run_evaluation(mode='intraday')
                        if result:
                            logger.info(f"盘中评估完成: {result.get('evaluated', 0)} 规则, "
                                        f"{result.get('triggered', 0)} 条触发")
                except Exception as e:
                    logger.error(f"盘中评估异常: {e}")
```

（`scheduler_manager` 实例持有 `self._app`，见 `scheduler_manager.py:65/73`。）

## 四、验证

- **定向测试** `backend/tests/test_514_intraday_eval_app_context.py`（1 passed）：以 `MagicMock` 承接 `add_interval_job` 捕获任务体，注入真实 `Flask(__name__)` 为 `_app`，monkeypatch `is_trading_time`→True 与 `run_evaluation`（内部访问 `current_app._get_current_object()`）→ 任务体执行成功且 `current_app` 即注入的 app ⇒ 证明已在 app context 内运行。
- `py_compile` 通过；`ruff` 无新增（本号未做全量回归）。
- 与 513 号定向测试合跑：**6 passed**。
- **实机确认（待观察）**：`DATA_DAEMON_RUNNING=1` 重启 API 后，交易时段 `notification_intraday_eval_15m` 不再报 `Working outside of application context`（下次触发为 15 分钟间隔）。

## 五、约定继承

**新增任何 APScheduler 后台任务 / 后台线程，若内部访问 Flask-SQLAlchemy 或 `current_app`，必须包 `self._app.app_context()`**（512 号教训，本号为该约定的第 9 个落实点）。
