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

---

# 五、灯色全量点位取证（2026-09-27，491 号批次3；产灯侧 12 处）

> 取证基线 HEAD＝`d464403`；行号为当前代码。**本表只取证，不含处置结论**（处置见 §六~§九）。

| # | 产出位置 | 键 | 值域 | 真实派生规则 |
|---|---|---|---|---|
| P1 | `dim2_structure_engine:352-357` | `judgment.light` + `judgment.overall_light`（同值） | green/yellow/red | 缠论方向：上升→green、下降→red、否则 yellow |
| P2 | `dim3_vp_engine:100-101,253-254` | `judgment.light`/`overall_light` | 同上 | vp_state 五态：强健康/健康→green、中性→yellow、背离/严重背离→red |
| P3 | `dim4_chip_fund_engine:5766,6178-6179` | `judgment.light`/`overall_light` | 同上 | main_force_phase：building/lifting→green、distributing→red、其余（washing/support/unknown）→yellow |
| P4 | `dim5_emotion_engine:57-65` | `judgment.market_light` | 同上 | PHASE_MAP 第 3 元素：ice→**red**、sprout→yellow、ferment→green、climax→**red**、ebb/regression/neutral→yellow |
| P5 | `dim5_emotion_engine:265-272` | `judgment.sector_light` | 同上 | sector_heat：top_10/top_20→green、normal/none/缺失→yellow |
| P6 | `dim5_emotion_engine:283-294` | `judgment.stock_light` | 同上 | 由**量价状态**派生：严重背离→red、健康→green、关注/中性/缺失→yellow |
| P7 | `dim5_emotion_engine:297-303` + `:510-514` | `judgment.overall_light` | 同上 | `_overall_light`：任一 red→red、≥2 green→green、否则 yellow；**另受 BOCIASI 四象限反向覆盖**（高点象限→market 改 red「高位风险」、低点象限→改 green「情绪底部」） |
| P8 | `dim6_risk_engine:206-214,527,563-564` | `judgment.light`/`overall_light` + `status_description.risk_light` | 同上 | 高风险源计数：≥2→red、=1→yellow、0→green |
| P9 | `dim7_valuation_engine:740-744` | `judgment.overall_light` + 4 个嵌套子项 light | 同上 | LEVEL_LIGHT：extreme_low/low→green、fair→yellow、high/extreme_high→red；子项：deviation>10→green/<-10→red、fina pass→green/fail→red、potential≥60→green/<30→red |
| P10 | `signal_analyzer:46-52,652-657` | `judgment.attribute.light`/`strength.light`/`maintenance.light`/`overall_light` | 同上 | LIGHT_MAP（属性码）+ 强度/衰减分档派生 |
| P11 | `dim8_summary_engine:46,161-162,806,1559` | 段 `light`（emoji）+ 顶层 `light` | 🟢🟡🔴 | `_extract_dim_light`（读各维 overall_light）+ `_LIGHT_EMOJI` |
| P12 | 各维（数据不足分支） | `'light': 'yellow'` 兜底 | yellow | 兜底默认 |

**关键观察（本次新发现）**：
- **P4 与 491 拍板的逆势方向自上不一致**：`market_light` 为**顺势语义**（ice→red 环境风险），而 `_EMOTION_DIRECTION` 为**逆势语义**（冰点→+1 操作机会）→ 同一状态「冰点」在 dim5 内部 direction=+1 而 light=red。
- P6 `stock_light` 的主源实为 **dim3 量价状态**（跨维），与 437-A D4「个股情绪主源=dim3」重复。

# 六、JUD 派生规则映射表（迁移后目标态）

**原则**：灯色＝**分析结论（status/state）的纯函数映射**（无判定、无干预）；由**单一规则表 SSOT** 派生，SIG 各维引擎**不再自产灯**；派生表同时供 JUD 判定层（dim8 共识/冲突、cross_validate、status_engine dims）与展示层（seven_dim_json 段灯色）调用。

