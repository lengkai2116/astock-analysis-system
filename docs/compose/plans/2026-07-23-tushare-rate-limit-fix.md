# Tushare 限流根治方案

## 一、全量调用审计

### 可改为批量查询（消除 3 个 per-stock 循环）

| 函数 | 当前方式 | 优化方式 | 减少调用量 |
|------|---------|---------|-----------|
| `_batch_adj_factor` | `pro.adj_factor(ts_code=code)` 逐只×500 | `pro.adj_factor(trade_date=date)` 全市场 **1次** | 500次 → 1次 |
| `_batch_top10_holders` | `pro.top10_holders(ts_code=code)` 逐只×500 | `pro.top10_holders(end_date=date)` 全市场 **1次** | 500次 → 1次 |
| `_batch_stk_holder` | `pro.stk_holdernumber(ts_code=code)` 逐只×500 | `pro.stk_holdernumber(end_date=date)` 全市场 **1次** | 500次 → 1次 |

### 必须保留逐只（5 个函数）

| 函数 | 原因 |
|------|------|
| `_batch_fina_indicator` | `period` + `ts_code` 都必填 |
| `_batch_income_recent` | 必须传 `ts_code` |
| `_batch_balancesheet` | 必须传 `ts_code` |
| `_batch_cashflow` | 必须传 `ts_code` |
| `_batch_forecast` | 必须传 `ts_code` |

### 最大调用量估算（优化后）

```
日终同步: 8 次  (daily/daily_basic/moneyflow/stk_limit/index_daily/lhb/lhb_detail/concept)
财务后台: 5 次  (fina_indicator/income/balancesheet/cashflow/forecast) ← 已优化，无需逐只
指数回填: 28 次 × rate_limited ← 当前限流根源
补充数据: adj_factor(1次) + top10_holders(1次) + stk_holder(1次) = 3次 ← 优化后

总计: 8 + 5 + 28 + 3 = 44 次 API 调用 ← 远低于 500次/分钟 限制
```

## 二、实施内容

### 2.1 全局速率限制器

在 `data_daemon.py` 顶部新增一个通用 Tushare 调用包装器：

```python
# ── Tushare 全局速率限制 ──
import time as _time
_ts_last_call = 0.0
_TS_MIN_INTERVAL = 0.2  # 5次/秒

def _ts(pro_func, *args, **kwargs):
    """带速率限制的 Tushare API 调用（全局节流，防止误伤）"""
    global _ts_last_call
    elapsed = _time.time() - _ts_last_call
    if elapsed < _TS_MIN_INTERVAL:
        _time.sleep(_TS_MIN_INTERVAL - elapsed)
    _ts_last_call = _time.time()
    return pro_func(*args, **kwargs)
```

使用时：`df = _ts(pro.daily, trade_date=today)`

### 2.2 3 个逐只函数改为批量

`_batch_adj_factor`:
```python
def _batch_adj_factor() -> int:
    """全市场复权因子 — 批量按 trade_date（替代逐只）"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    raw = _ts(pro.adj_factor, trade_date=yesterday)
    if raw is None or raw.empty:
        return 0
    df = raw.copy()
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_adj_factor_data(df)
    return len(df)
```

### 2.3 逐只函数加节流

保留的 5 个逐只函数（`income`/`balancesheet`/`cashflow`/`forecast`/`fina_indicator`）在循环内加 `_ts()` 包装。

### 2.4 申万行业指数回填速率控制

当前 `for offset in range(60): for code in 28 indices: pro.index_daily(...)` 在 5 秒内发起 **1680 次**调用。

修改：在外层循环加 `time.sleep(0.5)`，将速率控制在 ~2 次/秒。

## 三、改动汇总

| 文件 | 改动 | 行数 |
|------|------|------|
| `data_daemon.py` | 新增 `_ts()` 全局速率限制器 | +5 |
| `data_daemon.py` | 所有 `pro.*()` → `_ts(pro.*)` 替换 | ~25处，各改1行 |
| `data_daemon.py` | `_batch_adj_factor` → 批量 by trade_date | 重写函数体 |
| `data_daemon.py` | `_batch_top10_holders` → 批量 by end_date | 重写函数体 |
| `data_daemon.py` | `_batch_stk_holder` → 批量 by end_date | 重写函数体 |
| `data_daemon.py` | 申万回填循环加 `time.sleep(0.5)` | +1行 |
