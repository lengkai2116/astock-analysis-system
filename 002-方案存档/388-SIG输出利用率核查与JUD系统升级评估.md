---
title: SIG输出利用率核查与JUD系统升级评估
type: 核查报告+升级评估
date: 2026-09-16
version: v1.0
status: 📋 待实施
related:
  - 378-SIG环节8维度能力梳理与输出确认
  - 387-JUD环节调优方案
  - 358-策略分析与判定架构方案
---

# 388 — SIG输出利用率核查与JUD系统升级评估

> **背景**：基于378号文档（SIG 8维度输出清单）× 实际引擎evaluate()返回结构 × JUD消费代码（dim_adapter/conflict_detector/arbiter/status_engine）的逐字段精确对照，核查SIG输出在JUD环节的真实利用率，并基于LLM Wiki知识库评估JUD系统升级空间。
>
> **方法**：6个Explore子代理并行核查6个维度引擎的实际evaluate()返回dict结构，逐行追踪dim_adapter.convert_to_dims_format()、conflict_detector.detect_conflicts()、arbiter.arbitrate()、status_engine._aggregate()/_assemble()的真实读取代码。

---

## 一、SIG输出利用率全景（基于实际代码）

| 维度 | 引擎实际输出字段数 | JUD实际读取字段数 | 实际利用率 | JUD未读取的高价值字段 |
|------|------------------|-----------------|-----------|-------------------|
| dim2 结构 | 35+ | 6 | **17%** | buy_sell_points_detail/chanlun_phase/trend_structure_signal |
| dim3 量价 | 38 | 3 | **8%** | state_machine_direction/multi_timeframe_consistency/momentum |
| dim4 筹码 | 30 | 4 | **13%** | fund_flow/cost_profit_ratio(引擎输出但JUD读tags)/phase_confidence |
| dim5 情绪 | 31 | 3 | **10%** | bociasi_quadrant/bociasi_fast_signal/bociasi_slow_signal |
| dim6 风险 | 22 | 8 | **36%** | event_details/risk_factors |
| dim7 估值 | 20 | 2 | **10%** | composite_rating/potential_score/pe_percentile_5y/fina_health(引擎值) |
| dim1 信号 | ~8 | 0 | **0%** | judgment整体未被提取 |
| dim8 总结 | ~6 | 0 | **0%** | 引擎输出未被接入dims |
| **总计** | **~190** | **26** | **14%** | — |

---

## 二、逐维度已消费字段清单

### dim2（17%）— 已消费6个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| judgment.structure | dim_adapter:118 | → dims.structure.state |
| judgment.light | dim_adapter:119 | → dims.structure.light |
| status_description.level_cross_score | dim_adapter:114-116 | → dims.structure.confidence（387号新增） |
| status_description.plain | dim_adapter:121 | → dims.structure.evidence |
| status_description.level_trends | status_engine:618 | → 背景周期过滤（387号§5.8） |
| status_description.divergence_type | conflict_detector:52 | → 致命冲突检测（387号5.2） |

### dim3（8%）— 已消费3个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| judgment.state(=vp_state) | dim_adapter:138 | → dims.vp.state |
| judgment.light | dim_adapter:139 | → dims.vp.light |
| judgment.continuous_value | dim_adapter:140 | → dims.vp.confidence |

### dim4（13%）— 已消费4个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| judgment.phase | dim_adapter:150 | → dims.chip_fund.state（中文映射） |
| judgment.direction | dim_adapter:153 | → dims.chip_fund.state（降级） |
| judgment.light | dim_adapter:152 | → dims.chip_fund.light |
| status_description.crowding_level | conflict_detector:78 | → 高拥挤警告 |

### dim5（10%）— 已消费3个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| status_description.temperature | dim_adapter:168 | → dims.emotion.confidence |
| status_description.time_rhythm | dim_adapter:227 | → dims.time.state |
| status_description.temperature（极端值） | conflict_detector:84-90 | → 温度极端警告 |

