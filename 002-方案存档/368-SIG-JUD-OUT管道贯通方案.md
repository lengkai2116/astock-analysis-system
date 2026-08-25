---
title: 368-SIG-JUD-OUT管道贯通方案
type: 架构方案
date: 2026-08-23
version: v1.0
status: 待沟通确认
related:
  - 353-系统总体架构规划（统一命名·全链路梳理）
  - 358-【总纲】策略分析与判定架构方案
  - 366-353总纲与358方案双轨收敛变更方案
  - 367-355-356-357号补完与历史遗留清理执行方案
---

# 368 — SIG-JUD-OUT 管道贯通方案

> **目标**：打通353号方案定义的完整6环节管道 COL→RAW→SIG→JUD→OUT，使SIG的双产出（信号+现状描述）能够正确传输到JUD进行判定，JUD的判定结果和SIG的现状描述统一进入OUT成品仓供前端消费。

> **架构核心**：
> - SIG = 5引擎分析 + 七维现状描述（双产出）
> - JUD = 纯判定环节（不做分析，消费SIG输出）
> - OUT = 成品仓（含SIG七维描述 + JUD判定结果）

**前置条件**：COL→RAW管道已验证可运行（2026-08-23已验证COL-1~6 + RAW-1在运行）

---

## 一、现状审计与问题诊断

### 1.1 SIG现状

| 项 | 状态 | 详情 |
|----|------|------|
| SIG管道步骤 | ✅ 已建立 | `SIG` 步骤在 `_drive_pipeline` 中定义 |
| 引擎执行 | ✅ 可运行 | `UnifiedStrategyCore.compute_batch()` 4线程并行 |
| 输出表 | ✅ `strategy_signal_detail` | 5574行/日，schema_version=1 |
| 5引擎产出 | ✅ 有数据 | 缠论/量价/筹码/因子/BOCIASI，每引擎含status_recognition + raw_detail |
| 七维现状描述 | ⚠️ 函数存在但未集成 | `build_seven_dim_report()` 在 `status_engine.py` 中，仅在OUT阶段调用 |
| dim_results_json | ❌ 不存在 | strategy_signal_detail无此字段 |
| seven_dim_json | ❌ 不存在 | strategy_signal_detail无此字段 |

**SIG信号结构**（实测000007.SZ）：
```
signal_json.signals = {
  '筹码主力分析': { strategy_name, raw_score, direction, confidence, signal, evidence[], status_recognition{}, raw_detail{} },
  '缠论走势分析': { ... },
  '因子评分系统': { ... },
  '量价分析策略': { ... },
  'BOCIASI快线': { ... }
}
```

### 1.2 JUD现状

| 项 | 状态 | 详情 |
|----|------|------|
| JUD管道步骤 | ❌ 不存在 | 混在OUT步骤中 |
| StatusEngine.evaluate() | ✅ 已实现 | `status_engine.py:64-88`，完整链路 |
| 6维度引擎 | ✅ 薄包装已实现 | `dimensions/dim1~6_engine` |
| GATE(L0门禁) | ✅ 嵌入StatusEngine | `_apply_l0()` |
| AGG(共识聚合) | ✅ 嵌入StatusEngine | `_aggregate()` + `arbiter.arbitrate()` |
| 输出表 | ✅ `status_snapshot` | 19列，12维dim_states |

### 1.3 OUT现状

| 项 | 状态 | 详情 |
|----|------|------|
| OUT管道步骤 | ✅ 已建立 | 但包含JUD逻辑 |
| status_snapshot写入 | ✅ 可运行 | `_build_status_snapshot` |
| treemap_snapshot写入 | ✅ 可运行 | `_build_treemap_snapshot`（依赖status_snapshot） |
| history归档 | ⚠️ 未独立 | status_snapshot_history/treemap_snapshot_history |

### 1.4 DAG依赖关系（353号§4.1）

```
COL → STG → {IND, FEAT, FAC} → SIG → JUD → OUT → USE
                                     ↑
                                依赖 FEAT + SIG
```

**当前代码DAG**：
```
COL-1~6 → RAW-1 → RAW-2 → RAW-3 → SIG → OUT
                                  (JUD混在OUT中)
```

**目标DAG**：
```
COL-1~6 → RAW-1 → RAW-2 → RAW-3 → SIG → JUD → OUT
```

---

## 二、接口契约定义

### 2.1 SIG双产出规格

**产出1：信号+维度结果**（给JUD消费）

