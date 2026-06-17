# 统一十字光标方案 — 技术规范（路线A）

> 本规范定义将 `indicator-ide.html` 从多ECharts实例 + axisPointer同步，改造为**单实例多grid + graphic全渲染十字光标**的完整技术方案。

**目标**：一个十字光标、一个数据源、一个渲染入口、零残留风险。

---

## 一、架构变更总览

### 变更前（当前）

```
chart (ECharts实例#1, 主图)
  ├─ axisPointer(type:'cross')  ← 垂直线+横线跟随鼠标Y
  ├─ graphic(closeLine, 水平辅助线)
  ├─ dataZoom × 1
  └─ zr mousemove → dispatch showTip → 同步到↓

subChart_1 (ECharts实例#2)
  ├─ axisPointer(type:'cross')
  ├─ showTip → 同步回chart
  └─ mouseleave → dispatch hideTip

subChart_N (ECharts实例#N)
  ├─ axisPointer(type:'cross')
  ├─ showTip → 同步回chart
  └─ mouseleave → dispatch hideTip

问题: N个axisPointer状态不一致, 残留/同步/对齐问题
```

### 变更后（目标）

```
chart (唯一ECharts实例)
  ├─ grid[0]: 主图K线区
  ├─ grid[1..N]: 副图指标区
  ├─ tooltip.trigger: 'none'          ← 禁用原生axisPointer
  ├─ dataZoom × 1（自动同步所有grid）
  ├─ zr mousemove → updateCrosshair(idx)  ← 唯一渲染入口
  ├─ keyboard → updateCrosshair(idx)
  └─ graphic: [竖线, 横线, 价格标签, 日期标签, ...]
       ↑ 所有十字光标元素在同一次setOption中渲染

#sub-chart-area
  └─ DOM header（仅显示标题+数值文字, 无ECharts实例）
```

---

## 二、数据结构变更

### 2.1 grid配置

单一 `setOption` 中包含所有grid：

```javascript
// grid高度计算:
//   主图: 350px, top:10, bottom:15 → grid高 = 350 - 25 = 325px
//   子图: 每副图128px, top:6, bottom:6 → grid高 = 128 - 12 = 116px
//   间距: 子图header 约20px

var GRID_MAIN_TOP = 10;
var GRID_MAIN_HEIGHT = 325;  // 350-10-15

// 动态计算子图位置
var subGridTops = [];
var nextTop = GRID_MAIN_TOP + GRID_MAIN_HEIGHT + 15 + 20; // +15底部+20间距
activeSubs.forEach(function(name, i){
  subGridTops[i] = nextTop;
  nextTop += 128;  // 128px per sub-chart
});

chart.setOption({
  grid: [
    {left:55, right:20, top:GRID_MAIN_TOP, height:GRID_MAIN_HEIGHT, bottom:'auto'},
    ...activeSubs.map((name, i) => ({
      left:55, right:20, top:subGridTops[i], height:116, bottom:'auto'
    }))
  ],
  xAxis: [
    {type:'category', data:dates, gridIndex:0, show:true, axisLabel:{fontSize:9, color:'#64748B'}},
    ...activeSubs.map((_, i) => ({
      type:'category', data:dates, gridIndex:i+1, show:false
    }))
  ],
  yAxis: [
    {scale:true, gridIndex:0, axisLabel:{show:true, fontSize:9, color:'#64748B'}, splitLine:{lineStyle:{color:'#1E293B'}}},
    ...activeSubs.map((name, i) => ({
      scale:true, gridIndex:i+1, show:true, axisLabel:{fontSize:9, color:'#64748B'}, splitLine:{show:false}
    }))
  ],
  dataZoom: [{
    type:'slider', xAxisIndex:0, start:86, end:100,  // 作用于所有grid通过xAxisIndex共享
    height:0, bottom:-30, showDetail:false, showDataShadow:false,
    borderColor:'transparent', backgroundColor:'transparent', fillerColor:'transparent',
    handleStyle:{color:'transparent', borderColor:'transparent'},
    labelStyle:{color:'transparent', fontSize:0}, brushSelect:false
  }],
  tooltip: {
    trigger: 'none',            // ← 关键：禁用原生tooltip
    axisPointer: { type: 'cross' }  // 保留配置使dispatch仍有效
  },
  series: [
    // 主图系列（gridIndex:0, xAxisIndex:0, yAxisIndex:0）
    {type:'line', data:closes, lineStyle:{opacity:0}, symbol:'none', z:-1, silent:true},
    {type:'candlestick', data:ohlc, itemStyle:{color:'#EF4444', color0:'#22C55E', ...}},
    ...MA系列,
    // 副图系列（gridIndex:1..N, xAxisIndex:1..N, yAxisIndex:1..N）
    ...subSeries
  ]
});
```

