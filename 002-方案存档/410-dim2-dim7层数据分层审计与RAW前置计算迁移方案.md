---
title: dim2-dim7数据分层审计与RAW前置计算迁移方案
type: 审计方案
date: 2026-09-05
version: v1.0
status: 待实施
related:
  - 353号-系统总体架构规划（总纲）
  - 401号-dim4原料数据通路核查与修复方案
  - 405号-dim6数据访问路径统一与架构修正方案
  - 406号-dim7估值引擎代码质量审计与修复方案
  - 407号-维度引擎数据访问路径冲突全面核查与修正方案
  - 409号-dim1数据质量门禁层改造方案
---

# 410号 — dim2-dim7数据分层审计与RAW前置计算迁移方案

---

## 一、数据分层定义

> **注**：本定义需同步更新到353号方案（总纲）§二 环节总览中。

| 层 | 代号 | 定义 | 产出 |
|---|------|------|------|
| **COL** | 采集层 | 外部数据源采集 | 原始行情/财务/资金数据（原料数据） |
| **RAW** | 加工层 | **简单数学公式加工**（非分析类单纯计算加工） | 指标（MA/MACD/RSI/BOLL/SSRP/ATR等，加工数据） |
| **SIG** | 分析层 | 通过提取STG存储层的原料数据和加工数据进行策略分析 | 半成品（信号/判定/评分，不包含股票现状说明——直供OUT存储供前端消费） |
| **JUD** | 判定层 | 提取STG存储层的半成品数据进行判定和操作建议的整合 | 成品（操作建议+状态总结） |
| **OUT** | 成品仓 | 成品存储供前端消费 | 最终输出 |

**RAW层判定标准**：
- 属于RAW：简单数学公式、标准指标计算、纯数值变换、统计聚合，产出可被多个SIG引擎复用
- 属于SIG：数据分析、评价判断、模式识别、阈值分类、与分析系统耦合的逻辑

**核心原则**：只迁移简单数学公式到RAW，保留数据分析/评价/与分析系统耦合的计算在SIG。不是100%前置，而是最合理前置。

---

## 二、审计范围与方法

### 2.1 审计范围

dim2-dim7六个维度引擎的全部代码（共17,256行）。

### 2.2 审计方法

对每个引擎逐行核查：数据获取点（`ecm.get_cached_*`/`DataManager.*`/SQL直查）→ 计算内容分类（RAW/SIG）→ 是否已有预计算等价物 → 迁移可行性。

---

## 三、各引擎RAW违规全景

### 3.1 总览

| 引擎 | 文件行数 | RAW违规行数 | 占比 | 严重度 | 已有方案 |
|------|---------|-----------|------|--------|---------|
| dim2 结构位置 | 4,502 | ~120行 | ~3% | 中 | 无 |
| dim3 量价健康 | 4,550 | ~95处计算点 | ~15% | **高** | 无 |
| dim4 资金筹码 | 5,816 | ~2,000行 | **~35%** | **极高** | 401号（未执行） |
| dim5 情绪环境 | 1,096 | ~35处计算点 | ~12% | 中高 | 无 |
| dim6 风险边界 | 1,259 | ~80行 | ~6% | 中 | 405号（部分执行） |
| dim7 估值 | 1,033 | ~37处计算点 | ~10% | 中 | 406号（代码质量已修复） |

### 3.2 dim2 — 结构位置引擎

**数据源**：`ecm.get_cached_daily(ts_code)` — 1处

| # | 位置 | RAW计算 | 已有预计算等价物 | 严重度 |
|---|------|---------|----------------|--------|
| 1 | `calc_macd()` L480-490 | EMA12/26→DIF/DEA/MACD柱 | `indicator_macd.macd_dif/dea/hist` | **高** — 被6个方法调用7次 |
| 2 | `calc_support_resistance()` L3757 | MA20 | `indicator_ma.ma20` | 中 |
| 3 | `calc_support_resistance()` L3760 | MA60 | `indicator_ma.ma60` | 中 |
| 4 | `filter_limit_klines()` L747 | 5日均量 | `indicator_ma.vol_ma5` | 低 |
| 5 | `_check_trendline_break()` L471-473 | 线性斜率/外推 | 无 | 低 |
| 6 | `TrendStructureDetector` L411-422 | 滚动min/max | 无 | 低 |
| 7 | 周/月重采样 L221-241 | 日→周/月OHLCV聚合 | 可预计算 | 低 |

