---
title: SIG→RAW迁移实施状态审计与消费者接入补充方案
type: 审计方案
date: 2026-09-07
version: v3.0
status: 待实施
related:
  - 353号-系统总体架构规划（总纲）
  - 401号-dim4原料数据通路核查与修复方案
  - 405号-dim6数据访问路径统一与架构修正方案
  - 407号-维度引擎数据访问路径冲突全面核查与修正方案
  - 409号-dim1数据质量门禁层改造方案
  - 410号-dim2-dim7层数据分层审计与RAW前置计算迁移方案
  - 411号-维度引擎统一实施计划（407-410整合）
---

# 412号 — SIG→RAW迁移实施状态审计与消费者接入补充方案

---

## 一、背景

410号方案定义了8个Phase的SIG→RAW迁移（简单数学公式从dim引擎迁移到daemon预计算），411号方案整合为14个Phase。本轮审计核对：daemon端预计算是否已全量写入、存储管道是否畅通、dim引擎消费者是否已接入、数据量是否需要补充计算以保障dim1提取。

---

## 二、数据流架构

```
采集层(COL) → 存储层(STG) → 加工层(RAW) → 分析层(SIG) → 判定层(JUD) → 成品仓(OUT)
                                        ↑                  ↑
                                   data_daemon        dim engines
                                   _precompute_       evaluate()
                                   raw_features()     reads tags
                                        ↓                  ↓
                                   pre_feat_cache     tags (flat dict)
                                   (嵌套JSON)         ← _flatten_pre_feat()
```

**关键管道**：
1. `data_daemon._precompute_raw_features()` → 写入`pre_feat_cache`（嵌套JSON，21组特征，54+字段）
2. `StatusEngine._load_tags()` → 读取`pre_feat_cache` → `_flatten_pre_feat()` 扁平化为flat dict
3. dim engines的`evaluate()` → 从`tags`读取预计算值，回退到raw计算

---

## 三、411号方案14个Phase实施状态总览

411号方案整合407-410为14个Phase。下表为代码级审计结果（含本轮已修复项）。

| Phase | 内容 | 批次 | 审计状态 | 本轮修复 |
|-------|------|------|:--------:|----------|
| Phase 1 | 剔除signal_computation_service旧路径 | A | ✅ 已实现 | — |
| Phase 2 | dim1分析逻辑迁移到JUD(signal_analyzer.py) | A | ✅ 已实现 | — |
| Phase 3 | dim1重写为数据质量门禁层 | A | ✅ 已实现 | — |
| Phase 4 | status_engine适配+dim8适配 | A | ⚠️ 部分实现 | ✅ 修复dim8键名+递归bug |
| Phase 5 | MA/MACD/RSI改读预计算表 | B | ⚠️ 部分实现 | ✅ dim2/dim3 MACD接入 |
| Phase 6 | dim2-dim7消费data_context | B | ⚠️ 部分实现 | ✅ dim7接入data_context |
| Phase 7 | dim4筹码指标RAW迁移 | C | ⚠️ 部分实现 | — |
| Phase 8 | dim4 5日资金聚合RAW迁移 | C | ✅ 已实现 | ✅ dim4 _dim_fund接入 |
| Phase 9 | dim6几何化+波动率RAW迁移 | C | ✅ 已实现 | ✅ dim6 risk_ext接入 |
| Phase 10 | dim5市场级SQL改预计算 | D | ⚠️ 分裂 | — |
| Phase 11 | dim7估值指标RAW迁移 | D | ⚠️ 部分实现 | — |
| Phase 12 | dim4成本价RAW迁移 | D | ⚠️ 部分实现 | — |
| Phase 13 | dim3量指标RAW迁移 | E | ⚠️ 部分实现 | — |
| Phase 14 | 集成测试+全量验证 | E | ⚠️ 部分实现 | ✅ 创建test_411_pipeline.py(30测试) |

**test_411_pipeline.py测试覆盖**（30个测试，全部通过）：

| 测试类 | 测试数 | 覆盖Phase |
|--------|--------|-----------|
| TestPhase1_OldPathRemoved | 2 | Phase 1 |
| TestPhase2_SignalAnalyzer | 5 | Phase 2 |
| TestPhase3_Dim1Gate | 3 | Phase 3 |
| TestPhase4_StatusEngine | 4 | Phase 4 |
| TestPhase5_MACDPrecomputed | 5 | Phase 5 |
| TestPhase6_DataContext | 6 | Phase 6 |
| TestPhase9_Dim6Precomputed | 2 | Phase 9 |
| TestPhase8_Dim4FundPrecomputed | 1 | Phase 8 |
| TestDimAdapterFix | 1 | dim_adapter |
| TestEndToEnd | 1 | 端到端 |

**额外修复（非411方案定义）**：
- dim_adapter `_SIGNAL_CODE_DIRECTION` UnboundLocalError修复
- signal_decay_detector→signal_analyzer导入去重
- dim4 `_try_read_precomputed_rsi()` ts_code参数化修复

---

## 四、410方案8个Phase与RAW预计算逐项核对

### 4.1 核对总览

| Phase | 410方案内容 | 优先级 | daemon写入 | 消费者接入 | 完成度 |
|-------|------------|--------|:---------:|:---------:|:------:|
| Phase 1 | MA/MACD/RSI改读预计算表 | P0 | ✅ | ⚠️ | **40%** |
| Phase 2 | dim4筹码指标RAW迁移 | P1 | ✅ | ⚠️ | **17%** |
| Phase 3 | dim4 5日资金聚合RAW迁移 | P1 | ✅ | ✅ | **100%** |
| Phase 4 | dim6几何化+波动率RAW迁移 | P1 | ✅ | ✅ | **100%** |
| Phase 5 | dim5市场级SQL改预计算 | P2 | ✅ | ❌ | **0%** |
| Phase 6 | dim7估值指标RAW迁移 | P2 | ✅ | ❌ | **0%** |
| Phase 7 | dim4成本价RAW迁移 | P2 | ✅ | ❌ | **0%** |
| Phase 8 | dim3量指标RAW迁移 | P3 | ✅ | ❌ | **0%** |
| **总计** | | | **100%** | **~35%** | |

### 4.2 Phase 1 — MA/MACD/RSI改读预计算表（P0）

**预计算表结构**：

| 表名 | 列 | 写入方 |
|------|-----|--------|
| indicator_ma | ts_code, trade_date, ma5, ma10, ma20, ma30, ma60, vol_ma5, vol_ma10 | data_daemon._precompute_indicators()（管道驱动RAW-1） |
| indicator_macd | ts_code, trade_date, macd_dif, macd_dea, macd_hist | data_daemon._precompute_indicators()（管道驱动RAW-1） |
| indicator_other | ts_code, trade_date, rsi14, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower | data_daemon._precompute_indicators()（管道驱动RAW-1） |

**逐指标核对**：

| 指标 | 预计算表 | daemon/脚本写入 | dim2 | dim3 | dim4 | dim5 | 状态 |
|------|---------|:--------------:|:----:|:----:|:----:|:----:|------|
| MA5/10/20/30/60 | indicator_ma | ✅ | ❌ | ❌ | ❌ | ❌ | **消费者全未接入** |
| MACD(DIF/DEA/HIST) | indicator_macd | ✅ | ✅ | ✅ | — | — | **已完成** |
| RSI(14) | indicator_other | ✅ | — | — | ✅ | ✅ | **已完成** |
| BOLL(upper/mid/lower) | indicator_other | ✅ | — | — | — | ✅ | **已完成** |
| KDJ(K/D/J) | indicator_other | ✅ | — | — | — | — | **无消费者** |
| ATR(14) | — | ❌未写入 | — | — | — | — | **daemon未实现** |
| vol_ma5/10 | indicator_ma | ✅ | — | ❌ | — | — | **dim3未接入** |

**Phase 1 MACD预计算接入技术细节**：

dim2/dim3的`calc_macd()`已改造为支持预计算数据：
- 新增`precomputed`参数（dict，包含macd_dif/macd_dea/macd_hist数组）
- 模块级缓存`_MACD_PRECOMPUTED_CACHE`避免重复读取同一股票
- `_load_precomputed_macd(ts_code)`从`indicator_macd`表读取，缓存到模块级dict
- DivergenceDetector新增`_precomputed`属性，`detect()`方法接收precomputed参数
- 预计算长度不匹配时自动回退到raw ewm计算

dim3额外处理：`_detect_divergence_enhanced()`和背离检测中的inline MACD计算也已改为优先读预计算。
- dim2：`calc_support_resistance()`使用MA20/MA60（2处，无precomputed门控，主路径残留）
- dim3：`EnhancedPatternDetector` **~60个**pattern方法中MA5/10/20/30/60/120/250各自独立`np.mean()`计算（~80处raw计算），`VolumeStateAnalyzer`/`VPStateMachine`等5+处vol_ma计算
- dim4：`StageDetector` MA60（1处），`PhaseDetectionEngine` 多处MA
- dim5：`SectorRotationModel` MA5/MA20（per stock，raw rolling），`_bociasi_quickline()` MA5，`_time_rhythm()` MA20/BOLL

