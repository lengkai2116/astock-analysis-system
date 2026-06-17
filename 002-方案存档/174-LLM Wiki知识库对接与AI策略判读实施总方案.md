# LLM Wiki 知识库对接与AI策略判读实施总方案

> **文档编号**: 174
> **编制日期**: 2026-06-14
> **类型**: 架构方案 / 系统集成
> **状态**: 待实施
> **标签**: [LLM Wiki, 知识库, AI策略判读, 系统集成, RAG]
> **前提方案**: [139](./139-策略系统重构：三层递进筛选与闭环验证体系方案.md)、[166](./166-前端UI原型逐页调整记录.md)、[171](./171-功能视图API映射对照表.md)

---

## 一、背景与目标

### 1.1 当前状态

系统已具备三层筛选流水线（达尔文L1→筹码L2→策略L3），但L3的策略输出方式为**机械式评分直出建议**，缺少对股票现状的多维度描述和综合判读能力。同时桌面已部署 **LLM Wiki** 应用（`nashsu/llm_wiki`）并建立了完整的 A股研究知识库。

### 1.2 LLM Wiki 软件概述

| 属性 | 内容 |
|:-----|:------|
| 项目地址 | https://github.com/nashsu/llm_wiki |
| 技术栈 | Tauri v2 + React 19 + Rust |
| 运行方式 | macOS .app / Windows .msi / Linux .deb |
| 本地服务 | HTTP API `127.0.0.1:19828` + 可选 MCP Server |
| 知识库路径 | `/Users/kalence/Desktop/未命名文件夹/A股研究/wiki/` |
| 项目ID | `8e27eaf1-d636-414d-bc24-0ae5e94ad0c1` |
| API Token | 已配置（通过 `Authorization: Bearer` 认证） |

### 1.3 知识库现状

| 类型 | 数量 | 说明 |
|:-----|:----:|:-----|
| 概念页 (concepts) | 773 | 缠论/量价/筹码/因子/技术指标/市场理论等 |
| 实体页 (entities) | 273 | 公司/人物/产品等 |
| 来源文献 (sources) | 98 | PDF书籍摘要（缠论/量化/价值投资等）|
| 研究查询 (queries) | 63 | 历史深度研究结果 |
| 原始PDF | 48 | 完整本地存储 |
| 知识图谱 | ✅ | 4信号关联模型（直接链接/源重叠/Adamic-Adar/类型亲和）|

### 1.4 目标

建立 **策略评估结果 → 知识库查询 → AI综合判读** 的全链路，将L3策略从"机械评分"升级为"有知识支撑的AI判读"。

