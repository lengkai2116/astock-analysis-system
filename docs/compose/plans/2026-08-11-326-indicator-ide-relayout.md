# 326号方案实施计划（个股策略分析页下半部分排布重设计）

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 326 号方案 v2.0 改造 `_ui-prototype/indicator-ide.html`：下部左右分布布局（左缠论同款容器/右现状+建议）、一句话总览、策略建议改读 operation_advice、建议卡补 entry_rules、标签解说词典化升级、DeepSeek 九层改可选追问。

**Architecture:** 纯前端改造（HTML 结构 + CSS + JS 渲染函数），新增标签词典配置（前端 JS 常量，85 标签→大白话映射）。后端零改动，复用现有 `/api/v3/strategy/deepseek` 端点与 `operation_advice`/`opportunity_profile` 数据。

**Tech Stack:** 原生 HTML/CSS/JS（MPA 架构，无框架）、pytest（后端回归）、python 静态校验（JS 语法用 node 校验）

## Global Constraints

- 不修改任何后端代码（`backend/` 下零改动）；仅 `_ui-prototype/indicator-ide.html` + `_ui-prototype/assets/base.css` + 前端新增标签词典
- 缠论结构图（日线 + 60分钟双图）**完整保留**：原位置、原内容、原交互，不折叠、不降级、不移动（用户明确要求）
- 不引入新依赖、不做超出 326 方案范围的功能
- 代码风格遵循项目惯例：原生 JS、中文文案、A股红涨绿跌色板（--color-up 红/--color-down 绿）
- 数据来源合规：仅读前端已有数据结构（`operation_advice`/`opportunity_profile`/`tags`/快照），不得直调数据源
- 每次任务结束跑 `python3 -c "HTML 结构校验"`（标签配对）+ `node --check`（提取 JS 语法校验）

---
## 文件结构

| 文件 | 职责 |
|------|------|
| `_ui-prototype/indicator-ide.html` | 主改造：HTML 结构 + CSS + 渲染函数 + 标签词典常量 |
| `_ui-prototype/assets/base.css` | 补充通用样式（如 tag-explain/追问提示，若现有样式不足） |
| `docs/compose/plans/2026-08-11-326-indicator-ide-relayout.md` | 本计划 |

> 标签词典放 `indicator-ide.html` 内 `<script>` 常量（`window.TAG_DICTIONARY`），单页自洽、无需新增后端文件；85 标签按 325 档案逐组覆盖（先覆盖高频 30+ 标签，其余显示"—"不阻塞）。

## 关键现状（实施前置信息）

- 现有页面结构：`.main-area > .chart-flex`（左 `.chart-section` K线 + 右 `.side-panel` 基础信息）→ `.sub-below`（操作台 + `stockStatus` L794 + `strategyRec` L865 + `actionPlan` L911 + arbSources L948）
- 渲染链：`finishAnalysisReal`（L3288）→ renderStockStatus/renderStrategyRecommendation/renderActionPlan + loadChanlunCharts(L3324，缠论勾选时) + loadDeepseekText(L3328-3329，deepseek_available 时**自动调用**——326 需改为可选追问)
- `renderStrategyRecommendation`（L3394-3468）：前端推导仓位 `'50%'`/周期 `'波段持有 2-4周'`/价位直读缠论——326 改为改读 operation_advice
- `renderActionPlan`（L3473-3595）：已读 operation_advice（323 S7a 摘要），缺 entry_rules 区间/触发行
- `loadDiagnosisCard`（L1962-2033）：标签解说仅 4 行硬编码（L2021-2030）——326 改为词典化网格
- 原型参考：`_ui-prototype/indicator-ide-rev2-prototype.html`（v4 已定稿，布局/样式/文案照搬）

---

### Task 1: 布局改造（上部保留 + 下部左右分布 + 缠论容器同款）

**Covers:** 326 §二 2.1/2.2、§三 #3/#10

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（HTML 结构：`main-area` 内 `chart-flex` 之后新增 `analysis-below`；`sub-below` 内 `stockStatus/strategyRec/actionPlan` 迁入右列）
- Modify: `_ui-prototype/assets/base.css`（新增 `.analysis-below/.chanlun-col/.detail-col` 布局 + 缠论容器同款样式）

**Interfaces:**
- Consumes: 现有 `chart-flex`（K线 + side-panel）结构不变
- Produces: `.analysis-below` 容器（左 `.chanlun-col` 缠论容器 flex:1.7 同 K线容器样式；右 `.detail-col` flex:1）；`#stockStatus/#strategyRec/#actionPlan` 移入 detail-col

- [ ] **Step 1: 读取现有 HTML 结构全貌（L729-960）确认迁移边界**

- [ ] **Step 2: 在 `main-area` 内 `.chart-flex` 之后新增 `analysis-below` 容器，重构下部布局**

