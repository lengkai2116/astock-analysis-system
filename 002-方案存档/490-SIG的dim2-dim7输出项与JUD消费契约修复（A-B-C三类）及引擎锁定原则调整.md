---
title: SIG dim2-dim7 输出项 × JUD 消费键契约修复（A/B/C 三类）+ 引擎锁定原则的阶段适用性调整
type: 实施号（A/B/C 三类修复已实施；含规则调整声明）
date: 2026-09-27
version: v1.0
status: ✅ 全部实施（11 文件 + 1 测试新增；核验见 §四/§五）
related:
  - 489-SIG的dim2-dim7全量输出项在JUD环节消费核查报告（本号的唯一输入清单；§五 A/B/C 三类键契约断裂）
  - 435-SIG输出在JUD消费核查报告（键盘断层的初版基线）
  - 445-dim2-dim7引擎正确性知识库核查（**本号调整其「引擎冻结」的阶段适用范围**，见 §一）
  - 388/390/391（390 v390 管线与契约键设计来源）
  - 446 D10/D11/D12、447、449、452/453、457、475、479-9、487、488（各键既有修复先例，本号不改其取数口径）
  - 439-A（SIG 灯色迁移 JUD，仍待推进，本号不涉）
---

# 490号｜SIG dim2-dim7 输出项 × JUD 消费键契约修复 + 引擎锁定原则调整

## 一、规则调整（用户 2026-09-27 拍板，本节为后续工作的适用口径）

**原规则（445 号）**：策略引擎的「定稿/冻结」→ 分析逻辑（果）先行锁定，改动需独立号 + 知识库依据。

**本号调整后的规则**：

> 前期锁定引擎分析代码的修订，**是为了梳理 dim8 的修正**（即「先把各维现状描述定稿、dim8 归集口径稳定」这一阶段目标）；
> **现阶段已进入 JUD 改造环节**，**原定的引擎锁定原则不再适用于该阶段的工作**。
> 所有涉及 **SIG 引擎端**的问题，须**结合代码实际与产出具体情况**判断——**应该修正的必须修正**。

**适用边界（据 445 Freeze-vs-Fact 与本次调整共同确定）**：

| 类别 | 是否可改 | 依据 |
|---|---|---|
| 事实层（因）：数据获取错误、口径不统一、键未产出/未透传、容器与键名错位 | ✅ **必须修正**（本号主体） | 445「事实/输入该改就改」+ 本次调整 |
| 契约层：JUD 消费端读取路径/容器/形态错位 | ✅ **必须修正** | 同上（判定输入失真＝事实错误） |
| 判定语义层：分析结论的**判定阈值/权重/方向口径**（「果」） | ⚠️ 仍须**独立号 + 全链路验证 + 知识库依据** | 445 保留部分；本号对确属「激活既有设计分支」的最小改动已在 §三 逐条标注 |

## 二、范围与方法（来自 489 号 §五，逐条闭环）

**输入清单**：489 号 §五「消费悬空」A/B/C 三类 + §四「未消费」中已算未消费的关键项。

**处置策略（三类统一原则）**：
- **A 类 · 引擎未产出** → **引擎补产出**（保持 390 契约与 JUD 消费端不变）；值必须来自**引擎已算出或上游已算出**的真实量，不新造分析逻辑；
  - 例外：确无任何真实来源的键（如 dim3 多周期一致性）→ 消费端改取**跨维权威源**（dim2 多级别联立）或**删除 phantom 读取并登记**。
- **B 类 · 路径/形态/键名错位** → **消费端对齐真实键**；展示文本与数值语义共用一个键名时，**新增数值键**（`*_value`）并让消费端优先读取（先例：479-9 的 `pe_percentile` 文本 + `pe_percentile_5y` 数值）。
- **C 类 · 跨维取错** → 修正容器键（`'dim2'→'structure'` 等）与子键路径。

## 三、逐步实施清单（做了什么、为什么这样改）

### 3.1 A 类 · 引擎补产出

