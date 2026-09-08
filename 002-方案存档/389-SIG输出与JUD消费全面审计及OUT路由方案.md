---
title: SIG输出与JUD消费全面审计及OUT路由方案
type: 审计报告+路由规划
date: 2026-09-16
version: v1.0
status: 📋 待实施
related:
  - 378-SIG环节8维度能力梳理与输出确认
  - 387-JUD环节调优方案
  - 388-SIG输出利用率核查与JUD系统升级评估
---

# 389 — SIG输出与JUD消费全面审计及OUT路由方案

> **背景**：基于378号文档的SIG 8维度输出清单，逐一对照dim_adapter.py / conflict_detector.py / arbiter.py / status_engine.py的实际消费代码，精确审计每个字段的JUD使用情况，并制定未使用字段的OUT路由方案。
>
> **审计方法**：逐行追踪每个引擎evaluate()的status_description/judgment/audit返回结构，与JUD消费代码的字段读取路径一一对照。

---

## 一、dim1 信号确认引擎

### 1.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | 示例 | JUD消费 | 消费位置 |
|---|---------|--------|------|---------|---------|
| 1 | attribute | str | "右侧确认（基础确认）" | ❌ 未消费 | — |
| 2 | strength | str | "65/100（中等偏强）" | ❌ 未消费 | — |
| 3 | maintenance | str | "信号第15天（衰减中）" | ❌ 未消费 | — |
| 4 | risk_interaction | str | "风险等级中" | ❌ 未消费 | — |
| 5 | lifecycle_days | int | 15 | ❌ 未消费 | — |
| 6 | lifecycle_stage | str | "中期" | ❌ 未消费 | — |
| 7 | verified | bool | True | ❌ 未消费 | — |
| 8 | decay_detail | str | "衰减原因..." | ❌ 未消费 | — |
| 9 | plain | str | "信号确认状态：..." | ❌ 未消费 | — |

### 1.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | attribute.code | str | ❌ 未消费 | — |
| 2 | attribute.light | str | ❌ 未消费 | — |
| 3 | strength.level | str | ❌ 未消费 | — |
| 4 | strength.light | str | ❌ 未消费 | — |
| 5 | maintenance.status | str | ❌ 未消费 | — |
| 6 | maintenance.light | str | ❌ 未消费 | — |
| 7 | overall_light | str | ❌ 未消费 | — |
| 8 | overall_direction | int | ❌ 未消费 | — |
| 9 | continuous_value | float | ❌ 未消费 | — |

### 1.3 利用率

**0/9 status_description字段 + 0/9 judgment字段 = 0%**

dim1引擎的全部输出均未被JUD消费。当前JUD仅通过tags.right_side_confirm读取信号确认状态，完全无视dim1引擎的结构化分析结果。

---

## 二、dim2 结构位置引擎

### 2.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | chanlun_direction | str | ✅ 已消费 | dim_adapter:118 → dims.structure.state |
| 2 | chanlun_direction_evidence | str | ✅ 已消费 | dim_adapter:121 → dims.structure.evidence |
| 3 | chanlun_phase | str | ❌ 未消费 | — |
| 4 | chanlun_phase_evidence | str | ❌ 未消费 | — |
| 5 | chanlun_strength | float | ❌ 未消费 | — |
| 6 | chanlun_strength_components | dict | ❌ 未消费 | — |
| 7 | chanlun_strength_evidence | str | ❌ 未消费 | — |
| 8 | buy_sell_points | list | ❌ 未消费 | — |
| 9 | buy_sell_points_detail | list | ✅ 已消费 | arbiter:191-219 → 增强/削弱right_side_confirm |
| 10 | buy_sell_points_evidence | str | ❌ 未消费 | — |
| 11 | divergence_type | str | ✅ 已消费 | conflict_detector:52-56 → 致命冲突检测 |
| 12 | divergence_strength | float | ❌ 未消费 | — |
| 13 | divergence_multi_algo | dict | ❌ 未消费 | — |
| 14 | divergence_detail | str | ❌ 未消费 | — |
| 15 | divergence_evidence | str | ❌ 未消费 | — |
| 16 | level_trends | str | ✅ 已消费 | status_engine:476-485 → 背景周期过滤 |
| 17 | level_cross_score | float | ✅ 已消费 | dim_adapter:114-116 → dims.structure.confidence |
| 18 | level_confirmed | bool | ❌ 未消费 | — |
| 19 | level_adjustment | float | ❌ 未消费 | — |
| 20 | level_evidence | str | ❌ 未消费 | — |
| 21 | trend_structure_signal | str | ❌ 未消费 | — |
| 22 | trend_structure_strength | str | ❌ 未消费 | — |
| 23 | trend_structure_detail | list | ❌ 未消费 | — |
| 24 | trend_structure_evidence | str | ❌ 未消费 | — |
| 25 | fractals_summary | dict | ❌ 未消费 | — |
| 26 | segments_summary | dict | ❌ 未消费 | — |
| 27 | divergence_segments | dict | ❌ 未消费 | — |
| 28 | plain | str | ✅ 已消费 | dim_adapter:121 → dims.structure.evidence |

