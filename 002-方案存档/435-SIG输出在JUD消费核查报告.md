# 435号｜SIG 环节输出在 JUD 环节的实际消费情况核查报告

- **文档版本**：v1.2（2026-09-14，**行号校准** + §六「不存在」精确化为「A 类·引擎未产出 / B 类·路径·形态错位」两类 + 处置进度登记 436 号）
- **性质**：只读核查报告，**未修改任何代码**
- **生效判定版本**：`jud_engine_version: "v390"`（`backend/config/status_engine.yaml:8`）
- **相关前置**：370号（SIG/JUD 分工）、411号（维度引擎统一调度，Phase 1-6）、390号（v390 多因子管线）、418号（JUD 消费链补齐）、420号（dim8 消费面增强）、391号（advice target_zone 消费）

---

## 一、核查范围与方法

- **SIG 环节**：`data_daemon._precompute_strategy_signals`（`data_daemon.py:5763`）→ 写 `strategy_signal_detail` 表
- **JUD 环节**：管道内三件套 `_build_status_snapshot`（`data_daemon.py:4748`）→ `_jud_enrich_with_meta`（:4166）→ `_build_treemap_snapshot`（:4266），核心为 `StatusEngine.evaluate`（`status_engine.py:63`）的 v390 六组件管线
- **方法**：对 SIG 三大产物逐一追踪消费方，并在**维度引擎输出键 vs JUD 消费键**两级做差集比对

## 二、SIG 环节输出全景

### 2.0 SIG 的两类输出（本报告的核心区分）

自 370号方案 S1 起，SIG 环节对 `strategy_signal_detail` 是**两类输出、各有专属下游**（不是"一个产物被多方抢用"）：

| 类别 | 产物 | 下游 | 是否经 JUD |
|---|---|---|---|
| **数据类** | `dim_results_json` | **JUD** 消费（`StatusEngine.evaluate` v390 六组件 + dim8 + legacy 兼容层） | ✅ 是 |
| **文字类**（股票现状描述） | `seven_dim_json` | **OUT** 透传 → `status_snapshot.one_liner_detail` → **前端** | ❌ 否（设计上直通） |

- 依据①`app/data/enhanced_cache_manager.py:853` 建表注释：「370号方案S1：新增SIG双产出列（**seven_dim_json→OUT直通，dim_results_json→JUD消费**）」。
- 依据②`status_engine.py:928-933`（`generate_seven_dim_from_signals` docstring）：「**产出直接透传到OUT写入one_liner_detail，不经过JUD**」。
- 依据③除两类主产出外，`signal_json`（含 `signals`）作为 JUD 次级输入由 `_load_signals` 读取，但 signals 恒空而空转（见 2.2）。

> **本报告口径订正（v1.1）**：v1.0 把 `seven_dim_json` 列在"JUD 未消费项"中，虽事实（JUD 零消费）不误，但**归类口径有误**——它是**设计上给 OUT/前端的第二类输出**，本就不以 JUD 为消费方；"JUD 未消费"不是缺陷。其质量与去向应在 **OUT/前端** 侧核查。

### 2.1 三个产物明细

表结构：`ts_code, trade_date, signal_json, schema_version, cached_at` + 370号新增 `seven_dim_json` / `dim_results_json`，主键 `(ts_code, trade_date)`（`app/data/enhanced_cache_manager.py:844-860`）。

| 产物 | 类别/去向 | 结构 | 生成方 |
|---|---|---|---|
| **signal_json** | 数据类 → JUD（次级，signals 恒空） | `{ts_code, trade_date, period, signals, data_availability, schema_version}` | `UnifiedStrategyCore._to_standardized`（`unified_core.py:107`） |
| **seven_dim_json** | **文字类 → OUT → 前端** | 七维 `{dim: {title, light, text, evidence, confidence}}` | `generate_seven_dim_from_signals`（`status_engine.py:928`；SIG 预计算内调用 `data_daemon.py:5800-5801`） |
| **dim_results_json** | **数据类 → JUD（主）** | `{signal, structure, volume_price, chip_fund, emotion, risk, valuation, signal_analysis}` | `StatusEngine._build_dim_engine_results`（`status_engine.py:217`；SIG 预计算内调用 `data_daemon.py:5815`） |

