---
title: dim3 量价计算链路简化与 RAW 预计算未消费核查 + SIG→RAW 迁移补全实施（R1-R8）
type: 核查记录 + 实施方案
date: 2026-09-16
version: v1.0
status: ✅ R1-R7 已实施、**R8 已关闭**（2026-09-16 全量完成：R1 bug 修复 / R2 cost_ext / R3 无缺口关闭 / R4 维持现状关闭 / R5 删除 / R6 修复 / R7 双份收敛；**R8 于 2026-09-26 关闭**——437-A D1-D7 已于 09-20 拍板+实施，D1-D7 重审实证归集完整落地，R8 本体与问题2 同源已关闭）；**三问全部关闭（2026-09-26：问题3 已由 R7 收敛；问题1/2 维持现状——464 dim3 定稿+479-3 后已无实施动机）**
related:
  - 410-dim2-dim7层数据分层审计与RAW前置计算迁移方案
  - 411-维度引擎统一实施计划（407-410整合）
  - 412-SIG到RAW迁移实施状态审计与消费者接入补充方案
  - 426-RAW预计算环节配置核查报告与分库入库整改方案
  - 440-SIG素材质量前置修复方案
  - 437-dim8股票现状描述输出框架总纲
  - 442-SIG富字段系统性缺失修复方案
---

# 443 — dim3 量价计算链路简化与 RAW 预计算未消费核查

> **起因**：dim8 现状描述梳理（437 系）核查时发现 dim3 现状输出仅 9 字段，与 399 号（09-02）记录的 ~38 字段差距巨大。深挖发现：**440 号简化改造后，dim3 evaluate 不再调用内部完整 analyze()，改为读 RAW 预计算标签 + 粗拼健康度**。本号记录核查结论与三个待跟进问题（**未修改任何代码**）。

---

## 一、核查事实（2026-09-16，代码 + 生产库实证）

### 1.1 当前数据流（已核实）

```
RAW-2 预计算（data_daemon.py:3227）         SIG evaluate（dim3_vp_engine.py:4559）
  vps = VolumePriceStrategy()               vp_state ← tags['volume_price_fit'] 映射
  vps._detect_kline_patterns(df)            health_score ← 粗拼公式（tags 加权）
    └→ 完整 analyze（framework 版）         背离 ← tags['volume_price_fit']=='diverging'
       产出 30+ 字段（stage/momentum/       量比/形态 ← tags / PatternEngine
       three_laws/entry_zone/…）
    └→ 只持久化 6 个标签（data_daemon.py:3237-3246）:
       kline_pattern / ma_alignment / volume_price_fit / gap_type /
       breakout_attempts / volume_ratio
```

关键代码证据：
- `data_daemon.py:3024` `vps = VolumePriceStrategy()`（framework 版）→ `:3227` `vps._detect_kline_patterns(df)` → `:3244` `from app.engine.framework.volume_price_strategy import compute_volume_price_signal as _full_vp`（完整 analyze）→ 产出 `volume_price_fit`
- `data_daemon.py:3237-3246`：`features['volume_price']` **只保留 6 个字段**，stage/momentum/entry_zone/three_laws 等算完即弃

### 1.2 生产库实证（000002.SZ @ 09-14）

| 维 | 当前 status_description 字段数 | 399 号（09-02）历史字段数 |
|---|---|---|
| dim2 structure | 9 | 22 |
| dim3 volume_price | **9** | **~38** |
| dim4 chip_fund | 8 | 35 |
| dim5 emotion | 8 | 29 |
| dim6 risk | 24 | 24（保持原样） |
| dim7 valuation | 11 | 20 |

---

## 二、三个待跟进问题

> **✅ 三问全部关闭（2026-09-26 只读复核 + 用户拍板）**：
> - **问题1** → **维持现状关闭**：health_score 已由 464 dim3 定稿判「迁 JUD（439 同批）」且 479-1 清出 dim8 T 表——不再是 dim8 素材；改其成分属判定逻辑（445 冻结边界）+ 439-A 推迟范围，JUD 定型前不宜动。
> - **问题2** → **维持现状关闭**：RAW-2 量价已由 479-3 A5/A8 从 6 扩至 **9 字段**（+vp_state_label/vp_rule/divergence 三字段）；464 dim3 定稿补产出已全实现，momentum/共振**不在定稿输出键**（dim8 不消费）；「分位序列预计算」（412 P6 完整落地）443 附录已登记建议另开号、与 437-A R8 联动。
> - **问题3** → **已由 R7 收敛关闭**（2026-09-16）：dim3 删 4508 行 vendored 块（4760→252 行，现 432 行含 479-3 增量），framework 权威；§二问题3 原「方向待决策」为陈旧标注。

### 问题 1：health_score 精度降级（440 号简化改动的隐性代价）

- dim3 evaluate 用**粗拼公式**：`hs = (vp_score + ve + ms + cs + is_ + dp + pattern_deviation + 4)/12*10`（dim3:4600-4630）
- 只用了量比/均线/筹码/RSI/形态 6 个标签；**完整 analyze 里的动量(momentum)、共振评分(resonance_score)、三定律、供需、假突破等维度全部未进入该分**
- 影响：`health_score`（健康度 8/10）从完整量价分析降级为标签近似
- ~~**方向待决策**~~ **✅ 关闭（2026-09-26）：维持现状**——①hs 属判定逻辑（445 冻结边界），且 464 定稿「health_score/pattern_score 迁 JUD（439 同批）」+ 479-1 已清出 dim8 T 表 → 不再是 dim8 素材；②JUD 定型前改成分必返工；③接回 momentum 需联动问题2（RAW-2 扩字段），应一并放 JUD 阶段。现状公式已含 446 RPS 加分/450 背离扣分/形态偏差，非失真。

### 问题 2：RAW-2 量价持久化仅 6 字段，30+ 字段算完即弃

- 完整 analyze 的 stage/momentum/entry_zone/target_zone/three_laws/fake_breakout/supply_demand/state_machine_* 均已算出但**未持久化**（data_daemon.py:3237-3246 只存 6 字段）
- 这是 399 号 P1「22 个核心字段未消费」在 440 后的延续形态：从"evaluate 不输出"变成"RAW 不持久化"
- **影响**：dim8 现状描述要恢复完整量价素材（stage/动量/入场区间等），需先改 RAW-2 持久化契约
- ~~**方向待决策**~~ **✅ 关闭（2026-09-26）：维持现状**——①现状已 9 字段（479-3 A5/A8 补 vp_state_label/vp_rule/divergence_type/confidence/macd_confirmed）；②464 dim3 定稿补产出已全实现，momentum/共振不在定稿输出键，dim8 素材按定稿已齐；③「分位序列预计算」（412 P6 完整落地，省 SIG 实时分位 CPU）443 附录已登记建议另开号，与 437-A R8 联动。

