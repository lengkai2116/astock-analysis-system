# PreFilter 前置过滤层资产核实与重构方案

> **文档编号**: 138 (v2 修正版)
> **编制日期**: 2026-06-02
> **参考文档**: 132-策略体系完整方案与输出体系报告.md（六、多层筛选系统）
> **审计文件**: `chip_pre_filter.py`、`screener.py`、`routes/screener.py`、`signal_computation_service.py`、`pipeline.py`
> **声明**: 本文档初版（v1）存在架构概念混淆，v2 已修正并重新核实

---

## 一、v1 勘误声明

v1 版将 `chip_pre_filter.py` 错误地定义为"第一层风险筛选"，并声称 `DarwinRiskFilter` 未接入主路径。核实 132 文档六章后确认：

| 项目 | v1 的错误说法 | 实际真相 |
|------|-------------|---------|
| `DarwinRiskFilter` 是否接入 | 声称"未接入主路径" | **已接入** — 通过 `/api/v3/screener/run` 和 `/api/v3/screener/layer1` 公开 API |
| `chip_pre_filter.py` 的定位 | 定义为"第一层风险筛选" | **错误定位** — 它是筹码策略书内（第0-9章）的过滤逻辑，和 Darwin 筛选 L1 是两套东西 |
| `MultiLayerStockScreener` | 未提及 | **已完整实现**——132文档中完整的`compute_screening()` 调用链 |
| 138 方案目标 | 把 `chip_pre_filter` 接入信号路径 | **方向偏差**——需要先正确定位后重新规划 |

---

## 二、资产核实：两套独立的过滤系统

### 2.1 系统A：达尔文筛选路径（方案一）

**132文档定义**：六、多层筛选系统 → 全市场扫描

```
API: POST /api/v3/screener/run
路由: screener.py → compute_screening()
  ├─ L1: DarwinRiskFilter.filter()     → 从全市场快速剔除高风险
  ├─ L2: ChipScorer.score()            → 评分+排序，取前100
  └─ L3: extract_indicators + 子评分   → 输出精选列表
```

**当前实现质量评估：**

#### L1: `DarwinRiskFilter`（`screener.py`）

| 方法 | 当前实现 | 质量评估 | 实际影响 |
|------|---------|---------|---------|
| `_filter_st` | `'ST' not in symbol` | **不可靠** — 代码字符串匹配，不查 DB name 字段 | 部分 ST 股票漏过 |
| `_filter_continuous_loss` | `return True` | **纯占位符** | 无过滤效果 |
| `_filter_low_liquidity` | `vol > 10000` | **阈值无依据** — 单位不明确，非换手率 | 无法有效排除冷门股 |
| `_filter_high_valuation` | `return True` | **纯占位符** | 无过滤效果 |

**L1 核心问题**：架构设计正确（L1→L2→L3 流程、API 集成均完整），但**过滤规则的质量不达标**。

#### L2: `ChipScorer.score()`（`chip_strategy.py`）

| 维度 | 实现 | 质量 |
|------|------|------|
| 价格动量 (30%) | recent_return>0:+3, >-0.05:+1.5 | 可接受，但过于简化 |
| 成交量评分 (40%) | vol_ratio>=1.5:+4, >=1.2:+2.5, 基准+1 | 可接受 |
| 价格位置评分 (30%) | 30-60%分位:+3, 60-80%:+2, 其他:+1 | 可接受 |
| **综合** | 0-10分映射 | **与 chip_strategy_impl.py 的完整信号生成无关** |

**L2 问题**：评分维度的权重均等（实际是固定分值叠加），未区分不同市场状态的权重调整。

#### L3: 策略验证（`routes/screener.py:compute_screening()`）

| 验证项 | 实现 | 质量 |
|--------|------|------|
| 数据完整性 | `len(df) >= 60` | 合理 |
| ASR/集中度/量比/RSI | `extract_indicators()` 计算 | 简化版，但可用 |
| 子维度评分加权 | asr(0.4)+concentration(5)+profit(0.3)+volume(0.2)+rsi(0.15) | 与人无关的数值，需确认 |
| **缠论验证** | 未调用 `ChanlunAlphaModel` | 132文档中写了但未接入 |

**L3 问题**：132 文档宣称的"缠论Alpha验证"未实现，`ChanlunAlphaModel` 未接入 `compute_screening()`。

### 2.2 系统B：筹码策略专用过滤（`chip_pre_filter.py`）

**设计依据**：书本第0层-第9章的过滤逻辑