### 2.2 subDefs 迁移

当前每个 `subDef[name].render()` 独立 `echarts.init(dom)` + `setOption({series})`。
改为返回值模式：

```javascript
var subDefs = {
  macd: {
    label: 'MACD',
    getSeries: function(gridIndex) {
      return [
        {type:'bar', data:OD.macd, xAxisIndex:gridIndex, yAxisIndex:gridIndex,
         itemStyle:{color:function(p){return p.value>=0?'#EF4444':'#22C55E';}}},
        {type:'line', data:OD.dif, xAxisIndex:gridIndex, yAxisIndex:gridIndex,
         symbol:'none', lineStyle:{color:'white',width:1}},
        {type:'line', data:OD.dea, xAxisIndex:gridIndex, yAxisIndex:gridIndex,
         symbol:'none', lineStyle:{color:'#F59E0B',width:1}}
      ];
    }
  },
  vol: {
    label: 'VOL 成交量',
    getSeries: function(gridIndex) {
      return [
        {type:'bar', data:vol, xAxisIndex:gridIndex, yAxisIndex:gridIndex,
         itemStyle:{color:'rgba(59,130,246,0.4)'}},
        {type:'line', data:m5, xAxisIndex:gridIndex, yAxisIndex:gridIndex,
         symbol:'none', lineStyle:{color:'#F59E0B',width:1}}
      ];
    }
  },
  // ... 其他指标同理
};
```

`renderSubs()` 改造为：

```javascript
function renderSubs(){
  // 只生成DOM header，不创建ECharts实例
  var area = document.getElementById('sub-chart-area');
  area.innerHTML = '';
  activeSubs.forEach(function(name){
    var def = subDefs[name];
    if(!def) return;
    var wrap = document.createElement('div');
    wrap.className = 'sub-chart';
    var hdr = document.createElement('div'); hdr.className = 'sub-chart-header';
    var titleSpan = document.createElement('span'); titleSpan.textContent = def.label;
    var valSpan = document.createElement('span'); valSpan.className = 'sub-val sub-chart-'+name; valSpan.style.marginLeft='auto';
    var selBtn = document.createElement('button'); selBtn.className='sub-sel-btn'; selBtn.textContent='▼';
    selBtn.onclick=function(e){showSubSelect(e,name);};
    hdr.appendChild(titleSpan); hdr.appendChild(valSpan); hdr.appendChild(selBtn);
    wrap.appendChild(hdr);
    area.appendChild(wrap);
  });
  // 重建chart series
  rebuildChart();
}

function rebuildChart(){
  var allSeries = [buildBaseSeries()];  // 主图系列
  activeSubs.forEach(function(name, i){
    var def = subDefs[name];
    if(def && def.getSeries) allSeries.push(def.getSeries(i + 1));  // gridIndex从1开始
  });
  chart.setOption({series: allSeries.flat()});
}
```

---

## 三、核心：`updateCrosshair(idx)` — 唯一十字光标渲染函数

这是整个方案的核心函数，所有交互路径（鼠标、键盘）最终都调用它。