### 问题 3：dim3 内联 vendored 双份（与 434 号收敛的 dim2 缠论双份同模式）

- `dim3_vp_engine.py:4147` 内联了整份 `VolumePriceStrategy` + `:4298` `compute_volume_price_signal`（vendored 副本）
- 当前 evaluate **不调用**内联版；`compute_volume_price_signal` 仅测试引用（test_dim3_patterns.py）
- 与 `app/engine/framework/volume_price_strategy.py` 形成**双份**（类似 dim2 缠论双份，434 号已收敛 dim2，dim3 量价双份未收敛）
- ~~**方向待决策**~~ **✅ 已由 R7 收敛关闭（2026-09-16）**：434 式差异审计（双份远超方案假设：vendored 整份 volume_price_strategy ~4300 行 + kline_pattern）→ framework 回迁 412 增强（权威，零行为变更）→ dim3 删 4508 行 vendored 块（4760→252 行，现 432 行含 479-3 增量）。详见 §九 R7。附带消除 dim3 版 EPD `prev_ma` bug 与 `volume_ext=` 恒 TypeError 潜伏 bug。

---

## 三、附带发现（供后续联动核查）

- **dim3 evaluate 已不再调用内部 `analyze()`**（dim3:4161，返回 stage/volume_state/relation/signal_output/volume_price_detail 30+ 字段）——该方法是"算而不出"的丰富计算主体，被 RAW-2 的 framework 版取代后成为 SIG 侧死路径（仅测试可达）
- 410/412 号方案定义的「简单计算类指标转移到 RAW」中，**dim3 量指标（vol_ma/波动率/ROC）迁移 Phase 8 当时审计为未接入（0%）**——440 简化改造后现状需重新核对（见问题 2）

---

## 四、建议后续动作（✅ 2026-09-26 三问全部关闭，本节作废）

1. ~~确认问题 1 方向~~ → **维持现状关闭**（hs 迁 JUD 属 439-A/445 冻结，JUD 定型前不动）
2. ~~确认问题 2 方向~~ → **维持现状关闭**（479-3 已扩 9 字段满足 dim3 定稿；分位序列预计算另开号）
3. ~~确认问题 3 方向~~ → **已由 R7 收敛关闭**（2026-09-16）

---

## 五、补充核查：410/411/412 号「简单计算类指标转移到 RAW」的当前落地核对（2026-09-16）

> 承接 410（迁移方案）/ 411（14 Phase）/ 412（迁移状态审计，2026-09-07）。本轮按 412 的 8 个 Phase 逐项核对**当前**代码与生产库（412 后经历 426/430/431/433/434/436/437/438/439/440/441/442 改造）。

### 5.1 RAW 预计算持久化现状（pre_feat_cache features_json，17 组）

`data_daemon._precompute_raw_features`（data_daemon.py:2960-3563）实际持久化组：
`valuation/sentiment/sector/style/timing/volume_price/chanlun/chip/event/depth/derived/risk_ext/chip_fund_ext/fund_5d_ext/valuation_ext/cost_ext/volume_ext/emotion_ext/vp_health_ext/structure_ext/market_stats`（21 键，含空组）

### 5.2 逐 Phase 消费核对表（412 审计基线 → 当前状态）

| Phase | 410 内容 | 预计算组 | 412 审计(09-07) | **当前状态(09-16)** | 证据 |
|---|---|---|---|---|---|
| P1 | MA/MACD/RSI 改读预计算表 | indicator_ma/macd/other（独立表，非 pre_feat） | 40%（MACD 接入，MA 未接） | ⚠️ **MA 仍未接入**：dim2 `calc_support_resistance` 仍 raw 算 MA20/60（dim2:3757-3760 历史，现 calc_support_resistance 独立）；dim3 evaluate 简化版**不调用** VolumeStateAnalyzer（dim3:4161 analyze 不再被 evaluate 调用）→ indicator_ma 消费点变少 | dim3:4559 evaluate 全读 tags |
| P2 | dim4 筹码指标 RAW 迁移 | chip_fund_ext | 17%（仅 ssrp 接入） | ✅ **显著改善**：dim4 evaluate 传 `chip_fund_ext`（dim4:5970）→ `_dim_chip` 覆盖 raw（dim4:754-763）、`_dim_ssrp` 读 extra_tags（dim4:617）、`_score_chip_distribution` 优先预计算（dim4:2813/2841） | — |
| P3 | dim4 5日资金聚合 | fund_5d_ext | 100%（net_lg_5d 接入，consecutive 未接） | ✅ **基本保持**：`_dim_fund` 读 net_lg_5d/positive_ratio（dim4:505-514）；net_lg_5d_consecutive 无消费 | — |
| P4 | dim6 几何化+波动率 | risk_ext | **100% 唯一完整** | ✅ **保持完整**：`_geo_precomputed`/`_vol_precomputed` 门控（dim6:1110/1132） | — |
| P5 | dim5 市场级 SQL 改预计算 | market_stats | 0%（分裂） | ✅ **已修复**：dim5 evaluate 传 `market_stats` 给 BociasiQuadrantAnalyzer（dim5:429-430）——但 **emotion_ext（emotion_temperature 等）仍未被 dim5 消费**（dim5:499 自行 `calc_emotion_temperature` 重算） | — |
| P6 | dim7 估值指标 RAW | valuation_ext | 0%（未接入） | ❌ **仍未接入**：dim7 全部走 data_context（income/balancesheet/cashflow/fina_df，dim7:688-718），**不读 valuation_ext** | — |
| P7 | dim4 成本价 RAW | cost_ext | 0%（未接入） | ⚠️ **部分**：cost_ext 仅批量 `identify_phase` 路径消费（dim4:3740-3741）；**evaluate 主路径未传 cost_ext**（dim4:5974 只传 chip_fund_ext/moneyflow/indicator） | — |
| P8 | dim3 量指标 RAW | volume_ext | 0%（未接入） | ⚠️ **半接入**：VolumeStateAnalyzer.analyze 支持 volume_ext（dim3:2587-2598），但 **evaluate 简化版不调用该链**；仅 `compute_volume_price_signal`/`_detect_kline_patterns` 内部透传 | — |
| 额外 | vp_health_ext | vp_health_ext | 无消费者 | ❌ **仍无消费者**（vp_score=None 占位，vp_state_type/volume_energy 无人读） | — |
| 额外 | structure_ext | structure_ext | — | ✅ **已接入**：dim2 `_assess_vs_indicator` 读 indicator_status（dim2:245-246，442 缺陷③修复） | — |