写入 `strategy_signal_detail.signal_json`（已有），JUD从中提取：
- `signals.{引擎名}.direction` — 看多/看空/观望
- `signals.{引擎名}.confidence` — 置信度0~1
- `signals.{引擎名}.status_recognition` — 各引擎的状态认知
- `signals.{引擎名}.raw_detail` — 详细分析结果

**产出2：七维现状描述**（给用户/前端）

新增写入 `strategy_signal_detail.seven_dim_json`（JSON字符串），包含前6维分析中满足的条件/规则整理：

```json
{
  "dim1_signal": { "title": "信号确认状态", "conditions_met": [...], "evidence": [...] },
  "dim2_structure": { "title": "结构位置状态", "conditions_met": [...], "evidence": [...] },
  "dim3_volume_price": { "title": "量价健康度", "conditions_met": [...], "evidence": [...] },
  "dim4_chip_fund": { "title": "资金与筹码状态", "conditions_met": [...], "evidence": [...] },
  "dim5_emotion": { "title": "情绪环境状态", "conditions_met": [...], "evidence": [...] },
  "dim6_risk": { "title": "风险边界状态", "conditions_met": [...], "evidence": [...] }
}
```

**产出3：维度判定原始值**（给JUD消费，可选）

新增写入 `strategy_signal_detail.dim_results_json`（JSON字符串），包含6引擎的连续强度值+置信度：

```json
{
  "structure": { "continuous_value": 0.82, "confidence": 0.75 },
  "volume_price": { "continuous_value": 0.72, "confidence": 0.80 },
  "chip_fund": { "continuous_value": 0.65, "confidence": 0.70 },
  "emotion": { "continuous_value": 0.60, "confidence": 0.65 },
  "factor": { "continuous_value": 0.42, "confidence": 0.60 },
  "risk": { "continuous_value": -0.30, "confidence": 0.70 }
}
```

### 2.2 JUD消费规格

**JUD输入**（353号§3.5）：

| 数据 | 来源表 | JUD子步骤 |
|------|--------|----------|
| event/chip/valuation/depth | `pre_feat_cache.features_json` | JUD-1 GATE |
| SIG信号 | `strategy_signal_detail.signal_json` | JUD-2 消费 |
| SIG维度结果 | `strategy_signal_detail.dim_results_json` | JUD-2 消费 |
| lhb/holder/margin | STG原始表 | 主力在场判定 |
| timing + daily_cache | `pre_feat_cache` + `daily_cache` | L0c 持有期检查 |

**JUD-2 核心变化**：不再调用6维度引擎做分析，而是直接消费SIG的dim_results_json做判定（共识聚合+仲裁）。

### 2.3 JUD→OUT传输规格

| JUD输出 | OUT消费 | 存储目标 |
|---------|---------|---------|
| status_snapshot完整行 | 归档 | status_snapshot_history |
| treemap_snapshot完整行 | 归档 | treemap_snapshot_history |
| SIG七维现状描述 | 透传存储 | status_snapshot.one_liner_detail（已有字段） |

**关键**：SIG的seven_dim_json通过JUD透传到status_snapshot.one_liner_detail字段，前端从OUT读取。

---

## 三、实施阶段

### 阶段0：SIG接口规格确认（沟通+审计）

**目标**：确认SIG实际产出的数据结构，验证COL→RAW→SIG全流程可运行。

**步骤**：
1. 运行完整COL→RAW→SIG管道（非交易日手动触发）
2. 验证strategy_signal_detail的signal_json结构
3. 确认5引擎的status_recognition和raw_detail字段完整性
4. 确认七维现状描述（build_seven_dim_report）在当前引擎输出下的实际产出
5. 确认dim_results_json所需字段的来源（从哪个引擎输出提取）

**验证标准**：
- [ ] strategy_signal_detail行数 ≥ 5000（覆盖全市场）
- [ ] 5引擎信号完整（缠论/量价/筹码/因子/BOCIASI）
- [ ] status_recognition中state/trend/momentum/volume字段非空率 ≥ 90%
- [ ] build_seven_dim_report能正常生成7维输出

### 阶段1：SIG双产出增强

**目标**：SIG管道步骤产出三个JSON字段。

**改动**：
1. `strategy_signal_detail` 表新增 `seven_dim_json` 和 `dim_results_json` 两列
2. `_precompute_strategy_signals` 中，每个股票计算完后追加生成：
   - `dim_results_json`：从6引擎的status_recognition提取连续强度值
   - `seven_dim_json`：调用 `build_seven_dim_report()` 生成现状描述
