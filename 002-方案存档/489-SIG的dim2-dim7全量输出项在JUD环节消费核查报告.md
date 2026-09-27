---
title: SIG 的 dim2-dim7 全量输出项在 JUD 环节消费核查报告
type: 只读核查报告（未修改任何代码）
date: 2026-09-27
version: v1.0
status: 📋 核查完成（结论待用户裁定处置；键契约断裂清单可直接用作 JUD 阶段修复输入）
related:
  - 435-SIG输出在JUD消费核查报告（本报告为其「全量输出项 × 现状」复核与更新，435 聚焦 v390 约 20 个错位键，本报告覆盖 dim2-dim7 全部输出键）
  - 436-SIG文字类输出（七维现状描述）空壳化与键契约错位修复方案（B1 dim8 整体归集器已落地，本报告据其 T/E 字段表核定 dim8 消费面）
  - 444-SIG现状描述事实层构建与显现（dim_results 八维键契约）
  - 445-dim2-dim7引擎正确性知识库核查（引擎侧基准；445 冻结「果」不改判定逻辑）
  - 464-dim2-dim7分析输出项全量梳理（SIG现状层）（输出项原料清单；本报告为其 JUD 侧对偶）
  - 479-dim8改造与全链路收口总方案 / 479-9（dim7 数字键补产出）/ 488（dim5 temperature_basis）
  - 439-A（SIG 判定/灯色迁移 JUD，未实施）
---

# 489号｜SIG 的 dim2-dim7 全量输出项在 JUD 环节消费核查

**核查时点**：2026-09-27，HEAD = `b126cec`（= origin/main，工作树 clean）。
**生效判定配置**：`backend/config/status_engine.yaml` → `jud_engine_version: "v390"`（L1-L6 新管线生效，legacy 管线未启用）。
**性质**：只读核查，未改任何代码；结论以当前代码为准（已逐键复核，非引用 435 号旧行号）。

---

## 一、核查对象与方法

| 项 | 内容 |
|---|---|
| **SIG 产出（被消费方）** | `strategy_signal_detail.dim_results_json` = `{signal, structure, volume_price, chip_fund, emotion, risk, valuation, signal_analysis}`，由 SIG 预计算 `data_daemon._precompute_strategy_signals`（`data_daemon.py:6875-6918`，`dim_results = _se_engine._build_dim_engine_results(...)` → `json.dumps`）落库 |
| **SIG 全量输出项范围** | dim2 结构 / dim3 量价 / dim4 筹码资金 / dim5 情绪 / dim6 风险 / dim7 估值，六引擎 `evaluate()` 返回的 `status_description`（现状字段）+ `judgment`（结论字段）+ `audit`（条件稽核）全部键 |
| **JUD 消费方（判定方）** | 见 §二 |
| **方法** | ①读六引擎 `evaluate()` 返回构造点，枚举全部输出键（非引用 464/435 清单）；②枚举 JUD 侧全部 `dim_results` 读取点（`grep` 逐键扫描 20 个候选模块 + 逐键读消费代码确认容器/形态）；③对每个键判定「✅已消费 / 🔶消费悬空（读但取默认值）/ ⛔未消费」；④以 435 号为基线做差异对比 |
| **已核实「非 JUD 消费方」**（不计入本报告） | `seven_dim_json` 文字类通路（→OUT→前端，设计分流）；`advice_builder.build_operation_advice`（→ `routes/strategy_analyze.py`，OUT/前端侧）；`radar_service`（→ `routes/opportunity_library.py`）；`tag_extractor` / `event_monitor`（读 P2 信号原料与事件源，非 dim 引擎产出；且 app 内无 import 方）；`dim_adapter.convert_to_dims_format` / `extract_direction_score` / `advice_generator`（**无调用方的死代码**） |

---

## 二、JUD 环节的实际消费通路（现状）

`StatusEngine.evaluate(ts_code, dim_results=<precomputed>)`（`status_engine.py:63`）内，对 SIG 产出共 **5 条消费通路**：

```
strategy_signal_detail.dim_results_json
  │  （data_daemon._build_status_snapshot:5916-5930 预取 → evaluate(code, dim_results=...)）
  ▼
StatusEngine.evaluate
  ├─ ① dim8 总结（dim8_summary_engine.evaluate）→ dim_engine_results['summary']（落 status_snapshot.dim_engine_results）
  ├─ ② legacy dims 层（StatusEngine._convert_to_dims_format:332）
  │      → dims → _apply_l0（L0 分级）→ dim_states 落库 / status_bar / _detect_market_regime / _status_bar
  ├─ ③ v390 L1-L6 主管线（_aggregate_v390:748）
  │      L1 dim_adapter.convert_to_factors → L2 reliability_assessor.assess →
  │      L3 consensus_engine.compute → L4 conflict_matrix.detect → L5 factor_arbiter.arbitrate →
  │      L6 advice_engine.compute_advice（→ _assemble 并入 advice_params）
  ├─ ④ _detect_registered_signals（tags + signal_json.signals）
  └─ ⑤ 落库后回灌：cross_validate.L4CrossValidator._extract_real_dimensions 读 status_snapshot.dim_engine_results
         → _convert_dim_engine_to_legacy（诊断/机会图谱弹窗）
```