### 4.3 Phase 2 — dim4筹码指标RAW迁移（P1）

**daemon预计算字段（chip_fund_ext组）**：

| 字段 | daemon写入 | dim4 `_dim_ssrp()` | dim4 `_dim_chip()` | dim4 `_dim_asr()` | 状态 |
|------|:---------:|:------------------:|:------------------:|:-----------------:|------|
| ssrp | ✅ | ✅ 读取 | — | — | **已接入** |
| asr | ✅ | — | ❌ raw计算 | ❌ raw计算 | **未接入** |
| concentration | ✅ | — | ❌ raw计算 | — | **未接入** |
| profit_ratio | ✅ | — | ❌ raw计算 | — | **未接入** |
| cyqkl | ✅ | — | ❌ raw计算 | — | **未接入** |
| rsi | ✅ | — | — | — | **无消费者（dim4 RSI已改读indicator_other）** |

**根因**：`_dim_chip()`调用`_run_trading_phase_detector_v2()` → `ChipIndicators.calculate_all_indicators()`从raw重新计算全部筹码指标，忽略tags中的预计算值。

### 4.4 Phase 3 — dim4 5日资金聚合RAW迁移（P1）

| 字段 | daemon写入(fund_5d_ext) | dim4消费 | 状态 |
|------|:----------------------:|:--------:|------|
| net_lg_5d | ✅ | ✅ `_dim_fund()` | **已接入** |
| net_lg_5d_positive_ratio | ✅ | ✅ | **已接入** |
| net_lg_5d_consecutive | ✅ | ❌ 无消费者 | **未接入** |

### 4.5 Phase 4 — dim6几何化+波动率RAW迁移（P1）

| 字段 | daemon写入(risk_ext) | dim6消费 | 状态 |
|------|:-------------------:|:--------:|------|
| support_price | ✅ | ✅ | **已接入** |
| resistance_price | ✅ | ✅ | **已接入** |
| dist_to_support_pct | ✅ | ✅ | **已接入** |
| dist_to_resistance_pct | ✅ | ✅ | **已接入** |
| risk_reward | ✅ | ✅ | **已接入** |
| signal_days | ✅ | ✅ | **已接入** |
| dist_to_prev_high_pct | ✅ | ✅ | **已接入** |
| atr_14d | ✅ | ✅ | **已接入** |
| atr_pct | ✅ | ✅ | **已接入** |
| volatility_level | ✅ | ✅ | **已接入** |
| volatility_percentile | ✅ | ✅ | **已接入** |

**Phase 4是唯一完全落地的Phase**——daemon预计算+dim6消费者全部11个字段接入。

### 4.6 Phase 5 — dim5市场级SQL改预计算（P2）

**daemon `_precompute_market_stats()` 写入 `_market_stats_cache`**：

| 字段 | daemon写入 | dim5 BociasiQuadrantAnalyzer | bociasi_quadrant.py模块 | 状态 |
|------|:---------:|:---------------------------:|:----------------------:|------|
| ma20_ratio | ✅ | ❌ 独立SQL查询 | ✅ 读取 | **分裂** |
| turnover_percentile | ✅ | ❌ | ✅ | **分裂** |
| limit_ratio | ✅ | ❌ | ✅ | **分裂** |
| rsi_percentile | ✅ | ❌ | ✅ | **分裂** |
| erp_percentile | ✅ | ❌ | ✅ | **分裂** |
| margin_trend | ✅ | ❌ | ✅ | **分裂** |
| pe_percentile | ✅ | ❌ | ✅ | **分裂** |

**根因**：dim5使用自己的`BociasiQuadrantAnalyzer`本地类（line 481），而非import `bociasi_quadrant.py`模块。本地类独立执行6-7个SQL查询，完全忽略`_market_stats_cache`。

**`_market_stats_cache`是100%浪费的计算**——daemon每天执行6个市场级SQL查询写入cache，但无任何消费者读取。

**补充说明**：`bociasi_quadrant.py`模块（app/engine/framework/）确实读取`_market_stats_cache`并有完整fallback逻辑，但dim5的`BociasiQuadrantAnalyzer`是该模块的本地副本（line 481），不import该模块，因此cache从未被实际消费。修复方案：dim5改为import `bociasi_quadrant.py`模块，或在本地类中注入`_market_stats_cache`引用。

### 4.7 Phase 6 — dim7估值指标RAW迁移（P2）

| 字段 | daemon写入(valuation_ext) | dim7消费 | 状态 |
|------|:------------------------:|:--------:|------|
| pe_ttm | ✅ | ❌ dim7直接读ecm | **未接入** |
| pb | ✅ | ❌ | **未接入** |
| ps_ttm | ✅ | ❌ | **未接入** |
| total_mv | ✅ | ❌ | **未接入** |
| roe | ✅ | ❌ | **未接入** |
| roce | ✅ | ❌ | **未接入** |
| grossprofit_margin | ✅ | ❌ | **未接入** |

**说明**：dim7的`_compute_valuation()`需要历史百分位（PE/PB/PS近5年序列），预计算仅存储最新值。完全替代需扩展预计算为序列存储，工时较大。

### 4.8 Phase 7 — dim4成本价RAW迁移（P2）

| 字段 | daemon写入(cost_ext) | dim4消费 | 状态 |
|------|:-------------------:|:--------:|------|
| main_force_cost | ✅ | ❌ MainForceScorer内部计算 | **未接入** |
| margin_cost_price | ✅ | ❌ | **未接入** |

### 4.9 Phase 8 — dim3量指标RAW迁移（P3）

| 字段 | daemon写入(volume_ext) | dim3消费 | 状态 |
|------|:---------------------:|:--------:|------|
| vol_ma5 | ✅ | ❌ ~80处raw计算（EnhancedPatternDetector 60+ pattern方法 + VolumeStateAnalyzer 5+处 + StageDetector 2处） | **未接入** |
| vol_ma10 | ✅ | ❌ | **未接入** |
| vol_ma20 | ✅ | ❌ | **未接入** |
| volatility_20d | ✅ | ❌ | **未接入** |
| roc_20 | ✅ | ❌ | **未接入** |

**注意**：410号方案Phase 8预估"~31处raw计算"，代码审计实际发现**~80处**（EnhancedPatternDetector每个pattern方法各自内联`np.mean(closes[-N:])`，VolumeStateAnalyzer多处vol_ma，StageDetector的SMA）。工时需从0.3天上调至1.5-2.0天。

---

## 五、旧代码清理问题（fallback未清除）

**问题本质**：411号方案Phase 6的设计是"优先使用data_context预加载数据，回退独立查询"。这个"回退"设计违反了409号方案"dim1是唯一数据入口"的原则。fallback代码的存在意味着dim2-dim7仍然可以绕过dim1直接获取数据。

### 5.1 逐引擎残留旧代码核查

| 引擎 | 残留旧代码 | 位置 | 路径类型 | 说明 |
|------|-----------|------|:--------:|------|
| **dim2** | `closes.tail(20).mean()` / `closes.tail(60).mean()` | L3779, L3782 | **主路径** | `calc_support_resistance()`中MA20/MA60从raw closes计算，**无precomputed门控**，每次都执行 |
| **dim3** | `close.ewm(span=12).mean()` inline MACD | L4475-4479 | 回退 | 有precomputed-first门控（L4471-4473），raw EWM仅在预计算数据缺失时执行 |
| **dim4** | `self._get_dm().get_cached_moneyflow(ts_code)` | L479 | 回退 | `_dim_fund()`有precomputed-first（L464-475），raw查询仅在net_lg_5d缺失时执行 |
| **dim4** | `ChipIndicators.calculate_all_indicators()` | L702, L946, L5567 | **主路径** | `_dim_chip()`调用`_run_trading_phase_detector_v2()`从raw计算全部筹码指标，**无precomputed门控** |
| **dim4** | `MainForceScorer._calc_main_force_cost()` | L3268 | **主路径** | 主力成本价从raw计算，**无precomputed门控** |
| **dim4** | `MainForceScorer._calc_margin_cost_price()` | L3456 | **主路径** | 融资成本价从raw计算，**无precomputed门控** |
| **dim5** | `BociasiQuadrantAnalyzer` 6个SQL查询 | L654-777 | **主路径** | 本地类独立执行SQL查询（daily_cache/daily_basic_cache/indicator_other），**不读取_market_stats_cache** |
| **dim5** | `close.rolling(window=5).mean()` per stock | L892 | **主路径** | `SectorRotationModel`中MA5/MA20从raw计算，**无precomputed门控** |
| **dim6** | `calc_geometric(df)` / `_calc_volatility(df, tags)` | L1136, L1155 | 回退 | 已有precomputed-first门控（L1125, L1146），raw计算仅在tags缺失时执行 |
| **dim7** | `ecm.get_cached_income(ts_code)` | L716 | **主路径** | `_compute_valuation()`直接查ECM，**不从data_context获取** |
| **dim7** | `ecm.get_cached_balancesheet(ts_code)` | L720 | **主路径** | 同上 |
| **dim7** | `ecm.get_cached_cashflow(ts_code)` | L724 | **主路径** | 同上 |