### 2.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | structure | str | ✅ 已消费 | dim_adapter:118 → dims.structure.state |
| 2 | light | str | ✅ 已消费 | dim_adapter:119 → dims.structure.light |
| 3 | overall_direction | int | ❌ 未消费 | — |
| 4 | overall_light | str | ❌ 未消费 | — |
| 5 | continuous_value | float | ❌ 未消费 | — |

### 2.3 利用率

**7/28 status_description + 2/5 judgment = 9/33 = 27%**

---

## 三、dim3 量价健康度引擎

### 3.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | vp_state | str | ✅ 已消费 | dim_adapter:157 → dims.vp.state |
| 2 | vp_state_evidence | str | ❌ 未消费 | — |
| 3 | divergence | str | ❌ 未消费 | — |
| 4 | divergence_evidence | str | ❌ 未消费 | — |
| 5 | volume_energy | str | ❌ 未消费 | — |
| 6 | volume_energy_evidence | str | ❌ 未消费 | — |
| 7 | pattern | str | ❌ 未消费 | — |
| 8 | pattern_evidence | str | ❌ 未消费 | — |
| 9 | vol_ratio | str | ❌ 未消费 | — |
| 10 | granville | str | ❌ 未消费 | — |
| 11 | granville_evidence | str | ❌ 未消费 | — |
| 12 | state_machine_state | str | ❌ 未消费 | — |
| 13 | state_machine_direction | str | ✅ 已消费 | dim_adapter:141-147 → 增强vp置信度 |
| 14 | state_machine_confidence | float | ❌ 未消费 | — |
| 15 | state_machine_label | str | ❌ 未消费 | — |
| 16 | state_machine_position | str | ❌ 未消费 | — |
| 17 | state_machine_holding | str | ❌ 未消费 | — |
| 18 | state_machine_evidence | str | ❌ 未消费 | — |
| 19 | stage_name | str | ❌ 未消费 | — |
| 20 | stage_confidence | float | ❌ 未消费 | — |
| 21 | stage_valuation | str | ❌ 未消费 | — |
| 22 | stage_trend | str | ❌ 未消费 | — |
| 23 | stage_ma_alignment | str | ❌ 未消费 | — |
| 24 | vol_state_trend | str | ❌ 未消费 | — |
| 25 | vol_state_structure | str | ❌ 未消费 | — |
| 26 | vol_state_pattern | str | ❌ 未消费 | — |
| 27 | vol_state_institutional | str | ❌ 未消费 | — |
| 28 | three_laws | dict | ❌ 未消费 | — |
| 29 | resonance_score | int | ❌ 未消费 | — |
| 30 | momentum | dict | ❌ 未消费 | — |
| 31 | multi_timeframe_consistency | str | ✅ 已消费 | dim_adapter:149-155 → 增强/弱化vp置信度 |
| 32 | multi_timeframe_weekly_stage | str | ❌ 未消费 | — |
| 33 | multi_timeframe_weekly_direction | str | ❌ 未消费 | — |
| 34 | entry_zone | list | ✅ 已消费 | status_engine:649-651 → advice_params.entry_zone |
| 35 | risk_line | float | ❌ 未消费 | — |
| 36 | target_zone | list | ❌ 未消费 | — |
| 37 | evidence | str | ❌ 未消费 | — |
| 38 | risk_notes | list | ❌ 未消费 | — |
| 39 | plain | str | ❌ 未消费 | — |

