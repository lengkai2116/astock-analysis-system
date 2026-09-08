---
title: 维度引擎evidence字段消费链路核查方案
type: 核查方案
date: 2026-09-02
version: v1.0
status: 待实施
related:
  - 396-dim2结构位置引擎全面核查报告与修复方案
  - 395-dim8现状描述能力评估与改进方向
  - 392-SIG环节系统架构与能力说明
---

# 397 — 维度引擎evidence字段消费链路核查方案

> **背景**：396号方案核查dim2输出时发现大量 `*_evidence` 字段未被下游消费。这些字段是各维度引擎输出的分析过程证据，设计意图是供dim8三层描述架构（因为→所以→验证）的"验证层"使用。但当前dim8只读取了核心字段，未读取evidence字段。需要对所有维度引擎进行同类核查，确认每个evidence字段的消费状态，最终汇总到dim8统一处理。

---

## 一、问题定义

### 1.1 什么是evidence字段

各维度引擎的 `status_description` 中，以 `_evidence` 结尾的字段。例如dim2的：

| evidence字段 | 值示例 | 设计意图 |
|-------------|--------|---------|
| chanlun_direction_evidence | "最近50笔，趋势方向=up..." | 说明趋势判定的依据 |
| chanlun_phase_evidence | "趋势=up，末笔=down→欲病" | 说明阶段判定的依据 |
| buy_sell_points_evidence | "日线sell已确认" | 说明买卖点检测的依据 |
| divergence_evidence | "类型=trend，强度=0.832" | 说明背驰判定的依据 |
| level_evidence | "日down；周up" | 说明多级别联立的依据 |
| trend_structure_evidence | "信号=higher_low..." | 说明123法则的依据 |

### 1.2 当前状态

以dim2为例，13个核心字段被消费，但8-11个evidence字段未被消费。这意味着dim8生成的三层描述中缺少"验证层"——用户只能看到结论，看不到结论的支撑证据。

---

## 二、核查范围

对以下7个维度引擎逐一核查：

| 引擎 | 文件 | 关键evidence字段 |
|------|------|----------------|
| dim1_signal_engine | dim1_signal_engine.py | signal_evidence, attribute_evidence |
| dim2_structure_engine | dim2_structure_engine.py | chanlun_*_evidence, divergence_evidence, level_evidence等 |
| dim3_vp_engine | dim3_vp_engine.py | vp_evidence, divergence_evidence |
| dim4_chip_fund_engine | dim4_chip_fund_engine.py | phase_evidence, fund_flow_evidence |
| dim5_emotion_engine | dim5_emotion_engine.py | market_evidence, sector_evidence |
| dim6_risk_engine | dim6_risk_engine.py | risk_evidence, volatility_evidence |
| dim7_valuation_engine | dim7_valuation_engine.py | valuation_evidence, pe_evidence |

---

## 三、核查检查清单（每维度通用）

对每个维度引擎，按以下清单逐项核查：

### 检查项 A：evidence字段产出完整性

```
□ 列出该引擎 status_description 中所有 *_evidence 字段
□ 确认每个字段的赋值逻辑（何时有值、何时为空）
□ 确认字段值是否为有意义的分析文本（非空、非模板）
```

### 检查项 B：evidence字段消费链路

```
□ 在 dim_adapter.py 中搜索该字段 → 是否被读取？
□ 在 dim8_summary_engine.py 中搜索该字段 → 是否被读取？
□ 在 conflict_matrix.py 中搜索该字段 → 是否被读取？
□ 在 strategy_analyze.py（API层）中搜索该字段 → 是否被输出到前端？
□ 在前端代码中搜索该字段 → 是否被渲染？
```

### 检查项 C：消费方式分类

对每个evidence字段，标注消费状态：

| 状态 | 含义 | 处理方式 |
|------|------|---------|
| ✅ 已消费 | 字段被dim8/conflict_matrix/API读取并使用 | 无需处理 |
| ⚠️ 部分消费 | 字段被读取但仅用于日志/调试 | 评估是否需要正式消费 |
| ❌ 未消费 | 字段产出但无任何下游读取 | 纳入dim8统一消费或标记DEPRECATED |
| 🗑️ 可删除 | 字段无实际内容且无消费方 | 直接删除 |

### 检查项 D：dim8三层描述适配评估

```
□ 该evidence字段是否适合放入dim8的"验证层"？
□ 如果适合，应以什么格式呈现给用户？（一句话摘要/折叠详情/证据链）
□ 是否需要dim8的 _build_*_text() 函数增加evidence读取逻辑？
```

---

## 四、dim2核查示例（已完成）

### dim2 evidence字段消费状态