### dim6（36%）— 已消费8个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| judgment.risk_level(=level) | dim_adapter:184 | → dims.risk.state |
| judgment.light | dim_adapter:185 | → dims.risk.light |
| status_description.atr_pct | dim_adapter:180 + arbiter:192 | → risk confidence + P6阈值动态调整 |
| status_description.support_price | status_engine:778 | → advice_params.stop_loss_price |
| status_description.resistance_price | status_engine:780 | → advice_params.target_price |
| status_description.rr_value | status_engine:782 + conflict_detector:72 | → advice_params.risk_reward_ratio + 盈亏比警告 |
| status_description.invalidation | status_engine:784 | → advice_params.invalidation_conditions |
| status_description.atr_pct（2%风险规则） | status_engine:752-766 | → advice_params.risk_budget_position |

### dim7（10%）— 已消费2个字段

| 引擎字段 | JUD消费位置 | 消费方式 |
|---------|-----------|---------|
| judgment.valuation_level（嵌套dict） | dim_adapter:199-203 | → dims.valuation.state |
| judgment.overall_light | dim_adapter:207 | → dims.valuation.light |

---

## 三、JUD系统升级评估（基于知识库支撑）

### 3.1 知识库理论依据

| 知识库概念 | 核心要点 | 与JUD升级的关联 |
|-----------|---------|---------------|
| 信号冲突处理机制 | 因子冲突是常态；多指标共识≥2/3；三灯全绿才进场 | 冲突分层+多级别过滤 |
| 多指标共识机制 | 归一化+≥2/3方向一致才执行 | consensus_rate增强 |
| 市场状态依赖加权法 | 不同市场状态启用不同权重 | IC动态权重+情绪象限乘数 |
| 加权融合法 | IC加权/波动率倒数加权/相关性优化 | 权重引擎理论基础 |
| 凯利公式（仓位管理） | f=(bp-q)/b，半凯利辅助校准 | 2%风险规则的数学补充 |
| 多周期层级决策框架 | 背景周期→决策周期→执行周期；三灯全绿 | 背景周期过滤（已部分实施） |
| 标签化与仲裁机制 | 标签可组合（AND/OR） | buy_sell_points_detail接入仲裁 |

### 3.2 升级方案：基于SIG未消费高价值字段的JUD能力增强

#### 升级A：dim2买卖点详情接入仲裁（P1优先级）

**现状**：arbiter仅依赖tags.right_side_confirm（未确认/基础确认/强确认/否决），完全忽略dim2引擎的buy_sell_points_detail（含类型/级别/确认状态）。

**知识库依据**：《信号冲突处理机制》"标签化的可组合性——标签之间可逻辑组合（AND/OR）"

**升级方案**：
- 从dim_results.structure.status_description.buy_sell_points_detail提取买卖点列表
- confirmed=True的买点→增强right_side_confirm（如"基础确认"+confirmed买点→升级为"强确认"）
- confirmed=True的卖点→削弱right_side_confirm（如"强确认"+confirmed卖点→降级为"基础确认"）
- 多级别确认（日线+周线买卖点）→进一步增强

**预期效果**：仲裁输入从单一标签升级为多源验证，判定精度提升。

#### 升级B：dim7引擎输出替代tags粗粒度标签（P0优先级）

**现状**：JUD读取judgment.valuation_level.value（英文标签'high'/'low'等），完全忽略引擎精确计算的composite_rating（-2~+2连续值）和potential_score（0-100）。

**知识库依据**：《加权融合法》"信息系数（IC）加权法——根据历史IC值分配权重"；《统一投资决策框架》"四锚估值+7维潜力"

**升级方案**：
- composite_rating → 替代valuation_level英文标签，提供连续值估值判定
- potential_score → 接入factor维，替代当前固定"中性"状态
- pe_percentile_5y → 增强估值维置信度（分位>90%=高估确认）
- fina_health（引擎值）→ 替代tags粗粒度fina_health

**预期效果**：估值判定从粗粒度标签升级为连续值+多锚验证。

#### 升级C：dim3状态机方向接入维度判定（P1优先级）

**现状**：dim3的state_machine_direction（BUY/SELL/HOLD/WATCH）被丢弃，JUD仅消费vp_state标签。

**知识库依据**：《多指标共识机制》"多个独立指标同时发出同向信号时，信号可靠性显著提升"

**升级方案**：
- state_machine_direction → 增强dims.vp的方向判定（BUY=+1, SELL=-1, HOLD/WATCH=0）
- state_machine_confidence → 增强dims.vp置信度
- multi_timeframe_consistency → 周线+日线一致=信号强化