### 2.2 关键事实

**关键事实①**：`signal_json.signals` **恒为空**。411号 Phase 1 后 `compute_via_engines` 返回空列表（`signal_computation_service.py:80-101`，方法体 `signals = []` 于 `:91`、`return signals` 于 `:101`），`compute_for_stock` → `_apply_post_processing([])` 仍为空，`signal_json.signals = {}` 落库（`get_latest_signal_detail`（`app/data/enhanced_cache_manager.py:2385`）注释自认"signals 设计上为空"，见 `:2395`，另见 `:2342`）。

**关键事实②**：因 signals 空，`seven_dim_json` 实际只剩 `risk`/`summary` 两个兜底键（`_extract` 对 5 引擎全 None，`status_engine.py:930-968`），且 `risk` 证据为空——**七维已空壳化**。

## 三、两类输出的消费链路

### 3.1 数据类通路：dim_results_json → JUD

```
strategy_signal_detail.dim_results_json ──► StatusEngine.evaluate(ts_code, dim_results)
                                              ├─ dim8 总结（重算，追加 summary 键）
                                              ├─ _convert_to_dims_format（legacy 兼容层）
                                              ├─ _apply_l0（tags）
                                              ├─ _aggregate_v390（生效分支）
                                              │    ├─ convert_to_factors（dim_adapter）
                                              │    ├─ assess（reliability_assessor）
                                              │    ├─ consensus_compute（consensus_engine）
                                              │    ├─ conflict_detect（conflict_matrix）
                                              │    ├─ factor_arbitrate（factor_arbiter）
                                              │    └─ compute_advice（advice_engine）
                                              └─ _detect_registered_signals（tags + signal_json.signals）
strategy_signal_detail.signal_json.signals ──► StatusEngine._load_signals（:150，只取 signals 子集）
pre_feat_cache（RAW-2 产物，SIG 输入原料）──► _load_tags / _jud_enrich_with_meta（机会分类/潜力/右侧确认）
```

> 注：`_jud_enrich_with_meta` 与 `_build_treemap_snapshot` 消费的是 pre_feat_cache（RAW-2 产物）与 opportunity_tags_cache（标签库），均**非 SIG 输出**；JUD 对 SIG 输出的消费集中在 `evaluate` 链路。

### 3.2 文字类通路：seven_dim_json → OUT → 前端（不经 JUD）

```
SIG（_precompute_strategy_signals, data_daemon.py:5763）
  └─ generate_seven_dim_from_signals(signal_json)  ──► strategy_signal_detail.seven_dim_json
                                                                │
OUT（_out_transmit_seven_dim, data_daemon.py:4525）
  └─ UPDATE status_snapshot SET one_liner_detail = (SELECT ssd.seven_dim_json …)   :4561-4569
                                                                │
前端
  ├─ routes/strategy_analyze.py:814-815    （status_snapshot.one_liner_detail → _status_row）
  ├─ routes/strategy_analyze.py:1006-1008  （get_latest_signal_detail().seven_dim_json → seven_dim_report）
  └─ _ui-prototype/opportunity-treemap.html:746-754（s.seven_dim_report || s.one_liner_detail）
```

**关键辨析——dim8 不在此通路（避免与"文字类由 dim8 整理"混淆）**

- `dim8`（`Dim8SummaryEngine`）在**当前代码里只被 JUD 调用**：`StatusEngine.evaluate` 内 `dim_engine_results['summary'] = dim8.evaluate(...)`（`status_engine.py:93-95`），产物随 `dim_engine_results` 落 `status_snapshot.dim_engine_results`；它**不生产 `seven_dim_json`，也不写 `one_liner_detail`**。
- dim8 的定位（358号 v4.1 / 420号 已实施）是"**纯整理输出**：读取 dim1-dim7 组装综合报告"；其消费方为 `cross_validate.py:86`、`weight_engine.py:180-196`（历史 direction）与归档，**前端目前不直接展示 dim8 输出**（`strategy_analyze.py` 的 `_status_row`/`_status_verdict` 均不含 `dim_engine_results`）。
- 与"由 dim8 整理文字类输出到 OUT"相符的是 **394号方案《SIG环节dim8系统配置规划与实施方案》**（拟将 dim8 重定位为 SIG 侧"质量守门员 + 现状描述生成器"，T4.3/T4.5 由 dim8 读 dim2-dim7 的 `plain` 生成 `seven_dim_json` 并写入 SIG）。**该方案状态＝已作废**（2026-09-08，设计被 420号取代；"现状描述生成/质量检查/删除判定"功能**均未落地**，测试文件已删除）。故当前 SIG 文字类生产者为 `generate_seven_dim_from_signals`，**并非 dim8**。

