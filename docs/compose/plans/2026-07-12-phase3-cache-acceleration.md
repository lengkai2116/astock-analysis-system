# Phase 3：API 缓存 + 聚合 API + 前端加速

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过内存缓存、仪表盘数据聚合和前端资源本地化，将仪表盘加载时间从 5-15s 降至 1-3s。

**Architecture:** 扩展 TieredMemoryCache 加 `dashboard` 级别(60s TTL, 500条目)；新增 API 响应缓存装饰器；新增聚合端点 `/api/v3/dashboard/full`；CDN 资源下载到 `_ui-prototype/assets/` 并更新 HTML 引用。

**Tech Stack:** Python 3, cachetools.TTLCache, Flask, ECharts 5.4.3, Socket.IO 4.7.5

## Global Constraints

- cachetools 已依赖（`pyproject.toml`），无需新增包
- 所有缓存改动使用 `from cachetools import TTLCache`
- CDN 文件下载到 `_ui-prototype/assets/`，通过 Flask `send_from_directory` 提供
- 聚合 API 不引入新数据依赖——仅合并现有服务层调用

---

### Task C1: 扩展 TieredMemoryCache + 新增 `dashboard` 级别

**Covers:** 268号方案 §五-B1

**Files:**
- Modify: `backend/app/data/memory_cache.py:23-28`

- [ ] **Step 1: 扩展缓存级别配置**

```python
CACHE_LEVELS = {
    'realtime': {'ttl': 3, 'maxsize': 200},         # 实时行情，3s 刷新（原100→200）
    'intraday': {'ttl': 300, 'maxsize': 500},        # 盘中数据（原200→500）
    'analysis': {'ttl': 1800, 'maxsize': 300},       # 分析数据（原100→300）
    'dashboard': {'ttl': 60, 'maxsize': 500},        # 仪表盘响应，60s 过期（新增）
}
```

- [ ] **Step 2: 运行 Makefile 检查**

```bash
make lint
```

---

### Task C2: API 响应缓存装饰器

**Covers:** 268号方案 §五-B2

**Files:**
- Create: `backend/app/utils/api_cache.py`

- [ ] **Step 3: 创建 `api_cache.py`**

```python
"""
API 响应缓存装饰器
===================
基于 cachetools.TTLCache，按 (endpoint, query_string) 缓存 JSON 响应。
用于高频读取的低变化端点（仪表盘、市场总览等）。

用法：
    @api_cache(ttl=30)
    def my_route():
        return jsonify(data)
"""
from functools import wraps
from flask import request, jsonify
from cachetools import TTLCache
import hashlib
import logging

logger = logging.getLogger(__name__)

# 全局缓存：key=(route, sorted query params) → response_data
_response_cache = TTLCache(maxsize=500, ttl=60)

def api_cache(ttl: int = 30, maxsize: int = 200):
    """API 响应缓存装饰器

    Args:
        ttl: 缓存生存时间（秒）
        maxsize: 最大缓存条目数
    """
    cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 构建缓存键：路由 + 排序后的 query params
            params = tuple(sorted(request.args.items())) if request.args else ()
            key = (request.path, params)

            # 检查缓存
            cached = cache.get(key)
            if cached is not None:
                return cached

            # 执行原函数
            response = f(*args, **kwargs)

            # 仅缓存成功响应
            if isinstance(response, tuple):
                body, status = response
                if status == 200:
                    cache[key] = response
            else:
                cache[key] = response

            return response
        return wrapper
    return decorator

def invalidate_api_cache(pattern: str = None):
    """按路径前缀失效缓存（适配数据更新后清除旧缓存）"""
    if pattern is None:
        _response_cache.clear()
        return
    keys = [k for k in _response_cache if k[0].startswith(pattern)]
    for k in keys:
        del _response_cache[k]
```

- [ ] **Step 4: 在部分高频端点应用装饰器**

```python
# backend/app/routes/dashboard.py 中
from app.utils.api_cache import api_cache

@dashboard_bp.route('/api/v3/market/index-daily', methods=['GET'])
@api_cache(ttl=60)
@handle_exceptions
def get_index_daily():
    ...

@dashboard_bp.route('/api/v3/market/sector-sector', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_sector():
    ...

@dashboard_bp.route('/api/v3/market/sector-moneyflow', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_moneyflow():
    ...
```

- [ ] **Step 5: 运行 Makefile 检查**

```bash
make lint
```

---

### Task C3: 前端 CDN 资源本地化

**Covers:** 268号方案 §五-C2

**Files:**
- Download: `_ui-prototype/assets/echarts.min.js`
- Download: `_ui-prototype/assets/socket.io.min.js`
- Modify: `_ui-prototype/*.html` — 替换 CDN URLs

- [ ] **Step 6: 下载 CDN 资源到本地 assets 目录**

```bash
curl -sL -o _ui-prototype/assets/echarts.min.js \
  https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js
curl -sL -o _ui-prototype/assets/socket.io.min.js \
  https://cdn.socket.io/4.7.5/socket.io.min.js
```

- [ ] **Step 7: 更新 HTML 中的 CDN 引用（4 个文件）**

修改 `dashboard.html`, `indicator-ide.html`, `strategy-sandbox.html`, `backtest.html` 中的：
```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
```
替换为：
```html
<script src="assets/echarts.min.js"></script>
```