```javascript
// ── 唯一的十字光标渲染函数 ──
var _cursorIdx = 0;

function updateCrosshair(idx, options) {
  // options: { hideSubValues: false }

  // 无效索引 → 隐藏所有十字光标元素
  if (idx == null || idx < 0 || idx >= dates.length) {
    chart.setOption({
      graphic: [
        {id:'cv', invisible:true},  // 竖线
        {id:'ch', invisible:true},  // 横线
        {id:'cpl', invisible:true}, // 价格标签
        {id:'cdl', invisible:true}, // 日期标签
      ]
    }, {replaceMerge: ['graphic']});
    return;
  }

  _cursorIdx = idx;
  var closePrice = closes[idx];
  var dateText = dates[idx];

  // ── 坐标转换 ──
  // 竖线X: 通过主图xAxis转换
  var x = chart.convertToPixel({xAxisIndex: 0}, idx);
  if (x == null) return;

  // 横线Y: 通过主图yAxis转换
  var yPx = chart.convertToPixel({xAxisIndex: 0, yAxisIndex: 0}, [idx, closePrice]);
  if (!yPx || yPx[1] == null) return;
  var y = yPx[1];

  // ── 获取各grid的像素范围 ──
  var gridRects = [];
  for (var g = 0; ; g++) {
    var rect = chart.getModel().getComponent('grid', g)?.getRect();
    if (!rect) break;
    gridRects.push(rect);
  }
  if (gridRects.length === 0) return;

  var firstGrid = gridRects[0];
  var lastGrid = gridRects[gridRects.length - 1];

  // ── 构建graphic元素 ──
  var graphics = [
    // ① 竖线: 从第一个grid顶部到最后一个grid底部
    {
      id: 'cv',
      type: 'line',
      shape: {
        x1: x, y1: firstGrid.y,
        x2: x, y2: lastGrid.y + lastGrid.height
      },
      style: {
        stroke: '#E2E8F0',
        lineDash: [4, 4],
        lineWidth: 1
      },
      z: 100,
      invisible: false
    },
    // ② 横线: 仅主图grid宽度
    {
      id: 'ch',
      type: 'line',
      shape: {
        x1: firstGrid.x, y1: y,
        x2: firstGrid.x + firstGrid.width, y2: y
      },
      style: {
        stroke: '#E2E8F0',
        lineDash: [4, 4],
        lineWidth: 1
      },
      z: 100,
      invisible: false
    },
    // ③ 收盘价标签: 横线左端
    {
      id: 'cpl',
      type: 'text',
      style: {
        text: closePrice.toFixed(2),
        fill: '#E2E8F0',
        backgroundColor: '#334155',
        padding: [3, 8, 3, 8],
        fontSize: 11,
        fontFamily: 'monospace'
      },
      shape: {
        x: firstGrid.x - 5,
        y: y - 12
      },
      z: 101,
      invisible: false
    },
    // ④ 日期标签: 竖线底部（X轴位置下方）
    {
      id: 'cdl',
      type: 'text',
      style: {
        text: dateText,
        fill: '#E2E8F0',
        backgroundColor: '#334155',
        padding: [2, 6, 2, 6],
        fontSize: 10
      },
      shape: {
        x: x - 20,
        y: lastGrid.y + lastGrid.height + 2
      },
      z: 101,
      invisible: false
    }
  ];

  // ⚠️ 兼容路径：如果仍有子图ECharts实例需要dispatch
  for (var _k in subInstances) {
    try { subInstances[_k].dispatchAction({type:'showTip', seriesIndex:0, dataIndex:idx}); } catch(e) {}
  }

  // ── 一次性渲染 ──
  chart.setOption({ graphic: graphics }, { replaceMerge: ['graphic'] });

  // ── 更新副图DOM数值 ──
  updateSubHeaders(idx);
}
```

**关键设计要点：**

| 要点 | 说明 |
|------|------|
| `z: 100 / 101` | 确保graphic在series之上 |
| `replaceMerge:['graphic']` | 替换整个graphic数组，按id匹配 |
| `invisible: false/true` | 显示/隐藏控制，无需重建元素 |
| 所有路径统一入口 | 鼠标、键盘均调用 `updateCrosshair(idx)` |

---

## 四、交互路径

### 4.1 鼠标：zr mousemove → dataIndex → updateCrosshair

```javascript
// 禁用原生tooltip后，zr mousemove是唯一触发源
chart.getZr().on('mousemove', function(param){
  if (!param || _isDragging) return;
  var point = [param.offsetX, param.offsetY];
  // 通过主图xAxis将像素坐标转为dataIndex
  var pixel = chart.convertFromPixel({xAxisIndex: 0, yAxisIndex: 0}, point);
  if (!pixel || pixel[0] == null) return;
  var idx = Math.round(pixel[0]);
  if (idx < 0 || idx >= dates.length) return;
  updateCrosshair(idx);
});
```