### 5.3 结论

1. **持久化全量就绪**：17 组 ext 全部写入 pre_feat_cache（dim1 门禁清单 21 键全覆盖，dim1_signal_engine.py:254-257）；
2. **消费仍不均**：P2/P3/P4/P5 主体已接入；**P1(MA)/P6(valuation_ext)/P7(evaluate 路径 cost_ext)/P8(volume_ext)/vp_health_ext 仍存在「持久化但未消费」**——与 412 号审计的核心结论一致（「算而不出」在 440 简化后仍存）；
3. **dim8 影响**：valuaton_ext/cost_ext/volume_ext/vp_health_ext 若要进现状描述，需先补消费接入——与 437-A 素材缺口属同一类「素材在库、链路未接」。

### 5.4 全市场持久化实测（2026-09-16，09-14 全市场 5546 只 pre_feat_cache 逐行核查）

| 组.字段 | 非空覆盖率 | 说明 |
|---|---|---|
| fund_5d_ext.net_lg_5d | **100%** | ✅ 正常 |
| valuation_ext.pe_ttm | **100%** | ✅ 正常 |
| cost_ext.margin_cost_price | **100%** | ✅ 正常 |
| cost_ext.main_force_cost | 99.8% | ✅ 正常 |
| volume_ext.vol_ma5 | 99.8% | ✅ 正常 |
| emotion_ext.emotion_temperature | 100% | ✅ 正常 |
| vp_health_ext.volume_energy | 100% | ✅ 正常 |
| structure_ext.indicator_status | 100% | ✅ 正常 |
| risk_ext.support_price | 99.3% | ✅ 正常 |
| **chip_fund_ext.ssrp/asr/concentration/profit_ratio/cyqkl/rsi** | **0%** | ❌ **实锤 bug（见 5.5）** |
| vp_health_ext.vp_score | 0% | ⚠️ 占位 None（412 审计已标注） |
| market_stats | 0% | ⚠️ 个股行未写入（全市场共享，疑持久化路径未落行） |

### 5.5 chip_fund_ext 核心 6 字段全市场 0% —— 424 号改造引入的类型不匹配 bug（新发现）

- **根因**：`ChipDistributionEstimator.estimate()` 返回 **4 元组** `(chip_dist, min_price, max_price, price_step)`（dim4:121）；data_daemon:3376 用单变量 `chip_bins = cde.estimate(df)` 接收后传给 `ChipIndicators.calculate_all_indicators(chip_bins, ...)`（期望 **dict 列表**，内部 `b['chip_ratio']`/`b['price_bin']`，dim4:134-183）→ 对元组迭代时 `b['chip_ratio']` 对 numpy 数组取值 → **TypeError** → 被 data_daemon:3381 `except Exception: pass` **静默吞掉** → 6 字段从未写入。
- **引入时机**：424 号 §10 决策②「先算 chip_bins（cde.estimate）再算聚合指标」改造后（此前调用方式待 git 核实）。
- **影响**：dim4 `_dim_chip` 期望 chip_fund_ext 覆盖 raw（dim4:754-763）实际**永不生效**（字段缺失走 raw）；`_score_chip_distribution`（424 设计目的=避免重复计算完整分布）**未兑现**；且无任何日志暴露。
- **关联**：与 442 号「except: pass 静默吞异常」同模式（441 号 stk_holder 亦同根因），疑似系统级共性风险。

> **本文档性质**：核查记录，未修改任何代码。依据：dim3_vp_engine.py / data_daemon.py / framework/volume_price_strategy.py 源码逐点核实 + 生产库 snapshot_cache.db dim_results_json（09-14）键集合实测 + 399/410/411/412/426/440 号方案交叉引用。

---

## 六、399 号记录口径澄清（2026-09-16 补记，git 历史实证）

> **结论**：399 号（09-02）记录的每维 20-38 个 status_description 字段，**混入了引擎内部分析对象（analyze/ChipIndicators 等的返回结构）字段**，并非 evaluate 的真实输出。**evaluate 的输出契约从未被精简**——dim3 从文件诞生（08-25）起就是 9 字段。

### 6.1 git 历史实证（dim3）

| 时点 | evaluate 的 status_description | 说明 |
|---|---|---|
| 08-25 文件诞生（6e569f9，4549 行新建） | **9 字段**（vp_state/health_score/divergence/volume_energy/pattern/vol_ratio/pattern_score/granville/plain） | 从未变过 |
| 09-08（2a34db1，371-417 方案） | **9 字段** | 未变 |
| 当前（09-16） | **9 字段** | 未变 |

**结构事实**：dim3 `evaluate()`（:4559，Dim3VPEngine 类）与 `analyze()`（:4161，**VolumePriceStrategy 类**）是**两个独立类的方法**——evaluate **从不调用** analyze（evaluate 函数体内无 analyze/stage_detector/volume_analyzer 调用，已 grep 证实）。399 号的 stage_name/state_machine_*/resonance_score/multi_timeframe_*/status_recognition/momentum/three_laws/entry_zone/target_zone/fake_breakout/supply_demand/evidence 系列 = analyze() 返回的 `Stage.to_dict()/VolumeState.to_dict()/RelationResult.to_dict()/signal_output` **内部对象字段**。

dim4 同型：399 号 35 字段中的 cost_asr/cost_cyqkl/cost_profit_ratio/phase_confidence/pde_* = `ChipIndicators`/`PhaseDetectionEngine` 内部返回对象字段；evaluate 实际输出 8 字段。

### 6.2 口径修正公式

```
399 号记录字段数 = evaluate 真实输出字段 + 引擎内部分析对象字段（混记）
实际 evaluate 输出（下游消费口径）：
  dim2=9 / dim3=9 / dim4=8 / dim5=8 / dim6=24 / dim7=11（当前，09-14 生产库实测）
```

### 6.3 后续引用注意事项

1. **勿以 399 号字段数判断「输出被精简」**——evaluate 输出未变，变的是视角（399 混入内部对象字段）；
2. 399 号仍有效：它如实反映**引擎内部完整分析能力**（analyze 能算 stage/momentum/entry_zone 等 30+ 字段）——这部分对应「RAW-2 算完只持久化 6 标签、其余算完即弃」（本号问题 2），是**真实待办**；
3. dim8 现状描述要使用完整量价素材，路径=改 RAW-2 持久化契约（data_daemon:3237）或 dim8 直接消费 analyze 返回，**而非**「恢复 evaluate 输出」（evaluate 输出从来只有 9 字段）。

---

## 七、完整实现 SIG 简单核算迁移到 RAW 的可行性评估（2026-09-16）