### 5.2 问题分类

**主路径残留（6处）**——每次请求都会执行raw计算/查询，precomputed数据完全未被使用：

1. dim2 `calc_support_resistance()` MA20/MA60——应从indicator_ma读取
2. dim4 `calculate_all_indicators()` 筹码指标——应从chip_fund_ext读取
3. dim4 `_calc_main_force_cost()` 主力成本——应从cost_ext读取
4. dim4 `_calc_margin_cost_price()` 融资成本——应从cost_ext读取
5. dim5 `BociasiQuadrantAnalyzer` 6个SQL——应读取_market_stats_cache或删除本地类
6. dim7 `_compute_valuation()` income/balancesheet/cashflow——应从data_context获取

**回退路径残留（4处）**——有precomputed-first门控，但fallback仍保留：

1. dim3 inline MACD（L4475-4479）
2. dim4 `_dim_fund()` raw moneyflow查询（L479）
3. dim6 `calc_geometric()` / `_calc_volatility()`（L1136, L1155）
4. dim2 `calc_macd()` raw EWM（L529-533）

### 5.3 后果

1. **dim1门禁形同虚设**——dim1校验了5项数据，但dim7需要的income/balancesheet/cashflow完全绕过dim1
2. **数据一致性无法保证**——dim1加载的daily_df和dim7自行查询的daily_basic可能不是同一时间点
3. **STG补算闭环无法工作**——dim1发现数据缺失后无法推动补采，dim7会自行查询
4. **性能收益未兑现**——dim1集中加载本应消除dim2-dim7的重复IO，fallback使重复IO仍然发生
5. **降级路径依赖fallback**——411号方案§3.5定义的降级策略（dim1失败→dim2-dim7回退到独立查询）依赖fallback路径存活。**一刀切删除所有fallback会破坏降级能力**，需区分处理（见§5.4）

### 5.4 回退路径处理原则（411降级策略 vs 409唯一入口的平衡）

**核心矛盾**：409方案要求"dim2-dim7仅从dim1的data_context获取数据"（唯一入口原则），但411方案§3.5要求dim1失败时dim2-dim7回退到独立查询（降级策略）。两者天然冲突。

**解决原则**：区分"主路径"和"降级路径"，不同策略：

| 路径类型 | 定义 | 处理策略 |
|----------|------|----------|
| **主路径** | dim1正常返回data_context时的执行路径 | **必须统一到data_context/precomputed**，消除raw计算 |
| **降级路径** | dim1返回data_context=None时的回退路径 | **保留但设门控**：仅在data_context缺失时触发，正常运行时不执行 |

**具体处理方式**：

| 引擎残留 | 当前状态 | 主路径处理 | 降级路径处理 |
|----------|---------|-----------|-------------|
| dim2 `calc_support_resistance()` MA20/MA60 | 无precomputed门控，**每次都执行** | 加precomputed-first门控 | 保留raw计算作为fallback |
| dim3 inline MACD（L4475-4479） | 有precomputed-first门控 | **已正确** | **已正确** |
| dim4 `ChipIndicators.calculate_all_indicators()` | 无门控，**每次都执行** | 改为从tags读预计算 | 保留raw计算作为fallback |
| dim4 `_dim_fund()` moneyflow查询 | 有precomputed-first | **已正确** | **已正确** |
| dim4 `_calc_main_force_cost()` | 无门控，**每次都执行** | 改为从data_context读取 | 保留ECM查询作为fallback |
| dim4 `_calc_margin_cost_price()` | 无门控，**每次都执行** | 同上 | 同上 |
| dim5 `BociasiQuadrantAnalyzer` SQL | 无门控，独立SQL | 改为读`_market_stats_cache` | 保留SQL作为fallback |
| dim5 `SectorRotationModel` MA5/MA20 | 无门控，raw rolling | 改为从indicator_ma读取 | 保留raw作为fallback |
| dim6 `calc_geometric()`/`_calc_volatility()` | 有precomputed-first | **已正确** | **已正确** |
| dim7 income/balancesheet/cashflow | 无门控，ECM直查 | 改为从data_context获取 | 保留ECM查询作为fallback |
| dim2 `calc_macd()` raw EWM | 有precomputed-first | **已正确** | **已正确** |

**对8.1#2的修正**：原建议"删除所有ecm.get_cached_*独立查询"过于激进。应改为"主路径统一到data_context，降级路径保留fallback门控"。具体：
- dim7的ecm.get_cached_income/balancesheet/cashflow：主路径改为从data_context获取，降级路径保留ecm查询（当data_context=None时触发）
- dim5的BociasiQuadrantAnalyzer：主路径改为读_market_stats_cache，降级路径保留独立SQL
- dim4的_raw moneyflow查询：已有正确门控，无需修改

| 预计算组 | 字段数 | 原因 | 建议 |
|----------|--------|------|------|
| `_market_stats_cache` | 7字段 | dim5本地副本独立查询 | 接入dim5或删除cache |
| `valuation_ext` | 7字段 | dim7直接读ecm | 短期保留，长期扩展为序列存储 |
| `cost_ext` | 2字段 | 无消费者 | 接入dim4 |
| `volume_ext` | 5字段 | dim3从raw计算 | 接入dim3 |
| `emotion_ext` | 4字段 | dim5独立重算 | 接入dim5或删除 |
| `vp_health_ext` | 3字段(2个None) | 无消费者 | 补充计算或删除 |
| `signal_ext` | 3字段(2个None) | signal_analyzer从dims计算 | 补充decay_score计算或删除 |

---

## 六、关键Bug

| # | Bug | 影响 | 修复方案 |
|---|-----|------|----------|
| 1 | dim3读`volume_ratio`但daemon写`vol_price_ratio` | dim3始终拿到默认值1.0 | 统一键名为`volume_ratio` |
| 2 | dim6读`event_details`/`event_risk_factors`但daemon不写入 | 事件风险检测始终为空 | daemon补写`event_details`/`event_risk_factors`（从catalyst_event映射），或dim6改读`catalyst_event`/`catalyst_impact` |
| 3 | `signal_ext`的decay_score/resonance_score始终为None | 预计算占位但无实际值 | **需决定方向**：(A) daemon调用signal_analyzer的detect_decay/calc_resonance_score计算后写入（~20行）；(B) 废弃signal_ext组，删除相关预计算代码。建议选A |
| 4 | **dim5 `_market_stats_cache`列名不一致**：daemon `_precompute_market_stats()` L2137查询`RSI_14`（大写），但indicator_other表列名为`rsi14`（小写） | 当前因SQLite大小写不敏感不报错，但跨数据库迁移时会失败 | 统一为`rsi14`（与表定义一致） |
| 5 | **dim6 event_details/event_risk_factors键名不匹配**（同Bug #2的详细说明） | daemon写入的event组字段为`catalyst_event`/`catalyst_impact`/`event_composite_score`，dim6读取`event_details`/`event_risk_factors`，键名完全不同，事件风险检测永远为空 | dim6改为读取`catalyst_event`/`catalyst_impact`，或daemon补写映射字段 |

---

## 七、dim1数据提取保障评估

**结论：dim1当前实现严重偏离409号方案设计，需要大幅补强。**

### 7.1 409号方案定义的dim1职责

409号方案明确dim1是**SIG环节的唯一数据入口**，职责：

1. **数据提取**：集中预加载dim2-dim7所需的全部数据
2. **质量校验**：对预加载数据执行完整性检查
3. **STG联动**：校验不通过时触发STG补算闭环（398号方案）
4. **数据供应**：校验通过后通过data_context参数传递给dim2-dim7

dim2-dim7应当**仅从dim1的data_context获取数据**，不应有独立的数据加载路径。

### 7.2 409号定义的DataContext结构 vs 当前实现

| 409号定义的字段 | 当前dim1加载? | dim2-dim7从哪获取? |
|---------------|:------------:|-------------------|
| `daily` (daily_cache) | ✅ `daily_df` | data_context ✅ |
| `daily_basic` (daily_basic_cache) | ✅ `daily_basic_df` | data_context ✅ (dim7部分) / ecm直接查 ❌ |
| `moneyflow` (moneyflow_cache) | ✅ `moneyflow_df` | data_context ✅ (dim4部分) / ecm直接查 ❌ |
| `fina_indicator` (fina_indicator_cache) | ✅ `fina_df` | 未使用 ❌ |
| `income` (income_cache) | ❌ **未加载** | ecm.get_cached_income() 直接查 ❌ |
| `balancesheet` (balancesheet_cache) | ❌ **未加载** | ecm.get_cached_balancesheet() 直接查 ❌ |
| `cashflow` (cashflow_cache) | ❌ **未加载** | ecm.get_cached_cashflow() 直接查 ❌ |
| `margin` (margin_cache) | ✅ `margin_df` | 未使用 ❌ |
| `stk_holder` (stk_holder_cache) | ❌ **未加载** | ecm直接查 ❌ |
| `lhb` (lhb_cache) | ❌ **未加载** | ecm直接查 ❌ |
| `validation_result` | ❌ **无** | — |
| `completeness_score` | ❌ **无** | — |
| `missing_tables` | ❌ **无** | — |
| `stg_repair_count` | ❌ **无** | — |