**核心结论先行**：JUD 对 dim2-dim7 的消费**不是「输出过剩」，而是「消费形态与产出形态系统性不一致」**——三个层次并存：
**(a) 已真实接线**（446/447/449/475/479-9/488 等修复后大幅扩张）；
**(b) 消费悬空**（JUD 读了，引擎没产，或产在另一个容器 → 取默认值，静默退化）；
**(c) 零消费**（引擎产了，JUD 判定链从不读）。

---

## 三、逐维全量输出项 × JUD 消费对照（v1.0 现状）

**状态图例**：✅ 已消费（真实取值生效）｜🔶 消费悬空（JUD 读该键但取不到值/形态不匹配 → 默认值静默退化）｜⛔ 未消费（JUD 判定链零读取）

### 3.1 dim2 结构（`dim2_structure_engine.py:284-351`）

| 键（status_description） | JUD 消费方（通路） | 状态 |
|---|---|---|
| `vs_zhongshu` / `vs_ma` / `vs_support_resistance` | ②legacy dims evidence（`status_engine.py:347`）；⑥dim8 E | ✅ |
| `vs_indicator` | ①dim8 E 字段表 | ✅ |
| `vs_chip` | —（dim8 479 删除该字段，筹码主源改 dim4） | ⛔ |
| `chanlun_direction` / `trend_basis` | ①dim8 T | ✅ |
| `chanlun_strength` / `structure_health_score` | ③L1 dim_adapter（0-100→0-1 归一，structure_health_score 优先）；①dim8 标签（479 已删出 T 表） | ✅（L1 真实生效） |
| `buy_sell_points`（列表） | —（③读的是 `_detail`，①dim8 也读 `_detail`） | ⛔ |
| `buy_sell_points_detail` | ③L1（确认买/卖点改 direction）；①dim8 T | ✅ |
| `multi_level`（JSON） | —（同名键仅 `tag_extractor` 读 P2 原料，非 JUD） | ⛔ |
| `multi_level_direction_text` | ①dim8 T | ✅ |
| `level_cross_score` | ③L1 strength（0.4 权重）；③L2 reliability 三源融合 0.5 权重 | ✅ |
| `chanlun_phase` | ③L1（`'欲病' → ×0.7` 折减，实测值域 欲病/健康） | ✅ |
| `trend_structure_signal` / `ts_strength` | ③L1（`123_buy_breakout` 且 dir>0 → strength+ts_strength+0.05）；①dim8 E | ✅ |
| `stage_name` | ③L1 extras + ①dim8 T（另 ④conflict_matrix 亦读，但取错维，见 §五） | ✅（L1/dim8） |
| `divergence` | ③L1 extras + ①dim8 E | ✅ |
| `divergence_type` | ①dim8 E | ✅ |
| `divergence_strength` | ④conflict_matrix C6 唯一消费方，**但取错容器**（落 dim1 signal）→ 实际无消费 | ⛔ |
| `zhongshu_location_ratio` / `divergence_details` / `divergence_dual_confirmed` / `theorem_check_details` | ①dim8 E（479 A1/A3/A4 补产出透传） | ✅ |
| judgment.`structure` | ②legacy dims state；signal_analyzer.classify_attribute | ✅ |
| judgment.`light` | ②legacy dims light（→dim_states/status_bar） | ✅ |
| judgment.`overall_light` | ①dim8 `_extract_dim_light`；⑤cross_validate 回灌 | ✅ |
| judgment.`overall_direction` | ③L1 direction；①dim8 `_extract_dim_direction`；⑤cross_validate | ✅ |
| judgment.`continuous_value` | ③L1（0.2 权重）；①dim8 confidence | ✅ |
| judgment.`position` | —（legacy dims 未读该键） | ⛔ |

**合计**：25 个 sd 键 + 6 个 judgment 键；✅ 21 / ⛔ 5。
**评价**：dim2 是 446 D10 七契约键补产出后**消费面最完整**的一维；435 §六 中 dim2 的 A 类错位（level_cross_score / trend_structure_signal / chanlun_phase / buy_sell_points_detail）**已全部闭环**，仅剩 3 个展示性键未消费 + 1 个被 conflict_matrix 取错容器。

### 3.2 dim3 量价（`dim3_vp_engine.py:218-258`）

