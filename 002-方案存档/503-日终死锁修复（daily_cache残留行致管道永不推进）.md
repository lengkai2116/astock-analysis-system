# 503号｜日终死锁修复（daily_cache 残留行致管道永不推进——管道自愈 + 启动补采双管）

> **版本**：v1.1（2026-10-01 开号拍板 + A/B 实施 + 探针 13/13 全绿 + 定向 112 passed）
> **v1.1 补充**：A（管道自愈 `_maybe_backfill_daily` 接入 has_data 分支）+ B（`_core_data_stale` daily_cache 行数判断）已实施；探针 `_503_deadlock_probe.py` 13/13；定向回归 112 passed；data_daemon ruff 保持基线 38 errors 零新增。
> **前置**：`project/daily-eod-deadlock.md`（2026-09-28 实证死锁链）；resume-20261001 优先序第 1 项
> **性质**：管道推进/完整性判断修复（非「果」层判定语义）——按惯例**先核查+拍板、后实施**

---

## 一、缘起与拍板记录（2026-10-01）

用户「继续推进日终死锁修复」（resume-20261001 优先序第 1 项）→ 只读核查死锁链当前代码（行号较记忆已偏移）→ 2 组拍板 → 用户**全选推荐项**：

| 拍板 | 决策 | 实质 |
|------|------|------|
| 修复策略 | **管道自愈 + 启动补采双管** | A：`_drive_pipeline` has_data=False 时主动 `_batch_daily` 补采（30s tick 级自愈）；B：`_core_data_stale` 增加「最新日期行数<阈值视为滞后」→ 启动/整点 HIGH 补采 |
| 补采时点 | **≥18:00/历史才补** | 今日仅 `_is_today_data_ready()`（交易日且≥18:00，Tushare 已发布）触发；历史日期直接补；<18:00 长冷却（30min）防空转 |

## 二、死锁链现状核查（2026-10-01 代码实证，行号已较记忆偏移）

| # | 环节 | 当前代码（data_daemon.py） | 问题 |
|---|------|--------------------------|------|
| 1 | `_get_latest_data_date`（:6520） | `COUNT(*)` 全表>0 → 取 MAX(trade_date) | **全表行数≠最新日期行数**——96 行残留（深市次新盘中路径写入）→ 返回 09-28 |
| 2 | `_drive_pipeline`（:6613） | `has_data = COUNT(*) WHERE trade_date=? >= 4000`；False → `logger.debug` + **return** | **静默 return 不推进**（连 COL 阶段都进不去）；且**不因 ≥18:00 自愈**（补采只在独立巡检） |
| 3 | COL 跳过（:6645） | `数据已完整 → 直接标记 done` | 死锁场景进不去（has_data 检查先 return）——此为正常路径优化，非根因 |
| 4 | `_core_data_stale`（:311） | 仅看 MAX(trade_date) 滞后交易日（432 R3） | **不看行数** → 96 残留日判「不滞后」→ 启动/整点 HIGH 补采不触发 |
| 5 | `run_integrity_check` 今日补采（:2422） | 受 `_is_today_data_ready()`（≥18:00）门控 | <18:00 重启时跳过今日 → 无补采；>18:00 也仅靠独立巡检（间隔可达 1h+） |

**诱因**：daemon 在 <18:00 重启（收盘前）错过盘中采集 → 今日日线仅残留少量行（盘中路径写入）→ 上述 1/2/4 互锁 → 日终永不推进，直至手工 `_batch_daily`。

**阈值现状**：管道推进门槛 has_data **4000**（硬编码）；完整性补采 DAILY_THRESHOLD **5000**——语义各归各（推进 vs 完整），修复保持。

## 三、修复设计

### A. 管道自愈（`_drive_pipeline` has_data=False 分支）

```python
has_data = _query_table('daily_cache',
    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [data_date]) >= 4000
if not has_data:
    # 503号 A：死锁自愈——数据日期行数不足（如盘中残留 96 行）时主动补采，
    # 而非静默 return 等独立巡检（最长 1h+ 才可能补，日终卡死）
    _maybe_backfill_daily(data_date)
    return
```