### 3.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | vp_state | str | ✅ 已消费 | dim_adapter:157 → dims.vp.state |
| 2 | light | str | ✅ 已消费 | dim_adapter:158 → dims.vp.light |
| 3 | overall_direction | int | ❌ 未消费 | — |
| 4 | overall_light | str | ❌ 未消费 | — |
| 5 | continuous_value | float | ✅ 已消费 | dim_adapter:138 → dims.vp.confidence |

### 3.3 利用率

**5/39 status_description + 3/5 judgment = 8/44 = 18%**

---

## 四、dim4 资金与筹码引擎

### 4.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | phase | str | ✅ 已消费 | dim_adapter:170-171 → dims.chip_fund.state |
| 2 | phase_detail | str | ❌ 未消费 | — |
| 3 | phase_confidence | float | ✅ 已消费 | dim_adapter:175-177 → dims.chip_fund.confidence |
| 4 | phase_evidence | str | ❌ 未消费 | — |
| 5 | fund_flow | str | ✅ 已消费 | dim_adapter:179-185 → dims.chip_fund.evidence |
| 6 | fund_flow_detail | str | ❌ 未消费 | — |
| 7 | fund_flow_evidence | str | ❌ 未消费 | — |
| 8 | cost_structure | str | ❌ 未消费 | — |
| 9 | cost_concentration | str | ❌ 未消费 | — |
| 10 | cost_quality | str | ❌ 未消费 | — |
| 11 | cost_asr | float | ❌ 未消费 | — |
| 12 | cost_cyqkl | float | ❌ 未消费 | — |
| 13 | cost_profit_ratio | float | ✅ 已消费 | conflict_detector:36-43 → 获利盘冲突检测 |
| 14 | cost_evidence | str | ❌ 未消费 | — |
| 15 | signal | str | ❌ 未消费 | — |
| 16 | signal_type | str | ❌ 未消费 | — |
| 17 | signal_evidence | str | ❌ 未消费 | — |
| 18 | retail_institution | str | ❌ 未消费 | — |
| 19 | retail_institution_evidence | str | ❌ 未消费 | — |
| 20 | margin | str | ❌ 未消费 | — |
| 21 | margin_change_5d | float | ❌ 未消费 | — |
| 22 | margin_evidence | str | ❌ 未消费 | — |
| 23 | crowding | str | ❌ 未消费 | — |
| 24 | crowding_level | str | ✅ 已消费 | conflict_detector:76-80 → 拥挤度警告 |
| 25 | crowding_score | float | ❌ 未消费 | — |
| 26 | crowding_detail | str | ❌ 未消费 | — |
| 27 | crowding_evidence | str | ❌ 未消费 | — |
| 28 | pde_price_position | str | ❌ 未消费 | — |
| 29 | pde_trend | str | ❌ 未消费 | — |
| 30 | pde_conflict | bool | ❌ 未消费 | — |
| 31 | pde_vote_ratio | str | ❌ 未消费 | — |
| 32 | evidence | str | ❌ 未消费 | — |
| 33 | plain | str | ❌ 未消费 | — |

### 4.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | phase | str | ✅ 已消费 | dim_adapter:170-171 → dims.chip_fund.state |
| 2 | direction | str | ✅ 已消费 | dim_adapter:187 → dims.chip_fund.state(降级) |
| 3 | light | str | ✅ 已消费 | dim_adapter:189 → dims.chip_fund.light |
| 4 | overall_direction | int | ❌ 未消费 | — |
| 5 | overall_light | str | ❌ 未消费 | — |
| 6 | continuous_value | float | ❌ 未消费 | — |

### 4.3 利用率

**6/33 status_description + 3/6 judgment = 9/39 = 23%**

---

## 五、dim5 情绪环境引擎

