---
title: 375 — 机会图谱弹窗内容核查与SIG-JUD管道诊断报告
date: 2026-08-28
status: 存档
depends:
  - 353-系统总体架构规划（v3.1）
  - 368-SIG-JUD-OUT管道贯通方案
  - 370-JUD环节独立化实施计划
---

# 375 — 机会图谱弹窗内容核查与SIG-JUD管道诊断报告

> **核查目的**：用户反馈前端机会图谱板块的"机会地图"弹窗内容输出不理想，需核查弹窗取数是否基于353号方案OUT维度，以及系统中SIG和JUD环节的运行状态和输出质量。

## 1. 弹窗数据来源核查

### 1.1 数据流路径

```
treemap API (/api/v3/opportunity-atlas/treemap)
  → snapshot_cache.db / treemap_snapshot 表
  → get_treemap_snapshot_items() 组装 JSON 响应
  → 前端 loadMarketData() 加载到 RAW_STOCKS
  → showDetail() 渲染弹窗
```

弹窗使用两类数据源：

| 数据段 | 前端字段 | 后端来源 | 当前状态 |
|--------|----------|----------|----------|
| 基础信息 | signal_strength, opportunity_type, right_side_confirm 等 | treemap_snapshot（JUD 步骤构建） | 有数据 |
| 七维体检 | sevenDimReport（读 one_liner_detail 或 seven_dim_report） | treemap API 未返回此字段 | **缺失** |
| 机会画像 | opportunityProfile（读 opportunity_profile） | treemap_snapshot → opportunity_tags_cache | 有数据但质量低 |
| L4 诊断 | 异步调用 /diagnose 接口 | status_snapshot + L4CrossValidator | 有数据 |

### 1.2 结论：弹窗七维体检数据**不来自**353号方案的OUT维度

原因链：

1. `strategy_signal_detail.seven_dim_json` 在 SIG 步骤生成 → 有数据（5578条）
2. OUT 步骤应将 `seven_dim_json` 透传到 `status_snapshot.one_liner_detail` → **全部为 NULL**（0/5576）
3. `treemap_snapshot` 表**没有** `one_liner_detail` 或 `seven_dim_report` 列
4. `get_treemap_snapshot_items()` **不返回**这些字段
5. 前端 `loadMarketData()` 中 `sevenDimReport` 尝试读 `s.seven_dim_report || s.one_liner_detail` → 始终为 null

## 2. SIG 环节运行状态

### 2.1 管道执行记录

| 日期 | 状态 | 耗时 | 备注 |
|------|------|------|------|
| 20260828 | pending | - | 未运行 |
| 20260827 | done | 8957.6s（~2.5h） | 正常完成 |
| 20260826 | pending | - | 未运行（管道阻塞在 COL-7） |
| 20260825 | done | 6591.0s | 正常完成 |

### 2.2 seven_dim_json 质量问题

`generate_seven_dim_from_signals`（status_engine.py:782）从5引擎信号提取七维描述，但实际产出**维度缺失严重**：

| 股票 | 产出维度 | 缺失维度 |
|------|----------|----------|
| 000001.SH | risk, summary（2/7维） | signal, structure, volume_price, chip_fund, emotion |
| 000002.SZ | volume_price, chip_fund, emotion, risk, summary（5/7维） | signal, structure |
| 000007.SZ | volume_price, chip_fund, emotion, risk, summary（5/7维） | signal, structure |

**缺失的关键维度**：
- `signal`（信号确认）：来自 Dim1SignalEngine
- `structure`（结构位置）：来自 Dim2StructureEngine
- `valuation`（估值定位）：来自 Dim7ValuationEngine

### 2.3 数据量

- strategy_signal_detail 总行数：33440
- 有 seven_dim_json：5578（最新交易日 2026-08-26）
- 有 dim_results_json：5576

## 3. JUD 环节运行状态

### 3.1 管道执行记录

| 日期 | 状态 | 耗时 | 问题 |
|------|------|------|------|
| 20260828 | pending | - | 未运行 |
| 20260827 | done | 4626.9s（~1.3h） | 正常完成 |
| 20260825 | **failed** | 0.3s | `cannot import name 'generate_summary_text'` |

### 3.2 20260825 导入错误

```
ERROR: cannot import name 'generate_summary_text' from 'app.opportunity_atlas.status_engine'
```

说明 `generate_summary_text` 函数曾被移除或重命名，导致 JUD 步骤失败。20260827 已修复。

### 3.3 JUD 输出质量

| 字段 | 填充率 | 说明 |
|------|--------|------|
| dim_engine_results | 100%（5576/5576） | 维度引擎结果完整 |
| opportunity_state | 100% | 仲裁状态完整 |
| consensus_rate | 有数据 | 共识率正常 |
| **one_liner_detail** | **0%（0/5576）** | OUT 透传失败 |

