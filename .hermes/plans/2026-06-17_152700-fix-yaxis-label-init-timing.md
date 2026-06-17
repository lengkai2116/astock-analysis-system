# 修复方案：indicator-ide ECharts Y轴左侧数值不显示

> **For Hermes:** 按此方案任务逐项实现，经用户确认后方可修改代码。

**目标：** 解决 `_ui-prototype/indicator-ide.html` 页面首次加载时 K线主图左侧 Y轴数值标签不显示的问题。

**根因：** 页面初始侧栏折叠 IIFE（第 1053-1059 行）改变了 main-content 的 `marginLeft` 布局，但未调用 `chart.resize()`，导致 canvas 以错误尺寸（648px）渲染，ECharts 左侧 55px 网格区域内的轴标签像素被压缩/错位。

**技术栈：** ECharts 5.4.3, 纯 HTML/CSS/JS 原型

---

## 现状分析

### 执行时间线（问题来源）

| 步骤 | 行号 | 操作 | 副作用 |
|------|------|------|--------|
| 1 | 630 | `echarts.init()` | 此时侧栏**未折叠**，容器全宽 |
| 2 | 632-667 | `chart.setOption({...})` | ECharts 取到容器 offsetWidth = **784px**，但 canvas 渲染为 **648px** |
| 3 | 669 | `chart.setOption({graphic:...})` | closeLine x2 = chart.getWidth()-20 = **628px**（错误） |
| 4 | 1029 | `renderSubs()` | 子图也以错误宽度初始化 |
| 5 | 1053-1059 | 侧栏折叠 IIFE | marginLeft 改为 64px，但 **无 chart.resize()** |

### 实测数据

| 指标 | 初始化时 | `chart.resize()` 后 |
|------|---------|---------------------|
| canvas 绘制宽度 | **648px** | **784px** ✅ |
| 容器 offsetWidth | 784px | 784px |
| closeLine x2 | 628px | 764px ✅ |
| 左侧标签像素明亮比 | 4.4% | 8.5%（文本正常） |

### 为什么 canvas 初始为 648px？

`main-area` 的 CSS Grid 列布局 `1fr 340px` 中，1fr 列的宽度包含 `chart-flex` → `chart-section` → `#kline-chart`。侧栏折叠后 64px 的 `marginLeft` 使得 chart 可用宽度为 `1274 - 48 - 64 = 1162px`，但 648px ≈ (1162 - 340) × 约 0.79... 具体原因是 ECharts.init 时的 DOM 布局未完全稳定（CSS Grid + flex 延迟计算），导致取到的内容宽度小于实际容器。

**直接解决方案不是深究计数公式，而是：确保 layout 变化后强制 chart.resize()。**

---

## 修复方案

### 任务 1：侧栏折叠后强制 resize 所有图表

**改动文件：** `_ui-prototype/indicator-ide.html`

**行号：** 1053-1059（侧栏折叠 IIFE）

**改动内容：** 在 IIFE 末尾加入 `setTimeout(chart.resize, 50)` 及子图 resize，与 `toggleSidebar()` 函数第 1045-1050 行的做法保持一致。

**代码：**

```javascript
// ── 首次加载默认收起 ──
(function(){
  var s = document.querySelector('.sidebar'), m = document.querySelector('.main-content');
  if(s) s.classList.add('collapsed');
  if(m){ m.classList.add('collapsed'); m.style.marginLeft = '64px'; }
  var btn = document.querySelector('.sidebar-toggle');
  if(btn) btn.textContent = '▶';
  // ★ 修复：布局变更后强制重绘所有 ECharts 实例
  setTimeout(function(){
    if(typeof chart !== 'undefined' && chart.resize) chart.resize();
    for(var k in subInstances){
      try{ subInstances[k].resize(); }catch(e){}
    }
  }, 50);
})();
```

### 任务 2：修复 closeLine 初始宽度

**行号：** 669

**当前代码：** `x2:chart.getWidth()-20`

**问题：** `chart.getWidth()` 此时返回的是错误的 648px，导致 closeLine 水平线右侧截止于 628px。`chart.resize()` 修复画布尺寸后，closeLine 并不会自动更新其 shape 尺寸。

**修复方案：** 将 closeLine 绘制逻辑移入 `chart.getZr().on('mousemove')` 中（已在第 895-911 行的 `updateCloseLine` 函数中实现）。首次不需要静态初始化 closeLine graphic——因为只有当鼠标第一次进入图表时，`updateCloseLine` 才会被调用并设置正确的宽度。

**具体操作：** 删除第 668-669 行（closeLine 的静态初始化）。`updateCloseLine()` 已在 mousemove 回调中自动创建 closeLine（通过 `chart.setOption({graphic:[...]})`），无需重复初始化。

### 任务 3：验证

1. **加载页面：** 刷新 `http://localhost:8080/indicator-ide.html`
2. **JS 验证：** 在 console 执行 `document.querySelector('#kline-chart canvas').width`，预期返回 **784**（或接近容器宽度的值）
3. **视觉验证：** 左侧应显示 `14.00, 15.00, 16.00, 17.00, 18.00, 19.00, 20.00` 等价格刻度
4. **侧栏切换验证：** 点击侧栏折叠/展开按钮 → 图表自动 resize，Y轴标签始终可见
5. **canvas 像素采样：** 检查左侧 20-55px 区域的像素亮度比应 > 5%

### 副作用与风险

- **无风险：** `chart.resize()` 是幂等操作，多次调用无副作用
- **删除 closeLine 初始化** 也不会产生风险——`updateCloseLine()` 会在首次 mousemove 时创建。唯一区别是「首次鼠标进入图表前」没有那条水平虚线，这是预期行为（无交互时不应显示辅助线）

---

## 方案依据

- `frontend-ui-engineering` 技能的「Sidebar Collapse Pattern」节明确要求：侧栏折叠 IIFE 必须包含 `chart.resize()`  
- `toggleSidebar()` 函数（第 1032-1051 行）已有正确实现模板——只需要在页面初始化的 IIFE 中复用相同的 50ms setTimeout(resize) 模式