### 5.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | market_phase | str | ✅ 已消费 | status_engine:393 → emotion_position_cap |
| 2 | market_detail | str | ❌ 未消费 | — |
| 3 | market_light | str | ❌ 未消费 | — |
| 4 | bociasi_quadrant | str | ✅ 已消费 | weight_engine:111 → 权重乘数 + dim_adapter:216 → evidence |
| 5 | bociasi_quadrant_desc | str | ❌ 未消费 | — |
| 6 | bociasi_fast_signal | str | ✅ 已消费 | dim_adapter:208-214 → 增强emotion置信度 |
| 7 | bociasi_fast_confidence | float | ❌ 未消费 | — |
| 8 | bociasi_slow_signal | str | ❌ 未消费 | — |
| 9 | bociasi_slow_confidence | float | ❌ 未消费 | — |
| 10 | temperature | float | ✅ 已消费 | dim_adapter:203-206 → dims.emotion.confidence + conflict_detector:84-90 → 温度极端警告 + status_engine:647 → advice_params.temperature |
| 11 | temperature_level | str | ❌ 未消费 | — |
| 12 | time_rhythm | str | ✅ 已消费 | dim_adapter:332-337 → dims.time.state |
| 13 | sector_heat | str | ⚠️ 间接 | 通过tags.sector_heat(非引擎输出) |
| 14 | sector_detail | str | ❌ 未消费 | — |
| 15 | sector_name | str | ❌ 未消费 | — |
| 16 | sector_rank | int | ❌ 未消费 | — |
| 17 | sector_evidence | str | ❌ 未消费 | — |
| 18 | stock_emotion | str | ⚠️ 间接 | 通过tags.stock_emotion(非引擎输出) |
| 19 | stock_detail | str | ❌ 未消费 | — |
| 20 | stock_evidence | str | ❌ 未消费 | — |
| 21 | market_evidence | str | ❌ 未消费 | — |
| 22 | plain | str | ❌ 未消费 | — |

### 5.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | market_light | str | ❌ 未消费 | — |
| 2 | sector_light | str | ❌ 未消费 | — |
| 3 | stock_light | str | ❌ 未消费 | — |
| 4 | overall_light | str | ❌ 未消费 | — |
| 5 | overall_direction | int | ❌ 未消费 | — |
| 6 | continuous_value | float | ❌ 未消费 | — |

### 5.3 利用率

**5/22 status_description + 0/6 judgment = 5/28 = 18%**

---

## 六、dim6 风险边界引擎

### 6.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | risk_level | str | ✅ 已消费 | dim_adapter:232 → dims.risk.state |
| 2 | risk_detail | str | ❌ 未消费 | — |
| 3 | risk_light | str | ❌ 未消费 | — |
| 4 | risk_factors | list | ✅ 已消费 | conflict_detector:105-107 → 风险因素密集警告 |
| 5 | support_price | float | ✅ 已消费 | status_engine:637 → advice_params.stop_loss_price |
| 6 | resistance_price | float | ✅ 已消费 | status_engine:639 → advice_params.target_price |
| 7 | dist_to_support_pct | float | ❌ 未消费 | — |
| 8 | dist_to_resistance_pct | float | ❌ 未消费 | — |
| 9 | dist_to_prev_high_pct | float | ✅ 已消费 | conflict_detector:109-116 → 高位追涨风险 |
| 10 | rr_value | float | ✅ 已消费 | status_engine:641 → advice_params.risk_reward_ratio + conflict_detector:72-74 → 盈亏比不足警告 |
| 11 | rr_level | str | ❌ 未消费 | — |
| 12 | rr_assessment | str | ❌ 未消费 | — |
| 13 | volatility_level | str | ❌ 未消费 | — |
| 14 | atr_14d | float | ❌ 未消费 | — |
| 15 | atr_pct | float | ✅ 已消费 | dim_adapter:228-230 → dims.risk.confidence + arbiter:224-238 → P6阈值动态调整 + status_engine:645 → advice_params.atr_pct |
| 16 | volatility_percentile | float | ❌ 未消费 | — |
| 17 | signal_days | int | ❌ 未消费 | — |
| 18 | invalidation | list | ✅ 已消费 | status_engine:643 → advice_params.invalidation_conditions |
| 19 | event_count | int | ❌ 未消费 | — |
| 20 | event_details | list | ✅ 已消费 | conflict_detector:97-103 → 多负面事件冲突 |
| 21 | event_summary | list | ❌ 未消费 | — |
| 22 | risk_evidence | str | ❌ 未消费 | — |
| 23 | plain | str | ❌ 未消费 | — |

