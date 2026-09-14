---
title: daemon开机大量采补与Tushare空返回诊断报告
type: 诊断报告（含修复建议）
date: 2026-09-14
version: v1.1（v1.0 诊断存档 + v1.1 修复落地与启动轮验证）
status: ✅ 修复已落地（R1-R5，启动轮端到端验证通过）
related:
  - 428-427虚拟测试暴露问题修复方案
  - 425-数据端写入优先级调度与STG启动补采闭环方案
  - 431-430号遗留项核查清单与处置建议
---

# 432 — daemon 开机大量采补与 Tushare 空返回诊断报告

> **性质**：诊断存档（含修复建议）。v1.0 仅固定根因清单供决策；**v1.1（2026-09-14）按用户指示落地 R1-R5 全部修复并完成启动轮端到端验证**。
>
> **触发场景（用户提问）**：每天开机后 daemon 都有大量采补；前两日（09-12 周六 / 09-13 周日）为周末，每日采补本应补完，为何仍在采补？且存在大量 Tushare 空返回，是否正常？
>
> **核查手段**：`backend/logs/data_daemon.log`（2026-09-14 启动轮，442 行）+ 分库 SQLite 表查询（`data/duckdb/`）+ `data_daemon.py` / `enhanced_cache_manager.py` / `sharding_manager.py` 代码通读。**全程只读**（库表仅 SELECT）。
>
> **数据快照时间**：2026-09-14（启动轮 07:10~07:15；库表查询当日）。
>
> **编号说明**：`002-方案存档/` 当前最大实体编号为 431，故本文档取 **432**。（429 号仍被 425/426 号预留给「daemon 卡死根治」，无实体文件，未占用编号空间。）

---

## 一、结论摘要

1. **"每天开机大量采补"不是正常的**，由三个叠加原因造成，其中**主因是复权因子主表 / 分年表"两张皮"**：写入只落分年表、审计却读主表 → 恒报"滞后 27 天" → 每次完整性检查都触发一次 **250 万条**的降级逐只全历史重采（纯浪费）。
2. **大量 Tushare 空返回一半正常、一半异常**：盘前/周末查当日数据的空返回属正常现象（Tushare 日线收盘后才发布）；但**指数/测试代码混入日线补采列表**、**复权因子批量查询固定用"昨天"（周日）** 属系统缺陷，应避免。

---

## 二、关键证据（2026-09-14 快照）

| # | 证据 | 数值/内容 | 来源 |
|:--:|---|---|---|
| E1 | daily_cache 最新交易日 | **2026-09-11**（5553 行），09-12/13/14 无数据；09-07~09-11 逐日 5552~5555 行完整 | `market_cache.db` |
| E2 | adj_factor **主表** `adj_factor_cache` | MAX(trade_date)=**2026-08-18**；08-19 后 **0 行** | `history_cache.db` |
| E3 | adj_factor **2026 分年表** `adj_factor_cache_2026` | MAX=**2026-09-11**（5562 行/日，逐日完整），09-14 无（正常，当日未发布） | `history_cache.db` |
| E4 | 启动轮日志 | `[复权因子] 滞后 27 天（阈值3天），触发补采...` → `[复权因子] 降级逐只同步 2547423 条 (共 500 只)`；07:13:46 时效性仍报 `复权因子(adj_factor_cache) 滞后 27 天` | `data_daemon.log` |
| E5 | 启动轮空返回清单 | `trade_date=20260914` 的 daily / daily_basic / moneyflow / stk_limit / top_list / index_daily（07:13 盘前）；`adj_factor trade_date=20260913`（周日）；`top_inst trade_date=20260914`（07:10 盘前） | `data_daemon.log` |
| E6 | daily_cache ts_code 后缀分布 | BJ 273551 / SH 2726288 / **SI 162** / SZ 3414664 / **TEST 2** | `market_cache.db` |
| E7 | K线补采列表 | 124 只含 `000001.SH`、`399001.SZ`、`801xxx.SI`（申万行业指数）、`999997.TEST`、`999999.TEST` 等，`pro.daily` 对它们**必然空返回** | `data_daemon.log` + 库 |

---

## 三、根因分析

### 原因 A（主因）：adj_factor 主表/分年表"两张皮" → 恒滞后 27 天 → 每日 250 万条重采

**写入路径**：`EnhancedCacheManager.cache_adj_factor_data`（`enhanced_cache_manager.py:1760`）按 `trade_date` 年份分组，写入**分年表** `adj_factor_cache_YYYY`（经 `sharding_manager` → `history_cache.db`），**从不写主表** `adj_factor_cache`。主表自 **2026-08-18**（356 号大表拆分落地前后）起停更。