| 键 | JUD 消费方 | 状态 |
|---|---|---|
| `vp_state` | ①dim8 T；signal_analyzer（`_vp_health_score` 经 dims） | ✅ |
| `divergence` | ①dim8 E；④conflict_matrix C3/C11（读 `volume_price` ✓ 容器，但值域为「顶背离/底背离/空」，与规则比对的 `'top'` **形态不匹配** → 规则仍不触发） | ✅（读）/ 🔶（规则层悬空） |
| `volume_energy` | ①dim8 T | ✅ |
| `pattern` | ①dim8 T；①dim8 `_detect_conflicts` 规则7（形态与信号背离） | ✅ |
| `vol_ratio` | ①dim8 字段标签（文本「量比1.2」）；③L1 `_dim3_extras['vol_ratio'] = _safe_float(文本)` → **解析失败落 0.0** | 🔶 |
| `rps` | ①dim8 T（细项6 转「RPS=61.5（前38%分位）」表述） | ✅ |
| `granville` / `vp_state_label` / `vp_rule` | ①dim8 T/E（455/479 A5/A9 补产出） | ✅ |
| `divergence_type` / `divergence_confidence` / `divergence_macd_confirmed` | ①dim8 E（479 A8） | ✅ |
| `health_score` / `pattern_score` | 仅存在于 dim8 中文标签表（`_DIM8_FIELD_CN`），**无任何取值点**（479 已按 dim3 定稿「评分归 JUD」移出 T 表） | ⛔ |
| judgment.`state` / `light` / `score` | ②legacy dims 读 `judgment['vp_state']`（**键名错位，见 §五**）→ `state` 键本身无消费方；`light` ✅（legacy dims light） | 🔶/⛔ |
| judgment.`overall_light` / `overall_direction` | ①dim8；⑤cross_validate | ✅ |
| judgment.`continuous_value` | ③L1（0.7 权重）；①dim8 confidence | ✅ |

**合计**：14 个 sd 键 + 6 个 judgment 键；✅ 11 / ⛔ 2 / 其余以「读但取默认值」为主。

### 3.3 dim4 筹码资金（`dim4_chip_fund_engine.py:6100-6150`）

| 键 | JUD 消费方 | 状态 |
|---|---|---|
| `phase`（展示文本「建仓（PhaseDetector…）」） | ②legacy dims（另有 ④conflict C4 读，但值带括号 → 不等 `'building'`）；①dim8 T；⑤cross_validate | ✅（②/①）/ 🔶（④） |
| judgment.`phase`（枚举 `building/lifting/distributing`） | ③L1 direction（→ DIM_DIRECTION chip_fund）；①dim8 `_detect_conflicts` 规则1（结构上升+派发） | ✅ |
| `fund_flow` / `cost_structure` / `signal` / `margin` / `crowding` | ①dim8 T / subsections（「筹码成本/资金博弈」两小节） | ✅ |
| `retail_institution` | ①dim8 E + dim8 规则6（散户反向）；④conflict C4+ 读 `dim4.get('retail_institution')`（**取顶层，实际在 sd → 落空**） | ✅（①）/ 🔶（④） |
| `fund_price_divergence` / `_status` / `_risk` | ①dim8 T/E（446 补产出） | ✅ |
| judgment.`direction` / `light` / `overall_light` / `overall_direction` / `continuous_value` | ②legacy dims（读 `flow_direction` **键名错位** → 落「中性」，见 §五）；①dim8；③L1 strength 回退 continuous_value（= 1 − 拥挤分） | ✅/🔶 |

**合计**：10 个 sd 键 + 6 个 judgment 键；**无 ⛔ 键**，但 435 的 C4/C4+/C4++/C8 相关四键（`crowding_level` / `cost_concentration` / `cost_profit_ratio` / 顶层 `retail_institution`）**在 conflict_matrix 中仍全部落空**（见 §五）。

### 3.4 dim5 情绪（`dim5_emotion_engine.py:600-615`）

| 键 | JUD 消费方 | 状态 |
|---|---|---|
| `market` / `sector` / `quadrant` | ①dim8 T（`stock` 按 437-A D4 去重，由 dim3 vp_state 派生 → 不产句） | ✅ |
| `temperature`（文本「中性58.1/100」） | ①dim8 T（488 A1 升级「果（因）」形态）；③L1 `_safe_float(文本, 50.0)` → **落 50.0 → strength 恒 0**；L6 advice 透传文本 | 🔶 |
| `temperature_basis` | ①dim8（488 A1 新增） | ✅ |
| `bociasi_quick` / `bociasi_slow` | ①dim8 E（479 A10） | ✅ |
| `stock` | —（有意去重，无消费方） | ⛔ |
| judgment.`market_light` / `sector_light` / `stock_light` | —（dim8/legacy 均读 `overall_light`） | ⛔ |
| judgment.`overall_light` / `overall_direction` | ①dim8；②legacy dims light；⑤cross_validate；③L1 情绪方向经 `_EMOTION_DIRECTION`（但 direction 实际由 tags 回退，见 §五） | ✅/🔶 |
| judgment.`continuous_value` | ③L1/①dim8 | ✅ |

**合计**：8 个 sd 键 + 6 个 judgment 键；✅ 6 / ⛔ 1。

### 3.5 dim6 风险（`dim6_risk_engine.py:525-596`）★ 消费面最完整