## 四、消费情况总表（JUD 视角）

> 口径：本表只回答"JUD 是否消费"。据此，**文字类输出（`seven_dim_json`）不在 JUD 消费范围内，属正常分流，不构成缺陷**（见 §3.2）。

| SIG 输出 | JUD 消费 | 结论 |
|---|---|---|
| `dim_results_json` | ✅ 主消费（evaluate 全链路） | 已消费 |
| `signal_json.signals` | ⚠️ 消费但**恒空** | 消费空转 |
| `signal_json.data_availability` | ❌ 无任何读取 | **未消费** |
| `seven_dim_json` | ❌ JUD 零消费——**设计使然**（文字类第二输出：OUT 透传 `one_liner_detail` → 前端，`data_daemon.py:4561`） | 非 JUD 消费对象（分流正常） |
| `dim_results_json.signal_analysis` | ❌ 无消费方（内容已并入 `signal` 键） | **冗余输出** |
| `dim_results_json.signal.data_context` | ❌ JUD 预计算路径不消费 | **未消费**（含 DataFrame 巨型 JSON） |
| `dim_results_json.signal.status_quality` | ❌ dim8/v390 组件均不读 | **未消费** |

## 五、未消费项明确化

### 5.1 seven_dim_json（非"JUD 未消费"，而是 OUT/前端文字通路）
- **定性**：370号 设计的**第二类输出（文字类·股票现状描述）**，专属下游是 **OUT → 前端**，**本就不经 JUD**——"JUD 零消费"不是缺陷，**不应计入"JUD 未消费项"**。
- **去向**：OUT 步骤读取（`data_daemon.py:4561-4569`，`UPDATE status_snapshot SET one_liner_detail = (SELECT ssd.seven_dim_json …)`），docstring 明示"产出直接透传到OUT，**不经过JUD**"（`status_engine.py:928-933`）；前端经 `strategy_analyze.py:814-815`、`:1006-1008` 与 `opportunity-treemap.html:746-754` 消费。
- **真正的风险点（OUT/前端侧缺陷，非 JUD）**：因 `signal_json.signals` 恒空，`generate_seven_dim_from_signals` 的 `_extract` 对 5 引擎全 None，产出只剩 `risk`/`summary` 兜底键 → **文字类输出本身空壳化**，前端 `one_liner_detail`/`seven_dim_report` 看到的现状描述严重残缺

### 5.2 signal_json.data_availability（未消费）
- JUD 端 `_load_signals` 只取 `.get('signals')`（`status_engine.py:153`），`data_availability`（kline/daily_basic/moneyflow/index/market_state 五字段）无任何 JUD 读取
- 消费方在 SIG 自侧（`dim1` 门禁与 `dim4` 引擎读取 signal_detail，属 SIG 计算期依赖，非 JUD）

### 5.3 dim_results_json 内部冗余/死数据
| 键 | 说明 |
|---|---|
| `signal_analysis` | 独立键无消费方；其内容（status_description/judgment/audit）已合并进 `signal` 键（`status_engine.py:296-302`）。grep 证实仅测试 mock 与 route 展示标签引用，JUD 判定链零消费 |
| `signal.data_context` | 含 20+ 项原料（DataFrame 等），经 `json.dumps(default=str)` 序列化为**巨型字符串**入库；JUD 用预计算 dim_results 后不再执行 dim2–7，data_context 无注入消费 |
| `signal.status_quality` | dim1 门禁的质量标注（quality_level/completeness_score/missing_tables），JUD 判定链（dim8/v390 六组件）无读取 |