### 7.3 核心问题

1. **dim1仅加载5/10项数据**——缺少income、balancesheet、cashflow、stk_holder、lhb
2. **dim2-dim7仍可绕过dim1**——dim7直接调ecm.get_cached_income/balancesheet/cashflow，dim4部分路径直接调ecm.get_cached_moneyflow
3. **无质量校验逻辑**——仅标记quality_issues，无完整性评分、日期对齐检查、非空校验
4. **无STG联动**——未实现`_stg_repair_loop()`，未对接398号`RecomputeScheduler`
5. **dim1的quality_issues仅为字符串列表**——无结构化校验结果（validation_result/completeness_score/missing_tables/stg_repair_count），下游无法程序化消费

### 7.3.1 dim1质量校验与STG联动实施要求

409号方案定义dim1应包含4个子模块：`_batch_extract()` → `_validate()` → `_stg_repair_loop()` → 返回data_context。当前实现仅有第1步（`_batch_extract`），后3步完全缺失。

**实施要求**（对应8.1#3 "~50行新增"的展开）：

| 子模块 | 职责 | 输入 | 输出 | 实现要点 |
|--------|------|------|------|----------|
| `_validate()` | 数据完整性校验 | data_context中的各DataFrame | validation_result (dict) | 日期对齐检查（所有表最近交易日一致）；非空检查（daily_df必须非空，其余可选）；完整性评分（completeness_score = 已加载数/应加载数）；missing_tables列表 |
| `_notify_missing_data()` | 数据缺失异步通知 | validation_result | sync_requests写入 | **398号RecomputeScheduler尚未实现**，通过DataManager.request_data()写sync_requests通知daemon异步补采。dim1为同步调用，无法等待daemon完成（30s周期），写入后立即返回degraded状态，下次请求时数据恢复 |
| 结果组装 | 返回结构化data_context | 全部结果 | data_context + status_quality | status_quality包含validation_result、completeness_score、missing_tables |

**工时修正**：8.1#3的"~50行新增、0.5天"严重低估。质量校验+异步通知实际需要：
- `_validate()` ~30行 + 单元测试 ~20行 = 0.3天
- `_notify_missing_data()`对接DataManager.request_data ~20行 + 单元测试 ~15行 = 0.2天
- 结果组装和降级路径 ~20行 = 0.1天
- **合计：0.6天（原估计0.5天基本合理，但不再包含STG同步闭环）**

**对接sync_requests的接口约定**：

```python
# dim1新增方法
def _validate(self, data_context: dict, ts_code: str) -> dict:
    """返回 {validation_result, completeness_score, missing_tables, quality_level}"""
    # 检查daily_df非空、日期对齐、已加载项数

def _notify_missing_data(self, ts_code: str, missing_tables: list):
    """通过DataManager.request_data()写入sync_requests，通知daemon异步补采"""
    # 映射missing_tables到task_type（income_df→full_daily, stk_holder→top10_holders等）
    # 写入后dim1返回degraded，daemon异步补采后下次请求恢复
```

### 7.4 应有的数据流（409号方案）

```
dim1 (唯一数据入口)
  ├── _batch_extract(ts_code) → 从ECM批量加载全部10项数据
  ├── _validate() → 完整性校验（日期对齐/非空/完整性评分）
  ├── _stg_repair_loop() → 不通过时触发STG补算（最多3轮）
  └── 返回 data_context (含全部10项DataFrame + 校验元信息)
      ↓
dim2-dim7 (仅从data_context读取，不再独立查ECM)
  ├── dim2: df = data_context['daily']
  ├── dim3: df = data_context['daily']
  ├── dim4: df = data_context['daily'], mf = data_context['moneyflow']
  ├── dim5: df = data_context['daily'], db = data_context['daily_basic']
  ├── dim6: df = data_context['daily']
  └── dim7: db = data_context['daily_basic'], inc = data_context['income'],
            bs = data_context['balancesheet'], cf = data_context['cashflow']
```

### 7.5 当前dim1数据流（实际实现）

```
dim1 (部分实现)
  ├── 加载5项: daily_df / moneyflow_df / daily_basic_df / margin_df / fina_df
  ├── 无质量校验
  ├── 无STG联动
  └── 返回 data_context (仅5项)
      ↓
dim2-dim7 (部分使用data_context，部分绕过)
  ├── dim2: df = data_context['daily_df'] ✅ / ecm.get_cached_daily() fallback
  ├── dim3: df = data_context['daily_df'] ✅ / ecm fallback
  ├── dim4: df = data_context['daily_df'] ✅ / ecm.get_cached_moneyflow() fallback
  ├── dim5: df = data_context['daily_df'] ✅ / ecm fallback
  ├── dim6: df = data_context['daily_df'] ✅ / ecm fallback
  └── dim7: db = data_context['daily_basic_df'] ✅ / ecm.get_cached_income() ❌ 直查
                                  ecm.get_cached_balancesheet() ❌ 直查
                                  ecm.get_cached_cashflow() ❌ 直查
```

---

## 八、消费者接入补充计划

### 8.1 优先级P0（架构修复 + 最大性能收益）

| # | 补充项 | 涉及文件 | 改动量 | 工时 | 说明 |
|---|--------|---------|--------|------|------|
| 1 | **dim1补强**：补加载income/balancesheet/cashflow/stk_holder/lhb到data_context | dim1_signal_engine.py | ~30行新增 | 0.3天 | 对齐409方案定义的10项数据 |
| 2 | **dim2-dim7主路径统一**：将主路径从raw计算/ECM直查改为读取data_context/precomputed，**保留降级fallback** | dim2-dim7各引擎 | ~20处替换 | 1.0天 | 详见§5.4处理原则，**不删除降级路径** |
| 3 | **dim1质量校验+异步通知**：实现_validate() + _notify_missing_data() + 结果组装 | dim1_signal_engine.py | ~70行新增+35行测试 | 0.6天 | 详见§7.3.1，398号RecomputeScheduler未实现，走sync_requests异步通知 |
| 4 | dim2 `calc_support_resistance()` MA20/MA60加precomputed-first门控 | dim2_structure_engine.py | ~10行修改 | 0.1天 | 加indicator_ma读取，保留raw fallback |

**P0合计工时：2.3天**

### 8.2 优先级P1

| # | 补充项 | 涉及文件 | 改动量 | 工时 | 说明 |
|---|--------|---------|--------|------|------|
| 5 | dim5 BociasiQuadrantAnalyzer改为读_market_stats_cache（**需先确定方案**：改import模块 or 本地类注入cache引用） | dim5_emotion_engine.py | ~7处替换 | 0.3天 | 建议选"改import模块"（复用已有bociasi_quadrant.py的fallback逻辑） |
| 6 | dim4 MainForceScorer读取cost_ext（主路径），保留ECM查询作为降级fallback | dim4_chip_fund_engine.py | ~2处替换 | 0.2天 | |
| 7 | dim4 `_dim_chip()`中ChipIndicators改为从tags读预计算（asr/concentration/profit_ratio/cyqkl），保留raw计算作为降级 | dim4_chip_fund_engine.py | ~15处替换 | 0.5天 | 涉及_run_trading_phase_detector_v2内部改造 |
| 8 | dim5 SectorRotationModel MA5/MA20改为从indicator_ma读取 | dim5_emotion_engine.py | ~2处替换 | 0.1天 | |

**P1合计工时：1.1天**

### 8.3 优先级P2

| # | 补充项 | 涉及文件 | 改动量 | 工时 | 说明 |
|---|--------|---------|--------|------|------|
| 9 | dim7读取valuation_ext（当前值部分），保留ecm直查作为降级fallback | dim7_valuation_engine.py | ~7处替换 | 0.3天 | 仅接入最新值；历史百分位序列暂不迁移 |
| 10 | signal_ext补充decay_score/resonance_score计算（**需先决定：补全 or 废弃**） | data_daemon.py | ~20行新增 | 0.3天 | 建议：daemon调用signal_analyzer计算decay_score/resonance_score后写入；如废弃则删除signal_ext组 |
| 11 | dim3 EnhancedPatternDetector中MA5/10/20改为从indicator_ma读取（**改动量上调**） | dim3_vp_engine.py | **~80处替换** | **1.5-2.0天** | 60+ pattern方法各自内联np.mean()，VolumeStateAnalyzer 5+处vol_ma，StageDetector 2处SMA |
| 12 | dim3 vol_ma5/10/20改为从indicator_ma/volume_ext读取 | dim3_vp_engine.py | ~5处替换 | 0.3天 | VolumeStateAnalyzer/VPStateMachine |

**P2合计工时：2.4-3.0天**

### 8.4 可选清理