| # | 维 | 新增键 | 真实来源（已算未透传） |
|---|---|---|---|
| 490-1 | dim2 | `chanlun_strength_components` / `consistency_component` / `divergence_multi_algo` | ①`ChanlunScorer.structure_health_score()` 的 `details`（此前只取 score，明细丢弃）；②457 多级别联立 `direction_map` 的日线基准一致占比；③`Divergence.details` 的真实方法标记（macd/力度/中枢/趋势回测）+ `dual_confirmed` |
| 490-2 | dim3 | `state_machine_direction` / `state_machine_confidence` / `stage_name` / `stage_confidence` / `resonance_score` / `three_laws` / `risk_notes` / `entry_zone` / `target_zone` / `vol_ratio_value` | ①状态机方向/置信度＝引擎自产 `vp_state`+健康度映射（引擎已无独立状态机实现，语义等同方向；**不含新判定逻辑**）；②`resonance_score`/`three_laws`/`risk_notes`/`entry_zone`/`target_zone`＝RAW 已算 `compute_volume_price_signal` 产出（`vp_*` 前缀落 pre_feat，dim3 免重算）；③`vol_ratio_value`＝量比数值（原键为展示文本） |
| 490-3 | dim4 | `phase_confidence` / `pde_conflict` / `pde_vote_ratio` / `pde_price_position` / `crowding_level` / `cost_concentration` / `cost_profit_ratio` | PhaseDetectionEngine 真实产出（`phase_confidence`/`phase_conflict`/`phase_vote_ratio`/`price_position`；vote 取 `_supporters` 扁平票数，对齐 390「票差」语义）+ CrowdingFactor 分档 + 成本结构集中度 + `tags.profit_ratio` |
| 490-4 | dim5 | `market_phase` / `sector_heat` / `bociasi_fast_signal` / `bociasi_slow_signal` / `bociasi_slow_confidence` / `bociasi_quadrant` / `temperature_value` | PHASE_MAP 阶段原始枚举 / 板块热度等级 / 四象限度块真实产出（`fast_signal`/`slow_signal`/`quadrant`）/ 温度数值（原键为展示文本） |
| 490-5 | dim7 | `composite_rating` / `valuation_deviation` / `asset_anchor_rating` / `earnings_anchor_rating` / `dividend_yield_value` / `revenue_growth_value` | `_compute_valuation()` 返回值（`composite_rating`/`valuation_deviation`/锚定评级均已算出，此前只在展示文本内或未落 sd）；数值键对齐 L1 的 `>4%` / `>20%` 口径 |

### 3.2 B 类 · 路径/形态/键名错位（消费端对齐）

| # | 位置 | 原读（错） | 改为（真实） | 后果修复 |
|---|---|---|---|---|
| 490-6 | `status_engine._convert_to_dims_format` dim3 | `judgment['vp_state']`（不存在） | `judgment['state']`（sd.vp_state 兜底） | dims.vp.state 由恒「中性」→ 真实五态 |
| 490-7 | 同上 dim4 | `judgment['flow_direction']`（不存在） | `judgment['direction']`（inflow/outflow→流入/流出） | dims.chip_fund.state 由恒「中性」→ 真实资金方向（与 `_DIM_DIRECTION`/`classify_attribute` 词表一致） |
| 490-8 | 同上 dim5 | `judgment['phase']`（不存在） | `sd['market_phase']` + `ENGINE_STATE_TO_CN['emotion']` | dims.emotion.state 由恒「正常」→ 真实情绪阶段 |
| 490-9 | 同上 dim7 | 仅 tags（`valuation_level`/`fina_health`） | `judgment.valuation_level.value` / `fina_health.value` + EN→CN，缺则回退 tags | dim7 引擎结论首次进入 dim_states |
| 490-10 | `dim_adapter.convert_to_factors` dim3 | `sd['vol_ratio']`（文本） | `sd['vol_ratio_value']`（缺则回退） | 量比 extras 由恒 0.0 → 真实 |
| 490-11 | 同上 dim5 | `sd['temperature']`（文本） | `sd['temperature_value']`（缺则回退） | dim5 strength 由恒 0 → 真实（原文本解析恒失败） |
| 490-12 | 同上 dim7 | `sd['dividend_yield']`/`revenue_growth`（文本） | `*_value` 数值键（缺则回退） | 股息/营收加成由恒不触发 → 真实可触发 |
| 490-13 | `status_engine._build_dim_engine_results` Step3 | 取「judgment 中第一个 dict 型值的 value」作 state（dim2/3/5/6 全标量 → 恒「中性」） | 新增模块级 `_dim_state_for_signal()` 按各维真实契约键显式取 state | 信号属性分类由恒 `neutral`（signal_confirm 恒「中性观望」）→ 真实 |
| 490-14 | 文档口径 | — | `_EMOTION_DIRECTION`/`ENGINE_STATE_TO_CN['emotion']` 补 dim5 PHASE_MAP 全量枚举（sprout/ferment/regression/中文） | 情绪方向由 7 段中仅 3 段可映射 → 全量可映射 |

### 3.3 C 类 · 跨维取错（容器与子键）

