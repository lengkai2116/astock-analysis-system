---
title: 设计规范体系与Token系统
type: 设计规范
date: 2026-06-04
version: 1.0
tags: [设计规范, Token系统, 8pt网格, shadcn, 组件体系, 主题系统]
supersedes: 147-前端UI优化升级详细方案 (规范部分扩展)
---

# 设计规范体系与Token系统

> 本文档是对 `147-前端UI优化升级详细方案.md` 在**视觉规范层面**的审核、修订与扩展。147 的架构规划、组件逻辑、实施排期等非规范部分保持不变，本文档仅增补/替换其规范相关章节。

---

## 1. 147号文档审核结论

### 1.1 审核范围

对照新标准审核 147 文档中的以下方面：

- 布局规则（8pt 网格系统）
- 视觉统一规范（shadcn/ui 极简中性风格）
- 排版层级规范
- 页面结构要求
- 交互与细节要求

### 1.2 一致性判定

| 147 原有内容 | 新规范要求 | 判定 | 处理 |
|-------------|-----------|------|------|
| Phase 1-A: 设计 Token 提取 | 完整 Token 系统 + 8pt 网格 | ✅ 方向一致，需细化 | 本文档补充完整 Token 表 |
| 颜色: `#ef4444` 上涨 / `#22c55e` 下跌 | "仅1组品牌主色+中性灰阶" | ⚠️ 冲突 | 见 1.3 裁决 |
| 颜色: `#3b82f6` 主操作色 | 1组品牌主色 | ✅ 保留为唯一品牌色 |
| 颜色: `#f59e0b` 关注色 / `#fb7185` 风险色 | 禁止多色花哨 | ⚠️ 冲突 | 见 1.3 裁决 |
| 间距规范未明确 | 8pt 网格固定倍数 | ❌ 缺失 | 本文档补充 |
| 圆角: 各页面自定义 | 统一圆角 10px | ❌ 不一致 | 本文档统一 |
| 阴影: 各页面自定义 | 仅2层轻阴影 | ❌ 不一致 | 本文档统一 |
| 字号: 混合使用 | 仅 12/14/16/20/24/32px | ❌ 不规范 | 本文档统一定义 |
| 行高: 未定义 | 标题1.4 / 正文1.6 | ❌ 缺失 | 本文档补充 |
| 深色主题: 硬编码 | 浅色+深色双主题 | ⚠️ 半匹配 | 本文档规范双主题 |
| 页面结构: 未规定 | 标题+说明+操作按钮 | ❌ 缺失 | 本文档补充 |
| 空状态: 自定义空状态 | 渐变占位块+引导文案 | ❌ 不一致 | 本文档统一 |
| 交互: 有 hover 动画 | 仅 hover/focus 轻动画 | ✅ 方向一致 | 本文档规范参数 |

### 1.3 冲突裁决

**总原则**：项目功能最优、运行流程优先。当新规范与 A 股分析系统的业务语义冲突时，业务语义优先。

| 冲突项 | 裁决 | 理由 |
|--------|------|------|
| 涨跌色 vs 单色规范 | **业务语义优先** | 红涨绿跌是 A 股市场的核心语义，不可替代。上涨色 `#DC2626`、下跌色 `#16A34A` 作为**功能色**保留，不计入"装饰色" |
| 信号标签色 vs 单色规范 | **业务语义优先** | 看多/风险/观察/中性/失效五色是策略输出语义载体，保留但使用低饱和度调色 |
| 1200px 最大宽度 vs 金融终端信息密度 | **折中** | 页面容器 1200px 居中，但表格和 K 线图等**数据密集型组件**允许横向溢出滚动 |
| 单Card仅1+2信息 vs 策略信号密度 | **业务语义优先** | 策略信号卡片密度放宽至 1 核心 + 3 辅助，但结构仍保持克制 |

### 1.4 裁决后的配色结构

```
配色分为三层：
  Layer 1: 结构色（遵循单色+中性灰阶规范）
    → 背景/卡片/边框/文字/分割线
    → 仅使用品牌色 + 中性灰阶
  
  Layer 2: 语义功能色（业务语义优先）
    → 涨跌色: 红 `#DC2626` / 绿 `#16A34A`
    → 信号色: 看多/风险/关注/中性/失效
  
  Layer 3: 图表色（KLineCharts 自有配色保持不变）
    → K线颜色、技术指标颜色
    → 跟随 KLineChart 的样式配置