| # | 清理项 | 说明 | 工时 |
|---|--------|------|------|
| 13 | 删除signal_decay_detector.py | 已不再导入，与signal_analyzer重复（代码确认零引用） | 0.1天 |
| 14 | 删除emotion_ext/vp_health_ext预计算 | 无消费者，减少daemon CPU | 0.2天 |
| 15 | dim1 fina_df迁移后margin_df/fina_df确认使用 | 当前dim1加载但dim2-dim7未消费，确认后可选精简 | 0.1天 |

### 8.5 工时汇总

| 优先级 | 工时 | 占比 |
|--------|------|------|
| P0 | 2.0天 | 31% |
| P1 | 1.1天 | 17% |
| P2 | 2.4-3.0天 | 37-46% |
| 可选 | 0.4天 | 6% |
| **合计** | **5.9-6.5天** | |

**与411号方案工时对比**：411号方案Phase 5-13合计~4.5天，本方案补充~6.2天。差异原因：411工时低估（dim3量指标仅0.3天但实际130处改动），且未包含dim1质量校验的详细设计工时。

---

## 九、预计算管道验证

### 9.1 写入端验证

```bash
# 验证pre_feat_cache数据存在
cd backend && PYTHONPATH=. .venv/bin/python -c "
from app.data.enhanced_cache_manager import get_ecm_instance
ecm = get_ecm_instance()
# 检查最近一只股票的pre_feat_cache
import sqlite3
conn = sqlite3.connect('data/compute_cache.db')
row = conn.execute('SELECT ts_code, features FROM pre_feat_cache ORDER BY cached_at DESC LIMIT 1').fetchone()
if row:
    import json
    feat = json.loads(row[1])
    print(f'股票: {row[0]}')
    print(f'预计算组: {list(feat.keys())}')
    for g, d in feat.items():
        if isinstance(d, dict):
            print(f'  {g}: {len(d)} 字段')
"
```

### 9.2 扁平化验证

```bash
# 验证flatten后tags包含预计算字段
cd backend && PYTHONPATH=. .venv/bin/python -c "
from app.opportunity_atlas.status_engine import StatusEngine
tags = StatusEngine._load_tags('000001.SZ')
print(f'tags总字段数: {len(tags)}')
# 检查关键预计算字段
for key in ['support_price', 'atr_14d', 'ssrp', 'net_lg_5d', 'vol_ma5']:
    print(f'  {key}: {\"存在\" if key in tags else \"缺失\"} (值={tags.get(key, \"N/A\")})')
"
```

### 9.3 消费者接入验证

```bash
# 验证dim引擎读取预计算值
cd backend && PYTHONPATH=. .venv/bin/python -c "
from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine
import inspect
source = inspect.getsource(Dim6RiskEngine.evaluate)
assert '_geo_precomputed' in source, 'dim6未接入risk_ext'
assert '_vol_precomputed' in source, 'dim6未接入波动率预计算'
print('dim6 risk_ext接入验证通过')

from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_macd
import inspect
sig = inspect.signature(calc_macd)
assert 'precomputed' in sig.parameters, 'dim2 MACD未支持预计算'
print('dim2 MACD预计算接入验证通过')
"
```

---

## 十、风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| **dim1未按409号设计实现，dim2-dim7绕过dim1直接查ECM** | **高** | **高** | 优先补强dim1（8.1#1-3），主路径统一到data_context，降级路径保留fallback（§5.4） |
| **一刀切删除fallback导致降级路径断裂** | 中 | 高 | 严格按§5.4区分主路径/降级路径，不删除降级fallback |
| **dim1质量校验+STG联动实施工时超出预估** | 中 | 中 | 8.1#3工时已上调至0.9天，建议实施时预留buffer |
| MA改读indicator_ma后与raw计算有微小差异 | 低 | 低 | 预计算表精度float64，差异在1e-10级别 |
| dim4筹码指标迁移影响PhaseDetectionEngine | 中 | 中 | 渐进式迁移，保留raw fallback |
| dim5市场级SQL改为cache后数据时效性 | 低 | 低 | daemon日终预计算，与当前SQL查询时效一致 |
| **dim3 EnhancedPatternDetector改动量巨大（80+处）引入回归** | **高** | 中 | 分批替换（先volume_ext，再MA5/10/20），每批独立测试 |
| **signal_ext方向未定影响daemon和dim两侧改动范围** | 中 | 低 | 实施前明确补全or废弃（§六Bug #3） |
| 大规模替换引入回归 | 中 | 中 | 每个Phase独立测试+make check |

---

## 十一、dim4交叉改动排序方案

dim4是改动最密集的引擎，涉及411方案的Phase 5（MA改读）、Phase 6（data_context消费）、Phase 7（筹码RAW迁移）、Phase 12（成本价RAW迁移）共4个Phase。411号方案§3.4仅规定了"Phase 5先、Phase 6后"的串行顺序，未覆盖Phase 7和Phase 12的排序。

### 11.1 dim4改动矩阵

| Phase | 改动位置 | 改动内容 | 涉及文件区域 |
|-------|---------|---------|-------------|
| Phase 5 | StageDetector MA60 | 改读indicator_ma | dim4内部StageDetector类 |
| Phase 5 | PhaseDetectionEngine多处MA | 改读indicator_ma | dim4内部PhaseDetectionEngine类 |
| Phase 5 | ChipIndicators RSI | 已完成（改读indicator_other） | dim4 L137-151 |
| Phase 6 | evaluate()入口 | data_context参数注入 | dim4 evaluate() |
| Phase 7 | _dim_chip() | asr/concentration/profit_ratio/cyqkl改读tags预计算 | dim4 _dim_chip() L687-703 |
| Phase 12 | MainForceScorer | 主力/融资成本价改读cost_ext | dim4 L3268, L3456 |

### 11.2 推荐执行顺序

```
Phase 5 (MA改读)  →  Phase 7 (筹码RAW迁移)  →  Phase 12 (成本价RAW)  →  Phase 6 (data_context消费)
```

**理由**：
1. **Phase 5先**：MA/RSI改读预计算表是纯数据源替换，不改变dim4接口签名，风险最低
2. **Phase 7次之**：筹码指标改读tags需要修改_dim_chip()内部逻辑，与Phase 5无交叉
3. **Phase 12第三**：成本价改读cost_ext独立于前两者
4. **Phase 6最后**：data_context消费改造需要dim4所有数据读取方式确定后才稳定，避免反复修改evaluate()签名

### 11.3 每Phase间的验证检查点

| 检查点 | 验证内容 | 通过标准 |
|--------|---------|---------|
| Phase 5→7之间 | dim4筹码评分输出与改读前一致 | 单元测试对比输出差异<0.01 |
| Phase 7→12之间 | dim4主力评分输出与改读前一致 | 单元测试对比输出差异<0.01 |
| Phase 12→6之间 | dim4 evaluate()接受data_context正确传递 | 6个数据源全部从data_context获取 |

---

## 十二、Phase 14验证清单补充

411号方案§Phase 14定义了10项验证。本轮审计发现以下测试盲区需补充：

### 12.1 测试覆盖盲区

| # | 盲区 | 当前状态 | 补充测试 |
|---|------|---------|---------|
| 1 | dim4 chip_indicators预计算读取 | test_411无覆盖 | 新增：mock tags含asr/concentration/profit_ratio/cyqkl，验证_dim_chip()读取而非raw计算 |
| 2 | dim5 BociasiQuadrantAnalyzer与_market_stats_cache一致性 | 无覆盖 | 新增：验证本地类输出与模块输出一致（或改import后等价） |
| 3 | dim7 income/balancesheet/cashflow数据路径 | 无覆盖 | 新增：mock data_context含financial DataFrames，验证dim7使用data_context而非ecm直查 |
| 4 | dim1缺少数据时的降级路径 | 无覆盖 | 新增：data_context=None时验证dim2-dim7回退路径+dim_adapter默认值+输出标注degraded |
| 5 | dim1 _validate()完整性校验 | 无覆盖 | 新增：模拟缺失1/3/5项数据，验证completeness_score和quality_level |
| 6 | dim1 _stg_repair_loop() | 无覆盖 | 新增：模拟补算请求→验证sync_requests写入→验证修复后重新加载 |
| 7 | signal_confirm新路径一致性 | 无覆盖 | 新增：对比classify_attribute()结果与旧tags.right_side_confirm路径输出 |
| 8 | dim3 EnhancedPatternDetector MA改读后pattern一致性 | 无覆盖 | 新增：对比改读前后60+ pattern输出（最大改动风险点） |

### 12.2 建议测试增量

| 测试文件 | 新增测试数 | 说明 |
|----------|:----------:|------|
| test_411_pipeline.py | +12 | 补充Phase 7/11/12/13的消费者测试 + 降级路径测试 |
| test_dim1_gate.py（新建） | +8 | dim1质量校验+STG联动专项测试 |
| test_dim3_patterns.py（新建） | +5 | EnhancedPatternDetector MA改读后pattern一致性 |
| **合计** | **+25** | |

---

## 附录A：本轮已修复问题清单

