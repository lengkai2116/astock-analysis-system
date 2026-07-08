---
title: 选股系统L3策略组合与Vibe真实接入方案
type: 技术方案
date: 2026-07-08
status: ✅ 已完成（2026-07-08 全量实施并验证通过）
---

# 选股系统L3策略组合与Vibe真实接入方案

## 一、现状与问题

### 1.1 当前架构

```
选股系统 L3
├── 缠论: chanlun_strategy.analyze_chanlun()    ← 已固定接入 ✅
├── 量价: VolumePriceStrategy.analyze()          ← 已固定接入 ✅
├── 因子: _compute_factor_score()                ← 自算4个OHLCV指标，与组合选择无关 ❌
└── Vibe: _compute_vibe_bonus()                  ← 统一加分，非差异化执行 ❌
```

### 1.2 两个断点

**断点A — 因子组合未参与计算**：

```
用户勾选 "Fama-French 三因子" 或 "A股核心五因子"
    ↓  combo IDs 传入后端
    ↓  _compute_factor_score() 未查 PRESET_COMBOS
    ↓  直接自己从 OHLCV 算4个通用指标
    ↓  无论选哪个组合，得分完全相同
```

| PRESET_COMBOS 因子名 | 注册表类名 | 匹配状态 |
|---------------------|-----------|---------|
| 20日动量 / 5日动量 / 截面动量 | MOM_20 / MOM_5 | ✅ 7个可自动匹配 |
| 14日RSI / 5日量比 / 量比 / 20日波动率 | RSI_14 / VOL_RATIO_5 / VOL_RATIO / VOLATILITY_20 | ✅ |
| 20日换手率 / 均线乖离率 / PE倒数 / ROE / 股息率 / 资产负债率 / 营收增长率 / 净利润增长率 / 大单净买入 / 资金流向强度 / 换手率变化 | — | ❌ 12个需手动映射或使用财务/资金数据 |

**断点B — Vibe策略未从真实策略模板读取**：

```
策略模板库 (/api/v2/strategy/templates)
  11 个策略
  ├── L1重叠: DarwinRiskStrategy, MultiLevelRiskControlStrategy     → 应排除
  ├── L2重叠: MainForceTrackingStrategy, ChipStrategy                → 应排除
  ├── L3固定: ChanlunStrategy, VolumePriceStrategy                    → 应排除
  └── 候选Vibe: TrendChannelStrategy, MarketSentimentCycleStrategy,  → 应标记vibe=1
                 LimitUpShortTermStrategy, WaveTheoryStrategy,
                 FibonacciTimeCycleStrategy
        ↓  全部未标记 vibe=1
        ↓
选股系统 GET /api/v3/screener/strategies/vibe 查询 vibe=1
        ↓  返回 0 条
        ↓  回退到 3 个硬编码默认值
        ↓  统一 +0.5 分，无差异化执行
```

---

## 二、修复方案

### 2.1 修复A：因子组合真实接入 L3

**目标**：`_compute_factor_score()` 根据传入的组合 IDs 查 `PRESET_COMBOS`，计算真实的因子值后按权重加权。

**步骤**：

| # | 动作 | 涉及文件 | 说明 |
|--|------|---------|------|
| A1 | 建立中文名→注册表类名的映射表 | `screener_strategy_integration.py` 或 `factors.py` | 覆盖所有 34 个因子名的映射。已自动匹配 7 个（OHLCV类），其余 12 个需手动维护 |
| A2 | `_compute_factor_score()` 改为按组合计算 | `screener_strategy_integration.py` | 传入组合 IDs → 查 `PRESET_COMBOS` 获取 `factors: [{n, w}]` → 逐个计算因子值 → 按 `w` 加权 → 返回组合分 |
| A3 | 无法自动映射的因子使用 fallback | `screener_strategy_integration.py` | 对未匹配因子：有 `fina_indicator_cache`/`daily_basic_cache` 数据的使用财务替代计算，无数据的跳过（剩余因子归一化后加权） |

**因子名→注册表类名映射表**：