**预期效果**：量价维从单一标签升级为方向+置信度+多时间框架验证。

#### 升级D：dim5四象限接入权重调节（P2优先级）

**现状**：weight_engine已有EMOTION_MULTIPLIERS（LL=1.15, HH=0.75），但bociasi_quadrant未接入dims计算。

**知识库依据**：《市场状态依赖加权法》"根据市场状态实时调整权重"

**升级方案**：
- bociasi_quadrant → 作为权重乘数应用于dims.emotion和dims.risk的confidence
- bociasi_fast_signal → 增强emotion维方向判定
- bociasi_slow_signal → 增强valuation维长线性价比判定

**预期效果**：权重系统从静态矩阵升级为情绪象限感知的动态权重。

#### 升级E：dim4资金流向+拥挤度接入冲突检测（P2优先级）

**现状**：fund_flow（强流入/强流出）被丢弃；crowding_level已接入conflict_detector但cost_profit_ratio读的是tags而非引擎精确值。

**知识库依据**：《信号冲突处理机制》"因子拥挤与生命周期——有效因子被广泛使用后信号有效性下降"

**升级方案**：
- fund_flow → 接入dims.chip_fund的confidence（强流入=高置信度）
- cost_profit_ratio（引擎值）→ 替代tags.profit_ratio
- crowding_level HIGH → 增强conflict_detector的拥挤度权重
- phase_confidence → 增强chip_fund维置信度

**预期效果**：资金筹码维从3字段升级为7字段消费。

#### 升级F：dim6事件详情+风险因素接入仲裁（P3优先级）

**现状**：event_details（事件结构化详情）和risk_factors（风险因素列表）未被JUD消费。

**知识库依据**：《信号冲突处理机制》"多智能体架构——风控智能体拥有最高优先级，可直接否决"

**升级方案**：
- event_details → 接入conflict_detector（如lhb+regulatory同时出现=致命冲突）
- risk_factors → 接入L0软约束（如"财务异常+流动性风险"组合=增强position_coeff压缩）
- dist_to_prev_high_pct → 接入高位风险检测（>5%=追涨风险）

**预期效果**：风险维从8字段升级为12字段消费。

---

## 四、升级实施路径

### 优先级排序

| 优先级 | 升级项 | 预期利用率提升 | 复杂度 | 依赖 |
|--------|--------|-------------|--------|------|
| **P0** | B: dim7引擎输出接入 | +10% | 低 | 无 |
| **P1** | A: buy_sell_points_detail接入仲裁 | +5% | 低 | 无 |
| **P1** | C: dim3状态机方向接入 | +5% | 低 | 无 |
| **P2** | D: dim5四象限接入权重 | +5% | 中 | 无 |
| **P2** | E: dim4资金流向+拥挤度接入 | +5% | 中 | 无 |
| **P3** | F: dim6事件详情接入 | +3% | 中 | 无 |

### 预期效果

| 指标 | 当前值 | P0+P1后 | 全部实施后 |
|------|--------|---------|-----------|
| SIG利用率 | 14% | 34% | 57% |
| JUD消费字段数 | 26 | 42 | 58 |
| 估值判定精度 | 粗粒度标签 | 连续值+多锚 | 连续值+多锚+潜力 |
| 仲裁输入质量 | 单一标签 | 多源验证 | 多源+级别确认 |
| 权重调节能力 | 静态矩阵 | 静态+IC | 静态+IC+情绪象限 |

---

## 五、风险与约束

### 5.1 过拟合风险

- 新增约32个消费字段，每增加一个维度消耗研究员自由度（《过拟合防控》）
- 需通过P0回测框架验证新增字段对opportunity_state分布的影响
- 建议：分批实施，每批验证后再实施下一批

### 5.2 性能影响

- dim_results中status_description已包含所有字段，无需额外计算
- 新增字段读取增加约20行代码/维度，全市场5500只评估耗时增加<5%
- 实时诊断路径需验证双路径一致性

### 5.3 向后兼容

- 所有升级均为纯增量（新增字段读取），不改变现有字段消费逻辑
- advice_params新增字段向前兼容（JSON格式）
- dims格式不变（仍为{state, light, confidence, evidence}）

---

**文档版本**: v1.0
**编制日期**: 2026-09-16
**编制人**: MiMoCode
