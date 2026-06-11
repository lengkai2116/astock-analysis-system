---
title: 前端 Mock 数据全面审计报告
type: 审计报告
date: 2026-06-09
status: 已完成
---

# 前端 Mock 数据全面审计报告

> 审计日期：2026-06-09
> 审计范围：`frontend/vue-project/src/` 下全部 `.vue`、`.js` 文件
> 审计目标：识别前端使用硬编码 mock/假数据替代真实后端 API 的情况

---

## 一、审计方法论

1. 全量扫描前端 52 个源文件（`.vue` + `.js`）
2. 提取每个组件的 `data()` 初始化块，检测硬编码对象数组
3. 提取每个组件的 `mounted()/loadData()` 方法，追踪 API 调用路径
4. 匹配前端 API 调用与后端路由注册表，标记缺失端点
5. 分类分级：P0（显示假数据）/ P1（数据源不对）/ P2（端点缺失）

---

## 二、审计结果概览

| 等级 | 数量 | 描述 |
|------|------|------|
| 🔴 P0 | 7 项 | 前端直接填充硬编码数据，用户看到的是虚构值 |
| 🟡 P1 | 3 项 | 数据应来自 API 但前端用了占位硬编码 |
| 🔵 P2 | 5 项 | 后端端点缺失导致整页功能降级到 mock |
| ✅ 可接受 | 6 项 | UI 表格列定义 / 选项映射常量，非 mock 数据 |

---

## 三、🔴 P0 — 显示假数据却看起来像真的

### 3.1 仪表盘 — 四个数据区块全为 mock

**文件：** `frontend/vue-project/src/views/dashboard/index.vue`

仪表盘的 `loadData()` 并发调用了 4 个 API，其中 3 个后端不存在、1 个刚修复，全部失败后走 `catch` 分支的 `_mock*()` 兜底：

| 数据区块 | Mock 函数 | 行号 | 虚构内容示例 |
|---------|-----------|------|------------|
| 涨跌幅排行 | `_mockRankData()` | L695 | 平安银行 +3.21%、万科A +2.56% 等 5 只虚构股票 |
| 市场概况 | `_mockMarketData()` | L705 | 上证指数 3915（已更新，原为 3150，仍是兜底值） |
| 策略信号 | `_mockSignals()` | L713 | 平安银行「放量突破」、茅台「MACD死叉」等 3 条虚构信号 |
| 最近活动 | `_mockActivities()` | L720 | "数据源已切换至备用通道" 等 4 条虚构活动 |

**根因链路：**
```
getWatchlistData() → GET /api/v3/watchlist/dashboard ❌ 不存在
getMarketOverview() → GET /api/v3/market/overview ✅ 已修复
getStrategySignals() → GET /api/v3/signals/summary ❌ 不存在
getAIAnalysisSignals() → GET /api/v3/ai-analysis/signals ❌ 不存在
→ 全部 catch → _mock*()
```

### 3.2 因子选择器 — 11 个虚构因子

**文件：** `frontend/vue-project/src/components/FactorSelector/index.vue`

`data()` 中直接定义了 11 个硬编码因子对象（L144-154），涉及 Qlib、国泰君安、学术、动量等分类。这些因子**从未调用后端 `/api/factors` 端点**（该端点已实现）。

关键代码路径：
```javascript
// data()
mockFactors: [{ id: 'qlib_alpha1', name: 'Alpha#001', ... }, ...]

// computed
allFactors() { return this.mockFactors }
filteredFactors() { /* filter on mockFactors */ }
```

### 3.3 因子管理 — 10 个虚构因子 + 2 个虚构组合

**文件：** `frontend/vue-project/src/views/factor-manager/index.vue`

- `mockFactors: [10]` (L404-415)：与 FactorSelector 同源的硬编码因子
- `mockCombinations: [2]` (L381-383)：虚构的组合配置
- `computed.combinations()` (L422-427)：优先尝试从 store 读取，但 store 无数据时**静默回退到 mockCombinations**，用户无感知

---

## 四、🟡 P1 — 数据应来自 API 但硬编码

### 4.1 AI 分析 — 股票列表硬编码

**文件：** `frontend/vue-project/src/views/ai-analysis/index.vue` L216-224

```javascript
watchlist: [
  { symbol: '600519.SH', name: '贵州茅台' },
  { symbol: '000001.SZ', name: '平安银行' },
  // ... 共 7 只
]
```

股票选择下拉列表直接写死了 7 只 A 股核心资产，未从自选股 API 或股票列表 API 加载。

### 4.2 AI 分析 — 角色配置硬编码

**文件：** 同上 L231-237

```javascript
roles: [
  { key: 'technical', label: '技术面分析师' },
  // ... 共 5 个角色
]
```

应作为系统配置从后端加载，而非前端写死。

### 4.3 指标 IDE — 指标列表硬编码

**文件：** `frontend/vue-project/src/views/indicator-ide/index.vue` L545-555

```javascript
overlayIndicators: [MA5, MA10, MA20, BOLL]
subIndicators: [VOL, MACD, RSI, KDJ]
```

后端 `/api/v3/chart/indicators` 端点已实现可返回完整指标列表，但前端未调用。

---

## 五、🔵 P2 — 缺失后端端点

以下 5 个端点被前端代码调用（通过 `dataService.js`），但在后端无对应路由：

