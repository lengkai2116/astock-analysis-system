---
title: 538-仪表盘P2修复（板块涨跌家数+热度补算+market_stats缺PE）
type: 实施方案
date: 2026-10-22
status: 已完成（P2，2026-10-22）
---

# 538 仪表盘 P2 修复

**缘起**：537 修完 P1 后，用户拍板「开538号，修P2」。范围仅 2026-10-22 第四轮核查的 P2 三项。
**拍板（2026-10-22）**：P2-3 先补采 10-21 `daily_basic.pe_ttm`；若仍全空，允许 `pe_percentile=None` 落库（其余指标正常），不再让 state/alerts/breadth 停在 10-20。

---

## 一、P2 实证

1. `/market/sector-sector`：10 个板块 `up_count/down_count=0`、`lead_stock=""`；DB 降级分支硬编码。
2. `/market/sector-heat`：date=2026-10-19、`prev_rank` 全 null——`sector_fund_heat_cache` 仅有 10-19 一天；`/market/sector-heat-dim` 停在 10-20。
3. `market_stats_cache` 最新 10-20；daemon 反复报 `pe_percentile 无 2026-10-21 日源数据（置 None，不落库）`，10-21 `daily_basic_cache.pe_ttm` 5568 行全 NULL → `/market/state`、`/market/alerts` 停在 10-20；`/market/breadth` 家数 10-21、比率取 10-20。

---

## 二、实施

### P2-1 板块涨跌家数/领涨股

`get_sector_changes` DB 聚合增加：
- `up_count = pct_chg > 0` 计数、`down_count = pct_chg < 0` 计数；
- `lead_stock` = 行业内 `pct_chg` 最大个股名称（仅对 ≤31 个领涨代码调用 `_get_stock_names`，成本可控）；
- 前端板块柱状图 tooltip 展示涨跌家数与领涨股（数据缺失显示 0/空，不再硬编码）。

### P2-2 板块热度补算

- `sector_fund_heat_cache` 补 10-20、10-21 两天（同 530 RAW-2D 口径：近5日主力净流入 ÷ 当日流通市值）。
- `sector_heat_dim_cache` 补 10-21（复用 532 `build_sector_heat_rows` / 回算脚本）。
- 不改 daemon 日常调度；若下一次 EOD 仍不续算，再单独开号查管道。

### P2-3 market_stats 缺 PE

- 先重采 10-21 `daily_basic`（`pe_ttm` 仍空则保留）。
- `_precompute_market_stats` 的 426 P0-1 守卫把 `pe_percentile` 列为可选增强项：缺源时日志告警但允许落库；其余核心项缺源仍不落库。
- 重算并落库 10-21 `market_stats_cache`，使 state/alerts/breadth 同日。

---

## 三、验证

- 新增 `test_538_p2_dashboard_fixes.py`，覆盖板块涨跌家数/领涨股。
- 定向回归 537/535/533/524。
- 实机：`/market/sector-sector` 家数非 0、领涨股非空；`/market/sector-heat` date=10-21 且 prev_rank 有值；`/market/sector-heat-dim` date=10-21；`/market/state`/`alerts`/`breadth` 统一 10-21。
- 前端 `node --check`。

---

## 四、实施结果（2026-10-22）

### P2-1

- `get_sector_changes` DB 聚合已计算 `up_count/down_count`，并按行业 `pct_chg` 最大个股补 `lead_stock`。
- 实机 `/market/sector-sector`（10-21）：传媒 84 涨/40 跌/领涨兆讯传媒；农林牧渔 73/23/东方海洋；通信 76/42/通宇通讯。
- 前端板块柱状图 tooltip 追加涨跌家数与领涨股。

### P2-2

- `sector_fund_heat_cache` 补 10-20、10-21 各 31 行业（`_538_backfill_p2_sector_heat.py`）。
- `sector_heat_dim_cache` 补 10-20/10-21 各 31 行业（532 RAW-2E 回算，未改 yaml 阈值）。
- 实机 `/market/sector-heat` date=10-21、prev_rank 有值；`/market/sector-heat-dim` date=10-21、prev_date=10-20。

### P2-3

- 重采 10-21 `daily_basic`：`pe_ttm` 非空 0 → 3936 行。
- `market_stats_cache` 10-21 已落库：`pe_percentile=1.0`、`turnover_percentile=0.87295`、`limit_ratio=10.0`。
- `_precompute_market_stats` 的 426 守卫已将 `pe_percentile` 列为可选增强项（仍缺时允许空值落库，其余核心项缺源仍不落库）。
- 实机 `/market/state` data_date=10-21；`/market/alerts` date=10-21、count=0；`/market/breadth` trade_date=10-21、ma20=18.8、limit=10.0、turn=87.3、history 末条 10-21。

### 验证

- 新增 `test_538_p2_dashboard_fixes.py` 1 用例；538+537+535+533+524 定向 **28 passed**。
- `py_compile` 通过；前端内联脚本 `node --check` 通过。
- `data_daemon.py` 的 ruff 基线既有告警未在本轮处理；本轮新增/改动文件单独 lint 通过。

## 五、不在本轮

- 板块热度调度链路若仍不自动续算，单独核查 daemon EOD。
- 其他 OCR 历史暂缓项不动。