| 键 | JUD 消费方 | 状态 |
|---|---|---|
| `risk_level` / `risk_detail` / `risk_factors` | ②legacy dims state；③L1 direction；④conflict C5/C7/C13；①dim8 T | ✅ |
| `support_price` / `resistance_price` / `dist_to_support_pct` / `dist_to_resistance_pct` / `dist_to_prev_high_pct` / `signal_days` | ③L1 extras / ④conflict C13 / ⑥advice（止损位）/ ①dim8 T+E+小节「价格位置」 | ✅ |
| `rr_value` / `rr_level` / `rr_assessment` | ③L1（strength = rr/3）；④conflict；⑥advice；①dim8（+ `_extract_dim_rr` 驱动状态条） | ✅ |
| `volatility_level` / `atr_pct` / `volatility_percentile` | ③L1（×0.6 折减）；③L2 reliability（ATR 分档）；④conflict C5；⑥advice；①dim8 E | ✅ |
| `liquidity_detail` | ①dim8 E（452 双门槛口径已接线） | ✅ |
| `invalidation` | ⑥advice（失效条件）；①dim8 E | ✅ |
| `event_details`（dict-list） | ②_apply_l0 硬否决（448/453 读 event_type/direction）；①dim8 E | ✅ |
| `piers_leverage`（dict） | ①dim8 E（475 P2 达标状态可见） | ✅ |
| `risk_light` / `risk_sources` / `piers_leverage_triggered` / `atr_14d` / `liquidity_risk` / `liquidity_avg_amount_wan` / `liquidity_circ_mv_wan` / `event_count` / `event_summary` / `risk_evidence` / `support_resistance` | 全项目无 JUD 读取点（`event_count`/`event_summary` 仅 `event_monitor` 生产侧同名；`support_resistance` 仅 `tag_extractor` 读 P2 原料） | ⛔ |
| judgment.`level` / `risk_level` / `light` / `overall_light` / `overall_direction` / `continuous_value` | ③L1（level/rr）；②legacy dims（risk_level/light）；①dim8 | ✅ |

**合计**：29 个 sd 键 + 6 个 judgment 键；✅ 24 / ⛔ 11。

### 3.6 dim7 估值（`dim7_valuation_engine.py:720-780`）

| 键 | JUD 消费方 | 状态 |
|---|---|---|
| `valuation_level`（文本「极度低估（composite=1.21）」） | ①dim8 summary 尾置句（D2=A）；⑤cross_validate；②legacy dims 实际取 tags（非本键） | ✅（①/⑤） |
| `pe_percentile` / `pb_percentile` | ①dim8 T/E | ✅ |
| `pe_percentile_5y` / `pb_percentile_5y` / `ps_percentile_5y` | ③L2 reliability（PE 存在性 0.8/PB+PS 极端 0.95）；③L1 置信/分位；⑤cross_validate | ✅ |
| `fcf_yield` / `dividend_yield` / `revenue_growth` | ①dim8 T/E（487 收口 fcf 不适用置 None）；③L1 数值加成（**文本解析失败 → 0.0**） | ✅/🔶 |
| `value_trap` / `growth_trap` | ①dim8 尾置句（449 陷阱标注） | ✅ |
| `potential_breakdown` | ①dim8（`_parse_potential_breakdown` 六维 + B 方案来源标注） | ✅ |
| `potential_score` / `potential_strength` | ③L1（±0.1）；③legacy dims 的 factor 维（**死函数**，见 §一） | ✅（L1） |
| `fina_health`（文本） | ①dim8 字段；③L1 finance 维读 `judgment.fina_health.value`（非本键） | ✅（①） |
| judgment.`valuation_level{value,light}` / `fina_health{value,light}` | ②legacy dims（`status_engine._convert_to_dims_format` 未读，**死函数 dim_adapter 版本有读**）；③L1 finance 维读 fina_health.value | ✅/⛔ |
| judgment.`valuation_deviation{value,light}` / `potential_strength{value,light}` | dim8 未读；③L1 读 sd 平铺键（不存在） | ⛔ |
| judgment.`overall_light` / `overall_direction` / `continuous_value` | ①dim8；②legacy（valuation light 实际取 tags）；⑤cross_validate | ✅（①/⑤） |

**合计**：15 个 sd 键 + 7 个 judgment 键；✅ 13 / ⛔ 2。

---

## 四、未消费输出项（JUD 判定链零读取）——明确清单