### 6.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | level | str | ✅ 已消费 | dim_adapter:232 → dims.risk.state |
| 2 | light | str | ✅ 已消费 | dim_adapter:233 → dims.risk.light |
| 3 | overall_light | str | ❌ 未消费 | — |
| 4 | overall_direction | int | ❌ 未消费 | — |
| 5 | continuous_value | float | ❌ 未消费 | — |

### 6.3 利用率

**10/23 status_description + 2/5 judgment = 12/28 = 43%**

---

## 七、dim7 估值引擎

### 7.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | valuation_level | str | ✅ 已消费 | dim_adapter:248-267 → dims.valuation.state（composite_rating判定） |
| 2 | valuation_level_cn | str | ❌ 未消费 | — |
| 3 | composite_rating | float | ✅ 已消费 | dim_adapter:249-260 → 替代valuation_level英文标签 |
| 4 | valuation_deviation | float | ❌ 未消费 | — |
| 5 | asset_anchor_rating | float | ❌ 未消费 | — |
| 6 | earnings_anchor_rating | float | ❌ 未消费 | — |
| 7 | cashflow_anchor_rating | float | ❌ 未消费 | — |
| 8 | adjusted_anchor_rating | float | ❌ 未消费 | — |
| 9 | pe_percentile_5y | float | ✅ 已消费 | dim_adapter:271-277 → dims.valuation.confidence |
| 10 | pb_percentile_5y | float | ❌ 未消费 | — |
| 11 | ps_percentile_5y | float | ❌ 未消费 | — |
| 12 | fcf_yield | float | ❌ 未消费 | — |
| 13 | dividend_yield | float | ❌ 未消费 | — |
| 14 | revenue_growth | float | ❌ 未消费 | — |
| 15 | fina_health | str | ✅ 已消费 | dim_adapter:314-325 → dims.finance.state |
| 16 | roce_pass | bool | ❌ 未消费 | — |
| 17 | potential_score | int | ✅ 已消费 | dim_adapter:282-304 → dims.factor.state + dims.valuation.evidence |
| 18 | potential_breakdown | str | ❌ 未消费 | — |
| 19 | valuation_evidence | str | ❌ 未消费 | — |
| 20 | plain | str | ❌ 未消费 | — |

### 7.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | valuation_level | dict | ✅ 已消费 | dim_adapter:263-267 → dims.valuation.state（降级路径） |
| 2 | light | str | ❌ 未消费 | — |
| 3 | overall_light | str | ✅ 已消费 | dim_adapter:287 → dims.valuation.light |
| 4 | overall_direction | int | ❌ 未消费 | — |
| 5 | continuous_value | float | ❌ 未消费 | — |

### 7.3 利用率

**6/20 status_description + 2/5 judgment = 8/25 = 32%**

---

## 八、dim8 状态总结引擎

### 8.1 引擎输出结构（status_description）

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | status_bar | str | ❌ 未消费 | — |
| 2 | eight_dim_summary | list | ❌ 未消费 | — |
| 3 | consensus_rate | str | ❌ 未消费 | — |
| 4 | conflict_count | int | ❌ 未消费 | — |
| 5 | conflicts | list | ❌ 未消费 | — |
| 6 | text | str | ❌ 未消费 | — |
| 7 | plain | str | ❌ 未消费 | — |

### 8.2 judgment输出

| # | 输出字段 | 值类型 | JUD消费 | 消费位置 |
|---|---------|--------|---------|---------|
| 1 | status_bar | str | ❌ 未消费 | — |
| 2 | status_bar_cn | str | ❌ 未消费 | — |
| 3 | consensus_rate | float | ❌ 未消费 | — |
| 4 | direction | int | ❌ 未消费 | — |
| 5 | overall_light | str | ❌ 未消费 | — |
| 6 | overall_direction | int | ❌ 未消费 | — |

### 8.3 利用率

**0/7 status_description + 0/6 judgment = 0%**

dim8的全部输出均未被JUD消费。dim8通过status_engine.evaluate()调用后存储在dim_engine_results中，但dim_adapter/aggregate/assemble均未读取dim8的任何字段。