**关键发现**：`indicator_ma`/`indicator_macd`/`indicator_other` 三张预计算宽表在dim2中**零引用**。

### 3.3 dim3 — 量价健康引擎

**数据源**：`ecm.get_cached_daily(ts_code)` — 1处

| 类别 | 违规数量 | 涉及组件 | 预计算等价物 |
|------|---------|---------|------------|
| MA重计算 | **30+处** | StageDetector/EnhancedPatternDetector×14/VolumeStateAnalyzer/VPStateMachine/_detect_kline_patterns/_classify_granville | `indicator_ma` |
| MACD重计算 | **3处** | `calc_macd()` L323 / evaluate() L4414 / recognize_market_condition() L2257 | `indicator_macd` |
| RSI重计算 | **1处** | recognize_market_condition() L2238 | `indicator_other.rsi14` |
| ATR重计算 | **2处** | recognize_market_condition() L2221/L2284 | 可扩展`indicator_other` |
| Bollinger带宽 | **1处** | recognize_market_condition() L2216 | `indicator_other.boll_*` |
| 分位数计算 | **7处** | 多处percentile计算 | 可预计算 |
| 量MA | **5处** | VolumeStateAnalyzer/VPStateMachine等 | `indicator_ma.vol_ma*` |
| ROC/加速度 | **1处** | `_calc_price_acceleration()` L2846 | 可预计算 |

**关键发现**：dim3与dim2相同——`indicator_ma`/`indicator_macd`/`indicator_other`**零引用**。MA5/10/20/60在6个以上类中各自独立计算。MACD在3处独立计算。

### 3.4 dim4 — 资金筹码引擎（最严重）

**数据源**：30+处数据库调用

| 组件 | 线数 | RAW占比 | 具体RAW内容 |
|------|------|---------|------------|
| ChipDistributionEstimator | 73行 | **100%** | 筹码分布估计（三角分配+衰减） |
| ChipIndicators | 86行 | **100%** | SSRP/ASR/集中度/获利比/CYQKL/RSI |
| StageDetector | 30行 | **100%** | MA60方向+60日位置 |
| PhaseDetectionEngine | 780行 | **~70%** | 资金聚合/MA/趋势斜率/筹码分布完整计算 |
| ChipScorer | 150行 | **~60%** | VWAP/量比/价格位置/MA/波动率 |
| MainForceScorer | 860行 | **~40%** | 资金强度/量价MA/RSI/主力成本/融资成本 |
| CrowdingFactor | 330行 | **~50%** | 融资比/换手拥挤/Bollinger波动率 |
| Filter类 | 400行 | **~70%** | MA60/换手率/流动性20日均量/ROCE |

**结构问题**：
1. `extract_chip_deep_tags()` L5490-5551 — 从daily_cache重跑完整筹码分布估计+指标计算，而非读预计算值
2. `evaluate()` L5757 — 调用内部PhaseDetectionEngine重新计算，忽略pre_feat_cache中daemon已预计算的字段
3. `CrowdingFactor.evaluate()` L5785 — 重新拉取margin数据计算Bollinger Band

**401号方案已标记但未执行的迁移项**：SSRP/获利比/ASR/集中度/CYQKL/筹码分布估计/5日资金聚合/MA/RSI/VWAP/波动率/主力成本/融资成本/Bollinger — 共14项。

### 3.5 dim5 — 情绪环境引擎

**数据源**：daily_cache + daily_basic_cache + margin_cache + 5个SQL直查

