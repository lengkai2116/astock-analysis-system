# 个股策略分析（indicator-ide）修订确认清单

> 基于 166 号文档 §7 + §8 + 沟通记录 2026-06-15 ~ 2026-06-16，按最新沟通记录修正。
> 仅记录行动项，待逐项确认后统一交付。

---

### 7.1 时间跨度与交互规则（修订版）

#### ✅ 已确认不变项

| 项目 | 值 |
|:-----|:-----|
| 数据点数 | 750 根（2023-06-01 → 2026-06-15） |
| 默认视图 | dataZoom `start:86, end:100` → 末 100 根 |
| 滑块 | **取消**（`type:'slider'` hidden，`height:0; bottom:-30`） |
| 副图 dataZoom | 与主图完全一致：`start:86, end:100`，同步方式同 |

#### 🔧 图表移动方式（2种）

| 操作 | 效果 | 备注 |
|:-----|:------|:------|
| **① 鼠标左键按住左右拖拽** | 图表平行移动 | 10px ≈ 1% 步长 |
| **② 键盘 ← → 移动十字光标** | 光标到图表边缘时带动图表平移 20% | §7.5 已有定义，需确认实现 |

#### 🔧 筹码展开/收起同步（补充）

| 状态 | dataZoom.start | 副图同步 |
|:-----|:---------------|:---------|
| 筹码收起（默认） | **86** | `subInstances[k].dispatchAction({type:'dataZoom', start:86, end:100})` |
| 筹码展开 | **89** | 同上，start=89 |
| 十字光标移动 | 联动更新筹码数据面板 | `renderChipData(cursorIdx)` |

---

### 7.3 十字光标贯穿联动（修订版）

#### ❌ 待修正

| 当前代码（错误） | 应改为 |
|:-----------------|:--------|
| 副图 `axisPointer:{type:'line',label:{show:false}}` | **`axisPointer:{type:'cross',label:{show:false}}`** |
| 副图仅显示纵向虚线 | **副图同时显示竖线 + 横线（完整十字），仅隐藏标签数字** |

#### ✅ 已确认不变项

| 功能 | 实现 |
|:-----|:------|
| 多图联动 | 放弃 `echarts.connect` → 手动 `instance.on('showTip')` + `_isSyncing` 防循环 |
| 主图→副图 | `chart.on('showTip')` + `updateAxisPointer` dispatch 到所有 subInstances |
| 副图→主图 | `instance.on('showTip')` 反向 dispatch 到 `chart` + 其他副图 |
| 锁定收盘价 | `chart.getZr().on('mousemove')` → `convertFromPixel` → `dispatchAction(seriesIndex:0)` |
| 拖拽时不触发十字光标 | `_isDragging` 守卫跳过 mousemove |
| 副图无浮窗 | `showContent: false` |

---

### 8.3 副图▼下拉选择框（修订版）

#### ❌ 待修正

| 当前代码（待确认） | 应改为 |
|:-------------------|:--------|
| ▼ 按钮在副图标题**左侧** | ▼ 按钮在副图标题**右侧** |
| 底部指标栏 **「＋▼」** 按钮保留 | **「＋▼」按钮可以取消** |

#### ✅ 已确认不变项

| 功能 | 说明 |
|:-----|:------|
| ▼ 点击弹出列表 | 显示所有指标（19 个），含已激活标记 |
| 点击替换 | 点击某指标 → 替换当前副图 |
| 底部标签点选 | 原有 `toggleSub` 点选功能保持不变 |

---

### 筹码面板技术规范（§7.10 补充）

| 元素 | 对齐 | CSS |
|:-----|:------|:-----|
| 标题"筹码分布" | 与"数据:Tushare"同行 | `margin-top:2px;height:18px` |
| chip-chart 图谱 | 与 K 线 grid 绘图区同高、同价格范围 | `margin-top:34px;height:325px` |
| 数据面板 | 顶部对齐第一副图上沿 | `margin-top:31px` |
| Y 坐标映射 | `y = 325 × (1 - (price - minP) / priceRange)` | `getExtent()` 获取价格范围 |
| 十字光标联动 | `updateSubHeaders → renderChipData(cursorIdx)` | — |

---

### 待逐项核对清单

完成后逐一打勾 ✅ 确认。

| # | 项 | 状态 |
|:--|:----|:------|
| 1 | 主图 dataZoom start:86, end:100，滑块隐藏 | ☐ |
| 2 | 副图 dataZoom start:86, end:100，与主图完全一致 | ☐ |
| 3 | 筹码展开→start=89，收起→start=86，副图同步 | ☐ |
| 4 | 鼠标左键拖拽 → 图表平移（10px=1%） | ☐ |
| 5 | 键盘 ← → 到边缘 → 图表平移 20% | ☐ |
| 6 | 副图 axisPointer: `type:'cross',label:{show:false}` | ☐ |
| 7 | 副图 ▼ 按钮在标题右侧 | ☐ |
| 8 | 底部「＋▼」按钮取消 | ☐ |
| 9 | 筹码面板三元素对齐（标题/图谱/数据面板） | ☐ |
| 10 | 页面无功能性问题，刷新后正常渲染 | ☐ |