> **结论**：**可行，且剩余工作量小（约 1.5-2.5 天）**。410/411/412 规划的 8 个 Phase 中，主体已随 426/436/437/438/439/440/441/442 改造落地；当前剩余缺口为 **1 个 bug 修复 + 2 个消费接入 + 2 个占位/清理**，无架构性障碍。

### 7.1 当前实际完成度（与 412 审计对比，git+代码实证）

| Phase | 412 审计(09-07) | 当前(09-16) | 剩余缺口 |
|---|---|---|---|
| P1 MA/MACD/RSI 改读预计算表 | 40% | ⚠️ ~70%（dim2 已传 indicator_ma_df 给 calc_support_resistance（dim2:110-111）；MACD 已接；dim3 evaluate 简化版不调 analyze） | 低（dim3 内部 ~80 处 raw MA 不接也不影响输出——evaluate 不用） |
| P2 dim4 筹码指标 | 17% | ⚠️ 消费口在，**持久化 0%**（424 bug） | **修 bug**（§5.5）后即生效 |
| P3 dim4 5日资金聚合 | 100% | ✅ 保持 | 无（net_lg_5d_consecutive 可选） |
| P4 dim6 几何化+波动率 | 100% | ✅ 保持完整 | 无 |
| P5 dim5 市场级 SQL | 0% | ✅ **已修复**（market_stats 传入，dim5:429-430） | 无 |
| P6 dim7 估值指标 | 0% | ⚠️ ~80%（data_context-first 已实现 dim7:691-719；**不读 valuation_ext 但结果一致**） | 低（可选接入 valuation_ext） |
| P7 dim4 成本价 | 0% | ⚠️ 半（批量路径消费，evaluate 未传） | 中（evaluate 补传 cost_ext） |
| P8 dim3 量指标 | 0% | ⚠️ 半（VolumeStateAnalyzer 支持 volume_ext，evaluate 不调该链） | 中（evaluate 恢复调用或直接读 tags） |

### 7.2 剩余工作清单（按优先级）

| # | 缺口 | 改动点 | 工作量 | 收益 |
|---|---|---|---|---|
| R1 | **chip_fund_ext 持久化 bug**（424 引入，6 字段全 0%） | data_daemon:3376 解包 4 元组 `chip_bins, *_ = cde.estimate(df)` 再传 calculate_all_indicators；补日志防静默吞 | 0.2 天 | 恢复 ssrp/asr/concentration/profit_ratio/cyqkl/rsi 持久化；dim4 `_dim_chip` 覆盖 raw 生效；`_score_chip_distribution` 免重复计算兑现 |
| R2 | dim4 evaluate 补传 cost_ext | dim4:5974 从 data_context 取 cost_ext 传入 PhaseDetectionEngine | 0.1 天 | 主力/融资成本价预计算被 evaluate 消费（当前仅批量路径用） |
| R3 | dim3 evaluate 恢复 volume_ext 消费 | evaluate 简化版直接读 tags.vol_ma5/vol_ma10/vol_ma20（tags 已扁平化含 volume_ext）替代 raw rolling | 0.2 天 | 量 MA 预计算生效（当前 evaluate 全部 raw 算） |
| R4 | dim7 接入 valuation_ext（可选） | evaluate 读 tags.pe_ttm/pb 等；或维持现状（data_context 同源，无精度差） | 0.3 天 | 省 DB 调用；**可选**（无精度收益） |
| R5 | vp_health_ext 处置 | 补 vp_score 计算（vp_health_builder 就绪）或删除该组 | 0.3 天 | 清理占位 |
| R6 | market_stats 落行核查 | 确认全市场共享数据持久化路径（当前个股行 0%） | 0.2 天 | 数据可用性 |
| R7 | dim3 内联双份收敛（443 问题 3） | 434 式审计差异 → framework 权威 + dim3 回归 import | 0.5-1.0 天 | 消除双份 |
| R8 | （可选）RAW-2 量价持久化扩字段 | data_daemon:3237 加 stage/momentum/entry_zone 等（供 dim8 完整素材） | 0.5 天 | dim8 素材前置（437-A 关联） |

### 7.3 可行性结论

1. **无架构障碍**：预计算写入管道（RAW-2）、持久化表（pre_feat_cache 21 组）、消费链路（dim1 门禁 21 键 + tags 扁平化 + 各 dim precomputed-first 门控）**全部就绪**，剩余是点状修复而非系统性改造；
2. **核心收益**：R1（bug 修复）恢复 6 个筹码字段持久化（纯增益，零风险）；R2/R3 让已持久化数据被 evaluate 消费（消除重复 raw 计算）；
3. **精度影响**：R1-R8 均不改变分析逻辑（同源数据、同公式），只改变「在哪算、从哪读」——**无精度回归风险**；真正的精度问题（health_score 粗拼）独立于 RAW 迁移，属 443 问题 1；
4. **建议实施顺序**：R1 → R2/R3 → R7（收敛）→ R4/R5/R6（收尾）→ R8（可选，与 437-A dim8 素材联动）；
5. **不实施的影响**：现状系统功能正确（未消费项有 raw 兜底），损失仅为性能（重复计算）与素材可用性（dim8 用不了完整量价/估值预计算）——**无正确性风险**，故 R4-R8 均可按需推迟。

---

## 八、R1-R8 实施指令（2026-09-16 用户拍板，新对话交接）

> **交接说明**：本对话已完成全部核查（§一~§七），用户确认开展 R1-R8 实施，将在**新对话**进行。新对话先读本文档 §五/§六/§七 获取核查结论与证据，再按本节指令逐项实施。**每项完成后跑相关测试回归 + 更新本文档实施记录。**

### 通用前置（新对话第一步）

1. 确认无 data_daemon 进程在写库（`ps aux | grep data_daemon`）；
2. 备份：`cp data/duckdb/compute_cache.db data/duckdb/compute_cache.db.bak_443_$(date +%Y%m%d_%H%M%S)`（若涉及 RAW-2 重算需要，否则可跳过）；
3. 实施完所有 R1-R8 后统一跑：`cd backend && make check`（或 pytest 相关套件 test_411_pipeline / test_396_dim2_engine / test_419_dim5_compliance / test_dim3_patterns / test_436_b3_sandbox / test_442_*）；
4. **每项改动遵守 AGENTS.md §六 开发期数据隔离红线**（沙盒/临时隔离测试，不碰开发基准库写）。

### R1：修复 chip_fund_ext 持久化 bug（最高优先，唯一正确性隐患）

**文件**：`backend/data_daemon.py:3376` 附近（`_precompute_raw_features` 内 "13. 资金筹码扩展字段" 段）