| 组件 | 对应书本依据 | 功能 | 引用计数 |
|------|------------|------|---------|
| `MarketEnvironmentFilter` | 第7章§7.4 大盘环境 | 沪深300 vs 60日均线 → position_multiplier | **0** |
| `CircuitBreaker` | 第9章§9.5 熔断规则 | 单日>5%减半/连跌>8%清仓 | **0** |
| `EligibilityFilter` | 第9章§9.6 新股排除 | 排除上市<250交易日 | **0** |
| `LiquidityFilter` | 第3章§3.6 流动性 | 20日均换手率<2%排除 | **0** |
| `MarketCapAdapter` | 第9章§9.4 市值适配 | 4档调参 | **0** |

**定位**：这是筹码策略的**策略内过滤层**，应在筹码策略信号生成前执行。它不应该在达尔文筛选路径中（那里已经有一个L1了），而是在方案二的单只股票分析路径中。

**接入目标**：`pipeline.py` 的 `ChipDistributionStrategy.analyze()`，或者 `SignalComputationService._compute_chip_signal()`。

---

## 三、正确的问题界定

经过核实，现状不是"PreFilter 未接入"，而是**两条路径各自有独立的问题**：

### 路径一（达尔文筛选）：规则质量不达标

```
工作流完整:  L1→L2→L3 都在API层跑通了
但规则本身:  L1 的 _filter_st 不可靠，_filter_continuous_loss 和 _filter_high_valuation 是空壳
            L3 的缠论验证未接入
```

### 路径二（筹码策略信号）：策略内过滤悬空

```
chip_pre_filter.py 的5个子过滤器设计完整但零引用
ChipDistributionStrategy.analyze() 和 SignalComputationService 均无前置过滤
```

### 两条路径之间的映射关系

达尓文筛选路径和筹码策略信号路径之间**不是替代关系，而是流水线关系**：

```
┌──────────────────────────────────────────────┐
│ 方案一：全市场筛选（达尔文选择）              │
│                                               │
│  L1 DarwinRiskFilter                          │
│   (ST剔除 / 流动性粗筛 / 财务数据预留)        │
│       ↓                                       │
│  L2 ChipScorer.score()                        │
│   (快速评分, 取前100)                          │
│       ↓                                       │
│  L3 策略验证                                   │
│   (ASR/量比/RSI 子维度评分)                   │
│       ↓                                       │
│  输出: 精选列表 + 策略结论简述(方向/时机/仓位)   │
└──────────────────────────────────────────────┘
                    │
                    ▼ (用户从精选列表中选择个股)
                    │
┌──────────────────────────────────────────────┐
│ 方案二：单只股票深入分析                       │
│                                               │
│ [ChipPreFilter]   ← 筹码策略内过滤（当前跳过） │
│  (市场环境/熔断/新股/流动性/市值)              │
│       ↓                                       │
│  ChipDistributionStrategy.analyze()           │
│   (阶段检测 / 信号生成 / ConfirmLayer)         │
│       ↓                                       │
│  SignalComputationService                      │
│   (chip + chanlun + factor 三路信号)           │
│       ↓                                       │
│  输出: 完整分析报告 (结论+分析链/指标/依据)     │
└──────────────────────────────────────────────┘
```

---

## 四、修复方案

### 4.1 修复路径一（DarwinRiskFilter L1 — 三项修复）

| # | 问题 | 修复方案 | 文件 | 工作量 |
|---|------|---------|------|-------|
| A | `_filter_st` 代码匹配不可靠 | 改为从 Tushare API 获取股票名称字段判断，或从 `DataManager` 的 stock_list 中获取 `name` 字段 | `screener.py` | 小 |
| B | `_filter_low_liquidity` 阈值无依据 | 改用换手率判断（类似 `chip_pre_filter.LiquidityFilter` 的20日均换手率<2%标准），或保持成交量但改为明确金额阈值（日均成交额<5000万） | `screener.py` | 小 |
| C | `_filter_continuous_loss` / `_filter_high_valuation` 空壳 | 标注为明确预留点，不占位（改为 `return True` 带日志），等待财务数据接入后实现 | `screener.py` | 极小 |

### 4.2 修复路径二（ChipPreFilter 接入 — 两项）

