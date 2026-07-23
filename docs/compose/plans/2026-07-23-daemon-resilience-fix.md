# data_daemon 崩溃韧性与日终同步兜底方案

**Goal:** 解决 daemon 崩溃后不自动重启、日终同步错过、分钟数据不回填、日志膨胀恶性循环问题

**Architecture:** 4 个独立任务：进程守护 → 启动兜底 → 日志控制 → 分钟补采

---

### Task 1: 进程守护 — launchd TCC 绕过

**根因：** macOS TCC 阻止 `~/Desktop/` 路径执行 → launchd KeepAlive/RunAtLoad 失效 → Login Items 只跑一次不恢复

**方案选型：**

| 选项 | 复杂度 | 可靠性 | 说明 |
|------|--------|--------|------|
| A. 移出 `~/Desktop/` | 高 | ✅ | 需要迁移整个项目，影响大 |
| B. 签名 Python 二进制 | 中 | ⚠️ | 每次 Python 更新需重新签名 |
| **C. 简单看守脚本** | **低** | **✅** | **start_daemon.sh 加 while 循环，崩了自动重启** |

**推荐方案 C**（改动最小，一行脚本）：

```bash
# start_daemon.sh 修改：加 while 循环
#!/bin/bash
sleep 30
cd "/Users/kalence/Desktop/01-A股股票分析系统/backend" || exit 1
while true; do
    DATA_DIR="/Users/kalence/Desktop/01-A股股票分析系统/data" \
      "/Users/kalence/Desktop/01-A股股票分析系统/backend/.venv/bin/python3" \
      data_daemon.py
    logger "data_daemon exited (code $?), restarting in 10s..."
    sleep 10
done
```

**Files:**
- Modify: `start_daemon.sh`

---

### Task 2: 启动兜底 — 检查是否错过日终同步

**根因：** daemon 恢复运行时，15:30 窗口已过，不会自动补日终同步

**方案：** 在 `main()` 中 `run_integrity_check()` 之后，新增日终同步检查逻辑：

```python
def _check_daily_sync_backfill():
    """开机自检：如果当前 >15:30 且今日未完成日终同步，立即触发"""
    now = datetime.now()
    if now.weekday() >= 5:
        return  # 非交易日跳过
    if now.hour < 15 or (now.hour == 15 and now.minute < 35):
        return  # 还没到15:35，等正常窗口

    today = now.strftime('%Y%m%d')
    try:
        cnt = _ecm.conn.execute(
            "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?",
            [now.strftime('%Y-%m-%d')]
        ).fetchone()[0]
        if cnt < 1000:  # 日线数据不足 → 日终同步未执行
            logger.info("检测到今日日终同步未执行（日线不足），触发补采...")
            run_daily_sync()
            logger.info("日终补采完成")
    except Exception as e:
        logger.warning(f"日终同步自检失败: {e}")
```

在 `main()` 中的位置：
```python
    run_integrity_check(backfill_days=3)
    _check_daily_sync_backfill()    # ← 新增
    _check_precompute_status(today) # 原有
```

**Files:**
- Modify: `backend/data_daemon.py`

---

### Task 3: 日志控制 — 限制预计算失败的静默 WARNING 洪流

**根因：** `_run_precompute()` 对 5000 只 × 3 类异常逐一输出 WARNING，且异常被 except 捕获后不阻断流程但日志刷爆

**方案：** 将已知的预计算异常降级为 DEBUG，只对首次出现输出一次 WARNING：

在 `_run_precompute()` 中（`data_daemon.py` 约 1300 行），将统一异常处理改为：

```python
    except Exception as e:
        if not hasattr(_run_precompute, '_warned_errors'):
            _run_precompute._warned_errors = set()
        err_key = str(e)[:50]  # 截取前50字符作为去重key
        if err_key not in _run_precompute._warned_errors:
            _run_precompute._warned_errors.add(err_key)
            logger.warning(f"策略预计算异常（后续同类错误仅DEBUG）: {e}")
        else:
            logger.debug(f"策略预计算异常: {e}")
```

也可在 `signal_computation_service.py` 中将已知的 Chanlun/PreFilter 异常降级（但改动更大。建议先做 daemon 层的，一行改动挡掉 5000 条 WARNING）。

**Files:**
- Modify: `backend/data_daemon.py`（`_run_precompute()` 的 except 块）

---

### Task 4: 分钟数据 — 日终补采触发优化

**根因：** `_batch_backfill_minute_kline()` 在日终同步后触发，但只补自选股。并且 Tushare `stk_mins` 接口限流 1次/分钟

**方案：** 在 `run_daily_sync()` 末尾已有分钟回填触发。可增强为：

```python
    # 分钟K线回填（后台低优，补齐盘中未覆盖的股票）
    try:
        threading.Thread(target=_run_minute_backfill, daemon=True).start()
        logger.info("  分钟K线回填已触发（后台）")
    except Exception as e:
        logger.warning(f"  分钟K线回填触发失败: {e}")
```

但 Tushare `stk_mins` 限流太严（1次/分钟），靠逐只补无法满足全市场。回到 292 号架构的正确做法：

> **分钟数据应在数据采集时就写入 ECM，不依赖日终补采。**

当前 daemon 已经有 mootdx `minutes()` 线程在工作（`[minutes补齐] 完成: 88 只`），但它的补采逻辑有问题——每次只补 88 只自选股，而且用的是 Tushare pro_bar（限流）。

**正确做法：** 利用已经工作的东财 HTTP 快照数据（5s 周期），盘中就写入 5min 聚合 K 线。这其实是 252 号方案 Phase 1 的设计——`_feed_minute_aggregator()` 已经存在，但之前依赖 mootdx quotes() 的数据，现在快照数据来自东财HTTP，需要验证聚合链路是否仍然生效。

检查 `_feed_minute_aggregator()` 是否正常工作：
- 如果工作：只需确保它把聚合结果写入 `minute_kline_cache`，盘中即可拥有全市场分钟数据
- 如果不工作：把东财快照数据接入聚合器即可

**Files:**
- Verify: `mootdx_collector.py` 中的 `_feed_minute_aggregator()` 调用（已存在于 `_collect_dual_source_fallback()` 中）

---

### 实施顺序

| 任务 | 预计 | 效果 |
|------|------|------|
| **Task 1** 看守脚本 | 5min | daemon 崩溃后 10s 自动重启 |
| **Task 2** 启动兜底 | 15min | daemon 恢复后立即补日终同步+分钟数据 |
| **Task 3** 日志降级 | 5min | 日 WARNING 从 ~200MB 降到 ~1MB |
| **Task 4** 分钟链路验证 | 20min | 盘中即可获得全市场分钟数据，不依赖日终 |

**4 个任务互不依赖，可独立实施。** 其中 Task 1 + Task 3 合计 10 分钟即可阻断恶性循环的核心环节。