| # | 位置 | 原（错） | 改为（真实） |
|---|---|---|---|
| 490-15 | `conflict_matrix.detect` | `dim2 = get('dim2') or get('signal')`、`dim3 = get('dim3') or get('structure')`、`dim4/6/7` 同类回退 | `structure` / `volume_price` / `chip_fund` / `risk` / `valuation`（真实容器键）；局部变量名一并改为语义名（structure_sd/volume_price_sd/…） |
| 490-16 | 同上 · 子键 | `retail_institution`（读容器顶层）、`cost_concentration=='单峰密集'`、`crowding_level=='HIGH'` | 读 `sd['retail_institution']`；值域对齐引擎真实枚举（`concentrating`/`tight`、`HIGH_CROWDING`） |
| 490-17 | 同上 · 背离/量比 | `vp_divergence=sd['divergence']`（展示文本）比对 `'top'`；量比取默认入参 1.0 | `sd['divergence_type']`（结构化 'top'/'bottom'）；量比取 `sd['vol_ratio_value']`（缺则回退入参） |
| 490-18 | 同上 · C2/C2b | `stage_name=='DOWNTREND_ACTIVE'`（dim3 无该产出）；`level_trends`（无生产者） | **C2 删除并登记**（无产出源且与 C11 语义重叠）；C2b 改取 dim2 `multi_level.direction_map` 的日/周方向 |
| 490-19 | 同上 · C12 | `dim3.get('risk_notes')`（容器顶层） | `sd['risk_notes']`（490-2 已透传） |
| 490-20 | `dim_adapter` + `reliability_assessor` · dim3 多周期 | `multi_timeframe_consistency`/`weekly_direction`（无生产者） | 新增 `multi_level_consistency()`（跨维主源＝dim2 多级别联立）；reliability 周线修正取 `direction_map['weekly']`（'down' 视同原 'SELL'） |
| 490-21 | `cross_validate._convert_dim_engine_to_legacy` | `der.get('fund_chip')`（键名错位，应为 `chip_fund`）→ 筹码维永缺；`judg.get('phase',{}).get('direction')`（str 上调 .get 的潜在 AttributeError） | 键名修正 + 方向取 `judgment.overall_direction` |

### 3.4 未改动（明确保留/登记）

- **SIG 灯色类输出**（dim2-dim7 `overall_light`/`risk_light`/`market_light`…）：属 **439-A** 迁移 JUD 的主题，本号不动。
- **`seven_dim_json` 文字类通路**：不经 JUD（设计分流），本号不动。
- **`advice_engine` 的 `entry_zone`/`target_zone`**：本号**不改消费端**——490-2 已使 dim3 真实产出该两键（391 P1 消费链随之激活）；其生效需 pre_feat 重算（见 §五）。
- **未消费键（489 §四）**：`vs_chip`/`buy_sell_points`/`multi_level`/`health_score`/`pattern_score`/`stock`/dim6 十一键/audit.actual|threshold 等——多为 437-A 有意去重或 OUT 侧承载，本号不动；其中 **dim6 `risk_sources`/`piers_leverage_triggered`/`liquidity_*`** 登记为「因已算未消费」待裁。
- **`status_snapshot` 无 signals 列 / `volume_breakout` 恒失效 / `_build_status_snapshot` SELECT 未限 trade_date**（435 附加发现）：属 411/370 管线设计议题，**不在 A/B/C 三类**，登记待裁不动。
- **死代码**（`dim_adapter.convert_to_dims_format`/`extract_direction_score`/`advice_generator` 共 3 处）：本号不删（登记 490-R5，由 491 号批次1 处置）。⚠️ **491 号更正**：`arbiter` **不是死代码**（v390 主管线内不调用它，但 OUT 操作建议通路 `advice_engine/advice_builder.build_operation_advice`、`cross_validate.L4CrossValidator`、legacy `_aggregate` 仍在用）。

## 四、验证

### 4.1 单元测试

- 新增 `backend/tests/test_490_dim_contract_and_jud_keys.py`（**12 用例**全部通过）：C 类容器/子键取值与 11 条规则触发、legacy dims 三维 state、JUD 内 signal 桥接 state 提取、`multi_level_consistency` 跨维主源、`cross_validate` chip 维、A 类消费侧（dim3/dim5/dim7）取值、L2 三源与票差。
- **回归**：dim/JUD 相关 **94 个测试文件 / 1115 用例 → 1111 passed, 4 failed**。
- **4 项失败经 HEAD 对照（`git worktree` 于 `b126cec` 同跑）确认为既有失败，与本号无关**：
  | 失败 | 既有原因 |
  |---|---|
  | `test_428_gap_fixes::test_raw2_uses_run_with_timeout` | 源码串断言漂移（`_run_with_timeout(_raw2_one` 现为多行调用 → `find` 返回 -1） |
  | `test_464_17::test_margin_risk_30d_window` | 用固定日期 `2026-08-25` 对「30 日窗口」判定，随当前日期（09-27）漂出窗口 → 恒失败 |
  | `test_484_data_backfill::TestAnchorCashflowFCF`（2 例） | `Dim7ValuationEngine._anchor_cashflow` 已迁 `valuation_estimator._ve._anchor_cashflow`（479-9/487 收敛），测试未同步 |