| evidence字段 | 值示例 | 消费方 | 状态 |
|-------------|--------|--------|------|
| chanlun_direction_evidence | "最近50笔..." | 无 | ❌ 未消费 |
| chanlun_phase_evidence | "趋势=up，末笔=down→欲病" | 无 | ❌ 未消费 |
| chanlun_strength_evidence | "缠论评分=0.500×70%..." | 无 | ❌ 未消费 |
| chanlun_strength_components | `{chanlun_score:0.5,...}` | 无 | ❌ 未消费 |
| buy_sell_points_evidence | "日线sell已确认" | 无 | ❌ 未消费 |
| divergence_evidence | "类型=trend，强度=0.832" | 无 | ❌ 未消费 |
| level_evidence | "日down；周up" | 无 | ❌ 未消费 |
| trend_structure_evidence | "信号=higher_low..." | 无 | ❌ 未消费 |
| fractals_summary | `{last_3:[...]}` | 无 | ❌ 未消费 |
| segments_summary | `{}` | 无 | ❌ 未消费 |
| divergence_segments | `{}` | 无 | ❌ 未消费 |

**dim2结论**：11个evidence/中间字段全部未被消费。dim8的 `_build_structure_text` 只读取了核心字段（vs_ma/vs_zhongshu/chanlun_direction等），未读取任何evidence字段。

---

## 4.1 dim3核查示例（已完成）

### dim3 evidence字段消费状态

| evidence字段 | 值示例 | 消费方 | 状态 |
|-------------|--------|--------|------|
| divergence_evidence | "无" | 无 | ❌ 未消费 |
| volume_energy_evidence | "量比=1.00，量能趋势=STABLE，量均线结构=MIXED" | 无 | ❌ 未消费 |
| pattern_evidence | "基础形态=VP-2 价涨量平，增强形态=[...]" | 无 | ❌ 未消费 |
| granville_evidence | "格兰威尔八准则：量价中性" | 无 | ❌ 未消费 |
| state_machine_evidence | "【量价状态】放量突破(筹码转换)；【慢线分布】..." | 无 | ❌ 未消费 |
| evidence | "【量价状态】放量突破(筹码转换)；【慢线分布】..."（汇总） | 无 | ❌ 未消费 |

### dim3核心字段未消费清单（非evidence但无下游）

| 字段 | 值示例 | 说明 |
|------|--------|------|
| state_machine_label | `观察` | 方向标签，dim_adapter读direction但不读label |
| state_machine_position | `50%` | 建议仓位 |
| state_machine_holding | `2-4周（波段持有）` | 持有周期 |
| stage_confidence | `0.7` | 阶段判定置信度 |
| stage_valuation | `HIGH` | 价格分位 |
| stage_trend | `HH/HL 序列（上涨趋势）` | 趋势翻译 |
| stage_ma_alignment | `多头排列` | 均线排列 |
| vol_state_pattern | `堆量放量` | 量能形态 |
| granville | `量价中性` | 格兰威尔准则 |
| three_laws | dict(5项) | 三定律详情 |
| entry_zone | `[11.56, 12.16]` | 入场区间 |
| target_zone | `[12.52, 13.71]` | 目标区间 |
| fake_breakout | dict(3项) | 假突破检测 |
| supply_demand | dict(4项) | 供需检测 |
| momentum | dict(6项) | 动量详情（dim8仅读level子字段） |

### dim3结论

- **evidence字段**：6个evidence字段全部未被消费（与dim2同类问题）
- **核心分析字段**：15个核心字段已消费，22个字段未被消费
- **judgment/audit**：全部6个judgment字段和2个audit字段均未被消费
- dim8的 `_build_volume_price_text` 只读取vp_state/volume_energy/pattern/divergence/vol_ratio 5个核心字段
- dim8的 `_extract_key_metrics` 读取stage_name/vol_state_trend/structure/institutional/momentum.level共5个字段
- conflict_matrix仅读取risk_notes（1个字段）
- API层通过status_recognition输出到前端

---

## 五、实施计划

### Phase 1：逐维度核查（每个dim 0.5天）

按检查清单A-D对7个维度引擎逐一核查，产出每个维度的消费状态表。

### Phase 2：汇总分析（1天）

汇总所有维度的核查结果：
- 统计已消费/未消费/可删除的evidence字段数量
- 识别dim8需要新增消费的字段清单
- 评估前端是否需要展示evidence（用户需求确认）

### Phase 3：dim8统一消费方案（1天）

基于汇总结果，修改dim8的 `_build_*_text()` 函数，增加evidence字段读取逻辑：
- "验证层"格式：`{核心结论}（证据：{evidence摘要}）`
- 或折叠展示：默认隐藏，用户点击展开查看完整证据

### Phase 4：前端适配（0.5天）

如果决定展示evidence，前端弹窗需要适配新的数据结构。

---

## 六、预期产出

| 产出 | 说明 |
|------|------|
| 7份维度evidence核查表 | 每维度一份，格式同§四 |
| dim8消费方案修订 | 修改 `_build_*_text()` 读取evidence |
| 前端适配方案（如需） | 弹窗展示evidence |
| 测试用例 | 验证evidence正确传递到前端 |

**合计工时**：约3天

---

**文档编制日期**：2026-09-02
**编制依据**：396号方案dim2核查中发现的evidence未消费问题