---

## 九、全维度利用率汇总

| 维度 | 引擎 | status_desc字段数 | judgment字段数 | 总字段数 | JUD消费数 | 利用率 |
|------|------|------------------|---------------|---------|----------|--------|
| dim1 信号确认 | Dim1SignalEngine | 9 | 9 | 18 | 0 | **0%** |
| dim2 结构位置 | Dim2StructureEngine | 28 | 5 | 33 | 9 | **27%** |
| dim3 量价健康 | Dim3VPEngine | 39 | 5 | 44 | 8 | **18%** |
| dim4 资金筹码 | Dim4ChipFundEngine | 33 | 6 | 39 | 9 | **23%** |
| dim5 情绪环境 | Dim5EmotionEngine | 22 | 6 | 28 | 5 | **18%** |
| dim6 风险边界 | Dim6RiskEngine | 23 | 5 | 28 | 12 | **43%** |
| dim7 估值 | Dim7ValuationEngine | 20 | 5 | 25 | 8 | **32%** |
| dim8 状态总结 | Dim8SummaryEngine | 7 | 6 | 13 | 0 | **0%** |
| **总计** | — | **181** | **47** | **228** | **51** | **22%** |

**核心发现**：8个维度引擎共产出228个结构化字段，JUD仅消费其中51个（22%）。**177个字段未被JUD使用**。

---

## 十、未使用字段的OUT路由方案

### 10.1 路由原则

| 原则 | 说明 |
|------|------|
| **dim_engine_results全量透传** | 当前status_engine已将dim_engine_results整体JSON写入status_snapshot，OUT可直接读取 |
| **evidence字段优先透传** | 每个引擎的evidence/plain字段是用户可读的现状描述文本，前端展示价值最高 |
| **结构化数值字段选择性透传** | 高价值数值字段（如价位、百分位、评分）供前端图表组件使用 |
| **judgment字段不重复透传** | judgment已被JUD消费并转化为dims格式，前端通过dim_states展示，无需重复 |

### 10.2 各维度OUT路由建议

#### dim1 信号确认 → **建议直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| attribute | ⭐⭐⭐ 信号属性+详情 | OUT直接展示 |
| strength | ⭐⭐⭐ 信号强度评分 | OUT直接展示 |
| maintenance | ⭐⭐ 信号衰减状态 | OUT直接展示 |
| lifecycle_days | ⭐⭐ 信号持续天数 | OUT直接展示 |
| lifecycle_stage | ⭐⭐ 生命周期阶段 | OUT直接展示 |
| verified | ⭐ 是否已验证 | OUT直接展示 |
| overall_light | ⭐⭐⭐ 信号灯色 | OUT直接展示 |

**说明**：dim1完全未被JUD消费，但其输出对用户理解"当前信号处于什么状态"极有价值。建议在OUT环节从dim_engine_results.signal.status_description直接提取展示。

#### dim2 结构位置 → **未使用高价值字段直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| chanlun_phase | ⭐⭐⭐ 走势健康度（未病/欲病） | OUT直接展示 |
| chanlun_strength | ⭐⭐ 结构强度0-1 | OUT直接展示 |
| buy_sell_points_detail | ⭐⭐⭐ 买卖点详情 | OUT直接展示 |
| divergence_type | ⭐⭐⭐ 背驰类型 | OUT直接展示（conflict_detector已用于冲突检测） |
| divergence_strength | ⭐⭐ 背驰强度 | OUT直接展示 |
| level_trends | ⭐⭐⭐ 多周期趋势 | OUT直接展示 |
| level_cross_score | ⭐⭐ 级别一致性 | OUT直接展示 |
| trend_structure_signal | ⭐⭐ 123法则信号 | OUT直接展示 |
| fractals_summary | ⭐ 分型分析 | OUT直接展示 |
| segments_summary | ⭐ 线段分析 | OUT直接展示 |
| vs_zhongshu.* | ⭐⭐ 中枢分析 | OUT直接展示 |
| vs_ma.* | ⭐⭐ 均线分析 | OUT直接展示 |
| vs_sr.* | ⭐⭐⭐ 支撑阻力 | OUT直接展示 |
| vs_indicator.* | ⭐⭐ 技术指标 | OUT直接展示 |