- **另修正 1 个既有数据依赖测试**：`tests/test_322_s6_fund_direction.py::test_fund_strength_603201_negative` 硬编码「603201 必为 5 日净流出」，实测该股 2026-09-27 的 5 日净额已为 **+345.99**（净流入）→ 断言与数据脱钩恒失败；改为「有向强度符号 == 数据净额符号」（仍精确验证 313 号「方向不被 abs 抹掉」的原意，不弱化）。

### 4.2 真实数据探针（8 股，`backend/scripts/_490_sig_contract_probe.py`，只读）

**A 类补产出键落地率（8 股全覆盖统计）**：

| 维 | 缺/空 | 说明 |
|---|---|---|
| dim2 | 0/3（1 只 1/3） | `divergence_multi_algo` 在「无背驰」时为空＝设计预期 |
| dim3 | **0/10**（RAW 重算后） | 重算前 5/10（`resonance_score`/`three_laws`/`risk_notes`/`entry_zone`/`target_zone` 待 RAW 落库） |
| dim4 | 0/7（1 只 1/7） | 601318 无 `phase_confidence`＝PDE 走 tags 兜底路径（无引擎结果，可接受） |
| dim5 | **0/7** | 全部真实落库 |
| dim7 | **0/6** | 全部真实落库 |

**关键改善（实测值）**：

| 项 | 修复前 | 修复后（实测） |
|---|---|---|
| dim5 情绪方向 | 恒 0 | `dir=1`（`market_phase=ferment`→发酵→看多）/ `dir=-1` |
| dim7 估值方向/强度 | 恒 0 / 恒 0.5 | 600519 `dir=1 str=0.984`（composite 1.28）；000002 `dir=-1 str=0.571` |
| dim3 量价方向/强度 | 恒 0 / 恒 0.5 | 000002 `dir=1 str=0.93`；300750 `dir=1 str=0.51`；600519 `dir=0 str=0.47`（vp_state 中性→HOLD，正确） |
| dim3 量比 | 恒 0.0（文本解析失败） | 真实（0.59~1.25） |
| dim3 入场/目标区间（391 P1） | 永不出 | 600519 `entry[1199.89,1261.74] target[1298.85,1422.55]`；另 7 只同 |
| L2 量价可靠性 | **从未执行**（恒 0.5） | `vp ∈ {0.3, 0.45, 0.9}`（8 股分布） |
| L2 结构可靠性 | 三源中 2 源恒默认 | 真实（0.30~0.81，随个股差异） |
| L4 冲突 | 15 条中约 11 条恒不触发 | 真实触发：000002 **4 条**（C1/C4/C6/C7，语义=矛盾型）；600519/601318/000001 各 1 条（C10 等） |
| cross_validate 回灌筹码维 | 恒缺（`fund_chip` 键名错位） | 8 股全部含 `chip` ✓ |

**新增发现（本号内一并修复）**：`reliability_assessor._DIM_ASSESSORS` 注册键为 `volume_price`，而 L1（`dim_adapter`）量价因子键是 `vp` → **量价可靠性评估从未被调用**（`assess()` 末尾 `_KNOWN_DIMS` 分支补 0.5 默认）。已补 `'vp': _assess_volume_price` 别名（490-20 附带）。

### 4.2.1 ⚠️ 连带行为变更（须用户知悉，登记 490-R9）

**490-8（legacy dims 情绪 state 真实化）会激活 `_detect_market_regime` 的情绪分支**：