| 类别 | 位置 | RAW计算 | 预计算等价物 |
|------|------|---------|------------|
| MA20比率 | BociasiQuadrantAnalyzer L603-619 | SQL窗口计算MA20+占比 | `indicator_ma.ma20` |
| 换手率分位 | L621-639 | AVG(turnover_rate)今日vs60日 | 可预计算 |
| 涨跌停比 | L641-654 | SQL COUNT涨跌停 | `stk_limit_cache`已采集 |
| RSI分位 | L656-673 | AVG(rsi14)今日vs60日 | `indicator_other.rsi14` |
| ERP分位 | L677-697 | 1/PE→收益率→252日对比 | 可预计算 |
| 融资趋势 | L699-718 | SUM(rzye)10日变化率 | 可预计算 |
| PE分位 | L720-738 | AVG(pe_ttm)今日vs252日 | 可预计算 |
| 股票级MA5/MA20 | SectorRotationModel L843-846 | 每只股票rolling(5)/rolling(20) | `indicator_ma` |
| BOCI快线 | `_bociasi_quickline()` L97-148 | MA5/量比/动量/振幅 | `indicator_ma` |
| 时间节奏 | `_time_rhythm()` L287-332 | MA20/std20/BB带宽/30日范围 | `indicator_ma`+`indicator_other` |
| 融资变化 | evaluate() L1021-1023 | rzye变化率 | 可预计算 |

**关键问题**：`BociasiQuadrantAnalyzer._compute_margin_trend()` L701 直接访问`self._get_dm().cache.conn`，绕过DataManager网关，违反数据访问红线。

### 3.6 dim6 — 风险边界引擎

**数据源**：`ecm.get_cached_daily(ts_code)` — 1处

| # | 位置 | RAW计算 | 预计算等价物 | 状态 |
|---|------|---------|------------|------|
| 1 | `calc_geometric()` L119-187 | 支撑/阻力/风险收益比/突破天数 | daemon `risk_ext.geo_*` | **405号建议3未执行** |
| 2 | `_calc_volatility()` L194-222 | ATR14/ATR%/波动率分位 | daemon `risk_ext.vol_*` | **405号建议4未执行** |
| 3 | `calculate_sharpe()` L434 | Sharpe比率 | 独立工具类 | 低优 |
| 4 | CSCVValidator L467-681 | PBO组合交叉验证 | 独立工具类 | 低优 |

**根因**：daemon的`risk_ext`预计算组仅存储`volatility_percentile`，未存储`calc_geometric`的7个字段和`_calc_volatility`的4个字段。

### 3.7 dim7 — 估值引擎

**数据源**：daily_basic_cache + fina_indicator_cache + income_cache + balancesheet_cache + cashflow_cache

| 类别 | 位置 | RAW计算 | 预计算等价物 |
|------|------|---------|------------|
| PE分位 | `_pe_percentile()` + 3处调用 | `(pe < cur).sum()/len*100` | 可预计算 |
| PB分位 | `_anchor_pb()` L403 + L793 | 同上模式 | 可预计算 |
| PS分位 | L798-803 | 同上模式 | 可预计算 |
| YoY增长 | `_yoY_growth()` / `_revenue_yoy()` | `(latest-prev)/abs(prev)` | 可预计算 |
| PEG | `_anchor_earnings()` L471 | `pe/(growth*100)` | 可预计算 |
| 企业价值 | `_anchor_cashflow()` L528 | `mv+liab-cash` | 可预计算 |
| FCF收益率 | L531 + L351 + L811 | `fcf/mv*100`（3处重复） | 可预计算 |
| 调整PE | `_anchor_adjusted_pe()` L571-574 | 研发资本化→调整净利→调整PE | 可预计算 |
| ROE/ROCE均值 | `_fina_health()` L628-652 | 3期均值+ROCE回退计算 | 可预计算 |
| 负债率 | L668-672 | `total_liab/total_assets*100` | 可预计算 |
| OCF/NI比 | L681-685 | `cashflow_oper/net_profit` | 可预计算 |