### 5.4 维度引擎子键级未消费（引擎算了但 JUD 判定链未用）
| 引擎 | 引擎输出但 JUD 不消费的键 |
|---|---|
| dim2 | `vs_zhongshu/vs_ma/vs_support_resistance/vs_chip/vs_indicator`（仅 plain 展示用）、`chanlun_direction`、`buy_sell_points`（列表，v390 读的是**键名不同**的 `buy_sell_points_detail`，见 §六 B 类） |
| dim3 | `health_score/volume_energy/pattern_score/granville`、`pattern`（仅 dim8 用） |
| dim4 | `cost_structure/signal/margin/crowding/fund_flow`（展示文本）、`direction`（judgment） |
| dim5 | `market/sector/stock`（文本）、`bociasi_quick/bociasi_slow/quadrant` |
| dim6 | `risk_detail/risk_light/risk_factors/event_count/event_details/event_summary/risk_evidence/rr_level/rr_assessment/atr_14d/signal_days/support_resistance` |
| dim7 | `pe_percentile/pb_percentile/fcf_yield`、`potential_breakdown`、`judgment.fina_health{value,light}` 之外的嵌套 `{value,light}` 结构 |
| 全部 | `audit` 四键（仅 dim8 读 `audit.confidence` 做数据完整度提示；v390 组件不读） |

## 六、⚠️ 核心发现：JUD 消费键与 SIG 引擎输出键**契约错位**（消费悬空）

v390 组件按 390 方案设计的**结构化数值键**读取，但这些键要么**引擎根本没产出**，要么**算了却落在展示文本/嵌套结构/子对象中（或键名不同）**——JUD "消费"到的不是数值，而是默认值/失败值。按错位性质分两类：

- **A 类·引擎未产出该键**：该维度引擎的 `judgment`/`status_description` 输出中根本没有此键（近似量亦未产出），JUD 只能取默认值。
- **B 类·算了但路径/形态错位**：引擎算了该量，但落在**展示文本**（如 `f"量比{...}"`）、**嵌套 dict**（如 `{value, light}`）、**子对象/数据类**（如 `RelationResult.to_dict()`）中，或**键名不同**，导致顶层数值键读取落空。