**现状 bug**：`chip_bins = cde.estimate(df)` —— `ChipDistributionEstimator.estimate()`（dim4:90-121）返回 **4 元组** `(chip_dist, min_price, max_price, price_step)`，但此处分单变量接收后传给 `ChipIndicators.calculate_all_indicators(chip_bins, ...)`（期望 **dict 列表**，内部 `b['chip_ratio']`/`b['price_bin']`）→ 迭代 numpy 数组抛 TypeError → 被外层 `except Exception: pass` 静默吞 → **ssrp/asr/concentration/profit_ratio/cyqkl/rsi 全市场 0% 持久化**（09-14 实测 0/5546）。

**改法**：解包元组，取第一个元素（chip_dist 数组）——但注意 `calculate_all_indicators` 期望的是 **dict 列表**（每元素含 `price_bin`/`chip_ratio`），而 `estimate()` 返回的是 numpy 分布数组。**需先核对 `_calculate_ssrp` 等对 chip_bins 的消费方式**（`b['chip_ratio']`/`b['price_bin']` → dict 列表），决定改哪端：
- 方案 A（推荐）：RAW-2 处把 estimate 返回的 4 元组转成 dict 列表再传入（对齐 `calculate_all_indicators` 期望），或
- 方案 B：改 `calculate_all_indicators` 接受 numpy 数组形态。
- **实施时必须先读 dim4:90-183 确认两端的真实数据形态再动手，勿臆断**；补 `except Exception as e: logger.warning(...)` 防静默吞（对齐 442/441 的教训）。

**验证**：RAW-2 重算少量股票（如 `_precompute_single('000002.SZ')` 或冒烟脚本）后查 pre_feat_cache 该股 chip_fund_ext 含 ssrp/asr/concentration 非空；dim4 `_dim_chip` 覆盖逻辑（dim4:754-763）生效。

### R2：dim4 evaluate 补传 cost_ext

**文件**：`backend/app/opportunity_atlas/dimensions/dim4_chip_fund_engine.py:5974` 附近（evaluate 内 `pde.compute_tags(...)` 调用）

**现状**：evaluate 传 chip_fund_ext/moneyflow_df/indicator_ma_df/indicator_other_df，**未传 cost_ext**；cost_ext（main_force_cost/margin_cost_price）仅批量 `identify_phase` 路径消费（dim4:3740-3741）。

**改法**：`cost_ext = data_context.get('cost_ext') if data_context else None`，加入 compute_tags 调用参数（先确认 PhaseDetectionEngine.compute_tags 签名是否接受 cost_ext；若不接受则需在签名加参数并透传给阶段检测逻辑——**先读 dim4:383-540 compute_tags 与 _run_stage_detector_v2(:783) 确认**）。

**验证**：evaluate 走通后 dim4 phase 判定可用 cost_ext（主力成本近距 5% 内增强洗盘判定，dim4:3541-3544）。

### R3：dim3 evaluate 消费 volume_ext（量 MA）

**文件**：`backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py:4559` evaluate 简化版

**现状**：`VolumeStateAnalyzer.analyze` 支持 volume_ext（dim3:2587-2598），但 evaluate 简化版**不调用该链**（VolumePriceStrategy.analyze 仅在 RAW-2 `_detect_kline_patterns` 内部用），evaluate 内量 MA 全 raw 算（如 vol_ma5 计算点多处）。

**改法**：evaluate 内读 `tags.get('vol_ma5'/'vol_ma10'/'vol_ma20')`（tags 扁平化已含 volume_ext 组）替代局部 raw rolling——**先定位 evaluate 内实际用到量 MA 的计算点**（grep `vol_ma|rolling(5).mean()` 在 evaluate 函数体内）再替换；保留 raw fallback。

**验证**：evaluate 输出量能相关字段与改造前一致（同源同公式）；单测覆盖。

### R4：dim7 接入 valuation_ext（可选）

**文件**：`backend/app/opportunity_atlas/dimensions/dim7_valuation_engine.py:673` `_compute_valuation`

**现状**：data_context-first 已实现（dim7:691-719），结果与 valuation_ext 同源一致；不读 valuation_ext 无精度差，仅多 DB 调用。

**改法**：在 data_context 缺失对应 df 时优先读 `tags.pe_ttm/pb/ps_ttm/total_mv/roe/roce/grossprofit_margin`（valuation_ext 扁平化）再回退 ecm 查询。**低优先，可与用户确认是否纳入**。

**验证**：dim7 输出与改造前一致。

### R5：vp_health_ext 处置

**文件**：`backend/data_daemon.py:3540-3545`（vp_health_ext 段）

**现状**：vp_score=None 占位（注释"待 vp_health_builder 就绪"）、vp_state_type/volume_energy 无消费者。

**改法**：二选一（建议实施时与用户确认）——a) 补 vp_score 计算；b) **删除该组**（412 §8.4 建议删除无消费者预计算，省 daemon CPU）。若删：删 data_daemon 写入段 + dim1 optional 清单（dim1_signal_engine.py:254-257）移除 vp_health_ext 键。

### R6：market_stats 落行核查

**现状**：`features['market_stats'] = _market_stats_cache`（data_daemon:3561-3563），但 09-14 全市场 5546 只实测 **market_stats 均为空 dict**——疑似 `_market_stats_cache` 在 RAW-2 执行时为空（`_precompute_market_stats` 时序/调用关系待查）。

**改法**：先读 data_daemon:2766 `_precompute_market_stats` 与 :5663 调用点、:6676-6680 缓存恢复逻辑，确认 RAW-2 执行时缓存是否已预热；若时序问题则调整预热顺序或 RAW-2 内显式调用。**纯核查项，确认数据流即可**。

### R7：dim3 内联双份收敛（参照 434 号流程）

**文件**：`backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py:4147` 内联 `VolumePriceStrategy` + `:4298` `compute_volume_price_signal` vs `backend/app/engine/framework/volume_price_strategy.py`

**现状**：双份均存在；evaluate 不调用内联版；内联 `compute_volume_price_signal` 仅测试引用（test_dim3_patterns.py）。

**步骤**（参照 434 缠论收敛）：
1. 差异审计：SequenceMatcher 对比内联版与 framework 版（类似 dim2 缠论双份审计）；确认内联版独有/缺失内容；
2. 定权威：framework 版为权威（RAW-2 data_daemon:3024 用 framework 版）；
3. dim3 内部改为 import framework 版（`from app.engine.framework.volume_price_strategy import VolumePriceStrategy`），删除内联副本或改为薄封装；
4. 回归：test_dim3_patterns / test_411_pipeline / test_426_phase2_structure 等。

### R8：RAW-2 量价持久化扩字段（可选，dim8 素材前置）

