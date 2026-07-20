# 全局数据体系修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照279号方案修复全局数据体系全部违规项和数据缺口

**Architecture:** 四层架构（采集层→存储层→计算层→调用层），区分数据计算（后台预计算）和策略核算（用户按需触发）

**Tech Stack:** Python Flask, SQLite WAL, mootdx TCP, Tushare Pro

**Global Constraints:**
- 数据进程 `data_daemon.py` 与 API 进程 `run.py` 分离
- DataManager 是唯一数据网关，禁止绕过
- 禁止 API 路由直调外部数据源或实时计算
- 禁止 Mock 数据作为降级方案
- 分钟数据必须持久化到 minute_kline_cache

---

## 批次A：红线修复（P0）

### Task A1: 修复 chart.py 预计算指标缓存读取路径

**Files:**
- Modify: `backend/app/routes/chart.py:257-270`

**Issue:** `needed_sub.issubset(cached_cols)` 检查请求的副图指标短名（如 `'macd'`）是否在宽表列名（如 `'macd_dif'`）中，导致总是返回 False，回退到实时计算。

**Fix:** 将检查逻辑改为：宽表列名包含该指标所需的至少一个关键列即可认为该指标可用。

- [ ] **Step 1: 修复缓存检查逻辑**

在 `chart.py:262-264`，将：
```python
cached_cols = set(cached.columns) - {'ts_code', 'trade_date'}
needed_sub = set(k for k in requested_indicators if k in SUB_INDICATORS)
if needed_sub.issubset(cached_cols):
```

改为：
```python
cached_cols = set(cached.columns) - {'ts_code', 'trade_date'}
# 宽表列名映射：副图指标名 → 宽表中应有的关键列
INDICATOR_COL_MAP = {
    'macd': {'macd_dif', 'macd_dea', 'macd_hist'},
    'rsi': {'rsi14'},
    'kdj': {'kdj_k', 'kdj_d', 'kdj_j'},
    'vol': {'ma5', 'ma10'},  # vol本身不是指标，但vol副图需要均量线
}
needed_sub = set(k for k in requested_indicators if k in SUB_INDICATORS)
# 检查宽表是否包含每个请求指标所需的至少一个关键列
all_available = True
for ind in needed_sub:
    required_cols = INDICATOR_COL_MAP.get(ind, set())
    if required_cols and not required_cols.issubset(cached_cols):
        all_available = False
        break
if all_available and needed_sub:
```

同时增加 `nine_buy`/`nine_sell` 及 `ene` 等叠加指标的缓存支持（当前只在宽表中检查副图，叠加指标走独立逻辑）。

- [ ] **Step 2: 验证修复**
```bash
cd backend && python -c "
from app.routes.chart import get_kline_chart_data
# 静态验证导入正常
print('chart.py 导入正常')
"
```

### Task A2: 修复 chart.py /signals 端点

**Files:**
- Modify: `backend/app/routes/chart.py:475-538`

**Issue:** `/signals/<ts_code>` 每次实时计算全部指标+全部信号，应改为读取策略信号缓存。

**Fix:** 
1. 改为从 `data_manager.get_cached_signals(ts_code)` 读取预计算信号
2. 缓存未命中时回退到实时计算

- [ ] **Step 1: 改为优先读取缓存策略信号**
```python
@chart_bp.route('/signals/<ts_code>', methods=['GET'])
def get_chart_signals(ts_code):
    limit = request.args.get('limit', 100, type=int)
    try:
        data_manager = get_data_manager()
        # 优先读取预计算信号缓存
        cached_signals = data_manager.get_cached_signals(ts_code)
        if cached_signals is not None and not cached_signals.empty:
            # 转换为图表格式
            signal_markers = []
            for _, sig in cached_signals.tail(limit).iterrows():
                signal_markers.append({
                    'time': _format_time(ts_code, sig.get('trade_date')),
                    'type': 'buy' if sig.get('signal_level') in ('BUY', 'BULLISH', 'STRONG_BUY') else 'sell',
                    'price': float(sig.get('signal_value', 0)),
                    'text': 'B' if sig.get('signal_level') in ('BUY', 'BULLISH', 'STRONG_BUY') else 'S',
                    'color': '#22C55E' if sig.get('signal_level') in ('BUY', 'BULLISH', 'STRONG_BUY') else '#EF4444',
                })
            return jsonify({'success': True, 'data': signal_markers})
        
        # 缓存未命中，回退实时计算（兼容已有逻辑）
        ...保留原有实时计算代码...
```

### Task A3: factor_cache 消费打通

**Files:**
- Modify: `backend/app/services/signal_computation_service.py`（`_compute_factor_score` 方法）

**Issue:** `_compute_factor_score()` 实时计算因子值，应优先读取 `factor_cache`。

**Fix:** 在 `_compute_factor_score()` 中先查 `data_manager.get_cached_factors(ts_code)`，命中则直接使用。

- [ ] **Step 1: 修改 `_compute_factor_score()`**
添加因子缓存读取逻辑，仅缺失因子才实时计算。

### Task A4: indicator_ide.py 移除Mock回退

**Files:**
- Modify: `backend/app/routes/indicator_ide.py`

**Issue:** 代码中使用 `np.random.uniform` 生成随机数据作为降级方案，违反§13规则。

**Fix:** 移除 Mock 回退，返回空数据 + 错误信息。

### Task A5: reports.py 移除Mock回退

**Files:**
- Modify: `backend/app/routes/reports.py`

**Issue:** `_mock_backtest_result` 使用 `random.uniform` 模拟回测结果。

**Fix:** 移除该函数，改为返回错误信息。

### Task A6: DataManager._get_minute_data() 修复

**Files:**
- Modify: `backend/app/data/__init__.py:399-454`

**Issue:** mootdx TCP 返回空时仅有 Tushare 降级（付费产品），缺少 AKShare 回退。

**Fix:** 在 Tushare 降级后增加 AKShare 回退。

## 批次B：自选股分钟数据补采

### Task B1: 自选股5min历史采集函数

**Files:**
- Create: `backend/app/data/minute_backfill.py`
- Modify: `backend/data_daemon.py`

**Description:** 创建独立模块，日终读取自选股列表，逐只调用 mootdx `bars(freq=2)` 采集5min数据写入 `minute_kline_cache`。

### Task B2: 自选股1min历史采集

**Files:**
- Add to: `backend/app/data/minute_backfill.py`

**Description:** 利用 mootdx `minutes(YYYYMMDD)` 逐日获取自选股历史1min数据。

### Task B3: 聚合管道

**Files:**
- Add to: `backend/app/data/minute_backfill.py`

**Description:** 5min数据写入后自动聚合为15m/30m/60m 写入 ECM。

### Task B4: 注册到 data_daemon 日终同步

**Files:**
- Modify: `backend/data_daemon.py`

**Description:** 在 `run_daily_sync()` 中添加线程调用分钟数据采集。

## 验证

- make lint 通过
- make typecheck 通过
- `chart.py` 日志显示使用宽表预计算指标
- `_get_minute_data('000001.SZ', '60m')` 返回60分钟K线