| 维度 | 未消费键 | 说明 |
|---|---|---|
| dim2 | `vs_chip`、`buy_sell_points`（列表）、`multi_level`（JSON）、`divergence_strength`、judgment.`position` | `vs_chip`/`buy_sell_points` 属 437-A 主动去重（筹码主源 dim4、买卖点主源 `_detail`）；`multi_level` JSON 是前端富结构素材（479-7 推迟项）；`divergence_strength` 唯一消费方 conflict_matrix 取错容器 |
| dim3 | `health_score`、`pattern_score` | 仅中文标签表残留，无取值点（479 按「评分归 JUD」移出 dim8 T 表；JUD 判定链也未接） |
| dim5 | `stock`、judgment.`market_light`/`sector_light`/`stock_light` | `stock` 按 437-A D4 去重（主源 dim3 vp_state）；三层面灯色属灯色类输出（439-A 迁移对象） |
| dim6 | `risk_light`、`risk_sources`、`piers_leverage_triggered`、`atr_14d`、`liquidity_risk`、`liquidity_avg_amount_wan`、`liquidity_circ_mv_wan`、`event_count`、`event_summary`、`risk_evidence`、`support_resistance` | 11 键零消费；其中 `risk_sources`/`piers_leverage` 达标状态是 475 补产出的「因」，`piers_leverage` 已被 dim8 消费，`piers_leverage_triggered` 未消费 |
| dim7 | judgment.`valuation_deviation{value,light}`、judgment.`potential_strength{value,light}` | 数值在 sd 平铺键已消费；judgment 内嵌套副本无人读 |
| **全部维度** | `audit.conditions[].actual` / `.threshold` | **JUD 判定链不读**（`audit.confidence` 被 dim8 读作数据完整度；`satisfied_count/total_count` 仅 dim7 被 dim8 `_valuation_sentence` 用于「估值条件 N/8 满足」）；其去向是 dim8 透传进 `seven_dim_json` → 前端（属 OUT 侧） |

---

## 五、消费悬空（JUD 读键但引擎未产出 / 路径·形态·键名错位）——**当前最关键问题**

> 这是 435 号定义的核心缺陷类型，本报告复核后**依然大面积存在**（部分换成了新形态）。按错位性质分 A（引擎未产出）/ B（产出但路径·形态·键名错位）两类。

### 5.1 v390 L1（`dim_adapter.convert_to_factors`）— 因子空心化

| 维度 | JUD 读键 | 类别 | 引擎实际产出 | 后果（实测推断） |
|---|---|---|---|---|
| dim3 | `state_machine_direction` / `state_machine_confidence` / `resonance_score` / `multi_timeframe_consistency` / `multi_timeframe_sub_states` | **A**（全项目仅存在于消费侧与测试 mock） | 无 | **dim3 direction 恒 0**；strength = 0.7×0.5 + 0.3×0.5 = **恒 0.5** |
| dim3 | `stage_name` / `vol_ratio`（数值语义） | **B**（dim3 sd 无 `stage_name`；`vol_ratio` 为文本） | `vol_ratio`='量比1.2' | extras 落空 / `_safe_float` 失败 → 0.0 |
| dim4 | `phase_confidence` | **A** | 阶段置信度在引擎内部 `phase_info['confidence']`，未进 sd | L1 strength 退回 `continuous_value`（=1−拥挤分，非阶段置信） |
| dim4 | `pde_conflict` / `pde_vote_ratio` / `pde_price_position` | **A** | 无（PDE 明细仅存于 `phase_engine_result`，未透传 sd） | L1 extras + L2 票差修正全部落空 |
| dim5 | `market_phase` | **B**（引擎 sd 键为 `market` 文本） | `market`='市场处于发酵（…）' | L1 回退 tags `stock_emotion`/`sentiment_phase` |
| dim5 | `temperature` | **B**（文本「中性58.1/100」） | 数值版仅在函数内 `temperature` 变量 | `_safe_float`→50.0 → **dim5 strength 恒 0**（情绪极端修正永不触发） |
| dim5 | `bociasi_fast_signal` / `bociasi_slow_signal` / `bociasi_slow_confidence` / `bociasi_quadrant` / `sector_heat` | **B**（键名/路径错位） | sd 为 `bociasi_quick`/`bociasi_slow`/`quadrant` 文本；`sector` 亦为文本 | 快慢线共振加成、象限加权、板块加成全部落空 |
| dim7 | `composite_rating` | **B**（仅在 `valuation_level` 文本内 `composite=X`） | 无平铺键 | **dim7 direction 恒 0** |
| dim7 | `valuation_deviation` | **B**（judgment 内 `{value,light}` 嵌套） | 无平铺键 | strength 的 0.4×deviation 项恒 0 |
| dim7 | `dividend_yield` / `revenue_growth` | **B**（文本「股息率2.5%」） | 无平铺数值键 | `>4%` / `>20%` 加成永不触发 |

### 5.2 v390 L2（`reliability_assessor.assess`）— 三维可靠性恒默认值

| 维度 | JUD 读键 | 状态 |
|---|---|---|
| dim2 | `level_cross_score` ✅ / `consistency_component`·`chanlun_strength_components`·`chanlun_component`·`divergence_multi_algo` ⛔（引擎从未产出） | 三源融合仅 1/3 真实，其余取 0.5 默认 |
| dim3 | `multi_timeframe_consistency`·`weekly_direction`·`three_laws`·`stage_confidence` | 全未产出 → **dim3 可靠性恒 0.5** |
| dim4 | `pde_conflict`·`phase_confidence`·`pde_vote_ratio` | 全未产出 → **dim4 可靠性恒 0.5** |
| dim5 | `bociasi_slow_confidence`·`sector_heat` | 全未产出 → **dim5 可靠性恒 0.5** |
| dim6 | `atr_pct` ✅ / `volatility_percentile` ✅ | ✅ 真实生效 |
| dim7 | `pe_percentile_5y` ✅ / `pb_percentile_5y` ✅ / `ps_percentile_5y` ✅ | ✅ 真实生效 |