### A.1 修改文件清单（9个源码文件 + 1个测试文件）

| 文件 | 修复内容 | 关联Phase |
|------|----------|-----------|
| `dim8_summary_engine.py` | 7处`fund_chip`→`chip_fund`键名对齐 + `_extract_dim_audit_confidence`递归bug(`dim_results.get(dim_results,{})`→`dim_results.get(dim_name,{})`) | Phase 4 |
| `dim7_valuation_engine.py` | `evaluate()`传递data_context到`_compute_valuation()`；`_compute_valuation()`新增data_context参数，优先使用`daily_basic_df` | Phase 6 |
| `status_engine.py` | `dims_for_signal`构造改为显式key查找（`_META_KEYS`排除overall_light等meta字段），替代脆弱的`list(judg.values())[0]` | Phase 4 |
| `dim4_chip_fund_engine.py` | `_try_read_precomputed_rsi()`改为直接接收ts_code参数；`calculate_all_indicators()`新增ts_code参数；4处调用者更新传入ts_code；`_dim_fund()`新增extra_tags参数读取预计算5日资金聚合 | Phase 5, 8 |
| `dim2_structure_engine.py` | `calc_macd()`新增precomputed参数+模块级`_MACD_PRECOMPUTED_CACHE`+`_load_precomputed_macd()`辅助函数；DivergenceDetector新增`_precomputed`属性；6处calc_macd调用更新；`analyze()`中detect()调用传入precomputed | Phase 5 |
| `dim3_vp_engine.py` | `calc_macd()`新增precomputed参数+`_load_precomputed_macd()`辅助函数；`_detect_divergence_enhanced()`MACD改读预计算；背离检测inline MACD改读预计算 | Phase 5 |
| `dim6_risk_engine.py` | `evaluate()`中geo/vol读取改为优先从tags读取预计算risk_ext，回退raw计算 | Phase 9 |
| `dim_adapter.py` | 移除try块内`_SIGNAL_CODE_DIRECTION`局部变量遮蔽，使用模块级定义，修复UnboundLocalError | 修复 |
| `data_daemon.py` | `signal_decay_detector`→`signal_analyzer`导入去重；`calculate_all_indicators`调用传入ts_code | 修复 |
| `test_411_pipeline.py` | 新建411全流程集成测试（30个测试） | Phase 14 |

### A.2 测试结果

| 测试文件 | 结果 |
|----------|------|
| `test_411_pipeline.py`（新建） | **30/30 PASSED** |
| `test_390_integration.py` | **5/5 PASSED** |
| `test_api_health.py` | **4/4 PASSED** |
| 全部9个修改文件编译 | **ALL OK** |

---

**方案编制日期**：2026-09-07
**v2.0修订日期**：2026-09-07
**编制依据**：410号方案8个Phase逐项核对 + 411号方案14个Phase实施核查 + 代码级审计
**审计覆盖**：data_daemon.py `_precompute_raw_features()` 全量代码 + dim2-dim7全部消费者 + status_engine扁平化管道 + dim1_signal_engine.py + signal_analyzer.py + 3个预计算表定义
**本轮修复**：9个源码文件 + 1个测试文件，30个测试全部通过
**v2.0修订内容**：
- §5新增§5.4回退路径处理原则（区分主路径/降级路径，不一刀切删除fallback）
- §7新增§7.3.1 dim1质量校验与STG联动实施要求（含398号接口约定）
- §8全面重构：修正工时估算（dim3从0.3天→1.5-2.0天，dim1质量校验从0.5天→0.9天）、明确降级保留策略、新增dim4筹码改造、新增工时汇总
- §4.9修正dim3 raw计算数量（31处→80处）
- §六新增Bug #4（dim5列名不一致）和Bug #5（dim6键名不匹配详细说明）
- §十风险评估新增3项风险
- 新增§十一dim4交叉改动排序方案（Phase 5→7→12→6顺序）
- 新增§十二Phase 14验证清单补充（8项盲区+25个新增测试）
- 新增§十三实施计划（5条工作流、18个任务、代码级操作指南）

**v2.1修订内容**（基于架构专家+代码工程师双视角审核）：
- **A1修复**：明确DataManager缺少get_cached_cashflow代理（ECM有但__init__.py未暴露），新增前置条件要求先在data/__init__.py中补建代理方法
- **A3重写**：RecomputeScheduler确认不存在（398号方案待实施），从"同步3轮闭环"改为"异步通知模式"（dm.request_data()写sync_requests→daemon异步补采→下次请求恢复），明确同步等待不可行（evaluate()是同步调用链，阻塞等daemon会导致API超时）
- **D2重写**：EnhancedPatternDetector确认无__init__/self._ts_code/self._dm，原_get_ma方案不可行。改为detect_all()入口预计算MA dict方案（14个distinct MA值→85处np.mean消除），含完整代码示例和向后兼容设计
- **E3重写**：signal_ext确认时序不可行（detect_decay依赖lifecycle, calc_resonance_score依赖dims，daemon预计算阶段两者均不存在），从"补全计算"改为"废弃signal_ext组"
- **dim3统计修正**：从80处上调至130处（EnhancedPatternDetector 85 + VolumeStateAnalyzer 9 + StageDetector 36），D2工时从1.5天上调至2.3天，总工作流D从2.0天上调至2.8天
- **B4补充**：新增_fina_health() L605-623的5处ECM调用改造代码示例
- **依赖图修正**：新增A1→B4显式依赖标注（dim7需dim1先加载income等）
- **总工时修正**：从5.7天上调至6.3天（可压缩至5.0天）

**v3.0修订内容**（基于架构合规性审核，修正8个任务的架构违规）：
- **§13.0重写**：架构图和依赖关系——dim1为唯一数据入口，A完成后B/C/D并行
- **§13.1 A1扩展**：从"补加载5项ECM表"扩展为"加载3类20+项"（ECM表+indicator预计算表+pre_feat_cache ext组）
- **§13.2 B1/B2/B3重写**：从"dim引擎内部调用DataManager读indicator_ma"改为"dim1加载→data_context传递→dim引擎从data_context读取"
- **§13.3 C1/C2/C3重写**：从"dim4内部调用DataManager/读extra_tags"改为"dim1加载→data_context传递→dim4从data_context读取"
- **§13.4 D1/D2重写**：从"dim3内部调用DataManager"改为"dim1加载→data_context传递→dim3从data_context读取"
- **§13.7/§13.8更新**：问题对照表和时间线同步修正
- **总工时**：~6.8天（A先执行2.0天，B/C/D并行1.5天）

---

## 十三、实施计划

### 13.0 总体架构（v3.0 修订）

**核心原则**：dim1是唯一数据入口。所有原料数据（ECM表 + indicator预计算表 + pre_feat_cache ext组）由dim1统一加载到data_context，dim2-dim7仅从data_context读取，**禁止dim引擎内部直接调用DataManager/ECM/读取daemon内存**。

```
采集层(COL) → 存储层(STG) → 加工层(RAW) → dim1(唯一入口) → data_context → dim2-dim7
                                  ↓                    ↓
                           daemon预计算          统一加载+校验+分发
                                  ↓                    ↓
                           indicator_ma/macd/other   全部原料数据
                           pre_feat_cache(ext组)    (20+项)
```

```
工作流A（dim1全量数据加载）── 2.0天 ──┐
                                      ├──→ 工作流C（dim4改造）── 1.0天 ──┐
工作流B（dim2/dim5/dim7改造）── 1.5天 ─┤                                ├──→ 工作流F（回归验证）0.5天
                                      ├──→ 工作流D（dim3改造）── 1.5天 ──┤
                                      │                                │
                                      └── 工作流E（Bug修复）── 0.3天 ──┘
```

**总工时**：~6.8天（B/C/D在A完成后并行）

**依赖关系**：
- **A完成 → B/C/D开始**：所有dim引擎的data_context消费依赖dim1先加载全部数据
- B/C/D可并行：dim2/dim5/dim7、dim4、dim3各自独立
- **E可随时穿插**：Bug修复不阻塞主流程
- **F最后**：全量回归验证

### 13.1 工作流A — dim1全量数据加载（2.0天）

> **核心变更（v3.0）**：dim1不仅加载10项ECM表，还要加载indicator预计算表和pre_feat_cache中的ext组。
> 这是B/C/D工作流的前提——**所有dim引擎的data_context消费依赖dim1先加载全部数据**。

#### A1：dim1加载全部原料数据（1.0天）

**文件**：`backend/app/opportunity_atlas/dimensions/dim1_signal_engine.py`

**前置条件**：DataManager需新增`get_cached_cashflow`代理。

**dim1扩展为3类20+项数据加载**：