**注意**：`convertFromPixel({xAxisIndex:0, yAxisIndex:0}, point)` 即使鼠标在副图grid区域，只要传入主图的 `xAxisIndex`，返回的 `pixel[0]` 仍是基于主图xAxis的dataIndex。**竖线X坐标统一使用主图xAxis转换**，所有grid共享同一个时间轴。

### 4.2 键盘：keydown → cursorIdx ± 1 → updateCrosshair

```javascript
document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    var idx = _cursorIdx + (e.key === 'ArrowLeft' ? -1 : 1);

    // 到达边界 → dataZoom平移
    if (idx < 0 || idx >= dates.length) {
      var dz = chart.getOption().dataZoom[0];
      var range = dz.end - dz.start;
      var shift = Math.max(5, Math.round(range * 0.3));
      var ns = dz.start, ne = dz.end;
      if (e.key === 'ArrowLeft') { ns = dz.start - shift; ne = dz.end - shift; }
      else { ns = dz.start + shift; ne = dz.end + shift; }
      if (ns < 0) { ns = 0; ne = range; }
      if (ne > 100) { ne = 100; ns = 100 - range; }
      chart.dispatchAction({type: 'dataZoom', start: ns, end: ne});
      idx = e.key === 'ArrowLeft' ? dates.length - 1 : 0;
    }

    updateCrosshair(idx);
  }
});
```

### 4.3 鼠标移出 → 十字光标消失

在 `chart-wrap` 上绑定唯一一个mouseleave：

```javascript
document.querySelector('.chart-wrap').addEventListener('mouseleave', function() {
  updateCrosshair(-1);  // 无效索引 → 隐藏所有graphic
});
```

✅ 单一监听器，单一入口，无残留可能。

### 4.4 右键拖拽平移

```javascript
var _isDragging = false;
var _dragStartX = 0, _dragDzStart = 0, _dragDzEnd = 0;

chart.getZr().on('mousedown', function(e) {
  if (e.which !== 3) return;  // ← 改为右键
  _isDragging = true;
  _dragStartX = e.offsetX;
  var dz = chart.getOption().dataZoom[0];
  _dragDzStart = dz.start;
  _dragDzEnd = dz.end;
});

chart.getZr().on('mousemove', function(e) {
  if (!_isDragging) return;
  var dx = e.offsetX - _dragStartX;
  var totalPx = chart.getWidth();
  var pct = dx / totalPx * (_dragDzEnd - _dragDzStart);
  var ns = Math.max(0, _dragDzStart - pct);
  var ne = Math.min(100, _dragDzEnd - pct);
  if (ns < 0) { ns = 0; ne = _dragDzEnd - _dragDzStart; }
  if (ne > 100) { ne = 100; ns = 100 - (_dragDzEnd - _dragDzStart); }
  chart.dispatchAction({type: 'dataZoom', start: ns, end: ne});
});

document.addEventListener('mouseup', function() {
  _isDragging = false;
});

// 阻止浏览器默认右键菜单
document.querySelector('.chart-wrap').addEventListener('contextmenu', function(e) {
  e.preventDefault();
});
```

在 **单实例多grid** 架构下，`dataZoom` 自动同步所有grid——因为所有grid的X轴通过 `xAxisIndex` 共享同一个 `dataZoom`。

---

## 五、初始化流程

```
1. 生成模拟数据 + 指标计算 (现有逻辑, 不变)
2. buildBaseSeries() → 生成主图series (现有逻辑, 不变)
3. renderSubs() → 只创建DOM header, 不init ECharts实例
   ├── 调用 rebuildChart() → 合并主图+所有副图series
   └── 用 chart.setOption({grid, xAxis, yAxis, series}) 一次性初始化
4. 绑定事件:
   ├── zr mousemove → updateCrosshair
   ├── 右键拖拽 → dataZoom
   ├── keyboard → updateCrosshair + dataZoom
   └── chart-wrap mouseleave → updateCrosshair(-1)
5. 侧栏折叠IIFE → chart.resize() (已有)
```

---

## 六、变更对比：要删的和要留的

### 要删除的（约120行）