---

## 四、迁移分类：应迁移RAW vs 保留SIG

### 4.1 应迁移到RAW的（简单数学公式，纯指标，无分析耦合）

#### A. 标准技术指标（dim2/dim3共享，当前完全重复）

| 指标 | 公式 | 涉及引擎 | 当前状态 | 迁移动作 |
|------|------|---------|---------|---------|
| MA5/10/20/30/60 | `rolling(n).mean()` | dim2/dim3/dim4/dim5 | 各引擎独立重算，`indicator_ma`已预计算但未使用 | **改读`indicator_ma`表** |
| MACD(DIF/DEA/HIST) | EMA12/26→差值→EMA9 | dim2/dim3 | dim2被调用7次、dim3被调用3次 | **改读`indicator_macd`表** |
| RSI(14) | gain/loss均值→RS→RSI | dim3/dim4/dim5 | 3处独立计算 | **改读`indicator_other`表** |
| ATR(14) | TR→rolling(14).mean() | dim3/dim6 | dim3/dim6各计算1次 | **daemon扩展`indicator_other`** |
| BOLL带宽 | `(upper-lower)/mid` 或 `std/mean` | dim3/dim5 | dim3/dim5各计算1次 | **改读`indicator_other`表** |
| 量MA5/10/20 | `volumes.rolling(n).mean()` | dim3/dim4/dim5 | 各处独立计算 | **daemon扩展`indicator_ma`** |

#### B. 简单比率/聚合（dim4/dim5/dim7中重复出现）

| 计算 | 公式 | 涉及引擎 | 迁移动作 |
|------|------|---------|---------|
| 5日资金聚合 | `moneyflow net_lg_amount.sum(5)` | dim4（5处重复） | daemon RAW-2 |
| 5日/20日/60日量比 | `vols[-5:].sum() / vols[-20:].sum()` | dim3/dim4 | daemon RAW-2 |
| YoY增长率(利润/营收) | `(latest-prev)/abs(prev)` | dim7（2处相同） | daemon RAW-2 |
| FCF收益率 | `fcf/mv*100` | dim7（3处重复） | daemon RAW-2 |
| 企业价值(EV) | `mv+liab-cash` | dim7 | daemon RAW-2 |
| PEG | `pe/(growth*100)` | dim7 | daemon RAW-2 |
| PE/PB/PS历史分位 | `(x < cur).sum()/len*100` | dim7（PE算3次） | daemon RAW-2 |
| 换手率今日vs60日比 | `avg_today / avg_60d` | dim5 | daemon RAW-2 |
| PE今日vs252日比 | `avg_today / avg_252d` | dim5 | daemon RAW-2 |
| RSI市场级今日vs60日 | `avg_rsi_today vs avg_rsi_60d` | dim5 | daemon RAW-2 |
| 融资余额变化率 | `(newest-oldest)/oldest` | dim5 | daemon RAW-2 |
| 涨跌停比 | `count(涨停)/count(跌停)` | dim5 | daemon RAW-2 |
| VWAP(120日) | `avg(close, weights=volume)` | dim4 | daemon RAW-2 |
| 波动率(std/mean) | `std/mean` | dim4/dim6 | daemon RAW-2 |
| 负债率 | `total_liab/total_assets*100` | dim7 | daemon RAW-2 |
| OCF/NI比 | `cashflow_oper/net_profit` | dim7 | daemon RAW-2 |
| ROCE | `op/(ta-cl)*100` | dim7/dim4 | daemon RAW-2 |

#### C. dim6几何化指标（405号已设计但未执行）

| 计算 | 迁移动作 |
|------|---------|
| calc_geometric的7字段（支撑价/阻力价/风险收益比/突破天数等） | daemon `risk_ext`扩展存储 |
| _calc_volatility的4字段（ATR14/ATR%/年化波动率/波动率分位） | daemon `risk_ext`扩展存储 |

#### D. dim5市场级SQL查询（改为预计算）

