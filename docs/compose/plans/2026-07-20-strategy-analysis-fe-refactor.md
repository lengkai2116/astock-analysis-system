# 个股策略分析前端重设计 Implementation Plan

> **For agentic workers:** Inline execution within current session.

**Goal:** 将 indicator-ide.html 的策略分析区域从旧5卡设计重构为：操作台(STRATEGY CONSOLE) + 股票现状卡片(STOCK STATUS CARD) + 策略建议(STRATEGY RECOMMENDATION) + 实操建议(ACTION PLAN)

**Architecture:** 单文件 HTML + vanilla JS + CSS，所有新组件嵌入 indicator-ide.html。复用现有API端点(E12/E13/E14)和复盘中心接口(POST /api/v3/playback/entries)。

**Tech Stack:** HTML5 / CSS3 / Vanilla JS / 现有 REST API

---

### Task 1: STRATEGY CONSOLE — HTML+CSS

**Covers:** [S2]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html:700-756` — 替换旧strategyBar + strategyConfig

**Changes:**
1. 移除旧 strategy-bar (line 706-713) 、 strategy-config (line 717-737) 、strategy-empty (line 741-755)
2. 插入新 STRATEGY CONSOLE 的HTML结构
3. 添加玻璃态+霓虹边框的CSS样式
4. 保留 loading 状态 HTML (line 758-766)

### Task 2: STOCK STATUS CARD — HTML+CSS

**Covers:** [S3]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html:769-928` 替换旧dim-cards
- Modify: CSS 中的 `.dim-card` 样式替换为 dashboard-bar + deepseek-text 样式

**Changes:**
1. 移除 5 个 dim-card (lines 769-928)
2. 移除 dim-card CSS (lines 274-290)
3. 插入 5 格 Dashboard Bar HTML
4. 插入 DeepSeek 九层描述展示区（全展开，大字体）

### Task 3: STRATEGY RECOMMENDATION + ACTION PLAN — HTML+CSS

**Covers:** [S4, S5]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html:929-1060` 替换旧ai-arbitration

**Changes:**
1. 保留情景推演部分(线956-991)，但结构简化
2. 替换和补充为四象限策略建议卡片
3. 替换实操参考为三情景实操建议+复盘中心按钮

### Task 4: CSS 及整体样式

**Files:**
- Modify: `_ui-prototype/indicator-ide.html` 中所有新增CSS
- Modify: `_ui-prototype/assets/base.css` — 如有需要

### Task 5: JavaScript 逻辑实现

**Covers:** [S2, S3, S4, S5, S6]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html` JS section (lines 3171-3530+)

**Changes:**
1. 重写 startAnalysis() — 读取操作台配置并调用 API
2. 重写 finishAnalysisReal() — 填充新三组件
3. 新增 console toggle/logic + localStorage persistence
4. 新增 factor combo 异步加载
5. 新增 Vibe strategy 异步加载
6. 新增 复盘池/虚拟开仓 按钮逻辑
7. 新增 renderStockStatus(), renderStrategyRecommendation(), renderActionPlan()