```

---

## 2. 完整设计Token参数表

### 2.1 空间 Token（8pt 网格系统）

所有内边距、外边距、间距、尺寸仅使用以下固定倍数：

| Token 名 | 值 | 用途 |
|----------|-----|------|
| `space-4` | 4px | 极小间距，图标与文字间隙 |
| `space-8` | 8px | 内嵌元素间距，标签内部间距 |
| `space-12` | 12px | 紧凑布局间距，表格单元格内边距 |
| `space-16` | 16px | 卡片间距，元素组间距 |
| `space-24` | 24px | 卡片内边距，页面左右边距，区块间距 |
| `space-32` | 32px | 区块上下间距，大间隔 |
| `space-40` | 40px | 页面分区间距 |
| `space-48` | 48px | 超大间距，页面顶部/底部 |

```css
--space-4: 4px;
--space-8: 8px;
--space-12: 12px;
--space-16: 16px;
--space-24: 24px;
--space-32: 32px;
--space-40: 40px;
--space-48: 48px;
```

### 2.2 颜色 Token

#### 2.2.1 品牌色（唯一品牌主色）

| Token | 值 | 用途 |
|-------|-----|------|
| `--color-brand-50` | `#EFF6FF` | 极浅品牌色（浅色主题选中态背景） |
| `--color-brand-100` | `#DBEAFE` | 品牌色浅色（hover 背景） |
| `--color-brand-200` | `#BFDBFE` | 品牌色中浅 |
| `--color-brand-500` | `#3B82F6` | **品牌主色**，按钮、链接、激活态 |
| `--color-brand-600` | `#2563EB` | 品牌色深（按钮 hover） |
| `--color-brand-700` | `#1D4ED8` | 品牌色更深（active） |

#### 2.2.2 中性灰阶（浅色主题）

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-page` | `#FAFAFA` | 页面背景 |
| `--bg-surface` | `#FFFFFF` | 卡片/面板背景 |
| `--bg-subtle` | `#F5F5F5` | 次级背景（hover 状态、输入框） |
| `--bg-muted` | `#E5E5E5` | 禁态背景 |
| `--border-default` | `#E5E5E5` | 默认边框 |
| `--border-strong` | `#D4D4D4` | 强调边框（hover 态） |
| `--text-primary` | `#171717` | 主文字（大标题） |
| `--text-secondary` | `#525252` | 二级文字（正文） |
| `--text-muted` | `#A3A3A3` | 辅助文字（说明、占位符） |
| `--text-disabled` | `#D4D4D4` | 禁用文字 |

#### 2.2.3 中性灰阶（深色主题）

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-page` | `#0A0A0A` | 页面背景 |
| `--bg-surface` | `#1A1A1A` | 卡片/面板背景 |
| `--bg-subtle` | `#262626` | 次级背景 |
| `--bg-muted` | `#333333` | 禁态背景 |
| `--border-default` | `#333333` | 默认边框 |
| `--border-strong` | `#525252` | 强调边框 |
| `--text-primary` | `#FAFAFA` | 主文字 |
| `--text-secondary` | `#A3A3A3` | 二级文字 |
| `--text-muted` | `#666666` | 辅助文字 |
| `--text-disabled` | `#404040` | 禁用文字 |

#### 2.2.4 语义功能色（A 股标准）

| Token | 值 | 用途 |
|-------|-----|------|
| `--color-up` | `#DC2626` | 上涨、买入信号 |
| `--color-up-bg` | `#FEF2F2` | 上涨背景（浅色表盘） |
| `--color-down` | `#16A34A` | 下跌、卖出信号 |
| `--color-down-bg` | `#F0FDF4` | 下跌背景 |

深色主题：

| Token | 值 |
|-------|-----|
| `--color-up` | `#EF4444` |
| `--color-up-bg` | `#2A1515` |
| `--color-down` | `#22C55E` |
| `--color-down-bg` | `#132B1A` |

#### 2.2.5 信号语义色（低饱和度）