| 维 | 迁移后输入（SIG 分析结论） | 派生规则（建议，与现状等价） | 等价性 |
|---|---|---|---|
| structure | `judgment.structure`（上升/盘整/下降） | 上升→green、盘整→yellow、下降→red | ✅（P1 同源） |
| volume_price | `judgment.state`（强健康/健康/中性/背离/严重背离） | 强健康/健康→green、中性→yellow、背离/严重背离→red | ✅（P2） |
| chip_fund | `judgment.phase`（building/washing/lifting/distributing/support/unknown） | building/lifting→green、distributing→red、其余→yellow | ✅（P3）；备选口径见 Q-439A-5 |
| emotion（市场） | `status_description.market_phase`（ice/sprout/ferment/climax/ebb/regression/neutral） | **见 Q-439A-1**：环境口径（现状）ice/climax→red、ferment→green、其余→yellow；操作口径（逆势）ice→green | ⚠️ 待拍板 |
| emotion（板块） | `status_description.sector_heat` | top_10/top_20→green、normal/none→yellow | ✅（P5） |
| emotion（个股） | **主源改 dim3 `vp_state`**（跨维去重） | 严重背离→red、健康→green、其余→yellow | ✅（P6）但主源归一 |
| risk | `risk_sources` 中 level=高 的计数 | ≥2→red、=1→yellow、0→green | ✅（P8） |
| valuation | `judgment.valuation_level.value` | extreme_low/low→green、fair→yellow、high/extreme_high→red | ✅（P9） |
| signal | `judgment.attribute.code` | LIGHT_MAP：right_confirmed/right_emerging/trend_running→green、left_probing/consolidating/neutral→yellow、risk_warning→red | ✅（P10） |
| 无数据 | — | yellow（**语义改为「数据缺失」**） | 见 Q-439A-2 |
| 顶层/段（展示） | 各维派生灯聚合 | 沿用 `_overall_light` 聚合（任一 red→red、≥2 green→green）+ `_LIGHT_EMOJI` | ✅（P7/P11） |

# 七、消费方清单与迁移动作（10 处）

| # | 消费方 | 现读 | 迁移动作 |
|---|---|---|---|
| C1 | `dim8._extract_dim_light:76-79` | 各维 `judgment.overall_light` | 改调派生表（state→light） |
| C2 | `dim8._calc_consensus_rate:189-194` | light→(±1) 参与共识 | 同上（等价） |
| C3 | `dim8._detect_conflicts:227-256`（4 条规则） | vp/emotion/risk/valuation light | 同上 |
| C4 | `dim8._derive_status_bar:320-321` | risk light | 同上 |
| C5 | `dim8` 段 light + 顶层 emoji（`:806`/`:1559`） | light→`_LIGHT_EMOJI` | 同上（**前端契约字段名/值域不变**） |
| C6 | `cross_validate._convert_dim_engine_to_legacy:54` | emotion `overall_light` → 方向 | 改用 `judgment.overall_direction`（更直接）或派生灯 |
| C7 | `cross_validate` L4 diagnose `:585-587` | dims light → L1 方向计票 | 改用派生灯（等价） |
| C8 | `status_engine._convert_to_dims_format:393-488` | 各维 `judgment.light`/`overall_light` → `dims[dim].light` | 改派生；`dim_states` 落库契约不变 |
| C9 | `routes/strategy_analyze:156/217-218/847-872/923` | dim_states/seven_dim 的 light | 契约不变（读派生灯） |
| C10 | `data/stg_quality:554` | 段 light emoji 合法性校验 | 契约不变 |

# 八、迁移批次建议

1. **439-A-1（落地批次①）**：新增派生表 SSOT（建议 `backend/app/opportunity_atlas/light_derive.py`，接口 `derive_light(dim, state) -> str`）；SIG 6 维 + `signal_analyzer` 删自产灯（P1~P10）；消费方 C1~C8 改调 SSOT。
2. **439-A-2（落地批次②）**：展示层 C5 + 前端契约回归（C9/C10）。
3. **验证**：8 股 + 全市场抽样，逐股对比「迁移前灯色 vs 派生灯色」应**完全一致**（除非 Q-439A-1 改口径）。
4. **风险**：①`seven_dim_json` 段 light/emoji 字段名与值域须不变（前端直读）；②`status_snapshot.dim_states` 值域不变；③STG 质检门禁（C10）；④若 Q-439A-1 改口径 → C1~C5 结果变化，须前端同步。

# 九、待拍板项（Q-439A）