| # | 问题 | 修复方案 | 文件 | 工作量 |
|---|------|---------|------|-------|
| D | `ChipPreFilter` 零引用 | 注入 `ChipDistributionStrategy.analyze()` 开头，在阶段检测和信号生成前执行 | `pipeline.py` (analyze方法) | 中 |
| E | `EligibilityFilter` DB 依赖 | 改为从 `DataManager.get_stock_list()` 获取上市信息，或直接通过 Tushare API | `chip_pre_filter.py` | 小 |

### 4.3 修复路径一 L3（缠论验证接入 — 可选）

| # | 问题 | 修复方案 | 文件 | 工作量 |
|---|------|---------|------|-------|
| F | L3 未调用 `ChanlunAlphaModel` | 在 `compute_screening()` 的 L3 验证中增加 `ChanlunAlphaModel` 调用 | `routes/screener.py` | 中 |

---

## 五、分步实施建议

按优先级排列：

**Phase 1（优先）：修复 L1 规则质量**
- 改 `_filter_st` 为基于名称判断
- 改 `_filter_low_liquidity` 为换手率或成交额标准
- 清理占位符，预留接口
- 估算工作：~40行改动

**Phase 2：接入 ChipPreFilter 到策略路径**
- 修复 `EligibilityFilter` 的数据依赖
- 在 `ChipDistributionStrategy.analyze()` 开头调用
- `MarketEnvironmentFilter` + `MarketCapAdapter` 结果传参调节信号
- `CircuitBreaker` + `EligibilityFilter` + `LiquidityFilter` 不通过则提前返回
- 估算工作：~60行改动 + 测试

**Phase 3（可选）：完善 L3 策略验证**
- 接入 `ChanlunAlphaModel`
- 估算工作：~30行改动

---

## 六、改造后完整数据流

```
用户请求
    │
    ▼
┌───────────────────────┐
│  达尔文筛选 (方案一)   │
│  /api/v3/screener/run │
│                       │
│  L1: DarwinRiskFilter │  ← 修复: 正确判断ST/换手率
│      ↓                │
│  L2: ChipScorer       │
│      ↓                │
│  L3: 策略验证+缠论    │  ← 可选: 接入ChanlunAlphaModel
│      ↓                │
│  输出: 精选列表 + 策略结论简述  │
└───────────────────────┘
    │
    ▼ (用户选择个股)
    │
┌───────────────────────┐
│  单只股票分析 (方案二) │
│  /api/v2/strategy/    │
│                       │
│  ChipPreFilter        │  ← 新增: 市场环境/熔断/新股/流动性/市值
│      ↓                │
│  ChipDistribution     │
│  Strategy.analyze()   │
│  (阶段检测+信号生成)  │
│      ↓                │
│  SignalComputation    │
│  Service              │
│  (chip+chanlun+factor)│
│      ↓                │
│  输出: 完整分析及结论原因说明  │
└───────────────────────┘
```

---

## 七、与 136 报告方向的关联（修订后）

| 136方向 | 与本方案的关系 | 前置条件 |
|---------|--------------|---------|
| C-1 市场状态4D升级 | **依赖 Phase 2** — ChipPreFilter 接入后，MarketEnvironmentFilter 提供大盘状态基础 | Phase 2 完成后 |
| F-1 拥挤度因子 | **依赖 Phase 1+2** — L1 流动性过滤提供基础数据，ChipPreFilter 的流动性过滤与之互补 | Phase 1+2 完成后 |
| G-1 因子分级管理 | 间接关联 — 市值适配已体现因子分层思想 | 可独立推进 |

---

## 八、验收标准（修正后）

| # | 针对路径 | 检查项 | 验证方法 |
|---|---------|--------|---------|
| 1 | 达尔文L1 | `_filter_st` 正确识别ST股票 | 调用 `layer1` API 检查 ST 股是否被剔除 |
| 2 | 达尔文L1 | `_filter_low_liquidity` 使用合理阈值 | 调用 API，对比换手率<2%的股票是否被排除 |
| 3 | 筹码信号 | `ChipPreFilter` 通过时信号正常输出 | 对正常股票运行 `analyze()` 返回非空 |
| 4 | 筹码信号 | `EligibilityFilter` 排除新股 | 对模拟新股，`analyze()` 提前返回 |
| 5 | 筹码信号 | 大盘 POOR 时仓位乘数生效 | 信号中 `position_suggestion` 按预期缩减 |
| 6 | 筹码信号 | 熔断 LIQUIDATE_ALL 时阻断信号 | `analyze()` 返回空/未触发 |
| 7 | 全局 | 两条路径互不影响 | 筛选路径和信号路径各自独立工作 |
