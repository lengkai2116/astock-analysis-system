---
title: dim3 health_score 判定标准来源核查与归属建议（SIG/JUD 边界）
type: 核查文档（2026-09-20；464-dim3 五存疑点之六-1/六-4 深入研究；只研究不改码）
date: 2026-09-20
version: v1.0（研究归档，供拍板）
status: 📋 研究完成，处置方向待拍板
related:
  - 464-dim3量价健康引擎输出项全量梳理（464方法续）——本号的存疑点六-1/六-4 深入研究
  - 439-SIG功能区隔迁移预案——灯色/判定归 JUD 的推迟安排
  - sig-jud-boundary——SIG 仅分析+现状描述、JUD 判定
  - 445-引擎冻结边界——判定逻辑冻结 vs 事实输入该改就改
---

# dim3 health_score 判定标准来源核查与归属建议

> **背景**：464-dim3 梳理发现六-1（judgment.state 与 health_score 档位矛盾）+ 六-4（plain 内部矛盾，已随 plain 删除消解）。用户质疑：**hs 的 7 因子判定标准是什么？为何 SIG 会有这种"多现状→一结论"的合成？dim5 消费"个股情绪=量价状态强健康"是否合理？** 本号深入核查 hs 的标准来源与全部消费方，供拍板归属。
>
> **方法**：读 dim3_vp_engine.py hs 计算 + judgment/audit 全链 + framework compute_volume_price_signal（vp_state 权威）+ status_engine/dim_adapter/dim5 消费方。只研究不改码。

---

## 一、核心结论：两套标准来源完全不同

| | `vp_state`（强健康/中性/背离） | `health_score`（0-10 综合分） |
|---|---|---|
| **产生位置** | dim3 读 `tags.volume_price_fit` 映射 | dim3 本地 7 因子加权（**硬编码公式**） |
| **判定标准来源** | **framework `compute_volume_price_signal`**：281 号状态机（`state_machine.define` → STATE_SIGNAL_MAP → bullish/bearish/背离）→ 333 号定标"量价协调性权威" | **无方案号、无文档依据**——dim3 历史实现遗留的本地公式 |
| **性质** | 单一**现状标签**（量价关系这一维度） | **多现状加权合成的结论**（6 个维度合成一个分） |
| **各因子阈值** | framework 状态机（有知识库/方案背书） | 硬编码：量比>2、RPS>85、RSI 分档等（部分有 461/445 补产出背书，但**合成公式本身无依据**） |

**一句话**：`vp_state` 是有 281/333 号方案背书的 framework 权威标签；`health_score` 是 dim3 本地无方案依据的 7 因子加权公式——**hs 的"合成"动作正是 JUD 的职责（多现状→一结论）**，出现在 SIG 属越界。

## 二、hs 的 7 因子构成（代码实证）

| 因子 | 变量 | 数据源 | 阈值 | 有方案背书? |
|---|---|---|---|---|
| 1. 量价关系 | vp_score | volume_price_fit | healthy=2/diverging=-1/else=1 | ✅ 281/333 |
| 2. 量能 | ve | volume_ratio | >2→2/>1.2→1.5/>0.8→1/else=0 | ✅ 461-10 |
| 3. 均线 | ms | ma_alignment | 多头=1/空头=0/混=0.5 | ⚠ 通用常识 |
| 4. 筹码 | cs | chip_concentration | concentrating=1/else=0.5 | ⚠ 445-A3 修复 |
| 5. RSI | is_ | rsi | 60-70→1/30-40→0.8/极端→0.2 | ✅ 461-1 |
| 6. RPS | rps_factor | relative_strength | >85→+1 | ✅ 445/460 |
| 7. 背离 | dp | volume_price_fit | diverging→-1.5 | ✅ 450 |

```
raw = vp_score + ve + ms + cs + is_ + rps_factor + dp + pattern_deviation((pattern_score-5)/5×1.5)
hs  = (raw + 4) / 12 × 10   （clamp 0-10）
档位：≥8 强健康 / ≥6 健康 / ≥4 中性 / ≥2 弱 / else 严重背离
```

**注意**：hs 的第 1 因子就是 vp_state 的 source（volume_price_fit），但 hs 又叠加其余 6 因子 → 与 vp_state 出现档位差是必然（六-1 根因）。**合成权重 (raw+4)/12、各因子权重全为硬编码，无方案依据**。

## 三、hs 全部消费方（7 处）与合理性判断

| # | 消费方 | 位置 | 用途 | 合理性 |
|---|---|---|---|---|
| 1 | dim3 judgment.score | dim3_vp_engine.py:203 | SIG→JUD 强度输入 | ⚠ hs 作 score 输出，但 JUD 侧实际读 state（见 #7） |
| 2 | dim3 judgment.continuous_value | :204 | hs/10 作置信 | ⚠ 本地无依据公式参与置信 |
| 3 | audit 条件 2「健康度评分≥5」 | :210 | confidence 计算 | ⚠ 本地公式进 SIG 稽核 |
| 4 | audit 条件 1「量价关系」 | :209 | 用 vp_state | ✅ 权威标签 |
| 5 | dim8 段 text「健康度:8/10（强健康）」 | dim8_summary_engine T 表 | 现状描述 | ⚠ 无依据公式进叙事 |
| 6 | status_engine dims['vp']（兼容层） | status_engine:368 | JUD 投票 state | ⚠ 读 vp_state（键错位恒中性已记录） |
| 7 | dim_adapter dims['vp'] | dim_adapter:158 | JUD 投票 | ⚠ 读 `judg.get('vp_state')`（dim3 键是 'state' → 恒中性）+ `state_machine_direction`（dim3 不产 → 恒空） |