**文件**：`backend/data_daemon.py:3237-3246`（features['volume_price']）

**现状**：只持久化 6 字段（kline_pattern/ma_alignment/volume_price_fit/gap_type/breakout_attempts/volume_ratio）；完整 analyze 的 stage/momentum/entry_zone 等 30+ 字段算完即弃（`_detect_kline_patterns` 内 `_full_vp` 的返回未保留）。

**改法**：RAW-2 内把 `_full_vp('', df, volume_ext=...)` 的返回（signal_output/volume_price_detail/stage 等）关键字段并入 features['volume_price'] 或新组 features['volume_price_full']。**与 437-A D1-D7 拍板联动**（dim8 归集要哪些字段），建议等 437-A 拍板后实施。

**验证**：RAW-2 重算后 pre_feat_cache 含新增字段；dim8 归集（若已按 437-A 实施）可消费。

### 实施顺序建议

`R1 → R2 → R3 → R7 → R5/R6 → R4 → R8`（R8 最后，依赖 437-A 拍板；R4/R5/R6 可与用户确认取舍）。

### 每项完成后的记录要求

在本文档「§九 实施记录」追加：改动文件/行、验证命令与结果、测试通过数；全部完成后更新文档头部 status=✅。

---

## 九、实施记录（逐项填，实施在新对话进行）

### R1：chip_fund_ext 持久化 bug 修复
- 状态：✅ 已完成（2026-09-16）
- 改动：`backend/data_daemon.py`「13. 资金筹码扩展字段」段（原 :3376 附近）——`chip_bins = cde.estimate(df)` 改为解包 4 元组 `chip_dist, min_price, max_price, price_step = cde.estimate(df)`，将 numpy 分布数组按 `chip_distribution_service._format_chip_result` 同式转为 dict 列表（`price_bin = min_price + idx*step + step/2`、`chip_ratio = float(chip_dist[idx])`，各 round 2/4 位）再传 `ChipIndicators.calculate_all_indicators`；内层 `except Exception: pass` 改 `except Exception as e: logger.warning(...)` 防静默吞。新增 `backend/scripts/_443_r1_smoke_chip_fund.py`（冒烟验证脚本）。
- 验证：`DATA_DIR=... .venv/bin/python scripts/_443_r1_smoke_chip_fund.py --smoke 5` → 5/5 只 chip_fund_ext 六字段全部真实化（如 001232.SZ ssrp=178.9/asr=25.46/concentration=0.0322/profit_ratio=0.77/cyqkl=9.97/rsi=76.79），latest=2026-09-15，computed_at=2026-09-16 08:28:43（本次重算写入，非旧值残留）；对照 09-14 实测 0/5546。回归：pytest 7 套件（test_411_pipeline/test_396_dim2_engine/test_419_dim5_compliance/test_dim3_patterns/test_436_b3_sandbox/test_442_vs_indicator/test_442_margin）**76 passed**。前置：daemon 已停（含 start_daemon.sh 看守，无复活）；compute_cache.db 已备份（.bak_443_20260916_082325，注意备份时存在 -wal 未合并，如需回滚建议以该库 + 原 -wal 一并恢复或重跑 RAW-2 重建）。

### R2：dim4 evaluate 补传 cost_ext
- 状态：✅ 已完成（2026-09-16）
- 改动：`backend/app/opportunity_atlas/dimensions/dim4_chip_fund_engine.py` 四处——①`PhaseDetectionEngine.compute_tags` 签名新增 `cost_ext: Optional[Dict] = None`（含 docstring）；②dims 字典 `"ssrp": self._dim_ssrp(df_sorted, extra_tags, cost_ext=cost_ext)` 透传；③`_dim_ssrp` 签名新增 cost_ext 并实现主力成本近距增强——现价距 `main_force_cost` 5% 内返回 `{"washing": 0.5, "building": 0.2}`（对齐 `MainForceScorer.identify_phase` dim4:3541-3544 洗盘判定）；④`Dim4ChipFundEngine.evaluate` 读 `cost_ext_val = data_context.get('cost_ext')` 并传入 compute_tags（data_context 的 cost_ext 由 dim1 从 pre_feat_cache ext 组组装，RAW-2 已持久化 data_daemon:3484）。新增 `backend/tests/test_443_r2_cost_ext.py`（7 用例：near_cost 增强/远距不变/无 cost_ext 不变/ssrp 缺失空票/签名/inspect 数据流）。
- 验证：pytest `tests/test_443_r2_cost_ext.py` 7 passed；全量回归（8 套件含 R1 的 7 个 + R2 新测试）**83 passed**。

### R3：dim3 evaluate 消费 volume_ext
- 状态：✅ 关闭为无缺口（2026-09-16，用户确认）
- 结论：**方案前提被 440 号简化证伪**——dim3 evaluate（dim3:4559-4693）函数体内经方案指定 grep（`vol_ma|rolling|_sma|VolumeStateAnalyzer|analyze(`）**零命中**，无任何内联量 MA raw 计算可替代；量能输入全部来自 tags 预计算字段（volume_ratio/volume_price_fit/ma_alignment）。`volume_ext.vol_ma5/10/20`（覆盖率 99.8%）已由 `_flatten_pre_feat`（status_engine:135）扁平化进 tags，但 evaluate 不读属 440 简化后的设计现状（§5.2 P8「半接入」审计同结论：VolumeStateAnalyzer 支持 volume_ext 但 evaluate 简化版不调用该链）。vol_ma 的消费需求并入 R8/437-A dim8 素材前置跟踪，本项不再单独实施。
- 验证：`sed -n '4558,4693p' dim3_vp_engine.py | grep -nE 'vol_ma|rolling|_sma|analyze\('` → NO 命中；§5.2/§6.1 交叉核实（evaluate 与 analyze 是两独立类方法，evaluate 从不调用 analyze）。

### R4：dim7 接入 valuation_ext（可选）
- 状态：✅ 关闭为维持现状（2026-09-16，用户确认）
- 结论：**关键事实：dim1 data_context 已加载全部 4 个估值 df**（daily_basic_df:93 / income_df:117 / balancesheet_df:125 / cashflow_df:133），dim7 data_context-first 在 SIG 正常路径**已完整覆盖**，ecm fallback 几乎不触发——「不接入 valuation_ext」≠「dim7 更不精确」，dim7 精度由完整历史 df 实时计算保证。valuation_ext 仅最新单值快照（pe_ttm/pb/ps_ttm/total_mv/roe/roce/grossprofit_margin），四锚 `_anchor_*` 需要 ≥20 个历史值做分位（_anchor_pb dim7:369 空 df/不足 20 → 0.0），单值无法无损替代；任何 df 构造/单值兜底都会改变「数据源级缺失」场景输出（无数据→有值），违背精度不变约束。`_compute_potential`（dim7:852）已消费 `tags.roe`（valuation_ext 的 roe 已扁平化）——潜力评分路径已接入。**用户提出分位序列预计算方向（RAW-2 持久化 pe/pb 5 年分位等，dim7 四锚改读预计算）＝ 412 P6 完整落地，规模 ≈ R7（约 1 天），收益为 SIG 省实时分位 CPU + dim8 素材前置——非 R4 本身，建议与 437-A dim8 素材/R8 联动另开方案号。**
- 改动：无（维持现状）