| 维度 | JUD 读取的键（消费点） | 类别 | SIG 引擎实际输出（证据） | 后果 |
|---|---|---|---|---|
| dim2 | `level_cross_score`（`dim_adapter.py:114` / `:528`；`reliability_assessor.py:81`） | **A** | 无此键（引擎仅有 `chanlun_direction`/`chanlun_strength`，`dim2_structure_engine.py:148-149`） | strength=0.5 默认 |
| dim2 | `trend_structure_signal`（`dim_adapter.py:532`） | **A** | 无此键 | 123 突破增强失效 |
| dim2 | `chanlun_phase`（`dim_adapter.py:537`；`conflict_matrix.py:88`） | **A** | 无此键（`chanlun_*` 仅有 direction/strength） | 欲病折减失效 |
| dim2 | `buy_sell_points_detail`（`dim_adapter.py:542`） | **B·键名错位** | 引擎有 `buy_sell_points`（列表，`dim2_structure_engine.py:150`） | 买卖点方向增强失效 |
| dim3 | `state_machine_direction`/`state_machine_confidence`、`multi_timeframe_consistency`/`_sub_states`（`dim_adapter.py:141` / `:149` / `:579` / `:587` / `:592`） | **A** | 全项目仅出现在**消费侧** `dim_adapter.py` 与测试 mock，无任何引擎产出 | **dim3 direction 恒 0、strength 恒 0.35** |
| dim3 | `resonance_score`（`dim_adapter.py:588`） | **B·路径错位** | 引擎算了，但在 `RelationResult.to_dict()` 内（`dim3_vp_engine.py:165`，字段 `:153`），未进入 `evaluate()` 返回的 `status_description`/`judgment`（`:4670-4683`） | 上述 strength 公式缺 0.3 权重项 |
| dim3 | `vol_ratio`（`_safe_float` 解析） | **B·形态错位** | 文本 `f'量比{vol_ratio:.1f}'`（`dim3_vp_engine.py:4673`） | `_safe_float` 失败→0.0 |
| dim3 | `entry_zone`/`target_zone`（391号 P1 / advice_engine） | **B·路径错位** | 引擎算了（`VolumePriceSignal.entry_zone/:181`、`target_zone/:183`），但仅经 `to_output_dict` 输出（`:202`/`:204`，调用点 `:4215`），不在 `evaluate()` 返回内（`:4692`） | **advice 永无 target_zone/entry_zone**（391号 P1 消费悬空） |
| dim4 | `status_description.phase` | **B·形态错位** | 展示文本 `"吸筹（PhaseDetector…）"` | C4 匹配 `('building','lifting')` 永假 |
| dim4 | `crowding_level` | **B·路径错位** | 引擎算了（`dim4_chip_fund_engine.py:5595`），但 JUD 侧读的是 `crowding` 文本（`:6008`） | C4/C4++/C8 失效 |
| dim4 | `cost_concentration`/`cost_profit_ratio` | **B·键名错位** | 无同名键，近似量在 `cost_structure` 文本内（`dim4_chip_fund_engine.py:6006`） | C4/C4++/C8 失效 |
| dim4 | 顶层 `retail_institution` | **B·路径错位** | 引擎算了（`_assess_retail_institution`，`dim4_chip_fund_engine.py:5888`；调用 `:5935`），但输出为 `retail_institution` **文本**（`:6007`），非顶层结构化键 | C4+ 失效 |
| dim5 | `market_phase`（`dim_adapter.py:672` / `:679`） | **B·路径错位** | 引擎内部有该权重键（`dim5_emotion_engine.py:56` / `:276`），但输出侧只有 `market` **文本**（`:515`，形如"市场处于{phase}"） | 回退 tags |
| dim5 | `temperature`（`dim_adapter.py:203` / `:686`） | **B·形态错位** | 文本 `f"{temperature}/100"`（`dim5_emotion_engine.py:521`；数值版在 `:532` 名为 `continuous_value`） | `_safe_float` 失败→50.0 恒定 → **strength 恒 0，情绪极端修正永不触发** |
| dim5 | `bociasi_fast_signal`/`bociasi_slow_signal`/`bociasi_slow_confidence`/`bociasi_quadrant`（`dim_adapter.py:208` / `:216` / `:689-691`） | **B·键名·形态错位** | 引擎输出为 `bociasi_quick`/`bociasi_slow` **文本**（`dim5_emotion_engine.py:518-519`，形如"快线=BEARISH（0.8）"） | 共振加成失效 |
| dim5 | `time_rhythm`（`dim_adapter.py:327-330`） | **A** | dim5 引擎不产出（独立 `time_rhythm_engine.py` 未并入 dim_results；dim5 仅 docstring `:12` 提及） | time 辅助维恒 0 |
| dim7 | `composite_rating`（`dim_adapter.py:248` / `:782`） | **B·路径错位** | 引擎算了（raw dict `dim7_valuation_engine.py:844`），但 JUD 读的 `status_description` 里只在 `valuation_level` **文本**内（`:954`） | **dim7 direction 恒 0** |
| dim7 | `valuation_deviation`（`dim_adapter.py:793`） | **B·形态错位** | `judgment` 内为 `{value, light}` 嵌套（`dim7_valuation_engine.py:970`） | 读 status_description 落空→0 |
| dim7 | `dividend_yield`/`revenue_growth`（`dim_adapter.py:797` / `:802`） | **B·形态错位** | 嵌套 raw dict `:840-841`；status_description 内为文本（`:958-959`） | 加成失效→0 |
| dim7 | `asset_anchor_rating`/`earnings_anchor_rating`（`dim_adapter.py:815-816`；`conflict_matrix.py:131-132`） | **B·路径错位** | 引擎算了，但在嵌套 raw dict（`dim7_valuation_engine.py:845-846`），非顶层 keys | C14 失效 |
| dim3 | `stage_name`（`conflict_matrix.py:96`，取 **dim3** 的 status_description） | **B·键名错位** | 引擎算了阶段（`Stage` 数据类 `dim3_vp_engine.py:99`、`stage_name, stage_confidence = self._classify_stage(...)` `:2164`、`Stage(name=stage_name, ...)` `:2183`），但 dim3 status_description 输出键名为 `vp_state`（`:4671`） | C2/C3 名称类规则落空 |
| dim2 | `divergence_type`/`divergence_strength`/`level_trends`/`chanlun_phase`（`conflict_matrix.py:88-91` / `:153`，均取 **dim2** 的 status_description） | **A**（dim2 侧未产出） | dim2 引擎无这些键；近似量在 **dim3**（`RelationResult.divergence_type` `dim3_vp_engine.py:148`、`divergence_confidence` `:149`，且 `to_dict()` 键名改为 `divergence` `:163`）——既不回填 dim2，也完全没有 `level_trends`/`chanlun_phase` | **C1/C2/C2b/C3/C4/C6/C10/C11/C14 全部失效** |