### 5.3 v390 L4（`conflict_matrix.detect`）— **跨维取错 + 子键形态错位**，多数规则失效

| 问题 | 细节 |
|---|---|
| **跨维取错①** | `dim2 = dim_results.get('dim2') or dim_results.get('signal')`（`:86`）→ `dim_results` 无 `'dim2'` 键 → 实际读 **dim1 `signal`（signal_analyzer 产出）**；其 sd 为 `attribute/strength/maintenance/…`，**无** `chanlun_phase`/`divergence_type`/`divergence_strength`/`level_trends`/`trend_structure_signal` → C1 / C6 / C10 / C2b 失效 |
| **跨维取错②** | `dim3 = dim_results.get('dim3') or dim_results.get('structure')`（`:94`）→ 实际读 **dim2 结构引擎**；`stage_name`='上升/下降/盘整' ≠ `'DOWNTREND_ACTIVE'` → C2 失效；`divergence`='顶背驰' ≠ `'top'` → C11 / C11+ 失效；`risk_notes` 不存在 → C12 失效 |
| **dim4 子键形态错位** | `crowding_level`（sd 键为 `crowding` 文本）、`cost_concentration`/`cost_profit_ratio`（在 `cost_structure` 文本内）、顶层 `retail_institution`（实际在 sd 内）→ C4 / C4+ / C4++ / C8 失效 |
| **dim7 子键路径错位** | `asset_anchor_rating` / `earnings_anchor_rating`（引擎产在 `_compute_valuation` 内部 raw dict，未进 sd）→ C14 失效 |
| **dim3 `divergence` 值域不匹配** | C3 / C11 比对 `'top'`，实际值为「顶背离（置信0.60，MACD确认）」→ 规则不触发 |
| **`vol_ratio` 入参恒定** | `_aggregate_v390` 调 `conflict_detect(...)` **未传 vol_ratio** → 恒 1.0 → C11+ 的 `<0.5` 分支永不成立 |

**当前真正生效的规则**：C5（atr_pct / rr_value / consensus_rate）、C7（risk_level + tags）、C9（tags regulatory）、C13（rr_value / dist_*）。即 15 条规则中 **约 11 条失效**（与 435 号 §六 结论一致，失效原因更新为「跨维取错 + 子键错位」）。

### 5.4 legacy dims 层（`StatusEngine._convert_to_dims_format:332`）— 三维 state 恒默认

| 维度 | JUD 读键 | 引擎实际 | 后果 |
|---|---|---|---|
| dim3 | `judgment['vp_state']` | dim3 judgment 键为 `state`（`vp_state` 在 sd） | dims['vp'].state **恒「中性」** → dim_states 落库/status_bar/`_detect_market_regime` 的量价维恒中性 |
| dim4 | `judgment['flow_direction']` | dim4 judgment 键为 `direction` | dims['chip_fund'].state **恒「中性」** |
| dim5 | `judgment['phase']` | dim5 judgment 无 `phase`（key 为 `market_light`/`overall_light`） | dims['emotion'].state **恒「正常」** |
| dim7 | （不读 judgment） | valuation/finance/event/position 维**全部取自 tags**，非 dim 引擎 | dim7 引擎结论在 dim_states 不体现 |

> 注：`dim_adapter.convert_to_dims_format`（其内部已修正这些键名）**无任何调用方，是死代码**；真正生效的是 `status_engine.py:332` 的同名方法（键名未修正）。

### 5.5 dim8 内 `_convert_dim_engine_to_legacy`（cross_validate 回灌）— 键名错位（新增发现）

| 位置 | 问题 |
|---|---|
| `cross_validate.py:46` | `der.get('fund_chip')`——**dim_results 的真实键是 `chip_fund`** → 筹码维永缺（dims 无 `chip`）。所幸该空值使下一行 `judg.get('phase', {}).get('direction')` 未被执行，**掩盖了一个潜在 AttributeError**（dim4 judgment.`phase` 是字符串 `'building'`，对 str 调用 `.get` 会抛异常；若将来修正键名而不同步改取值形态，将导致该函数整体异常） |
| `cross_validate.py:49` | `judg.get('phase', {}).get('direction', 0)`——形态错位（字符串 vs dict） |

### 5.6 JUD 内 signal 维桥接（新增发现）