新增 `_maybe_backfill_daily(data_date)`：
- **发布门控**：`data_date==今天` 且 `not _is_today_data_ready()`（<18:00）→ 记录状态并 return（等 Tushare 发布，长冷却 30min 后再试）；历史日期直接补。
- **防抖**：模块级 `_DAILY_BACKFILL_STATE = {data_date: (ts, last_n)}`；常规冷却 10min；`last_n==0`（Tushare 空返回/失败）冷却拉长 30min。
- **动作**：`_batch_daily(data_date.replace('-',''))` → 记 `[管道自愈] {date} 日线不足，触发补采 {n} 条`；异常记 warning 不抛。

### B. 启动补采增强（`_core_data_stale`）

仅对 **daily_cache**（死锁链主角）增加行数判断：
```python
# 503号 B：行数完整性——最新交易日行数不足（如盘中残留 96 行）视为滞后
# （旧逻辑只看 MAX(trade_date) 判不滞后 → 启动/整点 HIGH 补采永不触发）
latest_count = _query_table('daily_cache',
    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [latest])
if latest_count is not None and latest_count < DAILY_THRESHOLD:
    logger.warning(f"  [启动补采] 日线(daily_cache) 最新日 {latest} 仅 {latest_count} 行（需≥{DAILY_THRESHOLD}），视为滞后")
    return True
```
其他表（daily_basic/moneyflow/stk_limit）保持日期滞后判断（不动，避免量级误判）。

> 注：B 对「历史日期残留」重启场景有效（HIGH 补采→run_integrity_check 补历史日，不受 ≥18:00 门控）；对「当日 <18:00 残留」由 A 在 ≥18:00 后下一个 30s tick 补采（比独立巡检快）。两者互补覆盖死锁全链。

## 四、验证口径

- **单元探针**（`_503_deadlock_probe.py`，mock 不触 Tushare/真库写）：
  - A-1 门控：mock `_is_today_data_ready=False` + data_date==今天 → `_batch_daily` 未被调（等发布）；
  - A-2 历史日：data_date==昨日 → `_batch_daily` 被调、补采日期传 YYYYMMDD；
  - A-3 防抖：同日期 10min 内二次调用 → `_batch_daily` 只调一次；last_n==0 时冷却 30min；
  - A-4 异常：`_batch_daily` 抛错 → 记 warning 不向上抛；
  - B-1：mock `_query_table` daily_cache 最新日 96 行 → `_core_data_stale()` True；
  - B-2：最新日 5557 行 → False（保持日期滞后判断）。
- **定向回归**：`py_compile` + ruff + 相关测试（426/432/355/411 管道/完整性）。
- **全量回归**：停 daemon 后全量 pytest（同 502 前置）；跑完重启 daemon。
- **实测观察**（推送后）：daemon 下次 <18:00 重启场景由 A 在 ≥18:00 自动补采解除（不手工介入）。

## 五、待定登记

| 登记 | 内容 | 处置 |
|------|------|------|
| 登记-1 | has_data 4000 vs DAILY_THRESHOLD 5000 语义并存 | 保持（推进门槛 vs 完整门槛）；修复用各自阈值 |
| 登记-2 | `_get_latest_data_date` 加「最新日期行数判断」 | **不改**（数据驱动核心、影响面大）；A/B 已覆盖死锁 |
| 登记-3 | daily_basic/moneyflow 等表是否同样加行数判断 | 本号不动（死锁主角为 daily）；如后续同类残留再扩展 |

## 六、沟通记录

- **2026-10-01 开号**：核查死锁链 5 环节（行号偏移核实）→ 2 组拍板（策略=双管、时点=≥18:00/历史）→ 本档 v1.0 落盘。
- **2026-10-01 实施（v1.1）**：A+B 双管落地——`_maybe_backfill_daily`（发布门控 + 10min/30min 双冷却防抖 + 异常捕获）接入 `_drive_pipeline` has_data=False 分支；`_core_data_stale` 对 daily_cache 最新日行数 <DAILY_THRESHOLD(5000) 视为滞后。探针 13/13（A-1 门控/A-1b ≥18:00/A-2 历史日/A-3 防抖双冷却/A-4 异常/B-1 96 行滞后/B-2 5557 行正常）；定向 112 passed；全量回归待 daemon 重启后确认。

## 七、实施记录（提交后补填）