修改 `dashboard.html`, `indicator-ide.html`, `watchlist.html` 中的：
```html
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
```
替换为：
```html
<script src="assets/socket.io.min.js"></script>
```

---

### Task C4: 仪表盘聚合 API `/api/v3/dashboard/full`

**Covers:** 268号方案 §五-D1/D2

**Files:**
- Modify: `backend/app/routes/dashboard.py` — 新增聚合端点
- Modify: `_ui-prototype/dashboard.html` — 前端改用聚合端点

- [ ] **Step 8: 在 `DashboardService` 中添加聚合方法**

```python
def get_dashboard_full(self) -> Optional[Dict]:
    """聚合仪表盘全部数据（一次调用替代 7 次独立请求）"""
    result = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    # 1. 指数行情总览
    try:
        overview = self.get_index_summary()
        if overview:
            result['market_overview'] = overview
    except Exception:
        pass

    # 2. 成交额柱状图
    try:
        volume = self.get_market_volume()
        if volume:
            result['market_volume'] = volume
    except Exception:
        pass

    # 3. AI 雷达 + 策略信号
    try:
        summary = self.get_dashboard_summary()
        if summary:
            result['dashboard_summary'] = summary
    except Exception:
        pass

    # 4. 资金流向
    try:
        moneyflow = self.get_moneyflow_summary()
        if moneyflow:
            result['moneyflow_summary'] = moneyflow
    except Exception:
        pass

    # 5. 板块涨跌幅
    try:
        sector = self.get_sector_changes()
        if sector:
            result['sector_changes'] = sector
    except Exception:
        pass

    # 6. 板块资金流向
    try:
        sec_mf = self.get_sector_moneyflow()
        if sec_mf:
            result['sector_moneyflow'] = sec_mf
    except Exception:
        pass

    # 7. 涨跌幅榜
    try:
        top_up = self.get_daily_top(type='up', limit=10)
        if top_up:
            result['daily_top_up'] = top_up
        top_down = self.get_daily_top(type='down', limit=10)
        if top_down:
            result['daily_top_down'] = top_down
    except Exception:
        pass

    if not result:
        return None
    return result
```

- [ ] **Step 9: 新增聚合路由**

```python
@dashboard_bp.route('/api/v3/dashboard/full', methods=['GET'])
@api_cache(ttl=30)
@handle_exceptions
def get_dashboard_full():
    """聚合仪表盘全部数据"""
    data = _service.get_dashboard_full()
    return _data_response(data)
```

- [ ] **Step 10: 更新前端使用聚合端点**

在 `dashboard.html` 中，在 `loadMarketOverview()` 等一系列独立加载函数之前，添加：

```javascript
// ===== [新增] 聚合加载（优先于独立请求）=====
function loadDashboardFull(){
  fetch(API+'/dashboard/full')
    .then(function(r){return r.json();})
    .then(function(d){
      if(!d.success||!d.data)throw new Error('no data');
      var dd=d.data;
      // 分发到各渲染函数
      if(dd.market_overview) applyMarketOverview(dd.market_overview);
      if(dd.market_volume) renderVolumeChart(dd.market_volume);
      if(dd.dashboard_summary){
        applyRadar(dd.dashboard_summary);
        applySignals(dd.dashboard_summary.signal_summary||{});
      }
      if(dd.moneyflow_summary) renderMoneyflow(dd.moneyflow_summary);
      if(dd.sector_changes) renderSectorChart(dd.sector_changes);
      if(dd.sector_moneyflow) renderSectorMoneyflow(dd.sector_moneyflow);
      if(dd.daily_top_up) renderGainers(dd.daily_top_up.stocks||[]);
    })
    .catch(function(e){
      console.warn('聚合加载失败，降级到独立请求',e);
      // 降级：触发原有独立请求
      loadMarketOverview();
      loadVolumeChart();
      loadRadar();
      loadMoneyflow();
      loadSectorChanges();
      loadSectorMoneyflow();
      loadTopGainers();
      loadSignalSummary();
    });
}

// 将原启动位置的 8 个独立调用替换为聚合调用
// 原：loadMarketOverview(); loadVolumeChart(); loadRadar(); ...
// 新：
loadDashboardFull();
```

同时将原有数据加载函数的内部逻辑提取为可复用的渲染函数（如 `applyMarketOverview()`、`renderVolumeChart()`、`applyRadar()` 等），使其可被聚合端点和新独立请求共同调用。

- [ ] **Step 11: 运行 Makefile 检查**

```bash
make lint
```

---

### Task C5: 验证

- [ ] **Step 12: 验证 CDN 文件可用**

```bash
ls -lh _ui-prototype/assets/echarts.min.js _ui-prototype/assets/socket.io.min.js
# 预期：两个文件存在且非空
```

- [ ] **Step 13: 验证 API 缓存生效**

```bash
# 启动后端
python3 backend/run.py --port 5001 &
sleep 3
# 首次请求
time curl -s http://localhost:5001/api/v3/market/sector-sector > /dev/null
# 第二次请求（应命中缓存）
time curl -s http://localhost:5001/api/v3/market/sector-sector > /dev/null
# 预期：第二次明显更快（<50ms vs 几百ms）
kill %1 2>/dev/null
```
