---
编号: 193
标题: AI多角色分析页设计研判（GitHub同类项目调研）
日期: 2026-06-22
类型: 调研/设计研判
状态: 初稿
标签: [AI分析, 多角色辩论, 投研框架, TradingAgents, 架构设计]
builds_on: [183, 180]
---

# 193 — AI多角色分析页设计研判

> **目的：** 针对 `_ui-prototype/ai-analysis.html` 页面，调研GitHub同类AI多角色股票分析项目，明确输入项、角色配置、分析维度、辩论形式、输出格式等全环节设计，为页面重构提供依据。

---

## 目录

1. [调研项目概览](#1-调研项目概览)
2. [各项目架构对比](#2-各项目架构对比)
3. [通用设计模式提炼](#3-通用设计模式提炼)
4. [本项目AI分析页的设计建议](#4-本项目AI分析页的设计建议)
5. [与个股策略分析页的关系定位](#5-与个股策略分析页的关系定位)
6. [推荐实施方案](#6-推荐实施方案)

---

## 1. 调研项目概览

本次调研覆盖了 5 个代表性的开源项目，覆盖从美股到A股、从纯后端到全栈可视化、从通用分析到特定场景的完整光谱。

### 1.1 TradingAgents（原版，TauricResearch）

| 属性 | 值 |
|:-----|:----|
| ⭐ | 65K+ Stars |
| 定位 | 通用多Agent LLM 交易框架（美股为主）|
| 论文 | arXiv 2412.20138 (UCLA + MIT) |
| 架构 | LangGraph StateGraph，12个LLM Agent + 2个支撑组件 |
| 发布 | PyPI: v0.3.0，Apache 2.0 |

### 1.2 TradingAgents-Astock（A股特化版）

| 属性 | 值 |
|:-----|:----|
| ⭐ | Fork 自原版，A股深度改造 |
| 定位 | A股专属多Agent投研框架 |
| 数据源 | mootdx + 腾讯财经 + 东方财富 + 新浪 + 同花顺 + 财联社 |
| 亮点 | 7分析师（含政策分析/游资追踪/解禁监控3个A股特有角色）|
| 实测 | ~¥0.2~0.3/份研报（国内大模型，MiniMax/DeepSeek）|

### 1.3 trading-arena（轻量辩论可视化）

| 属性 | 值 |
|:-----|:----|
| 定位 | 多Agent A股研究 + 实时辩论 + Web可视化 |
| 辩论格式 | claim → evidence → counter-argument → synthesis |
| 可视化 | WebSocket Dashboard，Agent意见绘制在agreement/conviction轴上 |
| 数据源 | Tushare, AKShare |

### 1.4 TradingAgents-Studio（全栈可视化平台）

| 属性 | 值 |
|:-----|:----|
| 定位 | 可视化多Agent LLM 交易研究平台 |
| 前端 | Vue 3 + Naive UI + klinecharts，WebSocket实时推送 |
| 辩论展示 | 左右气泡按轮次分割（Bulles），带实时脉冲动画 |
| A股特化 | cn_social(东财股吧)、event(因果链)、capital_flow(主力资金)、macro(宏观) |
| 衍生功能 | 持仓追踪、定时分析、模拟交易、决策回放回测、决策质量看板 |

### 1.5 AlphaInsight（对抗辩论式尽调）

| 属性 | 值 |
|:-----|:----|
| 定位 | 自动化金融尽职调查系统（LangGraph） |
| 核心创新 | 风控做空Agent（"挑刺者"）+ 财务Agent 多轮辩论（3-5轮）|
| 收敛条件 | 信息熵变化阈值 ΔH < ε 时中止 |
| 输出 | 精准溯源的20页深度尽调报告（引用至PDF段落）|

---

## 2. 各项目架构对比

### 2.1 角色体系对比

| 项目 | 分析师角色数 | 分析师角色 | 辩论角色 | 决策角色 |
|:-----|:-----------|:-----------|:---------|:---------|
| TradingAgents（原版） | 4 | 市场/舆情/新闻/基本面 | Bull/Bear Researcher + 风险3方 | Research Manager + Trader + Portfolio Manager |
| TradingAgents-Astock | 7 | 市场/舆情/新闻/基本面/政策/游资/解禁 | Bull/Bear Researcher + 风险3方 | Research Manager + Trader + Portfolio Manager |
| trading-arena | 4 | 基本面/技术面/情绪/风险 | Debate Arena 四角色直接辩论 | 共识引擎 |
| TradingAgents-Studio | 4+ | 板块/资金/宏观/因果/… | Bull/Bear对话气泡 | 同上 |
| AlphaInsight | 3 | 规划/财务分析(+做空) | 财务Agent ↔ 做空Agent（3-5轮）| 主笔Agent |

### 2.2 辩论机制对比

| 项目 | 辩论参与方 | 轮数控制 | 辩论格式 | 收敛判定 |
|:-----|:----------|:---------|:---------|:---------|
| TradingAgents | Bull ↔ Bear（定向对抗）+ 风险3方（循环） | max_debate_rounds（默认1轮） | 自由辩论，LLM各自维护上下文 | 轮数限制 |
| AlphaInsight | 财务Agent ↔ 做空Agent（独有"挑刺者"角色） | 3-5轮 | 针对具体矛盾点辩论（如营收增长下的供应商集中vs存货周转） | **信息熵变化阈值 ΔH < ε** |
| trading-arena | 全部4角色共议会场 | — | claim → evidence → counter-argument → synthesis | consensus达成 |
| 本项目2026设计（建议） | 技术面 ↔ 资金面 → 技术+资金 vs 基本面&消息 → 综合辩论 | 2轮：初辩+深辩 | 先组内共识，再跨组对抗 | 全角色共识或3轮上限 |

### 2.3 输出形式对比

| 项目 | 输出格式 | 是否评分 | 有无自然语言叙事 | 是否包含可追溯证据 |
|:-----|:---------|:---------|:----------------|:------------------|
| TradingAgents | BUY/HOLD/SELL + 投资计划 | ❌ | ✅ 自然语言推理过程 | ✅ 每条论据可追溯到分析师报告 |
| AlphaInsight | 尽调报告（~20页PDF） | ❌ | ✅ 完整尽调叙事 | ✅ **精准溯源（PDF段落引用）** |
| trading-arena | 共识报告 + 分歧标注 | ❌ | ✅ | ✅ |
| 本项目2026设计（建议） | 多角色分析报告（结构化 + 叙事） | ❌ 去评分化 | ✅ 多角色各自叙事 + 辩论摘要 + 综合结论 | ✅ **每条观点标注来源** |

---

## 3. 通用设计模式提炼

### 3.1 共同架构模式

```
┌─ 第一阶段：独立分析 ──────────────────────┐
│  Agent A          Agent B          Agent C  │
│  (数据+工具)      (数据+工具)      (数据+工具)│
│    ↓ 独立研报      ↓ 独立研报        ↓ 独立研报│
├─ 第二阶段：辩论对抗 ──────────────────────┤
│                Debate Arena                │
│    Bull ↔ Bear / 多方 ↔ 空方 / 共识↔质疑    │
│    ↑ 结构化论点 + 证据 + 反驳               │
├─ 第三阶段：综合研判 ──────────────────────┤
│    Research Manager / 共识引擎 / 主笔Agent  │
│    ↓ 汇总一致意见 + 标注分歧                 │
├─ 第四阶段：输出 ────────────────────────┤
│    研报 / 投资计划 / 尽调报告 + 证据追溯      │
└────────────────────────────────────────────┘
```

### 3.2 关键设计决策总结

| 决策维度 | 主流做法 | 为什么 |
|:---------|:---------|:-------|
| **角色独立性** | 每个Agent有自己的System Prompt、工具集、数据访问权限 | 防止信息串扰，确保视角真实 |
| **辩论结构化** | 混合模式：结构化报告（分析师之间）+ 自然语言对话（辩论环节） | 结构化防信息丢失，自然语言辩论更灵活 |
| **辩论收敛** | 轮数限制 + 可选信息熵停止条件 | 防止无限辩论，控制token成本 |
| **双LLM设计** | 快速LLM用于分析/辩论，深度LLM用于综合研判 | 成本效益优化：分析~¥0.2/次，综合~¥0.1/次 |
| **证据追溯** | 每条结论标注来源（分析师报告段/知识库/数据点） | 防止幻觉，提升可信度 |
| **无评分** | TradingAgents不输出评分，仅输出方向+推理 | 与180号§7 "去评分化"原则一致 |

### 3.3 A股特有的分析维度

从 TradingAgents-Astock 的改造实践中，A股需要的额外维度：

| A股特有维度 | 对应角色 | 数据来源（本项目现有） |
|:-----------|:---------|:---------------------|
| **游资/主力行为** | 游资追踪师 | Tushare moneyflow + 龙虎榜 |
| **限售解禁** | 解禁监控师 | Tushare 限售股数据 |
| **政策/行业监管** | 政策分析师 | 新闻/公告数据 |
| **北向资金** | 资金面分析师 | Tushare 北向资金 |
| **筹码分布** | 筹码分析师 | Tushare cyq_chip |
| **情绪拥挤度** | 情绪分析师 | 已实现的crowding_factor.py |
| **板块轮动** | 板块轮动分析师 | 已实现的sector_rotation_model.py |

---

## 4. 本项目AI分析页的设计建议

### 4.1 定位确认

参照 [183号方案](002-方案存档/183-三模块策略架构评估与建议.md) 的定义：

> ③ AI多角色评判 — **综合评判** — 多角色从不同视角对相同股票进行独立分析、讨论、综合评定，输出专业评判  
> **类比：** 投委会 — 各方专家会诊投票

与个股策略分析页（indicator-ide）的区分：

| 维度 | 个股策略分析页（模块②） | AI多角色分析页（模块③） |
|:-----|:----------------------|:----------------------|
| 核心能力 | LLM Wiki + 量化策略输出 → 现状解读 + 建议 | 多角色独立分析 + 辩论 → 综合评判 |
| 输出形式 | 五维现状卡片（卡1-5）+ 情境推演 | 多角色独立报告 + 辩论摘要 + 综合结论 |
| 用户场景 | "这只股票现在什么状态？" | "多个专家怎么看这只股票？" |
| 深度 | 纵向深度（策略维度拆解） | 横向广度（多视角碰撞） |
| LLM使用 | DeepSeek V4 Layer 1（叙事）+ Layer 2（仲裁） | 每个角色独立LLM + 辩论综合 |
| 数据输入 | 量化策略输出（缠论/量价/筹码等）+ Wiki | 量化策略输出 + 实时行情 + Wiki + 新闻 |
| 一体化关系 | indicator-ide底部工具条有"[📊 多角色对比]"按钮 → 跳转ai-analysis页面并携带当前股票 |

### 4.2 建议的角色体系

参照 TradingAgents-Astock 的7分析师模式，结合本项目已有的数据能力和策略输出，建议以下 **6大角色**：

| 角色 | 中文名 | 分析维度 | System Prompt 倾向 | 本项目已有数据源 |
|:-----|:-------|:---------|:------------------|:----------------|
| 📈 Technical Analyst | 技术分析师 | 走势结构、量价形态、缠论信号 | 关注价格结构、技术指标、形态识别 | 缠论/量价策略输出，chart K线数据 |
| 📊 Fundamental Analyst | 基本面分析师 | 财务数据、估值水平、行业位置 | 关注PE/PB/ROE、营收利润增长、行业对比 | Tushare fina_indicator（财务指标）|
| 🧩 Chip Analyst | 筹码/资金分析师 | 筹码分布、主力动向、资金流向 | 关注主力建仓/出货、集中度变化、北向资金 | chip_strategy + moneyflow + 北向资金 |
| 💬 Sentiment Analyst | 情绪/舆情分析师 | 市场情绪、板块热度、情绪周期 | 关注情绪阶段、拥挤度、板块轮动 | crowding_factor + sector_rotation_model |
| 📰 News Analyst | 消息面分析师 | 近期新闻、公告事件、机构研报 | 关注事件驱动、催化/利空、机构预期变化 | news路由 + reports路由 |
| 🛡️ Risk Analyst | 风控/风险分析师 | 下行风险、不确定因素、冲突识别 | 扮演"挑刺者"，主动发现矛盾点、数据缺失 | verification_chains + conflict_arbiter |

> **设计原则：** 每个角色 **不直接访问其他角色的分析结果**（防止信息串扰），仅在辩论阶段共享。每个角色使用独立的 System Prompt + 工具集。

### 4.3 建议的辩论流程

借鉴 TradingAgents 的两层辩论 + AlphaInsight 的对抗式辩论，建议 **3阶段辩论**：

```
第一阶段：独立分析（并行）
├── 📈 技术分析师 → 生成技术面研报
├── 📊 基本面分析师 → 生成基本面研报
├── 🧩 筹码分析师 → 生成筹码资金研报
├── 💬 情绪分析师 → 生成情绪面研报
├── 📰 消息面分析师 → 生成消息面研报
└── 🛡️ 风控分析师 → 等待其他结果 + 阅读后生成风险报告

第二阶段：对抗辩论（两轮）
├── 第一轮：技术面 vs 筹码资金（量价结构 vs 主力行为是否一致）
│   └── 基本面 vs 消息面（估值逻辑 vs 短期催化是否匹配）
│   ↓
├── 第二轮：多空联盟辩论
│   ├── 看多方（技术面+基本面）：提供正向论点
│   ├── 看空方（消息面+风控）：提供反向论点
│   └── 中立/裁决方（筹码+情绪+风控）：质疑双方并补充
│
└── 辩论产出：一致的结论 + 仍存在的分歧点 + 各角色论据摘要

第三阶段：综合研判
└── 综合Agent（DeepSeek V4 / 深度思考LLM）汇总：
    ├── 各角色核心观点（独立分析摘要）
    ├── 辩论共识点（所有角色一致的判断）
    ├── 辩论分歧点（角色间仍存在的矛盾）
    ├── 不确定因素评估（数据完整度、参数假设）
    ├── 综合信号方向（多/空/观望，附置信度等级）
    └── 多情景推演（if X then Y，引用各角色论据）
```

### 4.4 建议的输入项定义

| 输入类别 | 内容 | 提供者 | 对所有角色可用 |
|:---------|:-----|:-------|:-------------|
| 股票基本信息 | ts_code, name, industry, sector | 后端 | ✅ |
| 日线行情 | 近750根日线 OHLCV | chart | ✅ |
| 策略现状输出 | 缠论/量价/筹码/情绪等策略结果 | strategy endpoints | ✅（技术/筹码角色优先使用）|
| 财务数据 | PE/PB/ROE/营收/利润 | Tushare fina_indicator | ✅（基本面角色优先使用）|
| 资金流向 | 主力净流入/北向资金/大单分布 | Tushare moneyflow | ✅（筹码角色优先使用）|
| 新闻/公告 | 近期新闻、公告、研报 | news/reports | ✅（消息面角色优先使用）|
| 情绪指标 | 情绪周期阶段、拥挤度、板块轮动 | crowding/sector_rotation | ✅（情绪角色优先使用）|
| Wiki知识库 | LLM Wiki中相关概念和规则 | WikiConceptMatcher | ✅（所有角色检索使用）|
| 风控数据 | 验证链结果、冲突仲裁数据 | verification_chains + conflict_arbiter | ✅（风控角色优先使用）|

### 4.5 建议的输出结构

借鉴 TradingAgents-Astock 的研报格式 + AlphaInsight 的溯源做法，建议以下输出结构：

```json
{
  "stock": {
    "ts_code": "000762.SZ",
    "name": "西藏矿业",
    "analysis_date": "2026-06-22"
  },
  "independent_analysis": [
    {
      "role": "technical",
      "role_name": "技术分析师",
      "summary": "五维结构呈现震荡偏多格局，缠论中枢上沿有支撑...",
      "key_points": [
        "日线级别上升笔延续，中枢区间2950-3100",
        "量价形态识别为EAGLE状态，突破形态确认",
        "RSI 52.3，处于中性偏强区域"
      ],
      "sources": [
        {"type": "strategy", "source": "chanlun_strategy.py", "data": "上升笔+中枢"},
        {"type": "strategy", "source": "volume_price_strategy.py", "data": "FMZ状态=EAGLE"}
      ]
    },
    {
      "role": "fundamental",
      "role_name": "基本面分析师",
      "summary": "估值处于历史中低分位，但增长动力有所减弱...",
      "key_points": ["PE(TTM)=28.5x，低于行业均值", "营收增长12.3% YoY，增速放缓"],
      "sources": [{"type": "data", "source": "Tushare fina_indicator", "data": "..."}]
    }
    // ... 其他角色
  ],
  "debate": {
    "rounds": [
      {
        "round": 1,
        "topic": "走势结构与资金面一致性",
        "participants": [
          {"role": "technical", "stance": "看多", "argument": "中枢上沿支撑有效，放量突破概率大..."},
          {"role": "chip", "stance": "中性", "argument": "虽然主力资金持续流入但筹码集中度下降..."}
        ]
      },
      {
        "round": 2,
        "topic": "综合多空辩论",
        "participants": [
          {"role": "bull_side", "members": ["technical", "fundamental"], "argument": "..."},
          {"role": "bear_side", "members": ["news", "risk"], "argument": "..."},
          {"role": "neutral_side", "members": ["chip", "sentiment"], "argument": "..."}
        ]
      }
    ],
    "consensus_points": ["中期仍处于上行通道", "短期存在回踩需求"],
    "disagreement_points": [
      {"topic": "突破时点判断", "technical": "3-5日内", "chip": "至少1-2周"},
      {"topic": "估值支撑力度", "fundamental": "充分支撑", "news": "无明显催化"}
    ]
  },
  "synthesis": {
    "overall_direction": "中性偏多",
    "conviction_level": "中等（60-70%置信度）",
    "reasoning": "技术面和筹码资金面一致看多，但基本面和消息面偏谨慎...",
    "scenarios": [
      {"scenario": "放量突破", "condition": "近3日放量+站稳中枢上沿", "probability": "~40%", "target": "¥32-¥35"},
      {"scenario": "缩量回踩", "condition": "量能萎缩至均量50%以下", "probability": "~35%", "target": "中枢下沿¥28"},
      {"scenario": "破位下行", "condition": "情绪持续恶化+跌破中枢", "probability": "~25%", "target": "¥26-¥28"}
    ],
    "risk_warning": "消息面无明显催化，短期缺乏突破动力",
    "data_integrity": {"technical": "100%", "fundamental": "80%", "chip": "90%", "sentiment": "70%", "news": "60%"}
  }
}
```

---

## 5. 与个股策略分析页的关系定位

### 5.1 参照183号方案的三大模块定位

```
模块① 选股系统（screener）
    ↓ 筛选出候选股票
模块② 个股策略分析（indicator-ide）
    ↓ 策略现状识别 + DeepSeek V4叙事 + 单维情境推演
    ↓ 底部工具条 [📊 多角色对比] 按钮
模块③ AI多角色分析（ai-analysis）
    └→ 多角色独立分析 → 辩论 → 综合输出
```

### 5.2 共享 vs 差异化的能力

| 能力 | 个股策略分析 | AI多角色分析 | 关系 |
|:-----|:------------|:-------------|:------|
| 量价/缠论/筹码策略输出 | ✅ 卡1-3数据来源 | ✅ 各角色分析输入 | 复用 |
| DeepSeek V4 叙事引擎 | ✅ Layer 1 (卡内叙事) | ✅ 辩论综合阶段 | 共享端点 |
| LLM Wiki 知识库 | ✅ 幻觉防护锚定 | ✅ 各角色独立检索 | 复用 |
| 情景化推演 | ✅ 卡5的情境层 | ✅ 综合输出中的多情景 | 不同场景不同深度 |
| 幻觉防护体系 | ✅ 三层护栏 | ✅ 三层护栏 | 复用 |
| 多角色辩论 | ❌ | ✅ 核心能力 | 独有 |
| 角色对抗机制 | ❌ | ✅ 多轮辩论 | 独有 |
| 独立角色调研报告 | ❌ | ✅ 每个角色独立输出 | 独有 |

### 5.3 页面联动设计

```
[indicator-ide 底部工具条]
    ┌─────────────────────────────────────────┐
    │ [🔄 重新仲裁] [📊 多角色对比 →] [💾 保存分析] │
    └─────────────────────────────────────────┘
                              ↓ 点击
[ai-analysis 页面加载]
    ├── 自动填写当前股票代码
    ├── 自动获取 indicator-ide 当前分析结果作为输入
    └── 各角色开始并行分析
```

---

## 6. 推荐实施方案

### 6.1 设计原则总结

| 原则 | 说明 |
|:-----|:------|
| **去评分化** | 不输出6.8/10、置信度72%等评分数字（评分仅用于选股系统） |
| **结构化溯源** | 每条观点/数据点标注来源、策略输出段、Wiki知识点 |
| **角色独立** | 各角色独立运行，不共享上下文，仅在辩论阶段交叉 |
| **辩论透明** | 辩论过程对用户可见（折叠展开），不是黑箱 |
| **成本可控** | 参考TradingAgents实测，国内模型~¥0.2-0.3/份全量研报 |
| **降级兜底** | DeepSeek不可用时以结构化标签+预览文本展示 |

### 6.2 阶段实施建议

| 阶段 | 内容 | 前端工作量 | 后端工作量 | 参考项目 |
|:-----|:------|:----------|:----------|:---------|
| **Phase 0** | 当前原型清理 — 移除评分体系，重构为角色Tab布局 | 小 | 无 | — |
| **Phase 1** | 独立分析模式 — 每个角色调用各自数据源输出独立分析结果 | 中 | 中（编排逻辑） | TradingAgents Analyst Team |
| **Phase 2** | 对抗辩论 — 两轮辩论 + 共识/分歧标注 | 中 | 大（辩论编排） | TradingAgents Debate + AlphaInsight |
| **Phase 3** | 综合研判 + 情境推演 — DeepSeek V4 综合输出 | 小 | 小（复用现有） | TradingAgents Research Manager |
| **Phase 4** | 辩论过程可视化 — 实时泡/因果链 + indicator-ide联动 | 大 | 中（WebSocket/SSE） | TradingAgents-Studio + trading-arena |
| **Phase 5** | 历史分析记录 + 决策回放 | 中 | 中 | TradingAgents-Studio |

---

## 参考资料

- [TradingAgents: Multi-Agents LLM Financial Trading Framework (arXiv 2412.20138)](https://arxiv.org/abs/2412.20138)
- [TradingAgents GitHub (TauricResearch)](https://github.com/TauricResearch/TradingAgents)
- [TradingAgents-Astock (simonlin1212)](https://github.com/simonlin1212/TradingAgents-astock) — A股特化版
- [trading-arena (2aronS)](https://github.com/2aronS/trading-arena) — 实时辩论可视化
- [TradingAgents-Studio (wjhccc)](https://github.com/wjhccc/TradingAgents-Studio) — 全栈Web可视化平台
- [AlphaInsight (Robot-Nav)](https://github.com/Robot-Nav/AlphaInsight) — 对抗辩论式尽调
- [Orallexa AI Trading Agent (alex-jb)](https://github.com/alex-jb/orallexa-ai-trading-agent) — 4角色+多空辩论
- 本项目 [180号方案](002-方案存档/180-股票现状识别最优方式定义与现状对照.md) §7 — 去评分化+叙事输出范式
- 本项目 [183号方案](002-方案存档/183-三模块策略架构评估与建议.md) — 三模块定位