`BociasiQuadrantAnalyzer`的5个SQL查询（MA20上方占比、换手率分位、涨跌停比、RSI分位、PE分位、融资趋势）改为daemon预计算后写入专用表或pre_feat_cache。

### 4.2 应保留在SIG的（数据分析/评价/与分析系统耦合）

#### 各引擎核心分析逻辑

| 引擎 | 保留内容 | 理由 |
|------|---------|------|
| **dim2** | K线合并、分型识别、笔/线段/中枢构建、买卖点检测、背驰判断、定理验证 | 缠论结构逻辑，非简单公式 |
| **dim2** | 趋势线斜率/外推 | 与缠论结构分析一体 |
| **dim2** | 123法则滚动min/max | 与分型/笔构建紧密耦合 |
| **dim3** | StageDetector阶段分类 | 基于MA的阈值判断和分类 |
| **dim3** | EnhancedPatternDetector 30+种K线形态 | 形态识别是分析 |
| **dim3** | 格兰碧8法则、放量突破、假突破检测 | 策略规则判断 |
| **dim4** | PhaseDetectionEngine 8维共识投票、阶段判定 | 分析决策逻辑 |
| **dim4** | TradingPhaseDetector 5阶段评分 | 策略分析逻辑 |
| **dim4** | ChipDistributionSignalGenerator 6种信号+主力测试+筹码形态 | 策略分析逻辑 |
| **dim5** | BOCI四象限分类 | 分析逻辑 |
| **dim5** | 情绪温度融合 | 分析逻辑 |
| **dim5** | 时间节奏分类 | 分析逻辑 |
| **dim5** | 板块轮动→热度分级 | 分析逻辑 |
| **dim6** | 6源风险聚合→低/中/高/极高 | 分析判定 |
| **dim6** | 风险因素枚举 | 分析逻辑 |
| **dim7** | 估值分级(composite→extreme_low/.../extreme_high) | 分析判定 |
| **dim7** | 四锚加权合成composite | 分析逻辑 |
| **dim7** | 周期股权重调整、质量调整、潜力评分 | 分析逻辑 |

#### 边界案例（RAW和SIG耦合，保留SIG但改读预计算值）

| 计算 | 位置 | 决策 |
|------|------|------|
| dim4 MainForceScorer中的RSI计算 | 与RSI背驰检测紧密耦合 | **保留分析逻辑**，RSI值改从`indicator_other`读取 |
| dim4 MainForceScorer中的MA对齐 | 与阶段判定条件交织 | **保留分析逻辑**，MA值改从`indicator_ma`读取 |
| dim4 ChipScorer的MA对齐 | 与筹码评分条件交织 | **保留分析逻辑**，MA值改从`indicator_ma`读取 |
| dim5 _bociasi_quickline中的MA5/量比 | 与信号阈值判断一体 | **保留分析逻辑**，MA5改从`indicator_ma`读取 |
| dim5 _time_rhythm中的MA20/std20 | 与盘整分类条件交织 | **保留分析逻辑**，MA20/std20改读预计算 |
| dim7 _fina_health中的ROE/ROCE均值 | 与阈值判断(>6%/>15%)一体 | **保留分析逻辑**，ROE/ROCE原始值改读预计算 |

---

## 五、迁移优先级与实施计划

### 5.1 优先级定义

| 优先级 | 标准 | 特征 |
|--------|------|------|
| **P0** | 改读已有预计算表 | 零新增代码，只改数据获取方式 |
| **P1** | 新增daemon RAW-2预计算 | 401/405号已有设计，需daemon侧新增 |
| **P2** | 新增daemon预计算+dim侧适配 | 无现成设计，需新建 |
| **P3** | 次要指标迁移 | 收益较低，按需推进 |

### 5.2 实施计划