- **Q-439A-1（核心）**：**灯色语义**——「市场/环境风险」（现状：冰点=red、高潮=red）vs「操作含义」（与 491 逆势方向一致：冰点=机会=green）。**建议**：**明确分工**「灯＝环境风险、方向＝操作含义」，并在派生表注释中写明（这样 P4 保留红、不破坏现有前端观感；同时 direction 逆势表达机会）。
- **Q-439A-2**：`'yellow'` 兜底 → **删除** 还是 **保留为「数据缺失」色**？建议保留（dim8/前端需要无数据可视化），仅改语义标注。
- **Q-439A-3**：dim5 `stock_light`（主源实为 dim3 量价状态）是否随 437-A D4 跨维去重删除、由 dim3 侧统一派生？
- **Q-439A-4**：`signal_analyzer` 的灯（signal 维判定）→ 迁 JUD 由 JUD 派生，还是随 signal 段（437-A 已移出 dim8）交前端组合？
- **Q-439A-5**：派生细则口径——chip_fund 用 `phase` 还是 `direction`；emotion 板块 light 是否区分 top_10/top_20。

# 十、用户拍板（2026-09-27）与最终派生表

| 问题 | 决策 | 落地要点 |
|---|---|---|
| **Q-439A-1** 灯色语义 | **① 分工：灯＝环境风险，方向＝操作含义** | 派生表**保留现状（环境口径）**：ice/climax→🔴、ferment→🟢、sprout/ebb/regression/neutral→🟡；同时在派生表注释写明「灯＝环境风险；操作含义由 `judgment.overall_direction`（逆势：冰点+1）表达」→ 前端观感不变 |
| **Q-439A-2** 兜底黄灯 | **① 保留为「数据缺失」色** | `'yellow'` 兜底保留，语义标注为「数据缺失」（不再是判定）；`stg_quality` 合法性校验口径不变 |
| **Q-439A-3** dim5 `stock_light` | **① 删除、归 dim3** | dim5 不再产 `stock_light`；展示/JUD 侧的「个股情绪灯」由 dim3 `vp_state` 派生（对齐 437-A D4 跨维去重） |
| Q-439A-4 signal 维灯 | **建议＝随 439-A-1 一并迁移**（删 SIG 自产，由派生 SSOT 计算） | signal 段已移出 dim8（437-A）；其灯属 SIG 判定类输出，按 439 原则迁移。**待你确认/否决** |
| Q-439A-5 派生细则 | **建议＝保持现状等价** | chip_fund 用 `judgment.phase`（非 `direction`）；emotion 板块 light 不区分 top_10/top_20（均 🟢）。**待你确认/否决** |

## 10.1 最终派生表（SSOT 蓝图，供 439-A-1 实现）

```python
# backend/app/opportunity_atlas/light_derive.py（建议）
# 约定：灯＝环境风险（Q-439A-1 ①）；操作含义见 dim_adapter._EMOTION_DIRECTION / judgment.overall_direction
_STRUCTURE   = {'上升': 'green', '盘整': 'yellow', '下降': 'red'}
_VP          = {'强健康': 'green', '健康': 'green', '中性': 'yellow', '背离': 'red', '严重背离': 'red'}
_CHIP_FUND   = {'building': 'green', 'lifting': 'green', 'distributing': 'red'}   # 其余（washing/support/unknown）→ yellow
_EMOTION     = {'ferment': 'green', 'ice': 'red', 'climax': 'red'}               # 其余（sprout/ebb/regression/neutral）→ yellow
_SECTOR_HEAT = {'top_10': 'green', 'top_20': 'green'}                            # 其余→ yellow
_VALUATION   = {'extreme_low': 'green', 'low': 'green', 'fair': 'yellow',
                'high': 'red', 'extreme_high': 'red'}
_SIGNAL      = {'right_confirmed': 'green', 'right_emerging': 'green', 'trend_running': 'green',
                'left_probing': 'yellow', 'consolidating': 'yellow', 'neutral': 'yellow',
                'risk_warning': 'red'}
# risk：由 risk_sources 中 level=='高' 的计数派生（≥2→red、==1→yellow、0→green）
# 兜底：yellow ＝「数据缺失」语义（Q-439A-2）
# 聚合：任一 red→red；≥2 green→green；否则 yellow（沿用 _overall_light，P7）
```