```html
<!-- 在 .chart-flex 闭合后、main-area 内新增 -->
<div class="analysis-below">
  <!-- 左列：缠论结构图容器（同 K线图容器样式） -->
  <div class="chanlun-col">
    <div class="section-header">
      <h3>📐 缠论结构图</h3>
      <span class="section-sub">日线走势结构（长期策略）+ 60分钟走势结构（短期策略）</span>
    </div>
    <div class="cl-chart" id="chanlunChartLong">
      <div class="cl-header">日线走势结构（长期策略）</div>
      <div class="cl-body" id="clBodyLong"><div class="cl-placeholder">缠论分析中...</div></div>
    </div>
    <div class="cl-chart" id="chanlunChartShort">
      <div class="cl-header">60分钟走势结构（短期策略）</div>
      <div class="cl-body" id="clBodyShort"><div class="cl-placeholder">缠论分析中...</div></div>
    </div>
  </div>
  <!-- 右列：现状 + 建议 + 依据 -->
  <div class="detail-col">
    <div id="stockStatus">…现状卡片（含一句话总览/诊断/标签解说）…</div>
    <div id="strategyRec">…策略建议→并入操作建议…</div>
    <div id="actionPlan">…实操建议…</div>
    <div id="arbSources">…数据来源…</div>
  </div>
</div>
```

- [ ] **Step 3: 删除原 `.sub-below` 内的 `chanlunCharts` 区块（L826-835），缠论图迁移到 chanlun-col；删除原 `stockStatus/strategyRec/actionPlan` 在 sub-below 的位置，整体移入 detail-col**

- [ ] **Step 4: base.css 新增布局样式（照搬原型 v4）**

```css
.analysis-below { margin-top: var(--space-6); display: flex; gap: var(--space-4); align-items: stretch; }
.chanlun-col { flex: 1.7; min-width: 0; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: var(--space-12); display: flex; flex-direction: column; gap: var(--space-6); }
.detail-col { flex: 1; min-width: 460px; display: flex; flex-direction: column; gap: var(--space-6); }
.chanlun-col .cl-chart { flex: 1; }
```

- [ ] **Step 5: 校验 HTML 标签配对 + node --check JS 语法**

```bash
python3 -c "…HTMLParser 标签配对校验…" && node --check <提取的JS>
```

- [ ] **Step 6: 浏览器打开人工核查对齐（左列与 K线容器边缘对齐）**

---

### Task 2: 一句话总览（新增，置顶）

**Covers:** 326 §三 #1、§2.3 ①

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（stockStatus 顶部 + renderStockStatus/finishAnalysisReal）

**Interfaces:**
- Consumes: `analysisData.operation_advice`（signal_light/action_label/summary/confidence）+ 行情（sh-price/sh-pct）
- Produces: `#overviewBar` DOM 元素

- [ ] **Step 1: stockStatus 内顶部插入总览 HTML**

```html
<div class="overview-bar" id="overviewBar" style="display:none;">
  <span class="ov-light" id="ovLight">--</span>
  <span class="ov-action" id="ovAction">--</span>
  <span class="ov-summary" id="ovSummary">--</span>
  <span class="ov-price" id="ovPrice">--</span>
  <span class="ov-meta" id="ovMeta">--</span>
</div>
```

- [ ] **Step 2: renderStockStatus 或新增 `renderOverviewBar(analysisData)` 填充总览（signal_light→灯色、action_label→动作、summary→一句话、现价涨跌→ovPrice、数据日期+置信度→ovMeta）**

- [ ] **Step 3: finishAnalysisReal 在 renderStockStatus 前调用 renderOverviewBar**

- [ ] **Step 4: base.css 补 overview-bar 样式（照搬原型）**

- [ ] **Step 5: 校验 + 浏览器核查**

---

### Task 3: 策略建议改读 operation_advice + 建议卡补 entry_rules

**Covers:** 326 §三 #4/#5、§一 问题1/2/3

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（renderStrategyRecommendation L3394-3468 → 改读 operation_advice；renderActionPlan L3479-3514 补 entry_rules 渲染）

**Interfaces:**
- Consumes: `oa.operation_advice`（position.max_pct/entry_rules/exit_rules/target_levels/expected_holding/invalidation/evidence_top3/dimensions）
- Produces: 建议卡完整 10 字段（含入场区间 [x,y] 与触发条件行）；strategyRec 无硬编码残留

- [ ] **Step 1: renderStrategyRecommendation 改为：优先读 oa.executable.position.max_pct → recPosition；oa.expected_holding → recHoldingPeriod；oa 的止损/目标（executable/exit_rules 60日低点）→ recStopLoss/recTarget；删除 '50%'/'波段持有 2-4周'/缠论价位硬编码**

- [ ] **Step 2: renderActionPlan 建议卡 fields 增加两行：入场区间（entry_rules 提取区间 [min,max] 或首条 trigger）、触发条件（entry_rules trigger 中文化）**

- [ ] **Step 3: 校验 + 浏览器核查（600519/000039 建议卡 10 字段完整、无双价）**

---

### Task 4: 标签解说词典化升级 + 全量解说区块