### R5：vp_health_ext 处置
- 状态：✅ 已完成（2026-09-16，用户拍板 b 删除该组）
- 改动：`backend/data_daemon.py`——删除「15. 量价健康扩展字段」整段（vp_score=None 占位 / vp_state_type / volume_energy，约 20 行），并移除仅供该段使用的 `from ...shared_vol_ratio import calc_vol_ratio` 局部 import。dim1 optional 清单（dim1_signal_engine.py:254）**已无 vp_health_ext 键**（440/442 时已移除），无需改；pre_feat 旧行残留 vp_health_ext 键无害（无消费方，后续重算自然覆盖）。
- 验证：py_compile OK；RAW-2 冒烟 2/2（R1 chip_fund 无回归），新写入行不再含 vp_health_ext。

### R6：market_stats 落行核查
- 状态：✅ 已修复（2026-09-16）
- 结论：**根因 = `_precompute_market_stats` 用 `now-1` 硬算统计日，未锚定最新交易日**。证据链：①市场统计在 RAW 前同步执行（data_daemon:5673），时序无并发问题；②`_precompute_market_stats` 原默认 `today = datetime.now()-timedelta(days=1)`——09-14（周一）daemon 跑时统计日=09-13（周日）→ 各统计项全 None → `_market_stats_cache={}` 不落库（426 P0-1 防假值逻辑触发）→ RAW-2 落空 dict；③实测 pre_feat 09-04~09-11 market_stats 全有值、09-14 全 5546 行空、market_stats_cache 最近落库=09-11；④09-15 的 442 全量重算脚本直接调 `_precompute_raw_features`（进程内缓存空）也覆写 09-14 行为空。**源表时序分层实测**：daily=09-15 / daily_basic+stk_limit=09-14 / margin=09-11（采集断裂）——锚 daily 最大日仍会因 daily_basic 滞后置空，最终口径锚 **daily_basic_cache 最大日**（统计项公共依赖表，09-14 实测 7 项全有值）。
- 改动：`backend/data_daemon.py` `_precompute_market_stats`（:2776 附近）——统计日缺省时锚定 `daily_basic_cache` 最大 trade_date（替代 now-1），异常回退 now-1。新增 `backend/scripts/_443_r6_backfill_market_stats.py`（轻量回填，不重跑 RAW-2）。
- 验证：无参调用锚定 **2026-09-14**、8 项统计落库（market_stats_cache 新增 09-14 行）；回填 09-14 pre_feat 5546/5546 行 market_stats 真实化（含 ma20_ratio）；pytest test_411_pipeline + test_436_b3_sandbox **34 passed**。

### R7：dim3 内联双份收敛
- 状态：✅ 已完成（2026-09-16，用户拍板方案 A 全量收敛）
- 差异审计结论：**双份范围远超方案假设**——dim3（369 号物理合并）vendored 了**整份** framework/volume_price_strategy.py（ValuationZones→compute_volume_price_signal ~4300 行）+ framework/kline_pattern.py 的 KLinePattern/KLinePatternVerifier（逐字节一致 sim=1.0）。符号层 16 类：11 类 1.0 一致；分叉 5 类（EnhancedPatternDetector 0.9395=dim3 多 113 行+3 独有方法、VolumeStateAnalyzer 0.9413、StageDetector 0.9680、VolumePriceRelationAnalyzer 0.9906、VolumePriceStrategy 0.9923）+ calc_macd 0.2099 + compute_volume_price_signal 0.8748。**分叉方向与 434 相反**：dim3 份含 412 D1/D2/D3 v3.0 增强（volume_ext 透传、precomputed_ma、precomputed calc_macd），framework 权威份全部缺失。**逐方法核对发现 dim3 版 EPD 有 prev_ma bug**（注释「去掉最新一根」但赋值与 ma 相同数组未位移 → _is_granville_sell4 恒近真/_is_ma5_jiaotou_ma60 恒假，预验证 50/200 组不一致实锤）——framework 版 prev_ma 语义正确。
- 改动：
  - **framework 回迁 412 增强（权威，零行为变更）**：①`EnhancedPatternDetector` 加 `_get_ma/_get_prev_ma/_get_vol_ma/_get_prev_vol_ma` 4 helper + `detect_all` 加 `precomputed_ma` 参数，74 处内联 `np.mean(closes[-p:])/closes[-p-1:-1]/volumes[...]` 替换为 helper（**prev 用正确位移** `closes[-p-1:-1]`，未引入 dim3 的 bug；`closes[-62:-2]`/`volumes[:-1]`/`volumes[-10:-1]` 3 处特殊模式保留 raw）；②`VolumeStateAnalyzer.analyze` 加 `volume_ext` 参数（412 D1 v3.0，含 raw fallback）；③`VolumePriceStrategy.analyze`/`_detect_kline_patterns` 加 `volume_ext` 透传；④`compute_volume_price_signal` 加 `volume_ext` 透传；⑤`calc_macd` 升级 precomputed 版（411 Phase 5）。
  - **dim3 删 vendored 块**：4760→252 行（删 4508 行：volume_price_strategy 双份 + kline_pattern 双份），保留 dim3 独有 `_MACD_PRECOMPUTED_CACHE`/`_load_precomputed_macd`/`calc_vol_ratio`/`classify_vol_ratio`/`_classify_granville`/`Dim3VPEngine`（vendored 块后对 vendored 符号零引用，删除后无需新增 import）。
  - **测试改指**：test_dim3_patterns（EPD/VolumeStateAnalyzer/compute_volume_price_signal）与 test_411_pipeline calc_macd 改 `from app.engine.framework.volume_price_strategy import ...`。
- 验证：①EPD 回迁等价预验证 900 组（60 种子×15 边界长度：5/6/10/11/20/21/25/30/55/60/61/65/120/250/300）新 raw==旧 raw **PASS**、precomputed==raw **PASS**；②VolumePriceStrategy.analyze 链 60 组（10 种子×6 长度）signal_output/volume_price_detail/stage 全一致 **PASS**；③pytest 10 套件 **93 passed**；④data_daemon + framework + dim3 import 面冒烟 OK；⑤RAW-2 冒烟 3/3（R1 chip_fund 无回归）。附：dim3 内联 `_detect_kline_patterns` 调 framework `compute_volume_price_signal` 却传 `volume_ext=` 恒 TypeError→恒兜底的潜伏 bug 随内联块删除而消失（该链是死代码）。