#### dim3 量价健康 → **大量高价值字段建议直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| state_machine_direction | ⭐⭐⭐ 状态机方向(BUY/SELL/HOLD) | OUT直接展示 |
| state_machine_confidence | ⭐⭐ 状态机置信度 | OUT直接展示 |
| stage_name | ⭐⭐⭐ 趋势阶段(UPTREND_ACTIVE等) | OUT直接展示 |
| stage_valuation | ⭐⭐ 估值区间 | OUT直接展示 |
| multi_timeframe_consistency | ⭐⭐⭐ 多时间框架一致性 | OUT直接展示 |
| momentum | ⭐⭐ 多空动量 | OUT直接展示 |
| three_laws | ⭐⭐ 威科夫三定律 | OUT直接展示 |
| entry_zone / risk_line / target_zone | ⭐⭐⭐⭐ 入场/止损/目标价位 | OUT直接展示（entry_zone已接入advice_params） |
| divergence | ⭐⭐⭐ 量价背离信号 | OUT直接展示 |
| volume_energy | ⭐⭐ 量能强度 | OUT直接展示 |
| pattern | ⭐⭐ 量价形态 | OUT直接展示 |
| granville | ⭐ 格兰威尔准则 | OUT直接展示 |

#### dim4 资金筹码 → **部分高价值字段直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| cost_profit_ratio | ⭐⭐⭐ 获利盘比例 | OUT直接展示 |
| cost_concentration | ⭐⭐ 筹码集中度 | OUT直接展示 |
| cost_asr | ⭐⭐ 活跃筹码比率 | OUT直接展示 |
| fund_flow_detail | ⭐⭐ 资金流向详情 | OUT直接展示 |
| retail_institution | ⭐⭐ 散户与机构分析 | OUT直接展示 |
| crowding_level | ⭐⭐⭐ 拥挤度 | OUT直接展示 |
| crowding_score | ⭐⭐ 拥挤度分数 | OUT直接展示 |
| pde_price_position | ⭐⭐ PDE价格位置 | OUT直接展示 |
| pde_conflict | ⭐ 阶段冲突 | OUT直接展示 |

#### dim5 情绪环境 → **部分字段直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| bociasi_quadrant_desc | ⭐⭐ 象限含义 | OUT直接展示 |
| bociasi_fast_signal | ⭐⭐⭐ 快线信号 | OUT直接展示 |
| bociasi_fast_confidence | ⭐⭐ 快线置信度 | OUT直接展示 |
| bociasi_slow_signal | ⭐⭐⭐ 慢线信号 | OUT直接展示 |
| bociasi_slow_confidence | ⭐⭐ 慢线置信度 | OUT直接展示 |
| temperature_level | ⭐ 温度等级 | OUT直接展示 |
| market_evidence | ⭐⭐⭐ 市场情绪完整证据链 | OUT直接展示 |
| sector_name + sector_rank | ⭐⭐ 行业名称+排名 | OUT直接展示 |
| sector_evidence | ⭐⭐ 板块证据链 | OUT直接展示 |
| stock_evidence | ⭐⭐ 个股情绪证据链 | OUT直接展示 |

#### dim6 风险边界 → **部分字段直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| risk_detail | ⭐⭐ 风险详情 | OUT直接展示 |
| dist_to_support_pct | ⭐⭐ 距防守位百分比 | OUT直接展示 |
| dist_to_resistance_pct | ⭐⭐ 距压力位百分比 | OUT直接展示 |
| rr_level | ⭐⭐ 盈亏比等级 | OUT直接展示 |
| rr_assessment | ⭐⭐ 盈亏比描述 | OUT直接展示 |
| volatility_level | ⭐⭐ 波动率等级 | OUT直接展示 |
| atr_14d | ⭐⭐ ATR数值 | OUT直接展示 |
| volatility_percentile | ⭐⭐ 波动率历史分位 | OUT直接展示 |
| signal_days | ⭐ 突破天数 | OUT直接展示 |
| event_summary | ⭐⭐ 事件摘要 | OUT直接展示 |
| risk_evidence | ⭐⭐⭐ 风险完整证据链 | OUT直接展示 |