**Covers:** 326 §三 #6/#7、§四 4.2、§2.3 ②④

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（新增 `window.TAG_DICTIONARY` 常量 + loadDiagnosisCard L2021-2030 改词典渲染 + 深度依据区新增"标签解说全量"折叠块）

**Interfaces:**
- Consumes: `stock.tags` / 快照标签字段（opportunity_type/main_force_phase/fina_health + structure/chip_deep/fund_risk 组）
- Produces: `window.TAG_DICTIONARY`（tag_name→{解释,组}，先覆盖 30+ 高频标签）；标签解说网格（命中项渲染，未命中"—"）

- [ ] **Step 1: 新增 TAG_DICTIONARY 常量（照 325 档案：缠论二买/量价配合/主力洗盘/情绪高潮/筹码主峰/5日大单净流入 等 30+ 条）**

- [ ] **Step 2: loadDiagnosisCard 标签解说改：遍历命中标签→词典取解释→渲染网格（tag-expl 2列）；无命中显示"—"**

- [ ] **Step 3: 深度依据区（新增折叠块"🏷️ 标签解说全量（85 标签词典）"）复用同一渲染函数，默认展开**

- [ ] **Step 4: base.css 补 tag-explain/te-title/te-sub 样式**

- [ ] **Step 5: 校验 + 浏览器核查（诊断卡标签解说网格正常）**

---

### Task 5: DeepSeek 九层改可选追问

**Covers:** 326 §三 #8、§四 4.2/2

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（L3328-3329 移除自动调用；L851-861 九层区改折叠+追问按钮；L2833 loadDeepseekText 改按需触发）

**Interfaces:**
- Consumes: `/api/v3/strategy/deepseek?ts_code=`（现有端点）
- Produces: 九层区默认折叠显示"🤖 追问"按钮；点击后调用端点渲染；`deepseek_available` 不再自动触发

- [ ] **Step 1: finishAnalysisReal 删除 `if(analysisData.deepseek_available){ loadDeepseekText(...) }` 自动调用（L3328-3329）**

- [ ] **Step 2: 九层 HTML 区（L851-861）改为折叠块：summary 为"🤖 DeepSeek 追问：为什么给出这个判断？（可选）"，body 初始显示"点击加载"提示，点击触发 loadDeepseekText**

- [ ] **Step 3: loadDeepseekText 保持端点不变，渲染逻辑复用（renderStockStatus 传 deepseekText 渲染 dsBody）**

- [ ] **Step 4: 校验 + 浏览器核查（默认不调用 network、点击后渲染）**

---

### Task 6: 关注点/风险评估并入风险边界 + 回归

**Covers:** 326 §三 #9、§六 验证

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（renderStrategyRecommendation 关注点/风险评估 → 并入诊断卡 risk-boundary 行）

**Interfaces:**
- Consumes: verificationData（verification_chains/uncertainties）
- Produces: risk-boundary 行含关注点/风险评估摘要

- [ ] **Step 1: 诊断卡 risk-boundary 行扩展：追加关注点（前1条）+ 风险评估（验证链未通过数）**

- [ ] **Step 2: 删除 strategyRec 独立的风险评估/关注点区块渲染（或折叠）**

- [ ] **Step 3: 全量回归：pytest（backend/tests/）+ ruff（改动的仅前端，无 ruff 范围）+ JS 语法校验 + 浏览器端到端**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v --tb=short
```

---

## Self-Review

**Spec 覆盖核对**：
- §三 #1（总览）→ Task 2 ✅；#2（5格指标条并入）→ Task 2 附带（诊断卡已含完整度，可折叠 statusDashboard）——**标注**：5格指标条并入诊断卡需在 Task 2 一并处理
- #3/#10（布局+缠论容器）→ Task 1 ✅；#4/#5（建议卡）→ Task 3 ✅；#6/#7（标签词典+解说）→ Task 4 ✅；#8（追问）→ Task 5 ✅；#9（风险并入）→ Task 6 ✅
- §六 验证 6 项 → Task 6 Step 3 回归覆盖 ✅

**补充修正（自审发现）**：Task 2 需含"5格指标条并入七维诊断卡"子步骤（§三 #2）——折叠 `statusDashboard` 或并入 diag 网格，避免重复。

**类型一致性**：`window.TAG_DICTIONARY`（Task 4 定义）在 Task 4 Step 2/3 使用，无跨任务类型依赖；`renderOverviewBar(analysisData)`（Task 2）仅 Task 2 内使用。⚠️ 注意：Task 1 迁移 DOM 后，`finishAnalysisReal` 中 `stockStatus/strategyRec/actionPlan` 的 `getElementById` 仍有效（ID 不变，仅容器位置变化）；`switchStock` L2045 的 display 控制逻辑不变。

---

**文档版本**: v1.0
**编制日期**: 2026-08-11
**关联**: 326 号方案 v2.0（原型定稿）、323（建议卡）、325（标签档案）
