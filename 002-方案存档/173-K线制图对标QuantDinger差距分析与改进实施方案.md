# 173 — K线制图对标 QuantDinger 差距分析与改进实施方案

> 版本: 1.0 | 日期: 2026-06-12 | 类型: 技术方案/实施计划
> 对标对象: [QuantDinger](https://github.com/brokermr810/QuantDinger) (7,000+ Stars)
> 引用方案: 172-QuantDinger对标分析与能力差距评估暨改进建议方案.md §3.4 K线制图对比

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [现系统K线制图全景](#2-现系统k线制图全景)
3. [双方K线制图核心对比](#3-双方k线制图核心对比)
4. [差距分析与关键发现](#4-差距分析与关键发现)
5. [改进方案详述](#5-改进方案详述)
6. [分阶段实施计划](#6-分阶段实施计划)
7. [附录](#7-附录)

---

## 1. 背景与目标

### 1.1 分析动机

K线图表是量化分析平台的核心交互界面，用户大部分的分析行为都围绕K线展开。项目对标 QuantDinger 这一优秀开源项目，发现在K线制图方面既有**显著领先优势**，也存在**关键差距**。本方案旨在系统性地梳理差距，制定可执行的改进路线。

### 1.2 涉及的核心文件

| 层级 | 文件 | 说明 |
|------|------|------|
| **前端组件** | `frontend/vue-project/src/components/KLineChart/index.vue` | K线图表核心组件（357行） |
| **前端页面** | `frontend/vue-project/src/views/indicator-ide/index.vue` | 个股策略分析页面（1070行） |
| **前端数据** | `frontend/vue-project/src/services/chartService.js` | K线数据服务（116行） |
| **前端组件** | `frontend/vue-project/src/components/CodeEditor/index.vue` | 代码编辑器（关联K线信号） |
| **前端仪表盘** | `frontend/vue-project/src/views/dashboard/index.vue` | Dashboard多图布局 |
| **后端路由** | `backend/app/routes/chart.py` | K线图表API（450行） |
| **后端引擎** | `backend/app/indicators/__init__.py` | 指标计算引擎（259行） |
| **后端信号** | `backend/app/signals/__init__.py` | 信号生成系统（404行） |
| **上游数据** | `backend/app/data/__init__.py` | 数据管理器 |

### 1.3 涉及的前端依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `klinecharts` | ^9.8.0 | 核心K线渲染引擎 |
| `echarts` | ^5.4.3 | 辅助图表（迷你K线/资金流向/雷达图等） |
| `codemirror` | ^5.65.16 | 策略代码编辑器 |

---

## 2. 现系统K线制图全景

### 2.1 架构总览

```
Tushare(主) / AKShare(备) 数据源
        ↓
  DataManager (1→2→3级缓存：DuckDB→PostgreSQL→Redis)
        ↓
  TechnicalIndicatorEngine (后端向量化计算)
  → MA5/10/20 | MACD DIF/DEA/HIST | RSI14 | KDJ K/D/J | BOLL | VOL
        ↓
  chart.py API (/api/v3/chart/kline/{ts_code})
  → 返回 {kline[], overlays[], subcharts[], signals[], stock}
        ↓
  klinecharts 前端渲染
  → 4面板布局 (candle/vol/macd/rsi) + 信号标记 (simpleAnnotation)
        ↓
  ECharts 辅助渲染 (Dashboard)
  → 迷你K线 | 资金流向 | 雷达图 | 行业排行
```

### 2.2 数据管道流程

```
① chartService.fetchKlineData(tsCode, indicators, period, limit)
   → GET /api/v3/chart/kline/{tsCode}?indicators=ma5,ma20,macd,rsi,kdj&period=D&limit=300

② chart.py get_kline_chart_data()
   a. DataManager.get_cached_daily_data() → 取原始日线数据
   b. TechnicalIndicatorEngine.calculate_all_indicators() → 计算全部指标
      - MA5/10/20 (rolling mean)
      - MACD (EMA12-EMA26, DIF/DEA/HIST)
      - RSI14 (avg_gain/avg_loss)
      - KDJ (RSV→K→D→J)
      - BOLL (20日中轨±2σ)
      - VOL_MA5/MA10
   c. 分割为主图叠加(overlays) + 副图指标(subcharts)
   d. 返回标准JSON格式

③ KLineChart组件 initChart()
   a. init(chartRef, {locale, styles, layout})
      layout = [candle_pane(h=400), vol_pane(h=80), macd_pane(h=100), rsi_pane(h=80)]
   b. applyNewData(kline) → 加载OHLCV数据
   c. createIndicator('MA', {periods:[5,10,20]}) → 主图均线
   d. createIndicator('MACD') → 副图1
   e. createIndicator('RSI') → 副图2
   f. createIndicator('VOL') → 副图3
   g. createOverlay('simpleAnnotation', signals) → 信号标记

④ 策略信号并行加载
   → GET /api/v3/chart/signals/{tsCode}
   → SignalGenerator.generate_all_signals() 计算MA/MACD/RSI/KDJ/BOL/Resonance信号
   → 渲染到K线图作为买/卖标记
```

### 2.3 现系统已实现能力清单

| 编号 | 能力 | 实现方式 | 状态 |
|:----:|------|---------|:----:|
| C-01 | 标准OHLCV K线 | klinecharts `candle_solid` | ✅ |
| C-02 | 面积图 | klinecharts `chartType: 'area'` | ✅ |
| C-03 | 线图 | klinecharts `chartType: 'line'` | ✅ |
| C-04 | Heikin Ashi 平均K线 | 自定义 `_transformHeikinAshi()` | ✅ |
| C-05 | MA均线叠加 | `createIndicator('MA')` | ✅ |
| C-06 | BOLL布林带叠加 | `createIndicator('BOLL')` + 虚线样式 | ✅ |
| C-07 | MACD副图(DIF/DEA/柱状) | `createIndicator('MACD')` | ✅ |
| C-08 | RSI副图(含参考线) | `createIndicator('RSI')` | ✅ |
| C-09 | KDJ副图(K/D/J) | `createIndicator('KDJ')` | ✅ |
| C-10 | 成交量副图(红涨绿跌) | `createIndicator('VOL')` | ✅ |
| C-11 | 4面板自动布局 | layout配置 | ✅ |
| C-12 | 买卖信号标记(红绿圆点) | `createOverlay('simpleAnnotation')` | ✅ |
| C-13 | 多指标芯片选择 | 主图/副图Tag点击切换 | ✅ |
| C-14 | 多K线分屏(网格) | Dashboard 1×1至4×2布局 | ✅ |
| C-15 | 十字光标多图同步 | 自定义事件 `chart:crosshair` | ✅ |
| C-16 | ECharts迷你K线 | 四大指数卡片内嵌candlestick | ✅ |
| C-17 | 暗色主题CSS变量体系 | `darkStyles` 对象+CSS变量 | ✅ |
| C-18 | 数据加载loading/空状态 | `a-spin` + `a-empty` | ✅ |
| C-19 | 窗口resize自适应 | ResizeObserver | ✅ |
| C-20 | 周期切换(日/周/月) | period prop + 后端数据驱动 | ✅ |
| C-21 | L2/L3/自定义三层信号面板 | indicator-ide右侧信号面板 | ✅ |
| C-22 | 综合操作建议卡片 | 多层信号聚合→action/止损/目标 | ✅ |
| C-23 | 共振评分面板 | ResonancePanel组件 | ✅ |
| C-24 | AI信号总线展示 | AiSignalBus组件 | ✅ |
| C-25 | 多图图表类型独立切换 | 每个chart-cell独立chartType | ✅ |
| C-26 | 后端T+N回调信号 | SignalGenerator后端实时计算 | ✅ |
| C-27 | 前端指标去重 | 指标芯片刻意保留至少一个 | ✅ |
| C-28 | 股票搜索+自选切换 | indicator-ide顶部工具栏 | ✅ |

---

## 3. 双方K线制图核心对比

### 3.1 关键技术选型对比

| 维度 | 本项目 | QuantDinger | 对比结论 |
|------|--------|-------------|---------|
| **核心K线库** | klinecharts v9.8.0 | TradingView Lightweight Charts | 各有所长 |
| **辅助图表库** | ECharts v5.4.3 | 无（纯K线） | 本项目更丰富 |
| **代码编辑器** | CodeMirror v5 | Monaco Editor (VS Code内核) | **QuantDinger领先** |
| **K线库包体积** | ~40KB(gzip) | ~12KB(gzip) | QuantDinger更轻量 |
| **综合前端体积** | ~340KB (klinecharts+ECharts) | ~12KB | QuantDinger更轻量 |
| **内置指标引擎** | ✅ klinecharts内置(MA/MACD/RSI/KDJ/BOLL/VOL) | ❌ 无内置 | **本项目领先** |
| **A股复权** | ✅ 内置支持 | ❌ 不支持 | **本项目领先** |
| **中文文档/社区** | ✅ 中文原生 | ⚠️ 英文为主 | 持平（取决于团队） |
| **设计理念** | 开箱即用（Convention） | 最小内核+自由组合(Minimal) | 不同哲学 |

### 3.2 功能覆盖度对比

| ## | 能力项 | 本项目 | QuantDinger | 领先方 |
|:--:|:-------|:------:|:-----------:|:------:|
| F-01 | OHLCV K线渲染 | ✅ | ✅ | 持平 |
| F-02 | 面积图/线图 | ✅ | ✅ | 持平 |
| F-03 | Heikin Ashi | ✅ | ❌ | **本项目** |
| F-04 | 分钟级周期 | ⚠️ 降级日线 | ✅ (CCXT) | **QuantDinger** |
| F-05 | 多周期日/周/月 | ✅ | ✅ | 持平 |
| F-06 | A股复权 | ✅ | ❌ | **本项目** |
| F-07 | MA均线叠加 | ✅ (内置) | ⚠️ (需自绘) | **本项目** |
| F-08 | BOLL布林带 | ✅ (内置+虚线) | ⚠️ (需自绘) | **本项目** |
| F-09 | MACD副图 | ✅ (内置) | ⚠️ (需自绘) | **本项目** |
| F-10 | RSI副图 | ✅ (内置) | ⚠️ (需自绘) | **本项目** |
| F-11 | KDJ副图 | ✅ (内置) | ⚠️ (需自绘) | **本项目** |
| F-12 | 成交量副图 | ✅ (内置) | ⚠️ (需自绘) | **本项目** |
| F-13 | 多面板自动布局 | ✅ (4面板原生) | ❌ (单图) | **本项目** |
| F-14 | 买卖信号标记 | ✅ 红绿圆点+文字 | ✅ 示例标记 | 持平 |
| F-15 | 策略代码编辑器 | CodeMirror 5 | **Monaco Editor** | **QuantDinger** |
| F-16 | Vibe Coding生成 | ❌ 无 | ✅ AI→Python策略 | **QuantDinger** |
| F-17 | 多K线分屏 | ✅ 1×1→4×2 | ❌ 单图 | **本项目** |
| F-18 | 十字光标同步 | ✅ 多图联动 | ❌ 无 | **本项目** |
| F-19 | 指标芯片切换 | ✅ Tag点击 | ❌ 无 | **本项目** |
| F-20 | 图表类型一键切换 | ✅ candle/area/line/ha | ❌ 无 | **本项目** |
| F-21 | 辅助图表(雷达/资金流等) | ✅ ECharts | ❌ 无 | **本项目** |
| F-22 | 面板信号聚合 | ✅ L2/L3/自定义三层 | ❌ 无 | **本项目** |
| F-23 | 共振评分 | ✅ ResonancePanel | ❌ 无 | **本项目** |
| F-24 | AI信号总线 | ✅ AiSignalBus | ✅ AI面板 | 持平 |
| F-25 | K线右键菜单 | ❌ 无 | ❌ 无 | 持平 |
| F-26 | 画图工具(趋势线/斐波那契) | ❌ 依赖klinecharts插件API | ❌ 无 | 持平 |
| F-27 | K线拖拽选区间回测 | ❌ 无 | ❌ 无 | 持平 |
| F-28 | 深色/亮色主题 | ✅ CSS变量双主题 | ✅ | 持平 |

### 3.3 数据管道对比

```
本项目:
  数据 → 后端TechnicalIndicatorEngine(向量化) → chart.py(json) → klinecharts(内置指标渲染)
  ↑  全链路指标在服务端计算，前端仅做渲染
  ↑  后端支撑：25个Blueprint + 14+数据表 + 500+因子

QuantDinger:
  数据 → /api/market(json) → Lightweight Charts(addCandlestickSeries)
  ↑  纯数据传递，指标计算需另外实现
  ↑  后端支撑：10个端点 + 6数据表
```

### 3.4 指标量对比

| 指标类型 | 本项目(后端) | 本项目(前端klinecharts) | QuantDinger |
|---------|:-----------:|:---------------------:|:-----------:|
| **基础MA** | MA5/10/20/60 | ✅ MA(5,10,20,60) | ❌ 需自实现 |
| **MACD** | DIF/DEA/HIST | ✅ DIF/DEA/柱状 | ❌ 需自实现 |
| **RSI** | RSI14 | ✅ RSI(含超买超卖线) | ❌ 需自实现 |
| **KDJ** | K/D/J | ✅ K/D/J三线 | ❌ 需自实现 |
| **BOLL** | 上/中/下轨 | ✅ 中轨±2σ+虚线 | ❌ 需自实现 |
| **VOL** | 量+MA5/MA10 | ✅ 量柱+均量线 | ❌ 需自实现 |
| **自定义指标** | 需扩展计算引擎 | ⚠️ 通过overlay数据 | ✅ 自由度高 |
| **信号/策略** | 9种+缠论/筹码/量价 | simpleAnnotation标记 | ✅ buy/sell列映射 |

**核心发现**：本项目在**指标即开即用**上显著领先，但QuantDinger在**策略代码→图表可视化**的闭环上更顺滑。

---

## 4. 差距分析与关键发现

### 4.1 P0级差距（严重，需优先解决）

#### GAP-01: Vibe Coding 策略→信号自动可视化

| 维度 | 本项目现状 | QuantDinger做法 | 差距描述 |
|------|-----------|----------------|---------|
| **生成** | ❌ 无自然语言→策略代码 | ✅ 用户说人话→AI生成Python | 需手动编码 |
| **运行** | 点击"运行"→后端计算→返回信号 | ✅ 编辑器与K线实时联动 | 流程割裂 |
| **可视化** | 信号需通过额外API `signals/{tsCode}` | ✅ `df["buy"]/df["sell"]` 直接映射 | 多一步网络请求 |

**影响**：从"想策略"到"看到信号"需要经过`写代码→切换编辑器→点击运行→等待后端→查看面板`5步。QuantDinger是`描述→自动→看到`3步。

#### GAP-02: 代码编辑器差距

| 维度 | 本项目(CodeMirror 5) | QuantDinger(Monaco Editor) |
|------|---------------------|--------------------------|
| **智能补全** | 基础语法高亮 | VS Code级补全+IntelliSense |
| **语法检查** | ❌ 无 | ✅ 实时语法错误检查 |
| **多光标** | ❌ 无 | ✅ 多光标编辑 |
| **主题** | 有限 | ✅ 丰富内置主题 |
| **Diff模式** | ❌ 无 | ✅ 版本对比 |
| **包体积** | ~35KB(gzip) | ~200KB(gzip，支持懒加载) |

#### GAP-03: 前端指标性能（分钟级数据降级）

| 维度 | 现状 | 差距 |
|------|------|------|
| **分钟线** | 降级到日线（`if period in ['1m','5m','15m','30m','60m']: period = 'D'`） | **分钟级K线完全不可用** |
| **原因** | Tushare分钟线数据获取不稳定，未接入实时数据源 | 缺乏稳定的分钟级数据通道 |

### 4.2 P1级差距（重要，1-2月内解决）

#### GAP-04: 策略代码→K线信号自动映射

**现状**：策略信号走独立API `signals/{tsCode}`，与K线数据是两个独立请求/响应周期。

**对比与差距**：
- 本项目：策略信号 → `SignalGenerator` → `signals` API → `createOverlay` 渲染
- QuantDinger：`df["buy"]` → Lightweight Charts Series直接渲染

**本质差距**：不是功能缺失，而是**数据流的简洁性和实时性**。

#### GAP-05: K线区域选择交互

**现状**：K线图无鼠标拖拽选区域交互。

**描述**：用户在K线上右键→"从此处回测"或拖拽选择时间段→"回测此区间"的交互在金融平台中是标配能力。

#### GAP-06: 画图工具（Trend Line / Fibonacci）

**现状**：klinecharts内置画图工具API，但本项目未启用。

**描述**：画图工具（趋势线、斐波那契回撤、矩形标注、文字标注）是专业K线图表的标配功能。klinecharts本身支持，本项目只是没有调用。

### 4.3 P2级差距（中期改进）

| 编号 | 差距 | 优先级 | 说明 |
|:----:|------|:------:|------|
| GAP-07 | 主题与指标联动持久化 | P2 | 切换的指标组合未保存，每次打开需重新选择 |
| GAP-08 | 多图筛选联动 | P2 | Dashboard多图之间没有股票联动关系（如一图选股→其他图自动切换） |
| GAP-09 | ECharts图表的指标叠加 | P2 | ECharts迷你K线不支持叠加MA等指标 |
| GAP-10 | K线图缩放历史状态保存 | P2 | 图表缩放状态不跨Session保存 |

### 4.4 本项目领先优势（需保持）

| 优势 | 说明 | 保持策略 |
|:-----|:------|---------|
| 内置完整指标集 | klinecharts原生支持6大常用指标，无需额外计算 | 持续维护 |
| Heikin Ashi | 自定义转换实现，专业交易者刚需 | 保持 |
| 多图联动系统 | 十字光标同步+多布局+独立切换 | 保持并扩展 |
| ECharts辅助图表群 | 迷你K线/资金流向/雷达/行业排行，同一暗色主题 | 统一CSS Token |
| 信号聚合面板 | L2/L3/自定义三层+综合操作建议 | 持续精化 |
| 后端指标计算引擎 | 所有指标Python向量化计算，精度可控 | 保持 |
| 共振评分+AI信号 | 独有功能，QuantDinger不具备 | 深化 |

---

## 5. 改进方案详述

### 5.1 P0-EPS: Vibe Coding 信号自动可视化（Epic-1）

#### 5.1.1 目标

实现：用户在CodeEditor中运行策略→策略信号**自动**映射到K线图标记，无需额外API调用。

#### 5.1.2 设计

```
现有流程:
CodeEditor.run() → 后端计算 → 返回 signals[]
  ↓ (手动触发)
$refs.klineChart.renderSignalMarkers()

目标流程:
CodeEditor.run() → 后端计算 → 返回 signals[]
  ↓ (事件驱动)
CodeEditor emit('strategy-result', {signals})
  ↓
indicator-ide → KLineChart.refresh()
  ↓ (自动)
KLineChart.renderSignalMarkers()
```

#### 5.1.3 实施步骤

**Phase 1 — 事件驱动打通（2天）**

| 步骤 | 文件 | 修改内容 | 工作量 |
|:----:|:----|:---------|:------:|
| 1.1 | `components/CodeEditor/index.vue` | 运行策略后自动emit `strategy-result` 事件，携带`{signals, tsCode}` | 0.5天 |
| 1.2 | `views/indicator-ide/index.vue` | 监听CodeEditor的`strategy-result`事件后自动调用`$refs.klineChart.refresh()` | 0.25天 |
| 1.3 | `components/KLineChart/index.vue` | `_onStrategyResult()`方法自动更新`this.signals`并调用`renderSignalMarkers()` | 0.5天 |
| 1.4 | `services/chartService.js` | 新增`fetchWithStrategy()`方法：一次请求获取K线+策略信号合并数据 | 0.5天 |
| 1.5 | 测试 | 验证多股票切换+策略运行→信号自动叠加的完整性 | 0.25天 |

**Phase 2 — 信号高亮与交互增强（2天）**

| 步骤 | 文件 | 修改内容 | 工作量 |
|:----:|:----|:---------|:------:|
| 2.1 | `components/KLineChart/index.vue` | `renderSignalMarkers()` 新增多色系支持：买入(红)/卖出(绿)/关注(橙)/中性(灰) | 0.5天 |
| 2.2 | `components/KLineChart/index.vue` | 信号标记点击→弹出详情tooltip（信号类型/置信度/证据链） | 0.5天 |
| 2.3 | `components/KLineChart/index.vue` | 信号标记分层显示开关：L2/L3/自定义可单独开关 | 0.5天 |
| 2.4 | `components/KLineChart/index.vue` | 信号密度过高时自动聚合（如1日内多个同向信号→显示最强那个） | 0.5天 |

**Phase 3 — 数据流优化（1天）**

| 步骤 | 文件 | 修改内容 | 工作量 |
|:----:|:----|:---------|:------:|
| 3.1 | `backend/app/routes/chart.py` | `get_chart_signals()` 改为可选参数`embed=true`：指定后在K线数据响应内联信号，减少1次HTTP请求 | 0.5天 |
| 3.2 | `services/chartService.js` | 支持`embedSignals=true`参数，一次请求带回K线+信号+指标+策略 | 0.25天 |
| 3.3 | `components/KLineChart/index.vue` | 支持数据预加载：信号数据先于K线渲染完成时暂存队列，K线就绪后自动渲染 | 0.25天 |

**合计工作量**：5天（Phase1: 2天 + Phase2: 2天 + Phase3: 1天）

---

### 5.2 P0-EPS: 代码编辑器升级（Epic-2）

#### 5.2.1 目标

将 CodeMirror 5 升级到 Monaco Editor，获得 VS Code 级的策略编辑体验。

#### 5.2.2 设计

```
┌─────────────────────────────────────┐
│ CodeEditor (重构wrapper)            │
│  ├─ 复用现有props/events接口         │
│  ├─ 底层从codemirror→@monaco-editor │
│  └─ 新增：模板选择/运行按钮/AI辅助   │
└─────────────────────────────────────┘
```

#### 5.2.3 实施步骤

**Phase 1 — 依赖替换与基础集成（2天）**

| 步骤 | 文件/操作 | 内容 | 工作量 |
|:----:|:---------|:-----|:------:|
| 1.1 | `package.json` | 移除`codemirror`，新增`@monaco-editor/loader`(或`monaco-editor`)依赖 | 0.1天 |
| 1.2 | 新建`components/CodeEditor/monacoWrapper.js` | Monaco Editor加载器封装（CDN懒加载模式，避免增大vendor chunk） | 0.5天 |
| 1.3 | `components/CodeEditor/index.vue` | 重写`<template>`：`codemirror`→`<div ref="monacoEl" />`，保留`currentTemplate`/`dark`等现有prop接口 | 0.5天 |
| 1.4 | `components/CodeEditor/index.vue` | 重写`mounted()`：`initMonaco()`方法替代`CodeMirror.fromTextArea()` | 0.5天 |
| 1.5 | 测试 | 验证：模板加载→代码编辑→语法高亮→策略运行→结果返回 | 0.4天 |

**Phase 2 — 高级功能（2天）**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 2.1 | `components/CodeEditor/index.vue` | 注册Python语言服务：`monaco.languages.registerCompletionItemProvider('python', ...)` 提供策略API的自动补全（`get_data()`, `buy()`, `sell()`, `df`等） | 0.5天 |
| 2.2 | `components/CodeEditor/index.vue` | 新增语法标记：策略模板关键行用装饰器高亮（如买入条件标绿底、卖出条件标红底） | 0.5天 |
| 2.3 | `components/CodeEditor/index.vue` | 新增diff模式：策略修改前后对比，保存策略版本历史 | 0.5天 |
| 2.4 | `components/CodeEditor/index.vue` | 暗色/亮色主题与Monaco theme同步（`vs-dark` ↔ `vs`） | 0.3天 |
| 2.5 | 测试 | 验证多浏览器兼容性 + 中文输入正确性 | 0.2天 |

**Phase 3 — AI辅助功能预留（1天）**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 3.1 | `components/CodeEditor/index.vue` | 新增"AI帮我写"按钮→弹出prompt输入框→调用`/api/v3/ai/strategy-generate`→代码注入编辑器 | 0.3天 |
| 3.2 | `components/CodeEditor/index.vue` | 新增代码注释自动生成：选中代码→右键"添加注释"→AI生成注释插入 | 0.3天 |
| 3.3 | `components/CodeEditor/index.vue` | 新增策略代码版本快照：每次运行前自动保存快照到localStorage，最多20个版本 | 0.2天 |
| 3.4 | 测试 | 验证AI生成→注入→运行→结果可视化的完整链路 | 0.2天 |

**合计工作量**：5天（Phase1: 2天 + Phase2: 2天 + Phase3: 1天）

---

### 5.3 P0-EPS: 分钟级K线数据通道（Epic-3）

#### 5.3.1 目标

实现真实的分钟级K线支持，解决当前全部降级到日线的痛点。

#### 5.3.2 现状分析

当前 `chart.py` 第119-120行：
```python
if period in ['1m', '5m', '15m', '30m', '60m']:
    period = 'D'  # 直接降级到日线
```

数据源层面：`DataManager._get_minute_data()` 调用 Tushare `get_minute_data()`，但该接口需要较高积分权限且数据不稳定。

#### 5.3.3 实施步骤

**Phase 1 — AKShare分钟线接入（2天）**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1.1 | `backend/app/data/akshare_provider.py` | 新增`get_minute_data(ts_code, freq, start_date, end_date)`方法，使用akshare的`stock_zh_a_hist_min_em()`接口 | 0.5天 |
| 1.2 | `backend/app/data/data_source_manager.py` | 为分钟数据增源路由：分钟级请求优先走AKShare（因其免费且稳定），日线以上优先Tushare | 0.25天 |
| 1.3 | `backend/app/data/minute_data_manager.py` | 分钟级数据缓存：按股票+日期为key缓存到DuckDB，减少重复请求 | 0.5天 |
| 1.4 | `backend/app/data/__init__.py` | DataManager新增`get_minute_data_v2()`方法，集成AKShare分钟线 | 0.25天 |
| 1.5 | 测试 | 验证5/15/30/60分钟K线在至少3只股票上可用 | 0.5天 |

**Phase 2 — K线重采样服务（1天）**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 2.1 | `backend/app/data/kline_resampler.py` | 现有重采样功能验证并修复：确保1min→5/15/30/60min聚合正确（开盘取首、收盘取尾、最高取max、最低取min） | 0.25天 |
| 2.2 | `backend/app/routes/chart.py` | 移除`if period in ['1m','5m','15m','30m','60m']: period = 'D'`降级代码，改为调用`DataManager.get_minute_data_v2()` | 0.25天 |
| 2.3 | `backend/app/routes/chart.py` | 分钟级API限流：分钟数据请求频率限制（同一股票5秒内不重复请求） | 0.25天 |
| 2.4 | 测试 | 验证分钟K线各周期前后端完整链路 | 0.25天 |

**Phase 3 — 前端适配（1天）**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 3.1 | `views/indicator-ide/index.vue` | 周期选择器增加分钟选项：日线/周线/月线后追加分割线+1分钟/5分钟/15分钟/30分钟/60分钟 | 0.25天 |
| 3.2 | `components/KLineChart/index.vue` | 分钟级数据适配：klinecharts支持秒级时间戳（当前为日线Date级别），需确保timestamp正确传递 | 0.25天 |
| 3.3 | `components/KLineChart/index.vue` | 分钟级数据量限制：取最近500根K线（避免数据过多拖慢渲染） | 0.1天 |
| 3.4 | 测试 | 验证分钟K线在不同股票/不同周期下的正确性和性能 | 0.4天 |

**合计工作量**：4天（Phase1: 2天 + Phase2: 1天 + Phase3: 1天）

---

### 5.4 P1-EPS: K线交互增强（Epic-4）

#### 5.4.1 画图工具启用

**现状**：klinecharts 提供了画图工具API，本项目未调用。

**实施步骤（2天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `components/KLineChart/index.vue` | 新增`drawingTools` prop（Boolean，默认false），启用画图模式时加入klinecharts的`setDrawingTool()` API调用 | 0.5天 |
| 2 | `components/KLineChart/index.vue` | 新增画图工具浮层按钮组：趋势线/射线/平行线/斐波那契/矩形/文字/箭头 | 0.5天 |
| 3 | `backend/app/routes/__init__.py` + models | 画图数据持久化：复用现有`Drawing`模型（`backend/app/models/__init__.py` 已定义），新增保存/加载API | 0.5天 |
| 4 | `services/chartService.js` | 新增`saveDrawings()`/`loadDrawings()`方法 | 0.25天 |
| 5 | 测试 | 验证画图→保存→刷新→恢复的完整链路 | 0.25天 |

#### 5.4.2 K线拖拽选区间回测

**现状**：K线图无鼠标区域选择交互。

**实施步骤（2天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `components/KLineChart/index.vue` | 新增区域选择模式：`ctrl+click拖拽`选择时间段，高亮选中区域 | 0.5天 |
| 2 | `components/KLineChart/index.vue` | 选择后弹出操作菜单："回测此区间/添加自选标记/查看累计涨跌幅" | 0.5天 |
| 3 | `components/KLineChart/index.vue` | "回测此区间"→携带`{tsCode, startDate, endDate}`参数跳转到回测页面 | 0.5天 |
| 4 | `views/backtest/index.vue` | 接收K线传递的区间参数，自动填入回测时间范围 | 0.3天 |
| 5 | 测试 | 验证区间选择→回测参数传递→回测结果展示的完整链路 | 0.2天 |

**合计工作量**：4天（画图工具2天 + 区间选择回测2天）

---

### 5.5 P1-EPS: 数据流优化（Epic-5）

#### 5.5.1 统一图表数据API

**现状**：K线、策略信号使用两个独立API，导致前端需要两次HTTP请求。

**实施步骤（1天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `backend/app/routes/chart.py` | `get_kline_chart_data()` 增加`with_signals=true`参数：同时返回信号数据 | 0.25天 |
| 2 | `backend/app/routes/chart.py` | `get_kline_chart_data()` 增加`with_strategy=true`参数：同时返回策略计算结果 | 0.25天 |
| 3 | `services/chartService.js` | `fetchKlineData()` 新增`options`参数，透传`with_signals`和`with_strategy` | 0.25天 |
| 4 | `components/KLineChart/index.vue` | 根据响应数据中的`signals`字段直接调用`renderSignalMarkers()`，无需二次请求 | 0.25天 |

#### 5.5.2 指标状态持久化

**现状**：每次打开indicator-ide页，指标选择重置为默认。

**实施步骤（0.5天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `views/indicator-ide/index.vue` | `mounted()`时从`localStorage.getItem('ide_indicator_config')`恢复`activeOverlays`和`activeSubcharts` | 0.1天 |
| 2 | `views/indicator-ide/index.vue` | 任何指标切换操作时自动保存到localStorage | 0.1天 |
| 3 | `views/indicator-ide/index.vue` | 新增"保存为默认布局"按钮（区分"自动保存"与"手动保存默认"） | 0.2天 |
| 4 | 测试 | 验证：切换指标→刷新页面→指标状态恢复 | 0.1天 |

**合计工作量**：1.5天

---

### 5.6 P2-EPS: Dashboard图表增强（Epic-6）

#### 5.6.1 ECharts迷你K线叠加指标

**现状**：Dashboard四大指数卡片内嵌ECharts candlestick，但不支持指标叠加。

**实施步骤（2天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `views/dashboard/index.vue` | 每个迷你K线的ECharts option增加MA计算逻辑（简化为MA5，数据驱动计算而非后端请求） | 0.5天 |
| 2 | `views/dashboard/index.vue` | 迷你K线支持hover显示开盘/最高/最低/收盘/涨幅tooltip | 0.5天 |
| 3 | `views/dashboard/index.vue` | 迷你K线点击→切换到indicator-ide页面并打开该股票 | 0.3天 |
| 4 | `views/dashboard/index.vue` | 迷你K线响应式：卡片缩小到一定宽度时隐藏K线仅显示数值 | 0.3天 |
| 5 | 测试 | 验证四大指数迷你K线在响应式各断点下的正确行为 | 0.4天 |

#### 5.6.2 多图筛选联动

**现状**：Dashboard多图模式下，各图表独立展示不同股票，无联动关系。

**实施步骤（1天）：**

| 步骤 | 文件 | 内容 | 工作量 |
|:----:|:----|:-----|:------:|
| 1 | `views/dashboard/index.vue` | 新增"联动筛选"模式：用户在一个K线上选中的股票自动应用到其他图表 | 0.3天 |
| 2 | `views/dashboard/index.vue` | 新增"同股多周期"模式：所有chart-cell展示同一股票的不同周期（日/周/月/60分钟） | 0.3天 |
| 3 | `views/dashboard/index.vue` | 新增图表面板锁：pin图标锁定某个cell不随联动变化 | 0.2天 |
| 4 | 测试 | 验证联动/多周期/锁定三种模式的行为正确性 | 0.2天 |

**合计工作量**：3天

---

## 6. 分阶段实施计划

### 6.1 实施路线总图

```
Phase 0 (当前) ──── Phase 1 (2周) ───────── Phase 2 (4周) ────────── Phase 3 (8周) ──────── 长期维护
                │                    │                       │                       │
基准线           Epic-1: Vibe Coding  │  Epic-3: 分钟级数据    │  Epic-5: 数据流优化     │  持续迭代
C-01~C-28全部已  │  信号自动可视化     │  AKShare分钟线接入     │  统一图表API            │
实现             │  事件驱动打通        │  K线重采样服务         │  指标持久化              │
                │  信号高亮交互        │  前端适配              │                        │
                │                 │                       │                       │
                │ Epic-2: 编辑器升级   │  Epic-4: K线交互增强   │  Epic-6: Dashboard增强  │
                │  Monaco集成          │  画图工具启用           │  迷你K线指标叠加         │
                │  Python智能补全       │  区间选择回测           │  多图筛选联动            │
```

### 6.2 时间线

| 周次 | 重点工作 | 产出 |
|:----:|:---------|:-----|
| **W1** | Epic-1 Phase1 事件驱动打通 + Epic-2 Phase1 Monaco集成 | CodeEditor自动联动K线信号、Monaco基础可用 |
| **W2** | Epic-1 Phase2-3 信号增强+数据优化 + Epic-2 Phase2 高级功能 | 信号标记分层+tooltip、Monaco智能补全 |
| **W3** | Epic-3 Phase1-2 AKShare分钟线+重采样 + Epic-2 Phase3 AI辅助 | 分钟K线可用、AI生成代码注入编辑器 |
| **W4** | Epic-3 Phase3 前端适配 + Epic-4 Phase1 画图工具 | 分钟周期选择器、趋势线画图可用 |
| **W5** | Epic-4 Phase2 区间选择回测 + Epic-5 Phase1 统一API | 拖拽选区间→回测参数传递、K线+信号合一API |
| **W6** | Epic-5 Phase2 指标持久化 + Epic-6 Phase1 迷你K线增强 | 指标布局跨Session保存、Dashboard迷你K线可交互 |
| **W7** | Epic-6 Phase2 多图联动 | 联动筛选/同股多周期/面板锁定 |
| **W8** | 集成测试+性能优化+ Bug修复 | 全链路回归测试通过 |

### 6.3 里程碑定义

| 里程碑 | 时间 | 验收标准 |
|:-------|:-----|:---------|
| **M1 - 自动化信号流** | W2末 | CodeEditor运行策略→信号自动叠加到K线，无需手动刷新 |
| **M2 - 专业编辑器** | W2末 | Monaco Editor正常运行，Python模板+智能补全可用 |
| **M3 - 分钟级数据** | W4末 | 5/15/30/60分钟K线在前端周期选择器中可选且数据正确 |
| **M4 - 交互增强** | W5末 | 画图工具可用且持久化，K线拖拽选区间→回测可用 |
| **M5 - 数据流优化** | W6末 | 统一图表API（一次请求带回全部数据），指标持久化跨Session |
| **M6 - Dashboard增强** | W7末 | 迷你K线可点可hover，多图联动筛选模式可用 |
| **M7 - 全量回归** | W8末 | 所有28项现有能力无退化，6个Epic全部验收通过 |

### 6.4 风险与应对

| 风险 | 等级 | 应对策略 |
|:-----|:----|:---------|
| Monaco Editor包体积过大(~200KB) | 中 | 使用CDN懒加载（`@monaco-editor/loader`），仅在打开编辑器时加载 |
| AKShare分钟线接口限频 | 中 | 前端请求间隔1秒+缓存层避免重复请求+备用数据源通道 |
| klinecharts画图API与现有版本兼容性 | 低 | 版本锁定^9.8.0，画图功能作为可选插件不破坏核心渲染 |
| 分钟级与日线数据源切换用户感知 | 低 | 数据源状态指示器DataStatusBar显示当前数据源，自动降级时提示 |
| 多图联动性能（4×2=8个klinecharts实例） | 中 | 每个实例独立ResizeObserver+数据懒加载（不在可视区的图表暂停更新） |

---

## 7. 附录

### 7.1 对比双方引用信息

| 项目 | 链接 |
|------|------|
| QuantDinger GitHub | https://github.com/brokermr810/QuantDinger |
| QuantDinger 描述文章 | https://dev.to/yuhang_chen_969a8b10adae9/quantdinger-an-open-source-local-quantitative-trading-platform-25fa |
| klinecharts | https://www.npmjs.com/package/klinecharts |
| Lightweight Charts | https://www.npmjs.com/package/lightweight-charts |
| Monaco Editor | https://microsoft.github.io/monaco-editor/ |

### 7.2 当前系统K线能力状态清单（已实现28项）

见本方案 §2.3 — C-01 至 C-28 全部已实现。

### 7.3 改进后K线能力状态清单（改进后总计39项）

| 编号 | 能力 | 对应Epic | 状态 |
|:----:|:------|:--------:|:----:|
| C-01~C-28 | 现有28项能力 | — | ✅ 已实现 |
| C-29 | Vibe Coding策略信号自动叠加 | Epic-1 P1 | 🚧 |
| C-30 | 信号标记分层开关(L2/L3/自定义) | Epic-1 P2 | 🚧 |
| C-31 | 信号标记点击tooltip展示详情 | Epic-1 P2 | 🚧 |
| C-32 | Monaco Editor基础集成 | Epic-2 P1 | 🚧 |
| C-33 | Python策略API智能补全 | Epic-2 P2 | 🚧 |
| C-34 | 编辑器AI辅助(自然语言→代码) | Epic-2 P3 | 🚧 |
| C-35 | 真实分钟K线(5/15/30/60) | Epic-3 P1-3 | 🚧 |
| C-36 | 画图工具(趋势线/斐波那契/矩形/文字) | Epic-4 P1 | 🚧 |
| C-37 | K线拖拽选区间→一键回测 | Epic-4 P2 | 🚧 |
| C-38 | 统一图表API(一次请求全部数据) | Epic-5 P1 | 🚧 |
| C-39 | 指标布局跨Session持久化 | Epic-5 P2 | 🚧 |
| C-40 | 迷你K线叠加MA指标 | Epic-6 P1 | 🚧 |
| C-41 | 多图联动筛选 | Epic-6 P2 | 🚧 |

### 7.4 现有方案引用

| 编号 | 标题 | 关联章节 |
|------|------|---------|
| 150 | 观潮对标-前端UI设计优化借鉴方案 | Dashboard多图分屏/十字光标同步 |
| 152 | 观潮对标-策略架构深度分析与升级方案 | 共振评分/信号总线 |
| 165 | 前端UI架构重构与全功能设计实施总方案 | 组件树/页面规划 |
| 166 | 前端UI原型逐页调整记录 | Dashboard/indicator-ide原型 |
| 172 | QuantDinger对标分析与能力差距评估暨改进建议方案 | 总体对标框架（本方案之上层文档） |
| 171 | 功能视图API映射对照表 | API端点映射 |

### 7.5 术语说明

| 术语 | 说明 |
|:-----|:------|
| klinecharts | 国产开源K线图表库（本项目使用） |
| Lightweight Charts | TradingView出品的轻量级金融图表库（QuantDinger使用） |
| Monaco Editor | Microsoft出品的VS Code同内核代码编辑器 |
| CodeMirror | 轻量级代码编辑器（本项目当前使用v5） |
| Heikin Ashi | 平均K线，一种平滑K线的技术分析方法 |
| Vibe Coding | 用自然语言描述→AI自动生成代码（QuantDinger独创概念） |
| Epic | 改进方案的大粒度工作单元（Epic-1至Epic-6） |

---

> 文档结束