| # | 端点 | 前端调用方 | 影响范围 |
|---|------|-----------|---------|
| 1 | `POST /api/auth/login` | `login/index.vue` | 登录功能不可用 |
| 2 | `GET /api/auth/status` | `login/index.vue` | 自动登录检测不可用 |
| 3 | `GET /api/v3/watchlist/dashboard` | `dataService.getWatchlistData()` | 仪表盘涨跌幅排行 + 统计卡片 |
| 4 | `GET /api/v3/signals/summary` | `dataService.getStrategySignals()` | 仪表盘策略信号 + 活动日志 |
| 5 | `GET /api/v3/ai-analysis/signals` | `dataService.getAIAnalysisSignals()` | 仪表盘 AI 信号总线 + 共振评分 |

---

## 六、✅ 可接受 — UI 配置常量（非 mock 数据）

以下项虽包含硬编码对象数组，但属于 UI 展示层配置，不构成数据造假：

| 文件 | 内容 | 说明 |
|------|------|------|
| `ScreeningResults.vue` L92 | `columns: [6]` | AntDV 表格列定义 |
| `backtest/index.vue` L368 | `columns: [5]` | 回测结果列定义 |
| `ReportViewer.vue` L472 | `tradeColumns: [5]` | 交易记录列定义 |
| `watchlist/index.vue` L327 | `allColumns: [14]` | 自选股可开关列配置 |
| `SignalFusionConfig.vue` L141 | `strategies: [3]` | 策略 key→label 映射 |
| `factor-manager/index.vue` L374 | `screenColumns: [4]` | 筛选结果列定义 |

---

## 七、数据链路汇总图

```
用户界面层 (Vue)
  │
  ├─ 仪表盘 ────────────────────────────────── 4/4 区块 = mock ❌
  │   ├─ 涨跌幅排行 → dataService.getWatchlistData() → ❌ 端点缺失
  │   ├─ 市场概况   → dataService.getMarketOverview() → ✅ 已修复
  │   ├─ 策略信号   → dataService.getStrategySignals() → ❌ 端点缺失
  │   └─ 活动日志   → (同上)
  │
  ├─ 因子管理 ──────────────────────────────── 不调用 API ❌
  │   └─ FactorSelector + factor-manager → 直读 mockFactors
  │       └─ /api/factors → ✅ 后端已实现但前端不走
  │
  ├─ AI 分析 ─────────────────────────────── 硬编码占位 ❌
  │   ├─ watchlist → 7 只硬编码股票
  │   └─ roles → 5 个硬编码角色
  │
  ├─ 指标 IDE ────────────────────────────── 硬编码占位 ❌
  │   └─ indicatorList → 4+4 硬编码
  │       └─ /api/v3/chart/indicators → ✅ 已实现但前端不走
  │
  ├─ 登录页 ──────────────────────────────── API 缺失 ❌
  │   └─ /api/auth/login + /api/auth/status → ❌ 端点缺失
  │
  └─ 其他页面（选股、回测、报表、账户）──────── 基础功能可用
      └─ 调用已有后端端点 ✅
```

---

## 八、修复优先级与建议

### Phase 1 — 仪表盘打通（高影响，低复杂度）

1. 新增 `GET /api/v3/watchlist/dashboard` → 返回自选股概览数据（涨跌统计、排行）
2. 新增 `GET /api/v3/signals/summary` → 返回策略信号摘要
3. 新增 `GET /api/v3/ai-analysis/signals` → 返回 AI 信号摘要 + 共振评分
4. 前端 `dashboard/index.vue` 移除全部 `_mock*()` 函数

### Phase 2 — 因子系统真实数据化

1. `FactorSelector/index.vue` 移除 `mockFactors`，改为从 store 读取和 `factorService.getFactors()` 调用
2. `factor-manager/index.vue` 移除 `mockFactors` + `mockCombinations`，对接真实 API

### Phase 3 — 页面数据源纠正

1. AI 分析页面：watchlist 改为调用自选股/股票列表 API
2. 指标 IDE：indicators 改为调用 `chartService.getIndicatorList()`

### Phase 4 — 补齐缺失端点

1. 实现 `/api/auth/login` 和 `/api/auth/status`（或引入 JWT 鉴权）

---

## 九、附录

### 9.1 扫描命令

```bash
# 全量文件搜索 mock 关键字
grep -rn '_mock\|mockFactors\|假数据\|兜底' frontend/vue-project/src/ --include='*.vue'

# API 端点存在性匹配
python3 scripts/audit_api_endpoints.py
```

### 9.2 后端路由参考

已实现的关键路由（`backend/app/routes/`）：

| 路由文件 | 端点前缀 | 说明 |
|---------|---------|------|
| `factors.py` | `/api/factors` | 因子库（列表/计算/组合/评估） |
| `chart.py` | `/api/v3/chart` | K线图表/指标/股票列表 |
| `market.py` | `/api/v3/market` | 市场概况/行业/指数 |
| `phase3.py` | `/api/v3/*` | 自选股/模拟交易/告警 |
| `screener.py` | `/api/v3/screener` | 选股系统 |
| `strategy_templates.py` | `/api/strategy-templates` | 策略模板 |
| `reports.py` | `/api/v2/reports` | 报告生成 |
| `ai_analysis.py` | `/api/v3/ai` | AI 分析 |