> 注：`conflict_matrix.py` 从 **dim2** 读 `chanlun_phase`/`divergence_type`/`divergence_strength`/`level_trends`（`:88-91`、`:153`），从 **dim3** 读 `stage_name`（`:96`）；而这几项在引擎侧的真实归属分别是 dim2 的 `chanlun_direction`/`chanlun_strength`（`dim2_structure_engine.py:148-149`）与 dim3 的 `RelationResult`/`Stage`（`dim3_vp_engine.py:148-149`、`:99`/`:2183`），故此处**同时存在「跨维取错」与「键名错位」两类错位**。dim3 status_description 的实际键为 `vp_state/health_score/divergence/volume_energy/pattern/vol_ratio/pattern_score/granville/plain`（`dim3_vp_engine.py:4670-4677`），dim3 `evaluate()` 返回仅 `{status_description, judgment, audit}`（`:4692`）。

**受影响的具体判定项**（v390 生效管线）：
1. **conflict_matrix 18 条规则中约 10 条失效**（C1/C2/C2b/C3/C4/C4+/C4++/C6/C8/C10/C11/C11+/C14），仅 C5/C7/C9/C13 依赖 dim6/tags 的规则可用
2. **dim3/dim5/dim7 因子空心化**：direction 或 strength 恒默认值，L3 共识、L5 仲裁、L6 建议的对应输入失真
3. **compute_advice 的 entry_zone/target_zone 永不输出**（391号 P1 承诺的 dim3 target_zone 消费落空）
4. 仅 **dim6（risk）键匹配度最高**（rr_value/atr_pct/support_price/resistance_price/invalidation 等全部可用）

## 七、附加发现

1. **注册表信号 hits 算而未落**：`_assemble` 产出 `result['signals']`（缠论三买/放量突破/均线多头/平台突破/量价强势形态命中列表，`status_engine.py:870`），但 `status_snapshot` 表**无 signals 列**（建表见 `data_daemon.py:4785-4793`）→ JUD 算出的触发列表未持久化，treemap/OUT 均不读
2. **volume_breakout 注册信号永久失效**：`_detect_registered_signals` 读 `signals.get('量价分析策略')`（`status_engine.py:804`），411号后 signal_json.signals 恒空 → 该信号永不触发（其余 4 类依赖 tags 不受影响）
3. **JUD 读取 dim_results_json 未限定交易日**：`_build_status_snapshot` 的 SELECT 无 `ORDER BY trade_date DESC LIMIT 1`（`data_daemon.py:4820-4822`），若个股存在多交易日记录，dict 覆盖顺序不保证取最新（对比 `get_latest_signal_detail` 有 `ORDER BY trade_date DESC LIMIT 1`，`enhanced_cache_manager.py:2408`）
4. **legacy 兼容层同样错位**：`_convert_to_dims_format` 读 `chip_fund.judgment.flow_direction`（引擎为 `direction`）、`emotion.judgment.phase`（引擎无）→ 读默认值；当前 v390 下该层仅用于构造 dims 供 `_detect_market_regime`，回滚 legacy 时问题放大

## 八、结论