**审计/读取路径**：`data_daemon.py:1778-1790` 用
`_query_table('adj_factor_cache', "SELECT MAX(trade_date) FROM adj_factor_cache")` 读**主表** → 08-18 → 距今日（09-14）27 天 > 阈值 3 → 触发 `_batch_adj_factor()`。

**补采路径**：`_batch_adj_factor`（`data_daemon.py:1115`）批量查询用
`yesterday = (datetime.now() - timedelta(days=1))` → 今日（09-14 早）为**周日 09-13** → Tushare 必然空返回 → **降级逐只重采 `daily_cache` 前 500 只的全历史复权因子（2547423 条）**。

**闭环**：重采结果经 `cache_adj_factor_data` 仍写入**分年表** → 主表依旧 08-18 → **每次启动（`data_daemon.py:6326`）与每整点巡检（`data_daemon.py:6487`）都重复这轮 250 万条重采**。这是"每天开机大量采补"的最大来源，且数据本身并不缺（E3 证明分年表已完整到 09-11）。

### 原因 B：滞后判定用自然日，周末被计入 → 周一开机恒 HIGH

`_core_data_stale`（`data_daemon.py:232-268`）与 adj_factor 审计（`:1778-1796`）的滞后天数都用
`(今天 - 最新交易日).days`（自然日）。09-11（周五）→ 09-14（周一）= **3 天 > 1** → 周一开机恒进 HIGH 补采（启动日志实证：`[启动补采] 日线(daily_cache) 滞后 3 天，需要 HIGH 补采` → mootdx 高频线程降频让路）。实际上 09-11 数据完整（E1），缺的只是"周末两天没有交易日"这一事实未被识别。

### 原因 C：工作日"今日数据"检查在盘前采当日数据 → 必然空返回

`run_integrity_check`（`data_daemon.py:1816-1833`）用 `_is_weekday = datetime.now().weekday() < 5`（**非** `_is_market_day` 的节假日判断）→ 周一为真 → 检查 today（09-14）行数 < 阈值 → 调 `batch_fn(today)` → 07:13 Tushare 当日日线尚未发布（一般收盘后 17-18 点才出）→ 必然空 → `补采 0 条`。E5 中 daily/daily_basic/moneyflow/stk_limit/top_list/index_daily 的 `trade_date=20260914` 空返回全部来自这里。龙虎榜席位 `top_inst` 同理（盘后才发布）。

---

## 四、Tushare 空返回分类

| 空返回 | 判定 | 说明 |
|---|---|---|
| `trade_date=20260914`（盘前）日线系列 | **正常** | Tushare 当日数据收盘后才发布，盘前/盘中查询必然为空 |
| `adj_factor trade_date=20260913`（周日） | **正常** | 非交易日无数据 |
| `top_list` / `top_inst` 当日 | **正常** | 龙虎榜盘后发布 |
| K线补采中 `000001.SH` / `399001.SZ` / `399006.SZ` 走 `daily` 接口 | **正常但应避免** | `daily` 接口无指数数据，应走 `index_daily` |
| K线补采中 `.SI` 申万行业指数、`.TEST` 测试代码 | **异常（系统缺陷）** | `daily_cache` 混入 162 条 SI + 2 条 TEST；`_find_kline_insufficient` 不区分代码类型 → 每次开机固定 30+ 次无谓空返回、白耗 Tushare 配额 |
| `_batch_adj_factor` 批量查询"昨天"（周日） | **异常（系统缺陷）** | 批量必然失败 → 每天降级 250 万条重采（原因 A） |

---

## 五、修复建议（按优先级）

| # | 建议 | 对应原因 | 效果 |
|:--:|---|---|---|
| **R1** | adj_factor 审计改读**分年表/视图**：`_query_table` 改用已存在的 `adj_factor_view`（`create_views.py` 的 UNION ALL 视图）或动态取最新年份表 | A | 一处改动终结每天 250 万条重采 |
| **R2** | `_batch_adj_factor` 批量查询用**最近交易日**（回退周末/节假日，可复用 `_is_market_day` / trading_hours），而非"昨天"；降级逐只也只补缺失日期段，不重采全历史 | A | 批量不再必败；重采量从 250 万条降至仅缺量 |
| **R3** | 滞后判定**排除周末/按交易日**：`_core_data_stale` 与审计 `days_lag` 用交易日历计算（周五数据到周一不算滞后） | B | 周一/节假日开机不再误触发 HIGH |
| **R4** | "今日数据"检查**加时段判断**：收盘后（如 ≥18:00）才检查当日，盘前/盘中跳过或改补最近交易日缺口；并将 `_is_weekday` 替换为 `_is_market_day`（消除节假日误判） | C | 消除盘前必然失败的空返回刷屏 |
| **R5** | K线补采**过滤非个股代码**：`_find_kline_insufficient` 排除 `.SI` / `.TEST` / 指数后缀（指数日线已有独立 `index_daily` 检查） | 空返回异常类 | 消除固定空返回、节省配额 |