| 中文名 | 注册表类名 | 数据源 | 映射方式 |
|--------|-----------|--------|---------|
| 20日动量 | MOM_20 | daily_cache | ✅ 自动（docstring匹配）|
| 5日动量 | MOM_5 | daily_cache | ✅ |
| 14日RSI | RSI_14 | daily_cache | ✅ |
| 5日量比 | VOL_RATIO_5 | daily_cache | ✅ |
| 量比 | VOL_RATIO | daily_cache | ✅ |
| 20日波动率 | VOLATILITY_20 | daily_cache | ✅ |
| 5日反转因子 | MOM_5(取负) | daily_cache | ✅ 类名+符号反转 |
| 20日换手率 | → TURNOVER_20 | daily_basic_cache | 🟡 需新增因子类或inline计算 |
| 20日均线乖离率 | → BIAS_20 | daily_cache | 🟡 inline: (close-ma20)/ma20 |
| 市盈率倒数(EP) | → EP_RATIO | daily_basic_cache | 🟡 inline: 1/pe_ttm |
| ROE | → ROE | fina_indicator_cache | 🟡 inline: roe/100 |
| 股息率 | → DIVIDEND_YIELD | daily_basic_cache | 🟡 inline: dv_ratio |
| 资产负债率 | → DEBT_RATIO | balancesheet_cache | 🟡 inline 或跳过 |
| 营收增长率 | → REVENUE_GROWTH | income_cache | 🟡 inline 或跳过 |
| 净利润增长率 | → PROFIT_GROWTH | income_cache | 🟡 inline 或跳过 |
| 大单净买入 | → NET_BIG_ORDER | moneyflow_cache | 🟡 inline: net_lg_amount趋势 |
| 资金流向强度 | → MONEYFLOW_STRENGTH | moneyflow_cache | 🟡 inline |
| 换手率变化 | → TURNOVER_CHANGE | daily_basic_cache | 🟡 inline |
| 截面动量 | → CROSS_SECTION_MOM | daily_cache | 🟡 全市场排名后归一化 |

### 2.2 修复B：Vibe策略真实接入

**目标**：Vibe 策略从策略模板库读取，排除 L1/L2/L3 已用策略，对候选策略做差异化评分。

**步骤**：

| # | 动作 | 涉及文件 | 说明 |
|--|------|---------|------|
| B1 | 标记候选策略为 `vibe=1` | 数据库 `strategy_template_v2` | 更新以下策略的 `vibe` 字段为 true：TrendChannelStrategy、MarketSentimentCycleStrategy、LimitUpShortTermStrategy、WaveTheoryStrategy、FibonacciTimeCycleStrategy |
| B2 | `get_vibe_strategies()` 过滤逻辑 | `screener.py` | 在 `vibe=True` 基础上，增加 `cat NOT IN ('chanlun','vp','chip','darwin','s2','s5')` 或维护排除列表，确保不重复选择已内置的策略 |
| B3 | Vibe 加分差异化 | `screener_strategy_integration.py` | 从统一 `+0.5` 改为按策略的 `usage_count` 或 `ready` 状态加不同权重。如 ready=1 的 +0.8，in-dev 的 +0.3 |

### 2.3 修复C：策略模板数据维护（附带）

| # | 动作 | 说明 |
|--|------|------|
| C1 | `init_system_templates()` 添加 vibe 标记 | 启动种子数据时同时填充 `vibe` 字段，使新部署可自动获得正确标记 |

---

## 三、影响范围

| 模块 | 影响 | 风险 |
|------|------|------|
| `screener_strategy_integration.py` | 重写 `_compute_factor_score()` 和 `_compute_vibe_bonus()` | 中 — 因子计算变重，但只影响 L3 候选股（当前 106 只），可接受 |
| `screener.py` | `get_vibe_strategies()` 增加过滤条件 | 低 — 仅影响返回列表 |
| `factors.py` | 无改动（仅消费 PRESET_COMBOS） | 无 |
| 数据库 `strategy_template_v2` | update `vibe` 字段 | 低 — 幂等操作 |
| 个股策略分析板块 | **无影响** — `ChipScorer` 和 `analyze_chanlun` 等不变 | 无 |

---

## 四、验收标准

1. 勾选"Fama-French 三因子"时 `factor_score` 仅由其 3 个因子加权决定；勾选"A股核心五因子"时由另外 5 个因子决定
2. 不勾选任何因子组合 → `factor_score = 0`（因子权重自动归零）
3. Vibe 策略列表中不出现 ChanlunStrategy、VolumePriceStrategy、DarwinRiskStrategy、MainForceTrackingStrategy、ChipStrategy
4. Vibe 加分从统一值改为按策略差异化
5. 现有 L1/L2 筛选结果不受影响（106 只通过阈值不变）