3. 批量写入时同时写入三个JSON字段

**文件改动**：
- `enhanced_cache_manager.py` — ALTER TABLE新增两列 + 写入逻辑
- `data_daemon.py` `_precompute_strategy_signals` — 追加七维生成逻辑

### 阶段2：JUD能力评估与配置

**目标**：评估JUD现有能力，明确改造点。

**需要沟通确认的问题**：
1. JUD-2的共识聚合是否直接消费dim_results_json？还是仍需通过StatusEngine重新计算？
2. 353号定义的12维度体系中，B组（DIM-6~DIM-12）来自pre_feat_cache的标签维度，是否仍由JUD独立计算？
3. 七维框架（358号）vs 十二维体系（353号）的映射关系是否在JUD中处理？

**评估结论**：
- 如果JUD仍需12维度判定 → StatusEngine保持不变，JUD拆出为独立管道步骤
- 如果JUD只做7维判定 → StatusEngine需要重构，减少维度

### 阶段3：JUD管道独立化

**目标**：将JUD从OUT中拆出为独立管道步骤。

**改动**：
1. `_drive_pipeline` 中新增JUD步骤（在SIG之后、OUT之前）
2. JUD步骤调用 `_build_status_snapshot`（已实现的StatusEngine.evaluate）
3. OUT步骤简化为：归档 + treemap_snapshot + watchlist_status_diff
4. `ensure_pipeline_steps` 新增JUD（12步→13步：COL-1~6 + RAW-1~3 + SIG + JUD + OUT）
5. `_is_pipeline_complete` 更新为13步全done判定

**文件改动**：
- `data_daemon.py` `_drive_pipeline` — 拆分JUD和OUT
- `enhanced_cache_manager.py` `ensure_pipeline_steps` — 新增JUD
- `data_daemon.py` `_is_pipeline_complete` — 13步判定

### 阶段4：OUT简化与归档

**目标**：OUT只做归档和前端需要的数据存储。

**改动**：
1. `_build_status_snapshot` 保持（JUD写入时完成）
2. `_build_treemap_snapshot` 保持（JUD写入时完成）
3. 新增history归档逻辑（status_snapshot → status_snapshot_history）
4. 新增watchlist_status_diff检测
5. SIG七维描述透传到status_snapshot.one_liner_detail

### 阶段5：端到端验证

**目标**：验证COL→RAW→SIG→JUD→OUT全链路。

**验证标准**：
- [ ] strategy_signal_detail行数 ≥ 5000，含seven_dim_json和dim_results_json
- [ ] status_snapshot行数 ≥ 5000，含dim_states + opportunity_state + one_liner_detail
- [ ] treemap_snapshot行数 ≥ 5000
- [ ] 13个管道步骤全部done
- [ ] 前端能正确读取status_snapshot中的七维现状描述

---

## 四、风险与待确认项

| # | 问题 | 影响 | 建议处理 |
|---|------|------|---------|
| 1 | 七维框架(358号) vs 十二维体系(353号) | JUD维度判定路径选择 | 阶段2沟通确认 |
| 2 | SIG的5引擎 vs 353号的6引擎 | SIG-6(复合引擎)定位 | 确认是否保留SIG-6 |
| 3 | build_seven_dim_report依赖pre_feat_cache的tags | SIG需要tags做现状描述 | 确认SIG是否读pre_feat_cache |
| 4 | StatusEngine._build_dim_engine_results的dim引擎依赖tags | JUD消费路径 | 确认dim_results_json是否足够替代 |
| 5 | 366号双轨收敛方案的步骤7-10未实施 | 影响JUD-2维度引擎完整性 | 评估是否阻塞本次贯通 |

---

## 五、前置任务清单（本次沟通需确认）

| # | 问题 | 选项 |
|---|------|------|
| Q1 | JUD-2的共识聚合路径：A)直接消费dim_results_json B)仍通过StatusEngine重新计算 | |
| Q2 | 十二维体系(B组DIM-6~12)是否在JUD中独立计算？ | |
| Q3 | SIG-6复合引擎是否保留？ | |
| Q4 | 366号方案步骤7-10（analyzer/引擎整合）是否阻塞本次贯通？ | |
| Q5 | 七维描述的"冲突问题"是否需要在本次方案中解决？ | |
