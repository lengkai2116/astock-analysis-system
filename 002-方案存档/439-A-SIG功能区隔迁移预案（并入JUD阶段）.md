---
title: SIG 判定类灯色迁移/删除预案（并入 JUD 调整阶段统一规划）
type: 预案（仅记录，不实施；迁移/删除推迟到 JUD 盘查修正阶段）
date: 2026-09-15
version: v0.1
status: 只记录待办，未改代码；执行时机 = JUD 盘查修正阶段
related:
  - 439-SIG素材摸底与功能区隔核查（本预案的取证来源）
  - 436-SIG文字类输出修复方案（前置：本预案须在 436 前完成）
  - 437-dim8股票现状描述输出框架总纲
  - sig-jud-boundary 记忆（SIG/JUD 职责边界共识）
---

# SIG 判定类灯色迁移/删除预案

> **决策（2026-09-15 用户拍板）**：SIG 侧残留灯色判定（overall_light/light 等）**现不实施迁移/删除**——因 JUD 尚未盘查修正，此刻迁移会增加 JUD 后续核查复杂度。改为**详细记录本预案并于后续 JUD 调整阶段统一规划迁移或删除**；迁移前不碰 status_engine.py:928 等 SIG 产出点。

---

## 一、为什么现在不实施（决策依据）

迁移灯色到 JUD 会同时改动：
- SIG 侧删除判定（status_engine:928、dim2~7 evaluate、signal_analyzer:661、'yellow'兜底）；
- JUD 侧需**补齐对应判定逻辑**，否则判定链路断裂。

而 JUD 自身尚未做盘查修正（涉及灯色体系、verdict、消费契约等未定稿）。**先修 JUD 边界再动 SIG**，比先迁移再被 JUD 调整要求返工更省。

---

## 二、待迁移/删除清单（取证：439 号 §三）

### 2.1 判定 → 迁移 JUD
| 位置 | 现状 | 建议 |
|---|---|---|
| status_engine.py:928 `generate_seven_dim_from_signals` 的 `light` + summary"整体偏多/偏空" | SIG 直接产七维灯色 + 方向→灯色映射 | 迁移 JUD |
| dim2~dim7 各 `evaluate` 自产 `judgment.overall_light`/`light`（dim2:160 dim3:4680 dim4:6013 dim5:530 dim6:1209 dim7:973 + dim5 子 light:527-529 + dim6 risk_light + dim7 子项内嵌 light） | 随 dim_results_json 落库 | 迁移 JUD |
| signal_analyzer judgment `overall_light`（signal_analyzer.py:661） | 信号强度合成灯色 | 迁移 JUD |

### 2.2 兜底默认 → 删除
| 位置 | 现状 | 建议 |
|---|---|---|
| 各维 `'light':'yellow'` 数据不足兜底（dim2:155 dim3:4574 dim5:299/313/322 dim6:343 dim4:5832） | 数据不足恒黄 | 删除（缺失由 JUD 兜底） |

### 2.3 JUD 侧需补齐（迁移时点必须同步）
将判定逻辑从各维 evaluate 上移到 JUD 统一层，使 JUD 能基于 SIG 的分析字段（overall_direction/continuous_value/audit.conditions）独立算灯色，而非复制 SIG 侧判定。

---

## 三、执行时机与先后顺序

| 阶段 | 动作 |
|---|---|
| **本号（439-A）** | 仅记录此预案 + 记忆。**不改代码**。 |
| **JUD 盘查修正**（后续独立安排） | 先定 JUD 灯色体系/契约 → 再按本预案统一迁移 SIG 判定点或删除 'yellow' 兜底。 |
| **436 改造** | **前置条件**：功能隔离（本预案）须先完成，436 才能基于清洗后的 SIG 输出组装 seven_dim_json。故 436 现暂缓，待本预案落地后启动。 |

---

## 四、风险提示
- 迁移前 SIG 的 dim_results_json / seven_dim_json 仍含判定灯色，**属已知中间态**，不作为质量缺陷核查。
- dims={} 复原、英文→中文映射、跨维去重（439 §二 根因）属 SIG 素材质量前置，**不受本预案推迟影响**，可独立评估是否先行。

---

> **本预案性质**：决策记录 + 待办。无任何代码改动。执行入口 = JUD 盘查修正阶段。