| 类别 | 数据项 | 加载方式 | 消费者 |
|------|--------|---------|--------|
| **ECM原料表（10项）** | daily_df | dm.get_cached_daily_data() | dim2/3/4/5/6 |
| | moneyflow_df | dm.get_cached_moneyflow() | dim4 |
| | daily_basic_df | dm.get_cached_daily_basic() | dim5/7 |
| | margin_df | dm.get_cached_margin() | dim5 |
| | fina_df | dm.get_cached_fina_indicator() | dim7 |
| | income_df | dm.get_cached_income() | dim7 |
| | balancesheet_df | dm.get_cached_balancesheet() | dim7 |
| | cashflow_df | dm.get_cached_cashflow() | dim7 |
| | stk_holder_df | dm.get_cached_stk_holder() | 未来扩展 |
| | lhb_df | dm.get_cached_lhb() | 未来扩展 |
| **indicator预计算表（3项）** | indicator_ma_df | dm.get_cached_indicators() → 提取ma5/10/20/30/60/vol_ma5/10 | dim2/3/4/5 |
| | indicator_macd_df | dm.get_cached_indicators() → 提取macd_dif/dea/hist | dim2/3 |
| | indicator_other_df | dm.get_cached_indicators() → 提取rsi14/kdj/boll | dim4/5 |
| **pre_feat_cache ext组（8项）** | chip_fund_ext | dm.cache.get_pre_feat() → 提取asr/concentration/profit_ratio/cyqkl | dim4 |
| | cost_ext | dm.cache.get_pre_feat() → 提取main_force_cost/margin_cost_price | dim4 |
| | volume_ext | dm.cache.get_pre_feat() → 提取vol_ma5/10/20/volatility_20d/roc_20 | dim3 |
| | risk_ext | dm.cache.get_pre_feat() → 提取support/resistance/risk_reward等 | dim6 |
| | fund_5d_ext | dm.cache.get_pre_feat() → 提取net_lg_5d等 | dim4 |
| | emotion_ext | dm.cache.get_pre_feat() → 提取emotion_temperature等 | dim5 |
| | structure_ext | dm.cache.get_pre_feat() → 提取support_price/resistance_price | dim2 |
| | signal_ext | dm.cache.get_pre_feat() → 提取signal_attribute（废弃decay/resonance） | dim8 |

**关键约束**：
- indicator预计算表：通过`dm.get_cached_indicators(ts_code)`一次性读取（返回合并DataFrame），按列名拆分
- pre_feat_cache ext组：通过`dm.cache.get_pre_feat(ts_code)`读取嵌套JSON，按组名提取
- 所有数据写入`loaded_data` dict，通过`data_context`返回

**验收**：dim1返回data_context包含20+项数据，单元测试验证每类可达。

#### A2：dim1质量校验（0.4天）

新增`_validate(data_context, ts_code)`方法：日期对齐 + completeness_score + missing_tables + quality_level。

#### A3：dim1异步通知（0.4天）

新增`_notify_missing_data(ts_code, missing_tables)`：通过dm.request_data()写sync_requests通知daemon。

#### A4：测试（0.2天）

新建test_dim1_gate.py（8个用例）。

#### A2：dim1实现_validate()质量校验（0.4天）

**文件**：`backend/app/opportunity_atlas/dimensions/dim1_signal_engine.py`

新增`_validate(data_context, ts_code)`方法：

```python
def _validate(self, data_context: dict, ts_code: str) -> dict:
    """数据完整性校验"""
    required = ['daily_df']
    optional = ['moneyflow_df', 'daily_basic_df', 'margin_df', 'fina_df',
                'income_df', 'balancesheet_df', 'cashflow_df',
                'stk_holder_df', 'lhb_df']
    loaded_keys = [k for k, v in data_context.items()
                   if v is not None and not (isinstance(v, pd.DataFrame) and v.empty)]
    missing = [k for k in required + optional
               if k not in loaded_keys
               or (isinstance(data_context.get(k), pd.DataFrame) and data_context[k].empty)]

    # 日期对齐检查
    date_alignment_ok = True
    if 'daily_df' in loaded_keys and not data_context['daily_df'].empty:
        latest_date = data_context['daily_df']['trade_date'].max()
        for key in ['moneyflow_df', 'daily_basic_df']:
            if key in loaded_keys and not data_context[key].empty:
                if data_context[key]['trade_date'].max() != latest_date:
                    date_alignment_ok = False

    completeness_score = len(loaded_keys) / (len(required) + len(optional))
    quality_level = 'good' if not missing and date_alignment_ok else 'degraded'
    if not all(k in loaded_keys for k in required):
        quality_level = 'failed'

    return {
        'validation_result': {'date_alignment_ok': date_alignment_ok,
                              'loaded_count': len(loaded_keys), 'missing_count': len(missing)},
        'completeness_score': completeness_score,
        'missing_tables': missing,
        'quality_level': quality_level,
    }
```

**调用位置**：evaluate()中data_context组装后调用`_validate()`，合入status_quality。

#### A3：dim1数据缺失异步通知（0.4天）

**文件**：`backend/app/opportunity_atlas/dimensions/dim1_signal_engine.py`

**架构说明**：398号方案的RecomputeScheduler**尚未实现**，当前代码库仅有sync_requests队列机制（`enhanced_cache_manager.py:2540`的`request_data()`方法 + `DataManager.__init__.py:1826`的代理）。dim1的evaluate()是同步调用，而daemon消费sync_requests是30秒周期的异步行为——**无法在单次请求中等待daemon完成补采**。

因此_stg_repair_loop设计为**异步通知模式**（非同步3轮闭环）：

```python
def _notify_missing_data(self, ts_code: str, missing_tables: list):
    """数据缺失时通知daemon异步补采（异步闭环，非同步等待）"""
    if not missing_tables:
        return
    try:
        from app.data import DataManager
        dm = DataManager()
        # 映射missing_tables到task_type
        task_map = {
            'income_df': 'full_daily', 'balancesheet_df': 'full_daily',
            'cashflow_df': 'full_daily', 'stk_holder_df': 'top10_holders',
            'lhb_df': 'lhb',
        }
        for table in missing_tables:
            task_type = task_map.get(table, 'full_daily')
            dm.request_data(task_type=task_type, ts_code=ts_code)
            logger.info(f"dim1通知daemon补采: {task_type} {ts_code}")
    except Exception as e:
        logger.warning(f"dim1通知daemon失败: {e}")
```

**闭环机制**：
1. dim1发现数据缺失 → 写sync_requests通知daemon → 立即返回degraded状态
2. daemon 30s主循环消费sync_requests → 执行补采 → 数据写入ECM
3. 下次请求时dim1重新加载 → 数据已就绪 → quality_level恢复为good

**不实现同步3轮等待**：因为dim1的evaluate()是同步调用链的一部分，阻塞等待daemon（30s周期）会导致API请求超时。

#### A4：dim1降级路径测试（0.3天）

新建`test_dim1_gate.py`（8个用例）：

| 用例 | 验证内容 |
|------|---------|
| 1 | data_context=None时dim2-dim7回退到ecm查询 |
| 2 | dim_adapter在data_context=None时用默认值(direction=0, strength=0.5, reliability=0.5) |
| 3 | 输出标注data_quality=degraded |
| 4 | _validate()缺失daily_df → quality_level='failed' |
| 5 | _validate()缺失income_df → quality_level='degraded' |
| 6 | _validate()全量加载 → quality_level='good' |
| 7 | _notify_missing_data()正确调用dm.request_data() |
| 8 | 日期不对齐时date_alignment_ok=False |

### 13.2 工作流B — dim2/dim5/dim7改造（1.5天）

> **v3.0修正**：所有dim引擎从data_context读取数据，不在引擎内部直接调用DataManager/ECM。
> 前提：工作流A完成（dim1已加载全部数据到data_context）。

#### B1：dim2从data_context读取MA（0.3天）

**文件**：`dim2_structure_engine.py`

**当前问题**：calc_support_resistance()内部自行raw计算MA20/MA60，未使用data_context中的indicator_ma。

**改造方案**：
- calc_support_resistance()新增`indicator_ma_df`参数（由dim2 evaluate从data_context传入）
- MA20/MA60优先从indicator_ma_df读取，保留raw fallback
- **不在dim2内部调用DataManager**——数据由dim1通过data_context提供

```python
def calc_support_resistance(df=None, indicator_ma_df=None) -> dict:
    ma20 = None
    if indicator_ma_df is not None and not indicator_ma_df.empty and 'ma20' in indicator_ma_df.columns:
        ma20 = float(indicator_ma_df['ma20'].iloc[-1])
    if ma20 is None:
        ma20 = float(closes.tail(20).mean()) if len(df) >= 20 else None
    # ... 同理ma60
```

dim2 evaluate()中从data_context提取indicator_ma_df并传入。

#### B2：dim5 BociasiQuadrantAnalyzer从data_context读取market_stats（0.5天）

**文件**：`dim5_emotion_engine.py`

**当前问题**：dim5本地BociasiQuadrantAnalyzer类独立执行6个SQL查询，完全忽略_market_stats_cache。

**改造方案**：
- dim1加载market_stats到data_context（如`data_context['market_stats']`）
- dim5的BociasiQuadrantAnalyzer改为接收market_stats参数（非直接读daemon内存）
- 保留独立SQL作为降级fallback