### R8：RAW-2 量价持久化扩字段（可选）
- 状态：✅ **已关闭（2026-09-26）**——①依赖条件（437-A D1-D7 拍板）已于 2026-09-20 满足并实施（机制层字段级编排 + 核查修正 5 项闭环）；②R8 本体（RAW-2 量价扩字段）与问题2 同源，问题2 已拍板维持现状关闭（479-3 已扩至 9 字段、464 dim3 定稿素材已齐）；③D1-D7 重审（2026-09-26 真实数据 4 股实证）确认 dim8 归集完整落地（见文末 R8 关闭登记）。
- 改动：无
- 验证：D1-D7 重审探针 `scripts/_443r8_d1d7_probe.py` 4/4 通过（subsections/summary 前置尾置/去重主源/缺维不产段全实证）

### 总回归
- pytest 相关套件：**93 passed**（2026-09-16 最终全量：test_411_pipeline / test_396_dim2_engine / test_419_dim5_compliance / test_dim3_patterns / test_436_b3_sandbox / test_442_vs_indicator / test_442_margin / test_443_r2_cost_ext / test_t63_breakout / test_426_phase2_structure；含 R1-R7 全部改动后重跑）
- make check：backend 无 Makefile（方案泛指），以 pytest 全量为准
- 文档头部 status 更新：✅ R1-R7 已实施、R8 待 437-A 拍板（v1.0）

## 三问关闭登记（2026-09-26，只读复核 + 用户拍板）

对 §二 三个待跟进问题做现状只读复核（443 后经历 446/450/455/464/467/479-3 等 dim3 改造），结论**全部关闭**：

| 问题 | 关闭结论 | 依据 |
|---|---|---|
| **问题1** health_score 精度降级 | **维持现状关闭** | ①health_score 已由 464 dim3 定稿判「迁 JUD（439 同批）」+ 479-1 清出 dim8 T 表 → 不再是 dim8 素材；②改其成分属判定逻辑（445 冻结边界）+ 439-A 推迟，JUD 定型前动必返工；③接回 momentum 需联动问题2（RAW-2 扩字段），应一并放 JUD 阶段。现状公式含 446 RPS 加分/450 背离扣分/形态偏差，非失真 |
| **问题2** RAW-2 量价持久化仅 6 字段 | **维持现状关闭** | ①479-3 A5/A8 已从 6 扩至 **9 字段**（+vp_state_label/vp_rule/divergence 三字段，实测 data_daemon features['volume_price'] 9 键）；②464 dim3 定稿补产出已全实现，momentum/共振不在定稿输出键 → dim8 素材按定稿已齐、不消费；③「分位序列预计算」（412 P6 完整落地）443 §五附录已登记建议另开号，与 437-A R8 联动 |
| **问题3** dim3 内联 vendored 双份 | **已由 R7 收敛关闭** | R7（2026-09-16）434 式审计收敛：dim3 删 4508 行 vendored 块（4760→252 行，现 432 行含 479-3 增量），framework 权威；§二问题3 原「方向待决策」为陈旧标注（R7 已选收敛方向）；附带消除 dim3 版 EPD `prev_ma` bug 与 `volume_ext=` 恒 TypeError 潜伏 bug |

**复核实证**：`dim3_vp_engine.py` 现 432 行（无 `VolumePriceStrategy` 类/vendored 代码，仅留 dim3 独有 `_classify_granville` 等）；`features['volume_price']`（data_daemon:3806）9 字段；framework `AnalysisResult.to_dict` 仍含 momentum/resonance/three_laws（算完即弃确认）。
**登记**：本节为三问关闭权威记录；R8 已另于下方关闭。

## R8 关闭登记（2026-09-26，437-A D1-D7 重审 + 用户拍板）

R8 依赖条件（437-A D1-D7）已于 2026-09-20 拍板并实施，本日对 D1-D7 做**当前落地重审**（8 股真实数据构建 seven_dim，探针 `scripts/_443r8_d1d7_probe.py` 4/4 通过）：

| 决策项 | 拍板（09-20） | 当前落地证据（2026-09-26 实证） | 状态 |
|---|---|---|---|
| D1 fund_chip 合一段内分两小节 | A | `fund_chip.subsections=['筹码成本','资金博弈']`；risk 段同构 `['价格位置','风险状态']` | ✅ |
| D2 收益驱动并入 summary 尾置 | A | summary 尾置：PE/PB 分位→FCF/股息/营收→陷阱→潜力六维（标注来源→第4维/第2维/3/第一层）→「估值条件 N/8 满足」；无独立 valuation 段 | ✅ |
| D3 第一层三段并入 summary 前置 | A | summary 前置：大盘趋势（沪深300/上证 481①）→大盘状态→板块定位/行业（481②）→个股行业位置（481③）→相对强弱 | ✅ |
| D4 跨维去重主源 | 按建议值 | emotion 无 stock 子句（主源 dim3）；筹码=dim4；支撑阻力绝对价=dim6；fina_health=dim6 | ✅ |
| D5 支撑阻力一致性 | 另议开号 | **461-11 已统一** `shared.calc_support_resistance`；核对报告实证 dim2/dim6 数值一致（000002 3.13/3.40）——无缺口，另议取消 | ✅ 实质闭环 |
| D6 B 路径持续字段 | 维持后续项 | 未纳入（437 §九 后续项单独开号） | ➖ 维持 |
| D7 缺维不产段 | A | 段键=6 键（无 signal/valuation 独立段）；缺维段不产 | ✅ |

**R8 关闭理由**：①D1-D7 依赖已满足并实证落地；②R8 本体（RAW-2 量价扩字段）与三问问题2 同源——已拍板维持现状（479-3 扩至 9 字段、464 dim3 定稿素材已齐、momentum/共振不在定稿输出键）；③future「分位序列预计算」（412 P6）已登记另开号，与 437-A R8 联动。**443 号全项（R1-R7 + 三问 + R8）至此全部关闭。**

**附带发现（探针维护项）**：`scripts/_479_seven_dim_probe.py` 断言过时——479-5 因果链升级后 text「因为」部分引用 audit 条件名「健康度评分」，触发旧断言"评分键不应产句"误报（8/8 股）。已改断言为检查评分键**值**模式（`健康度 N/10`/`形态评分`），非条件名。