`StatusEngine._build_dim_engine_results` 第 3 步构造 `dims_for_signal` 时，取「judgment 中第一个 **dict 型**非 meta 值的 `value`」作为 state（`status_engine.py:294-302`）。dim2/3/4/5/6 的 judgment 全为标量 → `state_val` **恒「中性」**（仅 dim7 因 `valuation_level` 是 dict 而取到英文 level）。因此 `signal_analyzer.classify_attribute` 收到的 structure/chip_fund/risk/vp 全是「中性」→ **信号属性分类恒 `neutral`**（`dims['signal_confirm']` 恒「中性观望」），L1 `factors['signal'].direction` 恒 0，进而 `dims_for_signal` 参数中 dim2-dim7 的分析结论**实际未被信号维消费**。

### 5.7 435 号「附加发现」复核

| 435 附加发现 | 现状 |
|---|---|
| 注册表信号 hits 算而未落（`status_snapshot` 无 `signals` 列） | **仍存在**（DDL `data_daemon.py:5889-5896` 无该列） |
| `volume_breakout` 注册信号永久失效（`signal_json.signals` 恒空） | **仍存在**（`_detect_registered_signals` 读 `signals.get('量价分析策略')`） |
| `_build_status_snapshot` 读 `dim_results_json` 未限定 `trade_date` | **仍存在**（`data_daemon.py:5924` 无 `ORDER BY`) |
| legacy 兼容层键错位（`flow_direction`/`phase`） | **仍存在**，且新发现 dim3 `vp_state` 同类错位（见 §5.4） |

---

## 六、与 435 号基线的差异

### 6.1 已闭环（435 §六错位表 → 现已真实接线）

| 项 | 修复号 | 证据 |
|---|---|---|
| dim2 `level_cross_score` / `chanlun_phase` / `trend_structure_signal` / `ts_strength` / `buy_sell_points_detail` / `stage_name` / `divergence_type` 七契约键 | 446 D10（445 §6.1） | `dim2_structure_engine.py:284-315` 全键产出；`dim_adapter.py:520-560` 真实消费 |
| dim7 `pe_percentile_5y` / `pb_percentile_5y` / `ps_percentile_5y` 数字键（relibility L2 恒 0.3 根治） | 479-9-③ | `dim7_valuation_engine.py:735-737` |
| dim7 陷阱标注 / FCF 缺则降级 | 449 / 487 P2-3 | `:742-745` |
| dim4 资金×价格背离补产出 | 446 D11 | `dim4_chip_fund_engine.py:6088-6093` |
| dim5 温度 7 入参明细 | 488 A1 | `dim5_emotion_engine.py:604` `temperature_basis` |
| dim6 risk_sources / piers_leverage / dist_to_prev_high_pct / liquidity_detail | 475 / 452 | `dim6_risk_engine.py:527-536` |
| dim3 RPS / granville / vp_state_label / vp_rule 补产出 | 446 D12 / 455 / 479 A5 | `dim3_vp_engine.py:218-234` |
| dim2/dim3/dim6/dim7 大量 dim8 T/E 字段透传 | 479 系列 | `dim8_summary_engine.py:838-930` |

### 6.2 仍存在（435 结论延续）

- dim3 `state_machine_*` / `resonance_score` / `multi_timeframe_*` 未产出 → **direction 恒 0**（strength 由 0.35 → 现恒 0.5，因 `resonance_score` 默认 0.0 归一为 0.5）。
- dim5 `temperature` 文本解析失败 → **strength 恒 0**。
- dim7 `composite_rating` 未平铺 → **direction 恒 0**。
- `conflict_matrix` 约 10 条规则失效；`advice` 的 `entry_zone`/`target_zone` 仍永不出（`advice_engine.py:150-156` 读 dim3 sd 中不存在的键）。
- `_assemble` signals 未落库 / `volume_breakout` 恒失效 / SELECT 未限交易日。
- legacy 兼容层键错位。

### 6.3 新增发现（435 未列）

1. **`conflict_matrix` 的 `dim2`/`dim3` 回退取错维**（`:86`/`:94`）——435 只指出「dim2 侧 A 类未产出」，未指出畸形回退落到 `signal`/`structure` 容器。
2. **L2 可靠性三源融合键从未产出**（`consistency_component`/`chanlun_strength_components`/`chanlun_component`/`divergence_multi_algo`）。
3. **dim5 L1 追加的三个未产出键**（388 号升级 D 引入 `bociasi_fast_signal`/`bociasi_quadrant`/`sector_heat`）。
4. **legacy dims 层 dim3 `vp_state` 键名错位**（435 仅列 dim4 `flow_direction`/dim5 `phase`）。
5. **`cross_validate._convert_dim_engine_to_legacy` 的 `fund_chip` 键名错位**（365 号批次 C 引入）及被掩盖的潜在 AttributeError。
6. **JUD 内 signal 维桥接 `dims_for_signal` state 恒「中性」**（§5.6）。
7. **死代码确认**：`dim_adapter.convert_to_dims_format`、`dim_adapter.extract_direction_score`、`advice_generator`（3 处，全仓无调用方）——435 未评估。
   ⚠️ **491 号更正（2026-09-27）**：本条初稿曾把 `arbiter` 一并列为「死代码」——**有误，已更正**。`arbiter.arbitrate` 在 **v390 主管线之外仍被 3 条通路使用**：① OUT 操作建议 `advice_engine.build_operation_advice:485` / `advice_builder.build_operation_advice:123`（→ `routes/strategy_analyze.py`）；② 弹窗诊断 `cross_validate.L4CrossValidator`（`:510`/`:1070`/`:1327`）；③ legacy `status_engine._aggregate:776`。准确表述应为「v390 主管线内不调用 `arbiter`（改由 `factor_arbiter` 承担）」，**它不是死代码**。