## 4. OUT 环节问题（根因）

### 4.1 透传逻辑

`_out_transmit_seven_dim`（data_daemon.py:3784）执行：

```sql
UPDATE status_snapshot SET one_liner_detail = (
    SELECT ssd.seven_dim_json
    FROM strategy_signal_detail ssd
    WHERE ssd.ts_code = status_snapshot.ts_code
    AND ssd.trade_date = ?
    AND ssd.seven_dim_json IS NOT NULL
)
WHERE status_snapshot.trade_date = ?
```

### 4.2 跨库问题

- `strategy_signal_detail` 在 `stock_cache.db`
- `status_snapshot` 在 JUD 步骤中写入 `snapshot_cache.db`
- `_ecm.conn` 指向的数据库与 `status_snapshot` 实际所在数据库不一致
- 导致 UPDATE 语句无法匹配到任何行 → one_liner_detail 全量为 NULL

### 4.3 treemap_snapshot 也存在跨库问题

- `treemap_snapshot` 在 `snapshot_cache.db`（5581行）
- `stock_cache.db` 中 `treemap_snapshot` 为 0 行
- API 通过 `get_treemap_snapshot_items()` 读取的是 `snapshot_cache.db`

## 5. 数据时效性

| 指标 | 值 | 说明 |
|------|-----|------|
| treemap_snapshot.snapshot_date | 2026-08-27 | 最新快照构建日期 |
| treemap_snapshot.trade_date | 2026-08-26 | 数据交易日 |
| strategy_signal_detail.trade_date | 2026-08-26 | 最新信号日期 |
| 今天 | 2026-08-28 | 管道 SIG/JUD/OUT 尚未运行 |
| **数据滞后** | **2个交易日** | 前端显示数据比实际滞后 |

## 6. 问题汇总

| # | 问题 | 严重度 | 根因 | 影响 |
|---|------|--------|------|------|
| 1 | 弹窗七维体检无数据 | **高** | OUT透传失败 + treemap_snapshot无此列 + API未返回 | 弹窗核心展示区空白 |
| 2 | seven_dim_json 维度不全 | **高** | generate_seven_dim_from_signals 仅从部分引擎提取 | 即使透传成功，七维体检也只有2-5维 |
| 3 | JUD 曾导入失败 | **中** | generate_summary_text 函数引用断链（已修复） | 20260825 管道中断 |
| 4 | 数据滞后 2 天 | **中** | 20260828 管道未运行到 SIG/JUD/OUT | 前端数据过期 |
| 5 | 弹窗依赖前端本地近似计算 | **低** | 操作建议等由前端 JS 本地计算 | 非后端权威结论 |
| 6 | status_snapshot 跨库存储 | **中** | JUD 写 snapshot_cache.db，OUT 读 stock_cache.db | one_liner_detail 全量 NULL |

## 7. 修复实施（2026-08-28 已完成）

### 7.1 T1：OUT 透传逻辑修复 ✅

**文件**：`backend/data_daemon.py` → `_out_transmit_seven_dim()`

**改动**：将跨库 UPDATE 子查询（静默失败 0 行）改为 Python 级迭代：
1. 通过 `sharding_manager.get_connection()` 获取 `status_snapshot` 和 `strategy_signal_detail` 各自的正确数据库连接
2. 批量读取 `strategy_signal_detail.seven_dim_json`
3. 逐只 UPDATE `status_snapshot.one_liner_detail`

### 7.2 T2：SIG 七维维度补全 ✅

**文件**：`backend/app/opportunity_atlas/status_engine.py` → `generate_seven_dim_from_signals()`

**改动**：
1. 新增 `dim_results` 参数，从维度引擎预计算结果中提取 `valuation` 维度
2. `signal` 维度：无 `right_side_confirm` 时从 5 引擎方向推导（多/空/分歧）
3. `structure` 维度：无缠论引擎时从 `trend_alignment` 标签推导
4. 调用顺序调整：先计算 `dim_results` 再生成 `seven_dim_json`

### 7.3 T3：treemap_snapshot 增加 seven_dim_report 列 ✅

**文件**：`backend/data_daemon.py` + `backend/app/data/enhanced_cache_manager.py`

**改动**：
1. `treemap_snapshot` 建表新增 `seven_dim_report TEXT` 列
2. INSERT 时从 `strategy_signal_detail.seven_dim_json` 填充
3. `treemap_snapshot_history` 建表同步新增
4. `get_treemap_snapshot_items()` API 响应新增 `seven_dim_report` 字段
5. 添加迁移逻辑：ALTER TABLE 补列（兼容旧表）

## 8. 剩余待执行

1. **管道监控告警**：JUD/OUT 步骤失败时触发告警，避免长时间数据断供
2. **运行一次完整管道**验证修复效果（SIG→JUD→OUT 全链路）