| Token | 值（浅色） | 值（深色） | 语义 |
|-------|-----------|-----------|------|
| `--signal-bullish` | `#DC2626` | `#EF4444` | 看多 |
| `--signal-bearish` | `#16A34A` | `#22C55E` | 风险 |
| `--signal-watch` | `#D97706` | `#F59E0B` | 关注 |
| `--signal-neutral` | `#737373` | `#A3A3A3` | 中性 |
| `--signal-invalid` | `#991B1B` | `#7F1D1D` | 失效 |

### 2.3 圆角 Token

| Token | 值 | 用途 |
|-------|-----|------|
| `--radius-sm` | 6px | 标签、徽标、小元素 |
| `--radius-md` | **10px** | 卡片、弹窗、面板（统一标准） |
| `--radius-lg` | 12px | 大弹窗、下拉菜单 |
| `--radius-full` | 9999px | 按钮、输入框（圆形） |

### 2.4 阴影 Token

仅保留两层轻阴影，禁止厚重大投影：

| Token | 值 | 用途 |
|-------|-----|------|
| `--shadow-default` | `0 1px 2px 0 rgb(0 0 0 / 0.05)` | 卡片常态阴影，极轻微 |
| `--shadow-hover` | `0 4px 6px -1px rgb(0 0 0 / 0.08)` | 卡片 hover、下拉菜单 |
| `--shadow-none` | `0 0 #0000` | 无阴影 |

深色主题阴影透明度上浮：

| Token | 值 |
|-------|-----|
| `--shadow-default` | `0 1px 2px 0 rgb(0 0 0 / 0.3)` |
| `--shadow-hover` | `0 4px 6px -1px rgb(0 0 0 / 0.4)` |

### 2.5 排版 Token

#### 2.5.1 字号行高体系

| Token | 字号 | 行高 | 字重 | 用途 |
|-------|------|------|------|------|
| `--text-xs` | 12px | 1.5 | 400 | 辅助说明、标签文字、表格副信息 |
| `--text-sm` | 14px | 1.5 | 400 | 二级正文、输入框文字 |
| `--text-base` | 16px | **1.6** | 400 | **正文**、卡片内容、表格正文 |
| `--text-lg` | 20px | 1.5 | 500 | 区块小标题、卡片标题 |
| `--text-xl` | 24px | **1.4** | 600 | **页面大标题**、模块标题 |
| `--text-2xl` | 32px | 1.3 | 700 | 仪表盘数值、极少数强调 |

**字重规则**：
- 正文：400 (Regular)
- 小标题/按钮：500 (Medium)
- 大标题/强调数值：600 (SemiBold)
- 禁用 700+ 粗体在非数值场景

#### 2.5.2 字体系列

```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'PingFang SC',
              'Microsoft YaHei', 'Noto Sans SC', sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

- 界面文字：`--font-sans`
- 代码/数字/指标值：`--font-mono`

### 2.6 尺寸 Token

| Token | 值 | 用途 |
|-------|-----|------|
| `--btn-height` | 40px | 按钮标准高度 |
| `--input-height` | 40px | 输入框标准高度 |
| `--icon-sm` | 16px | 小型图标（表格内操作图标） |
| `--icon-md` | 20px | 标准图标（按钮图标、导航图标） |
| `--page-max-width` | 1200px | 页面内容最大宽度 |
| `--page-padding-x` | 24px | 页面左右预留边距 |
| `--card-padding` | 24px | 卡片内边距 |
| `--card-gap` | 16px | 卡片间距 |
| `--border-width` | 1px | 标准边框宽度 |

---

## 3. 组件拆分清单与规范

### 3.1 组件层级

```
LAYER 0: 基础 Token
├── tokens.css (所有 CSS 变量定义)
├── tailwind.config.js (Tailwind 扩展)
└── globals.css (全局重置 + body 样式)

LAYER 1: 原子组件 (Atoms)
├── Button         — 按钮 (primary/secondary/ghost/danger)
├── Input          — 输入框 (含 search/select 变体)
├── Badge          — 徽标 (涨跌/信号状态)
├── Tag            — 标签 (信号语义 5 色)
├── Icon           — 图标容器 (统一 16px/20px)
├── Spinner        — 加载指示器
├── Divider        — 分割线