---

## 七、结论

1. **JUD 对 SIG 产出的消费入口唯一**：`strategy_signal_detail.dim_results_json`，经 `StatusEngine.evaluate` 的 5 条通路消费（dim8 总结 / legacy dims / v390 L1-L6 / 注册信号 / cross_validate 回灌）。`seven_dim_json`（文字类）不经 JUD，属设计分流。
2. **自 435 号以来，dim2 侧契约错位已系统闭环**（446 D10 七契约键 + 479 系列透传），dim6 消费面最完整；dim2/dim6/dim7 的 dim8 现状描述字段已基本全量接线。
3. **仍存在三条系统性缺陷线**（均为「果」侧判定输入失真，属 JUD 阶段修复范围）：
   - **A 类·引擎未产出**：dim3 状态机四键、dim4 `pde_*`/`phase_confidence`、dim5 bociasi 快慢线信号键、dim2 可靠性三源键、dim7 `composite_rating`/`valuation_deviation`/锚定评级。
   - **B 类·路径·形态·键名错位**：dim3 `judgment['vp_state']`、dim4 `judgment['flow_direction']`、dim5 `judgment['phase']`（legacy dims）；dim5 `temperature` 文本、dim4 `crowding`/`cost_structure` 文本、dim7 `dividend_yield`/`revenue_growth` 文本（v390）；`cross_validate` 的 `fund_chip`。
   - **C 类·跨维取错**：`conflict_matrix` 的 `dim2→signal`、`dim3→structure` 回退。
4. **失效影响面**（v390 生效口径）：dim3 direction 恒 0 / strength 恒 0.5；dim5 strength 恒 0；dim7 direction 恒 0；dim3/dim4/dim5 可靠性恒 0.5；conflict_matrix 15 条规则中约 11 条失效；advice 永无 `entry_zone`/`target_zone`；legacy dims 的 vp/chip_fund/emotion 三维 state 恒默认；signal 维属性分类恒 `neutral`。
5. **未消费项（⛔）集中在展示/去重类键**（dim2 5 键、dim3 2 键、dim5 4 键、dim6 11 键、dim7 嵌套副本 2 键，及全部维度 `audit.conditions[].actual/threshold`）——多数是 437-A 有意去重或已改由 dim8→OUT 承载，**不属缺陷**，但 `dim6` 的 `risk_sources`/`piers_leverage_triggered`/`liquidity_*` 属「因」已算未消费，建议随 JUD 阶段一并裁定去向。
6. **本报告为只读核查，未改任何代码**。键契约断裂清单（§五）按 A/B/C 三类可直接作为 JUD 阶段修复的输入；处置是否开号、以及「A 类补产出」与「B/C 类消费端适配」的取舍，待用户裁定（445 Freeze-vs-Fact 边界：补产出/取值口径属「因」侧可改；判定阈值/权重属「果」侧，须独立号 + 全链路验证）。

---

## 附：核查方法（可复现）

```bash
# 1) 引擎产出键：六引擎 evaluate() 返回构造点
grep -n "'status_description'\|'judgment'\|'audit'" \
  backend/app/opportunity_atlas/dimensions/dim{2,3,4,5,6,7}_*.py
# 2) JUD 消费点扫描（逐键 × 20 候选模块）
#    见 /tmp/audit_scan.sh（status_engine/dim_adapter/reliability_assessor/consensus_engine/
#    conflict_matrix/factor_arbiter/advice_engine/arbiter/dim8_summary_engine/signal_analyzer/
#    cross_validate/advice_builder/advice_generator/potential_engine/event_monitor/tag_extractor/
#    radar_service/valuation_estimator/backtest_minimal/phase_detector）
# 3) 调用方核验（区分 live 与死代码）
grep -rn "convert_to_dims_format\|convert_to_factors\|extract_direction_score" --include=*.py backend/app
# 4) dim_results 键名核验（确证无 'dim2'/'dim3'/'dim4' 生产者）
grep -rn "'dim2'\|'dim3'\|'dim4'\|'dim6'\|'dim7'" --include=*.py backend/app backend/data_daemon.py
# 5) JUD 触发点：dim_results_json 预取与注入
sed -n '5916,5930p' backend/data_daemon.py
```

**核查时点代码基线**：HEAD `b126cec`（2026-09-27）。
