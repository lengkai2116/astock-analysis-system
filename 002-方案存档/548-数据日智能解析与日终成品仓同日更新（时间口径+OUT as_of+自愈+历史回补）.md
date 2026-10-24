---
title: 548-数据日智能解析与日终成品仓同日更新（时间口径 + OUT as_of + 自愈 + 历史回补）
type: 修复
date: 2026-10-24
status: 核心已实施并实机验证；10-20/10-21/10-22 历史回补已完成
---

# 548｜数据日智能解析与日终成品仓同日更新

## 一、问题

2026-10-24 目检：10-23 日终已完整完成（22:35 QA 27 项 passed），但仪表盘 7 个模块仍显示 10-22；
`panel_date=20261023`、`stale=false`，前端无法识别滞后。另 10-20/10-21 管道停在 RAW-2C，
SIG/JUD/OUT 从未执行，历史快照 10-20~10-22 全缺。

## 二、根因

1. **OUT 构建用墙钟而非目标日**：`_build_out_market_panel(today)` 内部 `DashboardService()` 取
   `datetime.now()`；7 个模块走 `_get_best_trade_date(before=today)`（`WHERE trade_date < today`）。
   当日 22:32 构建时 `today=10-23` ⇒ 取到 10-22。跨夜完成时次日早晨构建恰好对上，问题被掩盖。
2. **读取层只认 asof**：`get_panel(asof_date=None)` 取 `MAX(asof_date)`，`attach_meta` 的 `stale`
   只比 `panel.asof_date` 与 `treemap.trade_date`，两者同为 10-23 ⇒ 恒 false。
3. **历史缺口无自动回补**：`_check_eod_completion` 仅 target==最新数据日才续跑；
   `_run_history_qa_patrol` 只 warning。
4. **数据侧**：两融周末不补（`days_lag>7` 才补）、ETF 份额 SH 段缺失、指数日线在 OUT 后补采、
   `sync_requests per_stock` 触发整表深度清洗 352 次。

## 三、设计：统一数据日解析

新增 `backend/app/services/market_date_resolver.py`：

- 输入：交易日历 + 当前时段 + 各日 `daily_cache` 行数 + `pipeline_status(SIG/JUD/OUT/QA)` + 实时快照可用性。
- 输出：`view_date / last_complete_date / data_status`。
- 状态：
  - `live`：交易日盘中，实时字段可用；EOD 模块仍锚定上一完整日。
  - `eod_partial`：当日 EOD 原料与 SIG/JUD/OUT 已就绪，QA 未完成（收盘后当天可用）。
  - `eod_final`：当日 QA 完成。
  - `previous_complete`：当日不可用，回退上一完整日。
  - `missing`：无数据。
- `eod_date()` 供 EOD 模块统一锚定；`expected_panel_date()` 供读取层判定陈旧。
- 30s 进程内缓存；纯函数 `resolve_from_inputs()` 可单测；不触发任何采集/计算。

## 四、改动清单（已实施）

| 文件 | 改动 |
|---|---|
| `app/services/market_date_resolver.py` | 新增解析器与 30s 缓存 |
| `app/services/dashboard_service.py` | `DashboardService(as_of=)` + `_eod_date()`；8 处 `before=today` 改为统一锚定（compact/`YYYY-MM-DD` 归一） |
| `data_daemon.py` | OUT 构建传 `pipeline_date` 作 as_of；新增 `_finalize_out_market_panel()`（QA 后终版重建，`OUT-MARKET-FINAL` 幂等）；`_check_eod_completion` 改用 `eod_date()` 并在 QA done 时触发终版重建；看门狗按步骤阈值（RAW-2 240min 等）；两融 `days_lag>1` 即补 |
| `app/services/out_market_reader.py` | `attach_meta` 增 `panel_data_date`，`stale` 同时比较 payload 内部数据日 |
| `tests/test_548_market_date_resolver.py` | 新增 5 例（同日 partial/final、盘后回退、盘中 live、非交易日、stale） |
| `tests/test_535_*` / `test_543_*` | 适配显式 as_of 与分步骤阈值 |

## 五、验证

- 定向测试：`test_548` 5 + `test_535` 4 + `test_543` 5 = **14 passed**。
- 一次性按 10-23 重建：`out_market_panel: 17/17 模块，异常 0，耗时 4.2s`。
- 实机 `/api/v3/dashboard/full`：breadth/limit_ecology/emotion/overview_panel/sector_changes/
  eod_snapshot/flows_30d 均 `panel_data_date=2026-10-23`、`stale=false`。
- 两融：启动补采 `2026-10-23 ~ 20261024` 写入 4034 条。
- 历史回补：10-20 完成（signal 5565 / status history 5565 / treemap history 5565）；10-21 完成（signal 5566 / status history 5566 / treemap history 5566，`snapshot_date=2026-10-21`）。
  - 10-21 首轮 JUD 失败：`_build_status_snapshot` 用 `snapshot_date=date('now')`，与 10-20 的 5565 行 `(ts_code, 2026-10-24)` 撞唯一键；改为目标交易日后修复。
  - `_build_treemap_snapshot` 回补时同步 `UPDATE snapshot_date=as_of`；回补脚本新增 `--skip-sig`，10-21 未重跑 SIG。
  - 10-20 history 的 `snapshot_date` 仍为 2026-10-24（`trade_date` 正确；唯一键 `(ts_code, snapshot_date)` 已被 10-19 的 10-20 占用，未强改，不影响按 `trade_date` 消费）。
  - 10-22 history 已于 2026-10-24 20:58 补齐（signal 5569 / status/treemap 各 5568，`snapshot_date=2026-10-22`）。

## 六、数据侧三项（2026-10-24 已实施）

1. **ETF 份额 SH 段**：新增 `_check_fund_share_completeness()` 接入 `run_integrity_check`，
   按 SH/SZ 行数判缺（<500 即重采）。实机 10-22/10-23 已补 **SH 1009**（SZ 792/794）。
   源侧 `fund_share(trade_date)` 实测返回 **1801 行（SH 1009 + SZ 792）**，首采只落 SZ
   属发布时序，重采即可补齐。
2. **`sync_requests per_stock` 写放大**：新增 `_batch_daily_single()`，`per_stock` 分支
   只同步该 `ts_code`，不再调用全市场 `_batch_daily`（原每请求触发 5,500+ 行整表深度清洗，
   10-23 实证 352 次）。
3. **OUT 前指数顺序**：新增 `_missing_index_codes()` / `_ensure_index_daily()`，OUT 前校验
   `BROAD_INDEX_CODES`（5 只）并在缺失时补采；巡检日志改为输出实际缺失代码，不再固定打印
   「4只」。
4. **测试**：`test_548_data_side_fixes.py` **5 passed**（缺失代码/补齐/跳过/单只日线/ETF 重采）。

## 七、待拍板

- 同日 `eod_partial` 是否在前端显式标注（当前仅 `data_status` 字段，前端未展示）。
- 历史回补窗口是否固定为“周六 08:00–14:00”（避免与交易日日终争锁）。