**439-A-1 落地清单**：①新增 `light_derive.py`；②删自产灯：dim2/dim3/dim4/dim6/dim7 的 `judgment.light`+`overall_light`、dim6 `sd.risk_light`、dim5 `market_light`/`sector_light`/**`stock_light`（Q-439A-3）**/`overall_light`、dim7 4 个子项 light（保留 `valuation_level` 等嵌套结构但去 light，或保留灯改由 SSOT 计算）、signal_analyzer 灯（Q-439A-4 待确认）；③消费方 C1~C8 改调 `light_derive`；④C9/C10 契约字段不变。
**验证**：8 股 + 全市场抽样，逐股对比「迁移前灯色 vs 派生灯色」应**完全一致**（Q-439A-1 取分工方案 ⇒ 应 100% 相等）。

## 10.2 ✅ 439-A-1 实施记录（2026-09-27）

**新增 SSOT**：`backend/app/opportunity_atlas/light_derive.py`（6 组 state→light 映射 + `emotion_market_light`（含四象限覆盖）+ `emotion_stock_light`（跨维取 dim3）+ `signal_light`（三源聚合）+ `risk_light`（level 优先/高源计数兜底）+ `aggregate_lights` + `dim_light(dim_results, dim_name)` 主入口 + 别名 `fund_chip`/`vp`）。

**已删除的 SIG 自产灯（输出层）**：
| 位置 | 删除内容 |
|---|---|
| dim2 | `judgment.light` / `overall_light`（含本地 light 计算） |
| dim3 | 同上（含 light_map/vp_light） |
| dim4 | `_assess_phase` 的 `light`；`judgment.light`/`overall_light`；PDE 分支 phase_info 的 light |
| dim5 | `judgment.market_light`/`sector_light`/**`stock_light`（Q-439A-3 删除）**/`overall_light`（内部仍算整体灯供 `overall_direction` 派生，保证等价） |
| dim6 | `judgment.light`/`overall_light`、`status_description.risk_light` |
| dim7 | `judgment.overall_light` + 4 个子项 `light`（嵌套只留 `value`）+ 常量 `LEVEL_LIGHT` |
| signal_analyzer | `judgment.attribute/strength/maintenance.light`、`overall_light`、`LIGHT_MAP`、`_overall_light`（Q-439A-4 迁移） |

**消费方改调 SSOT（C1~C8）**：`dim8._extract_dim_light`（C1~C5 全部随之）、`dim8._segment_from_dim` 段灯与段 `judgment.overall_light`、`cross_validate._convert_dim_engine_to_legacy`（情绪维）、`status_engine._convert_to_dims_format`（五维 light → `_dl(...)`）、`status_engine` 的 `signal_confirm.light`（原读 `signal_analyzer.LIGHT_MAP`）、`status_engine` 内 `LIGHT_MAP` 引用。C9/C10（routes/stg_quality）契约字段未变。

**未改动（登记）**：①`dim8` summary 段灯（`judgment.overall_light` 由 `consensus_rate` 派生，属**归集层聚合**，非 SIG 判定，本批不动）；②前端 `seven_dim_json` 段 `light` emoji 与 `judgment.overall_light` **双轨契约保持不变**（值＝派生灯）。

**验证**：
- **等价性探针** `scripts/_439a_light_equivalence_probe.py`：迁移**前**（引擎仍产灯）逐股比对 8 股 × 11 项 → 首次跑出 **signal 维 5 处不一致**（派生误读 `strength.score`/`maintenance.decay_status`，应为 `strength.level`/`maintenance.status`）→ 修正派生后 **0 处不一致**；迁移后复跑为「派生灯自检」全绿。
- **回归**：dim/JUD 相关 94 文件 1121 用例 → **1117 passed / 4 failed**（4 项均为既有失败）→ 本批零新增失败。测试适配 9 处（test_420 mock 规范化 6 项、test_436_seven_dim mock 规范化、test_411 `LIGHT_MAP`→`SIGNAL_ATTR`、test_464_dim4/chanlun_strength 灯断言改派生、test_488 judgment 键集基线去掉 4 灯键）。
- **新增单测**：`tests/test_439a_light_derive.py`（7 用例，含「dim_results 不含任何灯键仍能正确派生」的关键回归）。