- 链路：`StatusEngine._aggregate_v390:832` → `_detect_market_regime(tags, dims)` → 读 `dims['emotion']['state']`；命中 `'退潮'`/`'高潮'` → 返回 `extreme_panic` → `weights = MARKET_REGIME_WEIGHTS['extreme_panic']`（risk **0.40** / valuation **0.25**，其余维 0.05~0.10）。
- 变更前：`dims['emotion']['state']` 读 `judgment['phase']`（不存在）→ **恒「正常」** → 该分支**不可达**（`status_bar` 并非 tags 键，故 extreme_panic 实际不可达）。
- 变更后：state 为真实情绪阶段（冰点/萌芽/发酵/高潮/退潮/回归/正常）→ **市场阶段处于「退潮」或「高潮」时，全市场个股进入 `extreme_panic` 权重档**。
- 影响面：`sentiment_phase` 是**市场级**（全市场同值，per-stock 落库）→ 影响是**全市场同时切换**，非个股个例。
- 8 股实测（2026-09-27）：`emotion_state='发酵'` → 情绪分支未命中，regime 由 `status_bar`/`risk` 决定（600519/000002=trending_down，其余=ranging）→ **当前样本无变化**；退潮/高潮日会生效。
- 性质判定：**判定权重（果）的选取被激活**——权重值本身未改、设计意图即如此（370 S7 动态权重），但属「果侧行为变更」，按 §一 边界**须用户知悉/追认**。
- 可选处置：①**接受**（恢复 370 设计意图）；②若认为情绪极端档不应直接覆盖全市场权重，则须调整 `_detect_market_regime` 的情绪判据（属判定语义，独立号）。临时回退手段：把 `_convert_to_dims_format` 的 emotion state 改回常量（**不建议**，等于退回 B 类缺陷）。

### 4.3 生效条件与数据侧

- dim3 的 5 个 RAW 透传键来自 daemon **RAW-2 预计算**：按 486-3 先例执行 8 股 **pre_feat 定向重算**（`scripts/_486_3_prefeat_recompute.py`，含 DB 备份，结论 `ALL_OK`）后全部落库。**全市场存量 pre_feat 待 daemon 下次日终自然刷新**。
- `advice_engine` 的 `entry_zone`/`target_zone`（391 P1）随 dim3 透传**自动激活**（消费端代码未改）。
- 探针可复现：daemon 停止态执行 `.venv/bin/python scripts/_490_sig_contract_probe.py`。

## 五、登记项（本号未做，待裁）

| # | 登记项 | 说明 / 待裁点 |
|---|---|---|
| 490-R1 | dim3 `multi_timeframe_consistency` / `multi_timeframe_sub_states` **不由引擎产出** | 消费端改跨维取 dim2 多级别联立（490-20）。若要求 dim3 自产，须先定义「量价多周期分析」（新分析逻辑，属冻结范畴，需独立号 + 知识库依据） |
| 490-R2 | **C2 规则删除** | 原判据 `stage_name=='DOWNTREND_ACTIVE'` 无任何产出源；如需恢复须由 dim3 定义量价趋势阶段枚举 |
| 490-R3 | dim6 `risk_sources` / `piers_leverage_triggered` / `liquidity_avg_amount_wan` / `liquidity_circ_mv_wan` 等「因已算未消费」 | 489 §四 未消费清单子集，本号不动，待裁定去向（dim8 采用 / 保留契约 / 删除） |
| 490-R4 | 435 附加发现三项（`status_snapshot` 无 signals 列 / `volume_breakout` 恒失效 / `_build_status_snapshot` SELECT 未限 trade_date） | 属 411/370 管线设计议题，不在 A/B/C 三类，本号不动 |
| 490-R5 | 死代码（`dim_adapter.convert_to_dims_format`/`extract_direction_score`/`advice_generator`——**不含 `arbiter`**，见 491 更正） | 491 号批次1 已删除该 3 处并重定向 `test_482`；注意 `dim_adapter.convert_to_dims_format` 副本**曾读旧键**（`judgment.vp_state`/`flow_direction`/`phase`）——删除即消除该复用陷阱 |
| 490-R6 | `_DIM_DIRECTION['emotion']`（`status_engine`：冰点→**-1**）与 v390 `_EMOTION_DIRECTION`（冰点→**+1**，均值回归）方向语义**相反** | 本号仅修取值路径（490-8），未统一语义；属 485-6「调 dim5/framework 阈值取值」JUD 阶段主题 |
| 490-R7 | `reliability` 输出仍含冗余键 `volume_price=0.5`（`_KNOWN_DIMS` 历史键名） | 只新增 `vp` 别名，未删旧键（避免影响未知消费方）；如确认无消费方可清理 |
| 490-R8 | SIG 灯色类输出（`overall_light`/`risk_light`/`market_light`…） | 属 **439-A** 迁移 JUD 主题，本号不动 |
| 490-R9 | **490-8 连带激活 `_detect_market_regime` 情绪分支**（退潮/高潮 → 全市场 `extreme_panic` 权重档：risk 0.40/valuation 0.25） | 属「判定权重选取被激活」的**果侧行为变更**，须用户**追认或改判据**；详见 §4.2.1 |