**dim5 个股情绪澄清**（回应你的疑问）：`_assess_stock_emotion`（dim5_emotion_engine.py:295-317）读的是 **`tags.volume_price_fit`（framework 权威标签）→ vp 映射**，**不是读 hs**！仅"严重背离"分支补充读 dim3 judgment.state（447 号 T4a）。所以 **dim5 的"个股情绪=量价状态强健康"用的是 vp_state（有 281 号背书），合理**；hs 未被 dim5 消费。

## 四、与 SIG/JUD 边界的对照

按已拍板边界（sig-jud-boundary 记忆）：
- **SIG = 分析 + 现状描述**：逐因子输出"量比多少、均线怎样、RPS 多少、量价关系标签"是 SIG 本职（各是各的现状，有独立数据源/阈值）。
- **JUD = 判定**：把多个现状**加权合成一个结论/灯色**是 JUD 职责。
- **hs 恰好做了 JUD 的事**（6 现状→1 分→灯色），且**无方案依据**——既越界又无标准背书。

**六-1 的本质修正**：不是"两个 SIG 现状冲突"，而是 **hs 这个"合成结论"越界进了 SIG**。真正该做的不是对齐 hs 与 vp_state（那是在 SIG 内部调和两个本该分属 SIG/JUD 的东西），而是**把 hs 的合成职责移出 SIG**（归 JUD），SIG 保留各因子现状 + vp_state。

## 五、处置方向建议（供拍板）

### 方案 A：hs 归 JUD 阶段（推荐，严格边界）
- SIG 保留：各因子现状（volume_energy/vol_ratio/rps/pattern_score 等 9 键）+ `vp_state`（framework 权威）。
- `health_score`/`score`/`continuous_value` 的**合成逻辑移 JUD**（或 JUD 直接以各因子现状+vp_state 自行判定）。
- 与 439 灯色迁移同批（都在 JUD 阶段统一规划）。
- **前置**：梳理 hs 5 处消费方迁移（audit 条件2、dim8 text、judgment.score/continuous_value）。

### 方案 B：hs 留 SIG 但补方案依据（折中）
- hs 公式**补方案号/文档依据**（如开新号定标 7 因子权重），使其成为有背书的"量价综合健康度现状"。
- 但仍是"合成结论"，与 SIG 只产现状的边界存在张力，且补标需 445 合规路径。

### 方案 C：先梳理再定（保守）
- 不动 hs，先完成 hs 消费方全量影响梳理（含 JUD 侧 dim3 因子恒默认的联动），形成迁移清单再拍板。

### 我的倾向
**A 为主**（符合 SIG/JUD 边界 + hs 无依据的事实），且**与 437-A 已记录的"JUD 侧 dim3 因子恒默认"是同一问题的两面**——JUD 读不到 dim3 真实状态（state 键错位 + state_machine_* 不产），恰因 SIG 该给 JUD 的"合成判定"没给对。建议：**hs 合成逻辑与 JUD 侧 dim3 因子接线一起，并入 JUD 阶段（439 同批）统一处置**；SIG 本次只归档说明，不改码。

---

> **本文档性质**：研究归档，**未修改任何代码**。六-1/六-4 结论：hs 的合成职责越界属 JUD，SIG 只产各因子现状 + vp_state；dim5 个股情绪读 vp_state 合理。处置随 JUD 阶段（439）统一规划。

## 📌 2026-09-20 拍板：选 A，hs 归 JUD 阶段统一处置

**用户拍板**：health_score 的 7 因子合成职责归 JUD 阶段统一处置（439 灯色迁移同批），SIG 本次不改码。

**处置范围（JUD 阶段待办，随 439 统一规划）**：
1. **hs 合成逻辑移出 SIG**：dim3 不再产 health_score/score/continuous_value 的 7 因子加权合成（SIG 保留各因子现状 9 键 + vp_state 权威标签）。
2. **hs 消费方迁移（5 处）**：judgment.score / continuous_value(hs/10) / audit 条件2「健康度≥5」/ dim8 text「健康度:8/10」/ JUD 侧 continuous_value 消费。
3. **与 JUD 侧 dim3 因子接线合并**：437-A 已记录 dim3 不产 state_machine_* → JUD 投票恒默认；JUD 阶段须定义 vp_state + 各因子现状 → 灯色的判定逻辑（替代 hs 合成 + 修复 state 键错位 status_engine:366/dim_adapter:157 读 judg.get('vp_state') 恒中性）。

**SIG 侧本次结论**：六-1 本质=hs 合成结论越界进 SIG（非"两个现状冲突"）；六-4 已随 plain 删除消解；dim5 个股情绪读 vp_state 合理（非 hs）。不改码，仅归档。