> **适用范围变更：** 经UI评估确认，AI判读功能将落地在 **个股策略分析（indicator-ide）页面**，而非选股系统（screener）。选股系统保留纯规则评分模式以保障批量筛选效率。详见[166号方案 §5](./166-前端UI原型逐页调整记录.md#5-选股系统-l3-升级规划ai判读方向)。

---

## 二、LLM Wiki API 与对接标准

### 2.1 服务地址

| 项目 | 值 |
|:-----|:----|
| 基础URL | `http://127.0.0.1:19828` |
| 认证方式 | `Authorization: Bearer <token>` |
| Token | `8vp3lOahrm3JalFWbN0CADwmShj7dSTTtA_i8aLDJ84` |
| 健康检查 | `GET /api/v1/health`（无需鉴权）|

### 2.2 可用API清单

| 端点 | 方法 | 用途 | 与本系统关联 |
|:-----|:-----|:------|:------------|
| `/api/v1/health` | GET | 存活探针 | 系统启动时检查LLM Wiki是否运行 |
| `/api/v1/projects` | GET | 列出所有项目 | 获取当前项目ID |
| `/api/v1/projects/{id}/files` | GET | 列出文件树 | 调试/维护用 |
| `/api/v1/projects/{id}/files/content` | GET | 获取文件内容 | 调试用 |
| `/api/v1/projects/{id}/search` | POST | **知识库检索** | **核心接口：策略判读时查询相关知识** |
| `/api/v1/projects/{id}/graph` | GET | 知识图谱查询 | 扩展分析用 |
| `/api/v1/projects/{id}/reviews` | GET | 获取待处理项 | 维护监控 |

### 2.3 知识库搜索接口详解

**请求格式：**
```json
POST /api/v1/projects/{projectId}/search
Authorization: Bearer <token>

{
  "query": "缠论 买卖点 中枢 上涨笔",
  "topK": 5,
  "includeContent": true
}
```

**响应格式：**
```json
{
  "ok": true,
  "results": [
    {
      "path": "wiki/concepts/chanlun.md",
      "score": 85.5,
      "snippet": "...",
      "content": "..."
    }
  ],
  "mode": "keyword"
}
```

**参数说明：**

| 参数 | 类型 | 默认 | 说明 |
|:-----|:-----|:-----|:------|
| `query` | string | 必填 | 搜索关键词（中文分词+语义匹配）|
| `topK` | int | 5 | 返回结果上限 |
| `includeContent` | bool | false | 是否包含完整文档内容 |
| `queryEmbedding` | float[] | 可选 | 显式向量（LLM Wiki自动处理）|

### 2.4 MCP Server（可选增强）

LLM Wiki 内置 MCP（Model Context Protocol）服务器，复用相同端口和认证。启用后智能体客户端可通过标准 MCP 协议直接查询知识库。

**启用条件：**
1. LLM Wiki 仓库中执行 `npm run mcp:build`
2. MCP 客户端连接 `http://127.0.0.1:19828/mcp`
3. 认证复用相同 Token

---

## 三、系统集成方案

### 3.1 全链路架构

```
┌─ 数据层 ──────────────────────────────────────────────────┐
│ Tushare/AKShare → DataManager → DuckDB/PostgreSQL          │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─ 策略层 (Screener Pipeline) ───────────────────────────────┐
│ L1: DarwinRiskFilter (风险剔除)                             │
│ L2: ChipScorer (主力识别)                                   │
│ L3: 策略验证 (用户自选)                                     │
│     ├─ ☑ 缠论策略 → 输出现状: "中枢震荡偏上，三买确认"      │
│     ├─ ☑ 量价策略 → 输出现状: "VP-1价涨量增，接近通道上轨" │
│     └─ ☑ 多因子评分 → 输出现状: "Alpha前15%，成长因子降速" │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ 现状解读(结构化文本)
┌─ 知识层 ───────────────────────────────────────────────────┐
│ LLM Wiki API 检索                                          │
│ POST /api/v1/projects/{id}/search                          │
│ → 返回缠论理论/量价规则/因子模型相关知识                    │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ 知识库结果 + 市场上下文
┌─ AI判读层 ─────────────────────────────────────────────────┐
│ StrategyAIInterpretationService                            │
│ + AiContextBuilder (市场环境/指数/行业/资金流)              │
│ + DeepSeek API → 综合判读                                  │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ 综合判读结果
┌─ 前端展示层 ───────────────────────────────────────────────┐
│ L3面板: 勾选策略 + AI判读区域                               │
│ ┌─ 现状评述 ───────────────────────────────────────────┐   │
│ │ 缠论: 中枢震荡偏上, 三买确认, 上行趋势笔延续          │   │
│ │ 量价: VP-1价涨量增, 接近通道上轨, 需警惕短期回调      │   │
│ │ 综合: 偏多格局, 适合逢低布局                          │   │
│ └──────────────────────────────────────────────────────┘   │
│ 评级: ✅ 推荐 (置信度78/100)                                │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 策略输出现状解读（L3改造）

每个策略需改造为输出**结构化现状描述**而非评分：

#### 3.2.1 缠论策略输出格式

```json
{
  "strategy": "chanlun",
  "status": {
    "direction": "bullish",          // bullish/bearish/neutral
    "trend_desc": "日线上涨笔延续",
    "zhongshu_zone": {"upper": 13.20, "lower": 11.80},
    "buy_sell_points": ["三买确认"],
    "divergence": null,
    "key_levels": {"support": 12.10, "resistance": 13.80}
  },
  "narrative": "日线级别中枢震荡偏上，已确认第三类买点，MACD零轴上方金叉，上行趋势笔延续。"
}
```

#### 3.2.2 量价策略输出格式

```json
{
  "strategy": "volume_price",
  "status": {
    "vp_pattern": "VP-1",
    "stage": "拉升阶段",
    "momentum": "偏强",
    "anomaly": "接近通道上轨"
  },
  "narrative": "价涨量增(VP-1)，处于拉升阶段，动量偏强但已接近上升通道上轨，需关注量能持续性。"
}
```

#### 3.2.3 多因子策略输出格式

```json
{
  "strategy": "factor",
  "status": {
    "alpha_rank": "前15%",
    "factor_contrib": {"momentum": 0.6, "value": -0.2, "quality": 0.3},
    "divergence_alert": "成长因子月环比下降"
  },
  "narrative": "Alpha因子综合排名前15%，动量因子贡献突出，但成长因子月环比下降，存在风格切换风险。"
}
```

### 3.3 知识库查询规范

#### 3.3.1 查询映射表

| 策略类型 | 搜索关键词 | 期望知识域 |
|:---------|:-----------|:-----------|
| 缠论 (chanlun) | "缠论 买卖点 中枢 背驰 级别" | 三类买卖点、中枢理论、背驰识别 |
| 量价 (volume_price) | "量价形态 VP 价涨量增 量价关系" | 量价九种形态、量价背离、量托量压 |
| 多因子 (factor) | "多因子选股 Alpha 因子模型 因子失效" | 因子分类、合成方法、常见陷阱 |
| 筹码 (chip) | "筹码分布 主力追踪 ASR CYQKL" | 筹码形态、主力阶段识别 |

#### 3.3.2 查询参数标准

```python
# Python 后端查询模板
def query_wiki(strategy_type: str, stock_narrative: str) -> List[Dict]:
    """查询 LLM Wiki 知识库"""
    keywords = STRATEGY_WIKI_KEYWORDS[strategy_type]
    query = f"{keywords} {stock_narrative}"
    
    response = requests.post(
        f"{LLM_WIKI_URL}/api/v1/projects/{PROJECT_ID}/search",
        headers={"Authorization": f"Bearer {LLM_WIKI_TOKEN}"},
        json={"query": query, "topK": 3, "includeContent": False}
    )
    return response.json().get("results", [])
```

#### 3.3.3 数据流时序

```
① 用户点击"执行筛选"
② Screener Pipeline 执行（L1→L2→L3）
   L3 各策略输出现状叙述（text）
③ 系统收集所有策略的现状叙述
④ 构造知识库查询关键词（从现状中提取关键术语）
⑤ 调用 LLM Wiki API 搜索 → 返回相关知识
⑥ 调用 AiContextBuilder 构建市场上下文
⑦ 调用 DeepSeek API（含知识库结果+现状+上下文）→ 生成综合判读
⑧ 前端展示：现状描述 + 知识参考 + AI判读
```

### 3.4 AI 判读 Prompt 模板

```
你是一位有20年经验的A股策略分析师。

【股票信息】
{ts_code} - {stock_name}

【策略现状】
{各策略的现状叙述}

【市场环境】
{大盘趋势}/{板块强度}/{资金流向}

【知识参考】
{LLM Wiki 查询结果摘要}

请基于以上信息，输出以下 JSON 格式的综合判读：
{
  "assessment": "现状综合评述（自然语言200字内）",
  "rating": "强烈推荐/推荐/关注/观望/规避",
  "confidence": 0-100,
  "key_evidence": ["证据1", "证据2", "证据3"],
  "risk_notes": ["风险提示1", "风险提示2"],
  "key_levels": {"support": "支撑位", "resistance": "阻力位"}
}
```

---

## 四、前端展示方案

### 4.1 L3 面板布局

```
┌─ L3 用户自选策略（勾选 → 输出现状 → AI判读）────────────────┐
│                                                              │
│  ☑ 缠论策略  ☑ 量价策略  ☑ 多因子评分  ☐ 其他(开发中)        │
│  ──────────────────────────────────────────────────────────   │
│  权重配置: 缠论40% / 量价30% / 因子30%                       │
│                                                              │
│  ══════════ AI 综合判读 ══════════                           │
│                                                              │
│  ┌─ 现状评述 ───────────────────────────────────────────┐   │
│  │ 日线中枢震荡偏上，第三类买点已确认，量价配合良好。    │   │
│  │ Alpha因子排名靠前，但接近通道上轨且成长因子增速放缓。 │   │
│  │ 综合判断为偏多格局，适合逢低布局，短线注意回调风险。  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  综合评级: ✅ 推荐 (置信度78/100)                            │
│  关键价位: 支撑 ¥12.10 / 阻力 ¥13.80                        │
│  风险提示: 通道上轨附近注意量能变化                          │
│                                                              │
│  ⚡ 点击重新AI判读  [触发]                                   │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 筛选结果表格

| 代码 | 名称 | 综合评分 | 评级 | AI判读摘要 | 选用策略 | 操作 |
|:----|:-----|:--------|:----|:----------|:---------|:-----|
| 000762.SZ | 西藏矿业 | 78 | ✅ 推荐 | 缠论三买+量价配合 | 缠+量+因子 | → 详情 |
| 000001.SZ | 平安银行 | 85 | 🔥 强烈推荐 | 缠论二买+底背离 | 缠+量+因子 | → 详情 |
| 002415.SZ | 海康威视 | 55 | 👀 关注 | 中枢震荡待方向 | 缠+量 | → 详情 |

### 4.3 与已有API映射（171号方案更新项）

| 端点 | 方法 | 状态 | 说明 |
|:-----|:-----|:-----|:------|
| `POST /api/v3/screener/run` | POST | ✅ 已有 | 需扩展输出字段（各策略现状叙述）|
| `POST /api/v3/llm-wiki/search` | POST | ⚠️ **新增** | 查询 LLM Wiki 知识库 |
| `POST /api/v3/ai/strategy-interpret` | POST | ⚠️ **新增** | 现状+知识库+上下文 → AI判读 |
| `GET /api/v3/llm-wiki/health` | GET | ⚠️ **新增** | 检查 LLM Wiki 服务状态 |

---

## 五、配置与环境变量

### 5.1 新增环境变量

| 变量 | 用途 | 示例值 |
|:-----|:-----|:-------|
| `LLM_WIKI_URL` | LLM Wiki API 地址 | `http://127.0.0.1:19828` |
| `LLM_WIKI_TOKEN` | API 访问令牌 | `8vp3lOahrm3JalFWbN0CADwmShj7dSTTtA_i8aLDJ84` |
| `LLM_WIKI_PROJECT_ID` | 项目ID | `8e27eaf1-d636-414d-bc24-0ae5e94ad0c1` |
| `LLM_PROVIDER` | LLM类型 | `deepseek`（当前mock，需切换）|
| `DEEPSEEK_API_KEY` | DeepSeek Key | 已在.env中配置 |
| `WIKI_PATH` | 知识库本地路径 | `/Users/kalence/Desktop/未命名文件夹/A股研究/wiki` |

### 5.2 系统健康检查条件

系统启动时需检查：
1. LLM Wiki 服务是否运行 → `GET /api/v1/health` 返回 200
2. 知识库是否可查询 → `POST /api/v1/projects/{id}/search` 返回结果
3. DeepSeek API 是否可用 → `LLM_PROVIDER=deepseek` 时检查API Key

若 LLM Wiki 不可用，L3 自动降级为纯规则评分模式。

---

## 六、实施路线

| Phase | 内容 | 工作量 | 依赖 |
|:------|:-----|:------|:-----|
| **P1** | 后端 `llm-wiki-search` 服务 + `strategy-interpret` 路由 | 2天 | 环境变量配置 |
| **P2** | 改造 L3 策略输出为"现状叙述"格式（缠论/量价/因子）| 3天 | P1 |
| **P3** | `StrategyAIInterpretationService` 集成 LLM Wiki查询 | 1天 | P1+P2 |
| **P4** | 前端 L3 勾选面板 + AI判读结果区改造 | 2天 | — |
| **P5** | `LLM_PROVIDER` 切换 deepseek + 集成测试 | 1天 | P3+P4 |
| **P6** | 171号方案 API 映射更新 | 0.5天 | P1~P5 |

**总计：~9.5 天**

---

## 七、风险与注意事项

| 风险 | 等级 | 应对 |
|:-----|:-----|:-----|
| LLM Wiki 后台未启动 | 🔴 高 | L3 自动降级为纯规则模式 |
| DeepSeek API 费用 | 🟡 中 | 仅对选股结果使用，非每只股票都调 |
| AI 判读延迟（~3秒/次）| 🟡 中 | 前端显示加载态，批处理时异步 |
| 知识库内容过期 | 🟢 低 | 缠论/量价理论相对稳定 |
| API Token 泄露 | 🟢 低 | 仅 localhost 可访问 |

---

> **文档版本**: v1.0
> **编制日期**: 2026-06-14
> **关联文档**: [139-策略系统重构](./139-策略系统重构：三层递进筛选与闭环验证体系方案.md)、[166-前端UI原型逐页调整记录](./166-前端UI原型逐页调整记录.md)、[171-功能视图API映射对照表](./171-功能视图API映射对照表.md)