```python
# dim5 evaluate()中：
market_stats = data_context.get('market_stats') if data_context else None
analyzer = BociasiQuadrantAnalyzer(ecm=ecm, market_stats=market_stats)
```

BociasiQuadrantAnalyzer的_analyze方法优先使用传入的market_stats，fallback到SQL查询。

#### B3：dim5 SectorRotationModel从data_context读取MA（0.2天）

**文件**：`dim5_emotion_engine.py`

**改造方案**：dim5 evaluate()从data_context提取indicator_ma_df，传递给SectorRotationModel。

```python
# dim5 evaluate()中：
indicator_ma = data_context.get('indicator_ma_df') if data_context else None
# 传递给SectorRotationModel.compute_all_heat()
```

SectorRotationModel.compute_all_heat()接收indicator_ma参数，MA5/MA20优先从预计算读取，保留raw rolling fallback。

#### B4：dim7从data_context读取财务数据（0.3天）

**文件**：`dim7_valuation_engine.py`

**已实现**（B4在之前已正确改造）。dim7的_compute_valuation和_fina_health已从data_context读取income/balancesheet/cashflow，保留ecm fallback。

**验证**：确认改造正确，无遗漏。

#### B5：回归测试（0.2天）

新建test_main_path_unified.py，验证dim2/dim5/dim7从data_context读取数据。

### 13.3 工作流C — dim4改造（1.0天）

> **v3.0修正**：dim4所有数据从data_context读取（dim1加载chip_fund_ext/cost_ext/indicator_ma），不在dim4内部直接调用DataManager。

#### C1：dim4从data_context读取chip_fund_ext（0.4天）

**文件**：`dim4_chip_fund_engine.py`

**当前问题**：_run_trading_phase_detector_v2()调用ChipIndicators.calculate_all_indicators()从raw计算筹码指标，忽略预计算值。

**改造方案**：
- dim1已加载chip_fund_ext到data_context（asr/concentration/profit_ratio/cyqkl）
- dim4 evaluate()从data_context提取chip_fund_ext
- _run_trading_phase_detector_v2()接收chip_fund_ext参数，用预计算值覆盖raw计算结果
- 保留raw计算作为降级fallback

#### C2：dim4从data_context读取cost_ext（0.2天）

**文件**：`dim4_chip_fund_engine.py`

**改造方案**：
- dim1已加载cost_ext到data_context（main_force_cost/margin_cost_price）
- dim4 evaluate()从data_context提取cost_ext
- identify_phase()使用预计算成本价增强阶段判断
- 保留raw计算作为降级fallback

#### C3：dim4从data_context读取indicator_ma（0.2天）

**文件**：`dim4_chip_fund_engine.py`

**改造方案**：
- dim1已加载indicator_ma_df到data_context
- PhaseDetectionEngine._price_position_analysis()和StageDetector.detect()从data_context读取MA值
- **不在dim4内部调用DataManager**——删除C1阶段错误添加的_load_ma()方法

#### C4：dim4 data_context消费（0.2天）

确保dim4 evaluate()从data_context获取全部所需数据（daily_df/moneyflow_df/chip_fund_ext/cost_ext/indicator_ma_df）。

### 13.4 工作流D — dim3改造（1.5天）

> **v3.0修正**：dim3所有数据从data_context读取（dim1加载volume_ext/indicator_ma），不在dim3内部直接调用DataManager。

#### D1：dim3从data_context读取volume_ext（0.3天）

**文件**：`dim3_vp_engine.py`

**改造方案**：
- dim1已加载volume_ext到data_context（vol_ma5/10/20/volatility_20d/roc_20）
- VolumeStateAnalyzer的vol_ma5/10/20优先从data_context读取，保留raw rolling fallback

#### D2：dim3 EnhancedPatternDetector MA替换（1.0天）

**文件**：`dim3_vp_engine.py`

**改造方案**：
- dim1已加载indicator_ma_df到data_context
- EnhancedPatternDetector.detect_all()接收precomputed_ma dict参数（由dim3 evaluate从data_context构建）
- ~85处np.mean(closes[-N:])改为从precomputed_ma字典读取
- StageDetector的MA计算同理

```python
# dim3 evaluate()中：
indicator_ma = data_context.get('indicator_ma_df') if data_context else None
precomputed_ma = {}
if indicator_ma is not None and not indicator_ma.empty:
    for col in ['ma5','ma10','ma20','ma30','ma60']:
        if col in indicator_ma.columns:
            precomputed_ma[col] = float(indicator_ma[col].iloc[-1])
# 传递给EnhancedPatternDetector.detect_all(..., precomputed_ma=precomputed_ma)
```

#### D3：pattern一致性测试（0.2天）

新建test_dim3_patterns.py，验证precomputed MA与raw MA输出差异<1e-10。

### 13.5 工作流E — Bug修复与清理（0.3天）

| 任务 | Bug | 文件 | 操作 | 工时 |
|------|-----|------|------|------|
| E1 | #1 dim3 volume_ratio | daemon/dim3 | 统一键名为`volume_ratio` | 0.05天 |
| E2 | #2+#5 dim6 event键名 | dim6_risk_engine.py | 改读`catalyst_event`/`catalyst_impact`/`event_composite_score` | 0.1天 |
| E3 | #3 signal_ext空占位 | data_daemon.py | **废弃signal_ext组**（时序不可行） | 0.05天 |
| E4 | #4 dim5 RSI列名 | data_daemon.py L2137 | `RSI_14` → `rsi14` | 0.05天 |
| E5 | 清理 | signal_decay_detector.py | 零引用，直接删除 | 0.05天 |

### 13.6 工作流F — 全量回归验证（0.5天）

#### F1：补充测试（0.3天）

| 测试文件 | 新增数 | 覆盖 |
|----------|:------:|------|
| test_dim1_gate.py（新建） | 8 | dim1验证+降级 |
| test_main_path_unified.py（新建） | 12 | dim2/5/7 data_context读取 |
| test_dim3_patterns.py（新建） | 5 | dim3 pattern一致性 |
| test_411_pipeline.py（补充） | +6 | dim4 chip预计算+signal_confirm |
| **合计** | **+31** | |

#### F2：端到端验证（0.2天）

```bash
make check  # lint + typecheck + test
# + dim引擎逐个验证 + data_context完整性验证 + 降级路径验证
```

### 13.7 问题对照表

| 412问题 | 实施任务 | 预期解决 |
|:-------:|---------|:--------:|
| §5.3#1 dim1门禁虚设 | A1(全量加载)+A2(校验)+B4(消费) | ✅ |
| §5.3#2 数据一致性 | A2(日期对齐检查) | ✅ |
| §5.3#3 STG补算不工作 | A3(异步通知) | ✅ |
| §5.3#4 性能收益未兑现 | A1+B/C/D(主路径统一到data_context) | ✅ |
| §5.3#5 降级路径依赖 | §5.4原则+全部保留fallback | ✅ |
| §6 Bug #1-#5 | E1-E4 | ✅ |
| §7 dim1缺数据 | A1(加载20+项) | ✅ |
| §7 无质量校验 | A2 | ✅ |
| §7 无STG联动 | A3(异步通知) | ✅ |
| §8.3#11 dim3低估 | D1+D2(130处) | ✅ |
| §11 dim4排序 | C1-C4串行 | ✅ |
| §12 #1-#8测试盲区 | F1(+31测试) | ✅ |

### 13.8 实施时间线

```
Day 1-3（A执行，B/C/D/E准备）:
  A: A1(全量加载20+项) → A2(validate) → A3(异步通知) → A4(测试)
  E: Bug #1-#5 + 清理（穿插进行）

Day 4-6（B/C/D并行，需A完成）:
  B: B1(dim2 MA) → B2(dim5 bociasi) → B3(dim5 MA) → B4(dim7验证) → B5(测试)
  C: C1(dim4 chip_fund_ext) → C2(dim4 cost_ext) → C3(dim4 indicator_ma) → C4(dim4 data_context)
  D: D1(vol_ma) → D2(130处MA替换) → D3(pattern测试)

Day 7:
  F: F1(31个新增测试) → F2(端到端验证) → make check
```

### 13.9 v3.0修订说明

**核心变更**：修正B1/B2/B3/C1/C2/C3/D1/D2共8个任务的架构违规——原计划在dim引擎内部直接调用DataManager/ECM/读取daemon内存，违反409方案"dim1是唯一数据入口"原则。

**修订内容**：
- §13.0：架构图和依赖关系重写（dim1为唯一入口，A完成后B/C/D并行）
- §13.1 A1：从"补加载5项"扩展为"加载3类20+项"（ECM表+indicator表+ext组）
- §13.2 B1/B2/B3：从"dim引擎内部调用DataManager"改为"从data_context读取"
- §13.3 C1/C2/C3：从"dim4内部调用DataManager/读tags"改为"从data_context读取"
- §13.4 D1/D2：从"dim3内部调用DataManager"改为"从data_context读取"
- §13.7/§13.8：同步更新问题对照表和时间线
- 总工时：~6.8天（A先执行2.0天，B/C/D并行1.5天）