**优先级组合**：R1+R2 是"每天开机大量采补"的直接解药；R3/R4/R5 消除空返回刷屏与 HIGH 误触发。

---

## 六、相关代码位置索引

| 位置 | 内容 |
|---|---|
| `data_daemon.py:1115` | `_batch_adj_factor`（批量用 yesterday → 降级逐只 500 只全历史） |
| `data_daemon.py:1778-1790` | adj_factor 时效性审计（读**主表** MAX(trade_date)） |
| `data_daemon.py:232-268` | `_core_data_stale`（自然日滞后 >1 天判定） |
| `data_daemon.py:1816-1833` | "今日数据"检查（`_is_weekday` 盘前补当日） |
| `data_daemon.py:1047` | `_find_kline_insufficient`（不区分代码类型） |
| `data_daemon.py:4889` | `_is_market_day`（trading_hours.is_holiday，已存在） |
| `data_daemon.py:6326` | 启动 `_run_priority_integrity_check(backfill_days=3)` |
| `data_daemon.py:6487` | 整点巡检（非交易时段）`_run_priority_integrity_check(backfill_days=1)` |
| `enhanced_cache_manager.py:1760` | `cache_adj_factor_data`（按年份写分年表，不写主表） |
| `sharding_manager.py:116` | `adj_factor_cache` → history_cache.db（主表路由） |
| `sharding_manager.py:142-144` | 前缀规则 `adj_factor_cache_` → history_cache.db（分年表路由） |

---

## 七、遗留风险与待决策点

1. **主表 `adj_factor_cache` 自 08-18 停更是 356 号拆分的预期副作用**（写入已切分年表），**v1.1 已改读分年表（R1）**，主表保留为历史只读；是否归档待确认（当前无消费方直接读主表时效）。
2. **v1.1 落地内容**（`data_daemon.py`，serena 结构化编辑 + 精确行编辑）：
   - **R1**：新增 `_get_adj_latest_date()` 读分年表最新日期；adj_factor 审计（完整性检查内）与 `_check_data_timeliness` 补充数据检查均改走该函数。
   - **R2**：`_batch_adj_factor` 改为最近 10 个交易日逐日批量（`_recent_trade_date`），删除降级逐只 500 只全历史路径（批量按日无数据时逐只必然无数据，降级纯浪费）。
   - **R3**：新增 `_lag_trading_days()` 交易日口径；`_core_data_stale`、adj_factor 审计、`_check_data_timeliness`（核心/补充数据）滞后判定全部改交易日口径。
   - **R4**：新增 `_is_today_data_ready()`（交易日且 ≥18:00）；今日数据检查、龙虎榜席位检查、指数日线今日检查加时段保护；回退补采循环与 idx_checks 节假日跳过（`_is_trading_day`）。
   - **R5**：`_find_kline_insufficient` SQL 排除 `.SI`/`.TEST`/`399%.SZ`/`000%.SH`/`899%.BJ`。
3. **验证结果（2026-09-14 07:41 启动轮 vs 07:10 修复前）**：

   | 项 | 修复前 | 修复后 |
   |---|---|---|
   | 复权因子审计 | 滞后 27 天 → 降级逐只重采 2547423 条 | 最新 09-11，滞后 1 个交易日 ✅，不触发 |
   | 今日数据检查 | 盘前补采 09-14 → 大量空返回 | 跳过（<18:00） |
   | K线补采 | 124 只（含指数/测试码 30+ 空返回） | 91 只纯个股，0 空返回 |
   | 启动优先级 | 滞后 3 天 → HIGH 降频 | 无 HIGH |
   | 时效性审计 | 滞后 3 天×4 + 滞后 27 天 警告 | 无警告 |
   | Tushare 空返回 | 大量 | **0** |
   
   辅助函数单测（`_lag_trading_days` 周末/节假日排除、`_recent_trade_date` 最近交易日、`_is_today_data_ready` 时段）与相关测试（test_425_priority / test_426_phase4_adj_factor / test_kline_adapter / test_426_phase4_retention，35 个）全部通过；`py_compile` 通过。
4. **429 号预留**给「daemon 卡死根治」，本文档不占用。
5. **未纳入本次范围的已知项**：`margin_cache` 审计仍为自然日口径（阈值 7 天宽，周末不误触发，仅日志口径差异）；背景数据（财务类）时效检查保持自然日（30 天宽阈值）；`[申万行业指数] 801020.SI 数据源永久缺失` 已有当日重试保护。

---

## 处置进度

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-09-14 | 首版诊断存档（含修复建议 R1~R5），未实施修复 |
| v1.1 | 2026-09-14 | **R1-R5 全部落地**（data_daemon.py），辅助函数单测 + 35 个相关测试 + 启动轮端到端验证通过；daemon 已重启运行 |