| 删除内容 | 行号（当前） | 原因 |
|---------|------------|------|
| `subInstances = {}`, `subAllData = {}`, `subData = {}` | 557-558 | 不再需要多实例 |
| `subXAxis()`, `subYAxis()` | 560-561 | 统一配置在setOption中 |
| `subDefs` 中所有 `echarts.init(dom)` + `setOption` | 563-626 | 改为getSeries |
| `renderSubs()` 中的 `echarts.init` + `instance.setOption` | 780-784 | 由rebuildChart替代 |
| `instance.on('showTip', ...)` 同步逻辑 | 786-797 | 不需要 |
| `instance.setOption({tooltip, dataZoom})` | 781-782 | 由主chart统一管理 |
| `_zoomSyncing` | 670 | 单一dataZoom无需同步 |
| `_isSyncing` 及所有相关逻辑 | 796, 915 | 不再需要防环 |
| 子图mouseleave handler `onSubLeave` | 798-808 | chart-wrap统一处理 |
| `chart.on('showTip')` 和 `chart.on('updateAxisPointer')` | 722-731, 936-966 | 由updateCrosshair统一 |
| `updateCloseLine()` + `_rafPending` | 899-912 | 由updateCrosshair中的横线替代 |
| 子图dataZoom dispatch循环 | 685-688,712-713,1000-1002 | 单一dataZoom自动同步 |
| `chart.getDom().mouseleave` | 934-935 | 由chart-wrap统一mouseleave替代 |

### 要保留或微调的（约30行）

| 保留/微调 | 说明 |
|----------|------|
| `buildBaseSeries()` | 主图series逻辑不变 |
| `toggleSub()` | 改为调rebuildChart() |
| `showSubSelect()` | 不变 |
| `updateSubHeaders()` | 不变（DOM文字） |
| `toggleOverlay()` | 改为调rebuildChart() |
| `toggleChipPanel()` | 不变 |
| `toggleSidebar()` | chart.resize()不变 |
| `Ctrl+滚轮缩放` | 不变（dataZoom dispatch） |
| `keyboard handler` | 改为调updateCrosshair |
| 侧栏折叠IIFE | chart.resize()不变 |

---

## 七、执行顺序

| 步骤 | 内容 | 难度 |
|------|------|------|
| 1 | 新增 `updateCrosshair(idx)` 函数（约50行） | 低 |
| 2 | 重写 `subDefs` → 改为 `getSeries(gridIndex)` 返回格式（20个指标） | 中 |
| 3 | 重写 `renderSubs()` → 只生成DOM header | 低 |
| 4 | 新增 `rebuildChart()` → 合并所有series一次性setOption | 中 |
| 5 | 将主图setOption改为多grid模式（grid[], xAxis[], yAxis[]） | 中 |
| 6 | 替换 zr mousemove → 调用 `updateCrosshair` | 低 |
| 7 | 替换 keyboard → 调用 `updateCrosshair` | 低 |
| 8 | 替换鼠标离开 → chart-wrap统一mouseleave | 低 |
| 9 | 右键拖拽（改一行条件 + 阻止contextmenu） | 低 |
| 10 | 删除所有不再需要的代码（约120行） | 低 |
| 11 | 验证全部5项功能 | 低 |

---

## 八、验证清单

- [ ] 初始页面干净（无十字光标）
- [ ] 鼠标进入主图区域 → 竖线贯穿所有grid + 横线在主图 + 收盘价标签（2位小数） + 日期标签
- [ ] 鼠标移到副图区域 → 竖线仍在同一日期，横线仍在主图
- [ ] 鼠标移出chart-wrap → 所有十字光标元素消失
- [ ] 键盘左右键 → 十字光标逐日移动
- [ ] 键盘到左边界再按← → dataZoom左移，光标跳到右侧
- [ ] 键盘到右边界再按→ → dataZoom右移，光标跳到左侧
- [ ] 右键拖拽 → 图表左右平移，十字光标不可见（拖拽中）
- [ ] 侧栏展开/折叠 → chart.resize()，十字光标位置正确
- [ ] 切换副图（toggleSub） → 重新渲染grid，十字光标保留
- [ ] 副图标题栏显示正确的十字光标位置数值
- [ ] Ctrl+滚轮缩放 → dataZoom正常