1. **SIG 是两类输出、各有专属下游**（370号设计）：**数据类** `dim_results_json` → JUD；**文字类**（股票现状描述）`seven_dim_json` → OUT → 前端。本报告核查对象为前者对 JUD 的实际消费。
2. **JUD 真正消费的 SIG 输出只有 `dim_results_json` 一个产物**，且消费集中在 v390 六组件对 `judgment`/`status_description` 的通用键（`overall_light/overall_direction/continuous_value/plain` 等）
3. **明确未消费（仅指 JUD 侧）**：`signal_json.data_availability`、`signal_analysis` 冗余键、`signal.data_context`、`signal.status_quality`、各维度 `audit` 与大量展示文本子键。**`seven_dim_json` 不计入此项**——它是设计上给 OUT/前端的文字类第二输出，本就不以 JUD 为消费方（其空壳化问题属 OUT/前端侧）
4. **更严重的是消费悬空**：v390 组件按方案设计的约 20 个数值键，在 SIG 引擎输出中**要么未产出（A 类·引擎未产出）、要么落在展示文本/嵌套结构/子对象中或键名不同（B 类·路径·形态错位）**（逐键分类与证据见 §六），导致 dim3/dim5/dim7 因子空心化、约 10 条冲突规则失效、advice 缺 target_zone/entry_zone——即 **JUD 对 SIG 输出的消费存在系统性键契约断裂**，并非"SIG 输出过剩"，而是"SIG 输出形态与 JUD 消费预期不一致"。两类错位的修复性质不同：**A 类需引擎补产出该键，B 类多数只需契约对齐（键名映射/取值路径修正）**
5. **同一根因（`signal_json.signals` 恒空）同时打击两类输出**：数据类侧使 `volume_breakout` 注册信号永久失效；文字类侧使 `seven_dim_json`（→ OUT `one_liner_detail` → 前端）空壳化
6. **dim8 归属澄清**：`Dim8SummaryEngine` 当前运行于 **JUD** 的 `StatusEngine.evaluate` 内（产物落 `status_snapshot.dim_engine_results`），**不是** OUT 文字通路的生产者；SIG 文字类生产者为 `generate_seven_dim_from_signals`。"由 dim8 整理文字类输出到 OUT"出自已作废的 394号方案，未落地（见 §3.2）

---

## 订正记录

| 版本 | 日期 | 订正内容 |
|---|---|---|
| v1.0 | 2026-09-14 | 初版：SIG 三产物追踪、JUD v390 消费链、未消费项、键契约错位表 |
| v1.1 | 2026-09-14 | ①明确 **SIG 两类输出**（数据类→JUD / 文字类→OUT→前端），新增 §2.0、§3.2；②修正 `seven_dim_json` 归类（由"JUD 未消费项"改为"设计分流，非缺陷"），同步改 §四、§5.1、§八；③新增 **dim8 归属辨析**（dim8 属 JUD，非 OUT 文字通路；394号方案已作废） |
| v1.2 | 2026-09-14 | ①**行号校准**（以 `grep -n` 1-based 复核，非结论变更）：`status_engine.py` `evaluate:62→63`、`_load_signals:149→150`、`.get('signals'):152→153`、`_detect_registered_signals 内 量价分析策略:849→804`；`data_daemon.py` OUT 透传 SQL 由"块区间 `4554-4572`"精确为"语句区间 `4561-4569`"、status_snapshot DDL `4785-4794→4785-4793`、dim_results SELECT `4802-4806→4820-4822`（原引为无关代码）、`_precompute_strategy_signals` 内 `5800→5800-5801`；补全 `app/data/enhanced_cache_manager.py` 路径前缀。②§六「不存在」精确化为 **A 类·引擎未产出 / B 类·路径·形态错位** 两类，表增「类别/引擎实际输出（含行号证据）/消费点」列，并更正 **conflict_matrix 的取值来源**（`chanlun_phase`/`divergence_type`/`divergence_strength`/`level_trends` 取自 **dim2**、`stage_name` 取自 **dim3**；dim2 侧属 A 类，dim3 侧属 B 类·键名错位），§八.4 同步两类口径。③处置进度登记 **436号** 已开号。**结论未变、未改任何代码** |

---

## 处置进度（按批次）

| 批次 | 内容 | 状态 |
|---|---|---|
| — | 本报告为纯核查存档 | 键契约错位（§六）待用户决定是否开号修复；**未改任何代码** |
| 435-1 | 文字类空壳化（§5.1，OUT/前端侧缺陷） | **已开号** → `002-方案存档/436-SIG文字类输出（七维现状描述）空壳化与键契约错位修复方案.md`（v1.0，📋 待实施；待用户就 §九 D1/D2/D4 拍板后按 §七 B1 开工，本报告不启动） |