LAYER 2: 分子组件 (Molecules)
├── Card           — 卡片容器 (24px padding, 10px radius, 1px border)
│   ├── Card.Header (标题+操作区)
│   ├── Card.Body (内容区)
│   └── Card.Footer (底部区域)
├── StatsCard      — 统计指标卡 (1主值+2辅值+趋势)
├── SignalTag      — 信号标签 (5色语义)
├── SearchInput    — 搜索输入框 (含防抖)
├── Select         — 选择器
├── Tabs           — 选项卡
├── Table          — 表格 (含分页、排序)
├── EmptyState     — 空状态 (渐变占位块+引导文案)
├── Tooltip        — 工具提示
├── Modal          — 弹窗

LAYER 3: 组织组件 (Organisms)
├── PageHeader     — 页面头部 (标题+说明+操作按钮)
├── BlockSection   — 功能区块 (大标题+说明+操作)
├── StatsRow       — 统计指标行 (4个StatsCard)
├── SignalPanel    — 策略建议面板 (信息密度1+3)
├── DataTable      — ProTable (查询栏+工具栏+表格+分页)
├── ReportSidebar  — 报告目录侧栏
├── ChartContainer — 图表容器 (KLine/ECharts 统一外壳)

LAYER 4: 模板/页面 (Templates)
├── DashboardLayout
├── AnalysisWorkbench
├── ScreenerPage
├── BacktestPage
├── AIReportPage
└── WatchlistPage
```

### 3.2 组件规范

#### 3.2.1 Card

```html
<!-- 结构 -->
<div class="card">
  <!-- 可选 header -->
  <div class="card-header space-between">
    <h3 class="card-title text-lg font-medium">标题</h3>
    <div class="card-actions"><!-- 操作按钮组 --></div>
  </div>
  <!-- 内容主体 -->
  <div class="card-body">
    <!-- 仅保留 1 核心主信息 + 2 辅助信息 -->
  </div>
</div>

<!-- CSS -->
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);  /* 10px */
  padding: var(--card-padding);     /* 24px */
  box-shadow: var(--shadow-default);
  transition: box-shadow 0.2s, border-color 0.2s;
}
.card:hover {
  box-shadow: var(--shadow-hover);
  border-color: var(--border-strong);
}
```

#### 3.2.2 StatsCard

```html
<StatsCard
  label="自选股总数"
  value="128"
  trend="up"        <!-- up | down | neutral -->
  subtitle="上涨 72 只"
  icon="stock"      <!-- 可选图标类型 -->
/>
<!-- 渲染结果:
┌──────────────────────────┐
│ 📈  自选股总数             │
│     128         ▲         │
│     上涨 72 只             │
└──────────────────────────┘
-->
```

1 核心主信息（数值 128）+ 2 辅助信息（标题"自选股总数"、副标题"上涨 72 只"）。

#### 3.2.3 EmptyState

```html
<EmptyState
  title="暂无自选股"
  description="添加关注的股票到自选列表，开启实时监控"
  action="添加股票"
  @action="handleAdd"