#### dim7 估值 → **大量高价值字段建议直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| composite_rating | ⭐⭐⭐⭐ 综合估值评分 | OUT直接展示 |
| valuation_deviation | ⭐⭐⭐ 估值偏离度 | OUT直接展示 |
| pe_percentile_5y | ⭐⭐⭐ PE近5年百分位 | OUT直接展示 |
| pb_percentile_5y | ⭐⭐⭐ PB近5年百分位 | OUT直接展示 |
| ps_percentile_5y | ⭐⭐ PS近5年百分位 | OUT直接展示 |
| dividend_yield | ⭐⭐⭐ 股息率 | OUT直接展示 |
| fcf_yield | ⭐⭐ 自由现金流收益率 | OUT直接展示 |
| revenue_growth | ⭐⭐ 营收增长率 | OUT直接展示 |
| asset_anchor_rating | ⭐⭐ PB资产锚 | OUT直接展示 |
| earnings_anchor_rating | ⭐⭐ PE收益锚 | OUT直接展示 |
| cashflow_anchor_rating | ⭐⭐ FCF现金流锚 | OUT直接展示 |
| adjusted_anchor_rating | ⭐ 调整PE锚 | OUT直接展示 |
| potential_breakdown | ⭐⭐⭐ 潜力6维明细 | OUT直接展示 |
| roce_pass | ⭐ ROCE达标 | OUT直接展示 |
| valuation_evidence | ⭐⭐⭐ 估值完整证据链 | OUT直接展示 |

#### dim8 状态总结 → **建议直通OUT**

| 字段 | OUT展示价值 | 建议路由 |
|------|-----------|---------|
| status_bar | ⭐⭐⭐ 状态条 | OUT直接展示 |
| eight_dim_summary | ⭐⭐⭐ 八维红绿灯总览 | OUT直接展示 |
| consensus_rate | ⭐⭐ 共识率 | OUT直接展示 |
| conflicts | ⭐⭐ 冲突列表 | OUT直接展示 |
| text | ⭐⭐⭐ 综合文字描述 | OUT直接展示 |

### 10.3 实施路径

#### 路径1：OUT环节从dim_engine_results直接读取（推荐，零代码改动）

当前status_engine已将dim_engine_results整体JSON写入status_snapshot.dim_engine_results列。OUT环节可直接读取并按维度拆分展示。

**优点**：无需修改JUD代码，OUT直接消费引擎原始输出
**缺点**：OUT需要解析大量JSON字段，前端需适配

#### 路径2：在status_snapshot中新增seven_dim_json字段

参考generate_seven_dim_from_signals()函数的思路，为每个维度新增结构化的OUT展示数据。

**优点**：前端展示数据结构化，读取方便
**缺点**：需要status_engine新增字段组装逻辑

#### 路径3：dim_engine_results + 前端按需解析（折中方案）

保持dim_engine_results全量存储，前端根据维度配置文件按需解析展示。

**优点**：灵活，新增字段无需后端改动
**缺点**：前端配置复杂度增加

### 10.4 各维度路由优先级

| 优先级 | 维度 | 原因 | 建议路由 |
|--------|------|------|---------|
| **P0** | dim7 估值 | 利用率低但字段价值极高，用户最关心估值 | 路径1+前端适配 |
| **P0** | dim1 信号确认 | 利用率0%，信号状态对用户极有价值 | 路径1+前端适配 |
| **P1** | dim8 状态总结 | 利用率0%，但已是综合性信息 | 路径1+前端适配 |
| **P1** | dim3 量价健康 | 39个字段仅消费5个，大量高价值字段浪费 | 路径1+前端适配 |
| **P2** | dim2 结构位置 | 已有部分消费，补充未使用的高价值字段 | 路径1+前端适配 |
| **P2** | dim4 资金筹码 | 已有部分消费，补充拥挤度/获利盘等 | 路径1+前端适配 |
| **P3** | dim5 情绪环境 | 已有部分消费，补充快慢线/象限描述 | 路径1+前端适配 |
| **P3** | dim6 风险边界 | 利用率最高(43%)，补充波动率/事件等 | 路径1+前端适配 |

---

**文档版本**: v1.0
**编制日期**: 2026-09-16
**编制人**: MiMoCode