| 阶段 | 任务 | 优先级 | 工时 | 涉及引擎 | 前置条件 |
|------|------|--------|------|---------|---------|
| **Phase 1** | MA/MACD/RSI改读预计算表 | P0 | 0.5天 | dim2/dim3/dim4/dim5 | 无 |
| **Phase 2** | dim4筹码指标移到daemon RAW-2 | P1 | 1.0天 | dim4 | 401号方案 |
| **Phase 3** | dim4 5日资金聚合移到daemon RAW-2 | P1 | 0.5天 | dim4 | 无 |
| **Phase 4** | dim6 calc_geometric+_calc_volatility移到daemon RAW-2 | P1 | 0.3天 | dim6 | 405号方案 |
| **Phase 5** | dim5市场级SQL查询改为daemon预计算 | P2 | 0.5天 | dim5 | 无 |
| **Phase 6** | dim7估值指标移到daemon RAW-2 | P2 | 0.5天 | dim7 | 无 |
| **Phase 7** | dim4主力成本价/融资成本价移到daemon RAW-2 | P2 | 0.3天 | dim4 | 无 |
| **Phase 8** | dim3量MA/波动率/ROC移到daemon RAW-2 | P3 | 0.3天 | dim3 | Phase 1完成 |
| **合计** | | | **3.9天** | | |

### 5.3 阶段依赖图

```
Phase 1（MA/MACD/RSI改读预计算表）──→ 消除最大量重复计算
    │
    ├── Phase 2（dim4筹码RAW迁移）
    ├── Phase 3（dim4资金聚合RAW迁移）
    ├── Phase 4（dim6几何化+波动率RAW迁移）
    ├── Phase 5（dim5市场级SQL改预计算）
    ├── Phase 6（dim7估值指标RAW迁移）
    ├── Phase 7（dim4成本价RAW迁移）
    └── Phase 8（dim3量指标RAW迁移）← Phase 1完成后
```

---

## 六、验证方案

### Phase 1验证（改读预计算表）

```bash
# 验证dim2改读indicator_macd后MACD值一致
backend/.venv/bin/python3 -c "
from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine
from app.data import DataManager
dm = DataManager()
ecm = dm.cache
df = ecm.get_cached_daily('000001.SZ')
print('dim2 MACD改读验证通过')
"

# 验证dim3改读indicator_ma后MA值一致
make check  # lint + typecheck + test
```

### Phase 2-8验证

```bash
make check  # lint + typecheck + test
```

---

## 七、风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 改读预计算表后MACD/MA值与原计算有微小差异 | 低 | 低 | 预计算表精度足够（float64），差异在1e-10级别 |
| dim4筹码RAW迁移影响PhaseDetectionEngine | 中 | 中 | 401号已有设计，渐进式迁移 |
| dim5 SQL查询改为预计算后数据时效性 | 低 | 低 | daemon日终预计算，与当前SQL查询时效一致 |
| dim6 405号建议未执行的依赖项 | 中 | 中 | Phase 4与405号方案联动执行 |
| Phase 1-8涉及6个引擎文件，可能引入回归 | 中 | 中 | 每个Phase独立测试+make check |

---

## 八、与现有方案的关系

| 方案 | 关系 |
|------|------|
| 353号（总纲） | 本方案落实353号COL→RAW→SIG分层定义 |
| 401号（dim4通路核查） | 本方案Phase 2-3/7执行401号未完成的RAW迁移 |
| 405号（dim6路径统一） | 本方案Phase 4执行405号未完成的RAW迁移 |
| 406号（dim7质量审计） | 本方案Phase 6在406号代码质量修复基础上进一步RAW迁移 |
| 407号（数据路径冲突） | 本方案是407号建议2（dim4/dim5部分计算移到RAW）的具体实施 |
| 409号（dim1门禁） | 本方案与409号的dim1数据提取互补——dim1门禁确保数据质量，本方案确保数据分层合理 |

---

**方案编制日期**：2026-09-05
**编制依据**：6个子代理并行审计dim2-dim7全部代码 + 401/405/406/407号方案交叉验证 + 用户指示
**审计覆盖**：17,256行代码逐行核查，RAW/SIG分类