/>
<!-- 渲染: 渐变浅色占位块 + 居中图标 + 标题 + 说明 + 按钮 -->
```

占位块使用 `linear-gradient(135deg, var(--bg-subtle), var(--bg-muted))`。

### 3.3 页面结构树

```
┌─ PageContainer (max-width: 1200px, padding: 0 24px)
│
├── PageHeader
│   ├── H1 (--text-xl, font-semibold)
│   ├── Description (--text-sm, --text-muted)
│   └── Primary Action Button
│
├── BlockSection (每个功能区块)
│   ├── Block Title (--text-lg, font-medium)
│   ├── Block Description (--text-sm, --text-secondary)
│   └── Block Action (Button / 链接)
│
│   └── Content Grid (卡片网格 / 表格 / 图表)
│       ├── Card 1
│       ├── Card 2
│       ├── Card 3
│       └── Card 4
│
├── BlockSection (第二个区块)
│   └── ...
│
└── EmptyState (当数据为空时)
```

---

## 4. 交互与动效规范

| 场景 | 动效 | 参数 |
|------|------|------|
| 卡片 hover | 阴影上浮 | `shadow-default` → `shadow-hover`，0.2s ease |
| 按钮 hover | 背景微加深 | opacity/color transition，0.15s ease |
| 按钮 active | 极轻微下压 | transform scale(0.98)，0.1s |
| 输入框 focus | 边框变强 | `--border-default` → `--border-strong`，0.15s |
| 链接 hover | 颜色过渡 | 0.15s ease |
| 页面切换 | 内容淡入 | opacity 0→1, 0.2s ease |
| 下拉展开 | 轻微展开 | max-height + opacity，0.2s ease |

禁止使用：弹跳动画、旋转动画、闪烁效果、大幅位移动画。

---

## 5. 审核结论：对147号文档的修订

| 147 章节 | 操作 | 说明 |
|----------|------|------|
| 1.3 目标原则 | 保留 | 不冲突 |
| 1.3 颜色 (`#141414` 等) | 替换为本文档 Token | 统一到 8pt + shadcn 体系 |
| Phase 1-A Token 提取 | **扩写**为本文档完整 Token 表 | 直接替换 147 对应段落 |
| Phase 1-B 文案统一 | 保留 | 不冲突 |
| Phase 1-C SignalTag | **扩写**颜色值为本文档低饱和度信号色 | 5 色语义保留，色值替换 |
| Phase 2-C StatsCard | **扩写**结构限制为 1+2 信息 | 追加密度控制规则 |
| Phase 3-C 策略建议面板 | **扩写**为 1+3 信息密度 | 业务语义优先 |
| 所有卡片组件 | **追加** 8pt 网格规范 | padding 24px, gap 16px, radius 10px |
| 所有阴影 | **替换**为 2 层轻阴影 | 删除 147 原有的大阴影引用 |
| 所有字号 | **替换**为 12/14/16/20/24/32px | 删除非标字号 |
| 排版行高 | **补充** 1.4/1.6 | 147 未定义 |
| 浅色/深色双主题 | **补充**完整 Token | 147 仅深色 |
| 页面结构 | **补充** BlockSection 结构模板 | 147 未定义 |
| 空状态 | **补充** 渐变占位块规范 | 147 未定义 |
| 交互动效 | **标准化**参数 | 147 仅原则无参数 |
| 组件库 | **补充** 4 层分层体系 | 147 有清单无分层 |

---

## 6. 附录

### 6.1 与 shadcn/ui 保持一致的部分

- 中性灰阶配色体系 (zinc/neutral 风格)
- 轻阴影分层（default / hover 两层）
- 圆角统一（10px 作为卡片标准）
- 排版字重（正文 400、按钮 500、标题 600）
- 双主题 CSS 变量切换机制
- 极简边框（1px 弱对比）

### 6.2 因业务需求偏离 shadcn 的部分

- 涨跌色保持红绿（shadcn 只用中性色）
- 信号标签保持五色语义（shadcn 只用中性色标签）
- 信息密度放宽（金融终端需要更高信息密度）
- 1200px 宽度限制（shadcn 一般无此限制）

### 6.3 本项目已有但与 Token 的对应关系

| 本项目已有 | 对应 Token | 备注 |
|-----------|-----------|------|
| `global.less` `--color-up: #EF4444` | `--color-up` 深色 `#EF4444` | 值一致，保留 |
| `global.less` `--color-down: #22C55E` | `--color-down` 深色 `#22C55E` | 值一致，保留 |
| `global.less` `--color-primary: #3B82F6` | `--color-brand-500` | 值一致，保留 |
| `global.less` `--color-accent: #F59E0B` | 移除为独立品牌色 | 关注信号使用 `--signal-watch` |
| `global.less` `--bg-surface: #1E293B` | `--bg-surface` 深色 `#1A1A1A` | **值不一致**，需迁移 |
| `global.less` `--text-primary: #F1F5F9` | `--text-primary` 深色 `#FAFAFA` | 值接近但需统一 |
| `@radius-md: 8px` (各页面 inline) | `--radius-md: 10px` | **需修改**为 10px |
| `--shadow-default` 无定义 | `--shadow-default: 0 1px 2px` | 新增 |
