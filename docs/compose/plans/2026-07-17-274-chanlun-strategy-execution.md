# 274号方案：缠论策略量化精度提升 —— 实施执行计划

> **For agentic workers:** 本计划按274号方案§三的8个批次逐一展开，每个批次内有独立的步骤链。步骤使用 `- [ ] ` 语法跟踪。实施者按批次顺序执行，每个批次完成后再进入下一个。

**目标:** 修正缠论策略中10项偏差，包括中枢无限扩张、线段划分精度不足、特征序列缺失、多级别联立缺失等，使中枢区间恢复正常、线段划分精确、支持分钟级多级别分析。

**架构:** 分8个批次(P-1 → 0 → 1 → 2 → 3 → 4 → 5 → 6)串行实施。P-1为数据基础设施层，批次P-1完成后才能开始批次0和1，批次0+1完成后才能开始批次2，以此类推。

**Tech Stack:** Python 3.11, Flask, SQLite WAL, mootdx(TDX TCP), pandas, numpy, pytest

---

## 文件影响总图

```
批次P-1 ─── 全局数据体系
  backend/app/data/__init__.py               DataManager (核心修改点)
  backend/app/routes/minute_data.py          前端分钟API
  backend/app/routes/chart.py                K线图API
  backend/app/services/benchmark_service.py  指数数据

批次0 ─── 线段层
  backend/app/engine/framework/chanlun_strategy.py  SegmentAnalyzer

批次1 ─── 数据层
  backend/app/services/signal_computation_service.py  复权/缠论入口
  backend/app/data/__init__.py                         复权参数
  backend/app/engine/framework/chanlun_strategy.py     KLineMerger/StrokeBuilder

批次2 ─── 结构层
  backend/app/engine/framework/chanlun_strategy.py     ZhongshuAnalyzer
  backend/app/services/signal_computation_service.py   输出层

批次3 ─── 工程层-长线
  backend/app/services/signal_computation_service.py   多级别联立调用
  backend/app/engine/framework/chanlun_strategy.py     T8验证器

批次4 ─── 信号层
  backend/app/engine/framework/chanlun_strategy.py     DivergenceDetector

批次5 ─── 中线扩展（E1第二阶段）
  backend/app/services/signal_computation_service.py   中线分析
  backend/app/engine/framework/chanlun_config.py       笔参数

批次6 ─── 短线扩展（E1第三阶段）
  backend/app/services/signal_computation_service.py   短线分析
  backend/app/engine/framework/chanlun_config.py       笔参数
```

---

## Global Constraints

- 不允许任何策略或前端代码直接调用 mootdx/Tushare/AKShare。所有K线数据统一走 `DataManager.get_kline_data()`
- 数据获取流程固定：ECM缓存优先 → 未命中则从数据源获取 → 写入ECM持久化 → 返回
- `minute_kline_cache` 表的 `freq` 字段用于区分不同频率，不得混用
- 60分钟/30分钟K线从5分钟数据聚合（复用 `MinuteDataManager._resample_minute()`），不直接从mootdx取
- 所有修改需通过 `python3 -m py_compile` 语法检查
- 每个批次完成后运行 `python3 backend/run.py --port 5001` 进行端到端验证（curl + python3检查关键字段）

---

## 批次P-1: 数据架构统一——全局数据体系

**前置条件:** 无

**说明:** 将分钟级K线数据通路从 Tushare 直连和 MinuteDataManager 独立通道收归到 DataManager 统一管理，实现 cache-on-demand 按需缓存。

**文件:**
- 修改: `backend/app/data/__init__.py`
- 修改: `backend/app/routes/minute_data.py`
- 修改: `backend/app/routes/chart.py`
- 修改: `backend/app/services/benchmark_service.py`

### P-1a: DataManager._get_mootdx_bars()

**Covers:** 274 §E1（数据源前提）

**文件:** `backend/app/data/__init__.py`
- 新增 `_get_mootdx_bars()` 私有方法（约25行）

**接口:**
- 输入: `ts_code: str, freq: int (default 9=日线), start: int (default 0), offset: int (default 800)`
- 返回: `pd.DataFrame` 统一列名 `(ts_code, trade_date/trade_time, open, high, low, close, vol, amount)`

- [ ] **Step 1: 编写测试函数**

```python
# 在 tests/test_274_implementation.py 中新增测试类
class TestBatchP1_MootdxBars:
    """P-1a: _get_mootdx_bars"""
    
    def test_daily_bars(self):
        """验证日线数据返回格式"""
        from app.data import DataManager
        dm = DataManager()
        df = dm._get_mootdx_bars('301042.SZ', freq=9)
        assert df is not None and not df.empty
        required = {'ts_code', 'open', 'high', 'low', 'close', 'vol'}
        assert required.issubset(set(df.columns))
        assert 'trade_date' in df.columns or 'trade_time' in df.columns
    
    def test_5min_bars(self):
        """验证5分钟数据返回格式"""
        from app.data import DataManager
        dm = DataManager()
        df = dm._get_mootdx_bars('301042.SZ', freq=2)
        assert df is not None and not df.empty
        assert 'trade_time' in df.columns  # 分钟线用 trade_time
```

- [ ] **Step 2: 写实现代码**

在 `backend/app/data/__init__.py` 中 `DataManager` 类内新增：

```python
def _get_mootdx_bars(self, ts_code: str, freq: int = 9,
                     start: int = 0, offset: int = 800) -> pd.DataFrame:
    """从 mootdx(TDX TCP) 获取K线数据，统一返回标准化 DataFrame
    
    Args:
        ts_code: 股票代码（含市场后缀，如 301042.SZ）
        freq: TDX频率码 9=日线 5=周线 2=5分钟 1=1分钟
        start: 起始偏移（用于分页）
        offset: 返回行数上限（最大800）
    
    Returns:
        标准化 DataFrame，列: ts_code, trade_date/trade_time, open, high, low, close, vol, amount
    """
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        raw = client.bars(symbol=symbol, frequency=freq, start=start, offset=offset)
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(columns={'volume': 'vol'})
        df['ts_code'] = ts_code
        # 日线/周线有 'date' 列，分钟线有 'datetime' 列
        if 'date' in df.columns:
            df = df.rename(columns={'date': 'trade_date'})
        elif 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'trade_time'})
            if 'trade_date' not in df.columns and 'year' in df.columns:
                # 从 year/month/day 构建 trade_date
                df['trade_date'] = pd.to_datetime(
                    df[['year', 'month', 'day']].astype(int).astype(str).agg('-'.join, axis=1)
                )
        cols = {'ts_code', 'open', 'high', 'low', 'close', 'vol', 'amount'}
        cols_exist = [c for c in cols if c in df.columns]
        return df[cols_exist]
    except Exception as e:
        logger.warning(f"_get_mootdx_bars({ts_code}) 失败: {e}")
        return pd.DataFrame()
```

- [ ] **Step 3: 编译检查**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/data/__init__.py
```

- [ ] **Step 4: 运行测试**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python3 -m pytest tests/test_274_implementation.py::TestBatchP1_MootdxBars -v --tb=short
```

预期: PASS


### P-1b: DataManager._get_minute_data() 重构为 cache-on-demand

**Covers:** 274 §P-1b

**文件:** `backend/app/data/__init__.py`
- 修改 `_get_minute_data()` 方法（约40行）

**接口:**
- 输入: `ts_code, freq ('1m'/'5m'/'15m'/'30m'/'60m'), start_date, end_date`
- 返回: `pd.DataFrame`
- 三路径: ECM缓存 → mootdx bars + 聚合 → Tushare(备选)

- [ ] **Step 1: 写测试**

```python
class TestBatchP1_MinuteCache:
    """P-1b: 分钟级cache-on-demand"""
    
    def test_5min_cache_miss_then_hit(self):
        """首次调取未命中→从mootdx获取→写入ECM→第二次命中"""
        from app.data import DataManager
        dm = DataManager()
        # 第一次调用（应该未命中，走mootdx）
        df1 = dm._get_minute_data('301042.SZ', '5m')
        assert df1 is not None and not df1.empty
        # 第二次调用（应该命中缓存）
        df2 = dm._get_minute_data('301042.SZ', '5m')
        assert df2 is not None and not df2.empty
```

- [ ] **Step 2: 写实现代码**

```python
def _get_minute_data(self, ts_code, freq, start_date=None, end_date=None):
    """获取分钟线数据 — ECM缓存优先的 cache-on-demand"""
    # freq 参数映射: '5m' → '5min', '60m' → '60min'
    freq_map = {'1m': '1min', '5m': '5min', '15m': '15min', '30m': '30min', '60m': '60min'}
    ecm_freq = freq_map.get(freq, freq.replace('m', 'min'))
    
    # 第一步: 查 ECM 缓存
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        df_cache = ecm.get_cached_minute_kline(ts_code, freq=ecm_freq)
        if df_cache is not None and not df_cache.empty:
            return df_cache
    except Exception:
        pass
    
    # 第二步: 从 mootdx bars(freq=2) 获取5min数据
    freq_num = 2  # 5分钟
    # 如果是1分钟，直接从 minutes() API 获取
    if ecm_freq == '1min':
        return self._get_mootdx_minutes(ts_code)  # 见后续步骤
    # 5min: 直接从 bars() 获取
    if ecm_freq == '5min':
        df_5min = self._get_mootdx_bars(ts_code, freq=2)
        if not df_5min.empty:
            # 写入ECM并返回
            self._cache_minute_to_ecm(df_5min, ts_code, '5min')
            return df_5min
    # 15min: 从5min聚合
    if ecm_freq in ('15min', '30min', '60min'):
        df_5min = self._get_mootdx_bars(ts_code, freq=2)
        if not df_5min.empty:
            # 聚合为目标频率
            target_min = int(ecm_freq.replace('min', ''))
            from app.data.minute_data_manager import MinuteDataManager
            mm = MinuteDataManager()
            records = df_5min.to_dict('records')
            aggregated = mm._resample_minute(records, '5min', ecm_freq)
            if aggregated:
                df_agg = pd.DataFrame(aggregated)
                df_agg['ts_code'] = ts_code
                self._cache_minute_to_ecm(df_agg, ts_code, ecm_freq)
                return df_agg
    
    # 第三步: Tushare 降级（备选）
    try:
        data = self.tushare.get_minute_data(ts_code, freq, start_date, end_date)
        if data:
            return pd.DataFrame(data)
    except Exception:
        pass
    
    return pd.DataFrame()

def _cache_minute_to_ecm(self, df, ts_code, freq):
    """将分钟K线写入 ECM minute_kline_cache 持久化"""
    if df.empty:
        return
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        df_copy = df.copy()
        df_copy['ts_code'] = ts_code
        df_copy['freq'] = freq
        if 'trade_time' not in df_copy.columns and 'trade_date' in df_copy.columns:
            df_copy['trade_time'] = df_copy['trade_date']
        ecm.cache_minute_kline(df_copy)
    except Exception as e:
        logger.debug(f"缓存分钟K线失败 ({ts_code}/{freq}): {e}")

def _get_mootdx_minutes(self, ts_code):
    """从 mootdx minutes() 获取1分钟数据（单日）"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        today = datetime.now().strftime('%Y%m%d')
        raw = client.minutes(symbol=symbol, date=today)
        if raw is not None and not raw.empty:
            rows = []
            for _, r in raw.iterrows():
                rows.append({'trade_time': today[:4]+'-'+today[4:6]+'-'+today[6:8]+' 09:30:00',
                           'open': float(r.get('price', 0)), 'high': float(r.get('price', 0)),
                           'low': float(r.get('price', 0)), 'close': float(r.get('price', 0)),
                           'vol': int(r.get('vol', 0))})
            return pd.DataFrame(rows)
    except Exception as e:
        logger.debug(f"_get_mootdx_minutes({ts_code}) 失败: {e}")
    return pd.DataFrame()
```

- [ ] **Step 3: 编译检查**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/data/__init__.py
```

- [ ] **Step 4: 测试**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python3 -m pytest tests/test_274_implementation.py::TestBatchP1_MinuteCache -v --tb=short
```


### P-1c: 前端分钟API路由到 DataManager

**Covers:** 274 §P-1c

**文件:** `backend/app/routes/minute_data.py`
- 替换 `MinuteDataManager` 直连为 `DataManager.get_kline_data()`

- [ ] **Step 1: 修改路由**

```python
# routes/minute_data.py 中修改 get_minute_kline 函数
@minute_data_bp.route('/api/minute/<ts_code>', methods=['GET'])
@handle_exceptions
def get_minute_kline(ts_code):
    freq = request.args.get('freq', '15min')
    # period 格式映射: 15min → 15m
    period_map = {'1min': '1m', '5min': '5m', '15min': '15m', '30min': '30m', '60min': '60m'}
    period = period_map.get(freq, '15m')
    try:
        from app.data import DataManager
        dm = DataManager()
        df = dm.get_kline_data(ts_code, period=period)
        if df is not None and not df.empty:
            records = df.to_dict('records')
            return jsonify({'code': 0, 'data': records, 'total': len(records), 'source': 'cache'})
        return jsonify({'code': 0, 'data': [], 'total': 0, 'source': 'empty'})
    except Exception as e:
        logger.error(f"分钟数据获取失败: {e}")
        return jsonify({'code': -1, 'msg': str(e), 'data': []})
```

- [ ] **Step 2: 编译+测试**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/routes/minute_data.py
```


### P-1d: K线图路由支持分钟级按需采集

**Covers:** 274 §P-1d

**文件:** `backend/app/routes/chart.py`
- 修改 `_get_kline_data()` 中的分钟K线路径

- [ ] **Step 1: 修改 _get_kline_data**

```python
def _get_kline_data(data_manager, ts_code, limit=200, period='D'):
    import pandas as pd
    # 分钟线：通过 DataManager 统一获取（触发 cache-on-demand）
    if period in ['1m', '5m', '15m', '30m', '60m']:
        try:
            kline_data = data_manager.get_kline_data(ts_code, period=period)
            if kline_data is not None and not kline_data.empty:
                return kline_data, 'minute'
        except Exception as e:
            logger.warning(f"分钟K线获取失败 ({ts_code}/{period}): {e}")
        # 降级：走 DataManager 日线（此时 ECM minute_kline_cache 已有可能缓存上一级的尝试数据）
        kline_data = data_manager.get_kline_data(ts_code, period='D')
        if kline_data is not None and not kline_data.empty:
            return kline_data, None
        return pd.DataFrame(), None
    # 非分钟K线：走原有逻辑
    kline_data = data_manager.get_kline_data(ts_code, period=period)
    ...
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/routes/chart.py
```


### P-1e: 周线ECM缓存

**Covers:** 274 §P-1e

**文件:** `backend/app/data/__init__.py`
- 修改 `_get_weekly_data()`（约15行）

- [ ] **Step 1: 修改 _get_weekly_data**

```python
def _get_weekly_data(self, ts_code, start_date=None, end_date=None):
    """获取周线数据，ECM缓存优先"""
    # 查ECM缓存（用 minute_kline_cache freq='W' 存储）
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        df_cached = ecm.get_cached_minute_kline(ts_code, freq='W')
        if df_cached is not None and not df_cached.empty:
            return df_cached
    except Exception:
        pass
    # 从 mootdx bars(freq=5) 获取
    df = self._get_mootdx_bars(ts_code, freq=5)
    if not df.empty:
        df['freq'] = 'W'
        self._cache_minute_to_ecm(df, ts_code, 'W')
        return df
    # 降级: 从日线聚合（原逻辑）
    daily_data = self.get_cached_daily_data(ts_code, start_date, end_date)
    if not daily_data.empty:
        return self._aggregate_daily_to_weekly(daily_data)
    return pd.DataFrame()
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/data/__init__.py
```


### P-1f: 60分钟/30分钟聚合链路

**Covers:** 274 §P-1f

**文件:** `backend/app/data/__init__.py`
- 新增 `_get_aggregated_kline()`（约30行）

- [ ] **Step 1: 写实现**

```python
def _get_aggregated_kline(self, ts_code, target_freq):
    """从5分钟数据聚合为目标频率（60min/30min）并缓存
    
    Args:
        ts_code: 股票代码
        target_freq: '30min' 或 '60min'
    """
    ecm_freq = target_freq
    # 查ECM缓存
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        df_cached = ecm.get_cached_minute_kline(ts_code, freq=ecm_freq)
        if df_cached is not None and not df_cached.empty:
            return df_cached
    except Exception:
        pass
    # 获取5min原始数据
    df_5min = self._get_mootdx_bars(ts_code, freq=2)
    if df_5min.empty:
        return pd.DataFrame()
    # 聚合
    from app.data.minute_data_manager import MinuteDataManager
    mm = MinuteDataManager()
    records = df_5min.to_dict('records')
    aggregated = mm._resample_minute(records, '5min', ecm_freq)
    if not aggregated:
        return pd.DataFrame()
    df_agg = pd.DataFrame(aggregated)
    df_agg['ts_code'] = ts_code
    df_agg['freq'] = ecm_freq
    # 缓存
    self._cache_minute_to_ecm(df_agg, ts_code, ecm_freq)
    return df_agg
```

- [ ] **Step 2: 在 get_kline_data 中集成**

```python
def get_kline_data(self, ts_code, period='D', start_date=None, end_date=None):
    if period in ('60m', '30m'):
        freq_map = {'60m': '60min', '30m': '30min'}
        return self._get_aggregated_kline(ts_code, freq_map[period])
    if period == '5m':
        return self._get_minute_data(ts_code, '5m', start_date, end_date)
    if period == 'W':
        return self._get_weekly_data(ts_code, start_date, end_date)
    # ... 原有逻辑
```

- [ ] **Step 3: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/data/__init__.py
```


### P-1g: BenchmarkService mootdx回退

**Covers:** 274 §P-1g

**文件:** `backend/app/services/benchmark_service.py`

- [ ] **Step 1: 增加 mootdx index_bars 回退**

```python
def get_index_daily(self, ts_code='000300.SH', start_date=None, end_date=None):
    """获取指数日线数据（增加 mootdx index_bars 回退）"""
    # ... 原有 Tushare 路径 ...
    # 若 Tushare 失败或无数据:
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '')
        df = client.index_bars(symbol=symbol, frequency=9, start=0, offset=800)
        if df is not None and not df.empty:
            import pandas as pd
            result = pd.DataFrame()
            result['trade_date'] = pd.to_datetime(
                df[['year', 'month', 'day']].astype(str).agg('-'.join, axis=1)
            )
            result['close'] = df['close'].astype(float)
            result['open'] = df['open'].astype(float)
            result['high'] = df['high'].astype(float)
            result['low'] = df['low'].astype(float)
            result['vol'] = df['vol'].astype(float)
            result['amount'] = df['amount'].astype(float)
            return result.sort_values('trade_date').reset_index(drop=True)
    except Exception as e:
        logger.debug(f"指数数据 mootdx 回退失败: {e}")
    return pd.DataFrame()
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/services/benchmark_service.py
```


### P-1 端到端验证

- [ ] 启动服务器并验证

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python3 run.py --port 5001 &> /tmp/p1_test.log &
sleep 8
# 验证60分钟数据是否成功 cache-on-demand
curl -s --max-time 15 "http://localhost:5001/api/v3/strategy/analyze" -H 'Content-Type: application/json' -d '{"ts_code":"301042.SZ"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('deepseek_text 有' if d['data']['dimensions']['chanlun'].get('deepseek_text') else '无')"
# 验证K线图多周期
curl -s --max-time 15 "http://localhost:5001/kline/301042.SZ?period=60m" | python3 -c "import sys,json; d=json.load(sys.stdin); print('60min K线' if d.get('data') and len(d['data'])>0 else '失败')"
# 验证grep无mootdx直连
grep -r "mootdx" backend/app/services/ backend/app/routes/ || echo "✅ 无直接mootdx引用"
kill %1
```

---

## 批次0: 线段层修复

**前置条件:** 无（与P-1无代码冲突可以并行）

**文件:** `backend/app/engine/framework/chanlun_strategy.py`
- `_is_valid_segment` + `SegmentAnalyzer` 修改

### 0a: _is_valid_segment 增加终止条件

- [ ] **Step 1: 修改函数**

```python
def _is_valid_segment(self, s1: Stroke, s2: Stroke, s3: Stroke) -> bool:
    """判断三笔是否构成线段"""
    if s1.direction == s2.direction or s2.direction == s3.direction:
        return False
    if not self._has_overlap(s1, s2, s3):
        return False
    # 新增：终止条件检查
    if s1.direction == 'up':
        # 向上线段：第三笔终点 > 第一笔起点
        return s3.end_price > s1.start_price
    else:
        # 向下线段：第三笔终点 < 第一笔起点
        return s3.end_price < s1.start_price
```

- [ ] **Step 2: 编译+验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```


### 0b: 特征序列包含处理

- [ ] **Step 1: 在 SegmentAnalyzer 中新增特征序列合并方法**

```python
def _merge_feature_sequence(self, strokes: List[Stroke], direction: str) -> List[Stroke]:
    """特征序列元素包含处理（与K线包含处理相同的逻辑）
    
    对特征序列元素（上升段中的下跌笔/下降段中的上涨笔）
    按包含关系进行合并，直到不再包含。
    
    Args:
        strokes: 特征序列元素列表
        direction: 线段方向 'up'/'down'
    Returns:
        合并后的特征序列元素列表
    """
    if len(strokes) < 2:
        return strokes
    
    result = [strokes[0]]
    for i in range(1, len(strokes)):
        prev = result[-1]
        curr = strokes[i]
        
        # 检查包含关系
        curr_range = { 'low': min(curr.start_price, curr.end_price),
                      'high': max(curr.start_price, curr.end_price) }
        prev_range = { 'low': min(prev.start_price, prev.end_price),
                      'high': max(prev.start_price, prev.end_price) }
        
        if curr_range['low'] >= prev_range['low'] and curr_range['high'] <= prev_range['high']:
            # curr 被 prev 包含：合并
            # 向上段特征序列(下跌笔)：取低低
            new_low = min(curr_range['low'], prev_range['low'])
            new_high = min(curr_range['high'], prev_range['high'])
            # 替换 prev 为合并结果
            merged = Stroke(
                start_idx=prev.start_idx, end_idx=curr.end_idx,
                start_price=prev.start_price, end_price=curr.end_price,
                start_date=prev.start_date, end_date=curr.end_date,
                direction=prev.direction,
                low=new_low, high=new_high
            )
            result[-1] = merged
        elif prev_range['low'] >= curr_range['low'] and prev_range['high'] <= curr_range['high']:
            # prev 被 curr 包含：prev被包含在curr中，取curr
            new_low = min(curr_range['low'], prev_range['low'])
            new_high = min(curr_range['high'], prev_range['high'])
            merged = Stroke(
                start_idx=prev.start_idx, end_idx=curr.end_idx,
                start_price=prev.start_price, end_price=curr.end_price,
                start_date=prev.start_date, end_date=curr.end_date,
                direction=prev.direction,
                low=new_low, high=new_high
            )
            result[-1] = merged
        else:
            result.append(curr)
    
    return result
```

- [ ] **Step 2: 在 build() 的线段延续循环中调用**

```python
# 在 build() 方法中，line 688-711 的特征序列终结判定之前，
# 对 current_strokes 中的反向笔做特征序列包含处理：
if seg_direction == 'up':
    # 上升段：提取下跌笔作为特征序列
    feature_elements = [s for s in current_strokes if s.direction == 'down']
    merged = self._merge_feature_sequence(feature_elements, seg_direction)
    # 检查合并后的特征序列是否形成顶分型破坏
    # ... 代码 ...
```

- [ ] **Step 3: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```


### 0c: 线段终结改用特征序列分型

- [ ] **Step 1: 修改终结判定**

将 `def build()` 中的 `if next_stroke.end_price < ref_low: break` 替换为：

```python
# 上升段：合并后的特征序列（下跌笔）形成顶分型时，线段终结
if seg_direction == 'up' and next_stroke.direction == 'down':
    feature_merged = self._merge_feature_sequence(
        [s for s in current_strokes if s.direction == 'down'] + [next_stroke],
        seg_direction
    )
    if len(feature_merged) >= 3:
        # 检查最近3个特征元素是否形成顶分型
        f1, f2, f3 = feature_merged[-3], feature_merged[-2], feature_merged[-1]
        f1_high = max(f1.start_price, f1.end_price)
        f2_high = max(f2.start_price, f2.end_price)
        f3_high = max(f3.start_price, f3.end_price)
        f1_low = min(f1.start_price, f1.end_price)
        f2_low = min(f2.start_price, f2.end_price)
        f3_low = min(f3.start_price, f3.end_price)
        # 顶分型：中间元素 high > 两侧 high，中间 low > 两侧 low
        if f2_high > f1_high and f2_high > f3_high and f2_low > f1_low and f2_low > f3_low:
            break
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```

---

## 批次1: 数据层修复

**前置条件:** 无（可与P-1/0并行）

### 1a: 分析管道改用后复权

- [ ] **Step 1: DataManager 增加后复权参数**

```python
def get_cached_daily_data(self, ts_code, start_date=None, end_date=None, adj='hfq'):
    """获取日线数据（支持复权类型: hfq后复权 / qfq前复权 / None未复权）"""
    df = self.cache.get_cached_daily(ts_code, start_date, end_date)
    if df.empty or adj is None:
        return df
    if adj == 'hfq':
        # 用 adj_factor_cache 做后复权
        df_adj = self.cache.get_cached_adj_factor(ts_code)
        if df_adj is not None and not df_adj.empty:
            df = df.merge(df_adj[['trade_date', 'adj_factor']], on='trade_date', how='left')
            df['adj_factor'] = df['adj_factor'].fillna(method='ffill')
            base_adj = df['adj_factor'].iloc[-1]  # 以最新复权因子为基准
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col] * (df['adj_factor'] / base_adj)
            df['vol'] = df['vol'] / (df['adj_factor'] / base_adj)  # 复权调整成交量
            df.drop(columns=['adj_factor'], inplace=True)
    return df
```

- [ ] **Step 2: SignalComputationService 传递参数**

```python
def compute_for_stock(self, ts_code, limit=5):
    # ...
    df = self.data_manager.get_cached_daily_data(ts_code, adj='hfq')  # ← 增加 adj='hfq'
    # ...
```

- [ ] **Step 3: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/data/__init__.py backend/app/services/signal_computation_service.py
```


### 1b: 涨跌停K线过滤

- [ ] **Step 1: StrokeBuilder 增加涨跌停检测**

```python
def _is_limit_up(self, kline: KLine, closes_series) -> bool:
    """检查是否为涨停K线"""
    if kline.close == kline.high:  # 收盘在最高价（涨停）
        avg_vol_5 = sum(closes_series[-5:]) / 5 if len(closes_series) >= 5 else 0
        return kline.volume < avg_vol_5 * 0.3  # 成交量低于5日均量30%
    return False

def _is_limit_down(self, kline: KLine, closes_series) -> bool:
    """检查是否为跌停K线"""
    if kline.close == kline.low:  # 收盘在最低价（跌停）
        avg_vol_5 = sum(closes_series[-5:]) / 5 if len(closes_series) >= 5 else 0
        return kline.volume < avg_vol_5 * 0.3
    return False
```

- [ ] **Step 2: 在 build() 的分形配对中跳过涨跌停**

在 `build()` 的 while 循环中，对每个 candidate 检查：

```python
if self._is_limit_up(f2.kline, ...) or self._is_limit_down(f2.kline, ...):
    j += 1
    continue  # 跳过涨跌停K线
```

- [ ] **Step 3: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```


### 1c: K线包含处理递归化

- [ ] **Step 1: 修改 KLineMerger.merge()**

```python
@staticmethod
def merge(klines: List[KLine]) -> List[KLine]:
    """处理K线包含关系（递归至无包含，上限10次）"""
    if len(klines) < 2:
        return klines
    
    max_iter = 10
    for _ in range(max_iter):
        merged = KLineMerger._merge_once(klines)
        if len(merged) == len(klines):
            return merged  # 不再变化，完成
        klines = merged
    return klines  # 达到上限后返回

@staticmethod
def _merge_once(klines: List[KLine]) -> List[KLine]:
    """单次包含合并"""
    if len(klines) < 2:
        return klines
    result = [klines[0]]
    direction = None
    for i in range(1, len(klines)):
        current = klines[i]
        prev = result[-1]
        if KLineMerger.is_contained(prev, current):
            if direction is not None:
                # 合并
                if direction == 'up':
                    new_high = max(prev.high, current.high)
                    new_low = max(prev.low, current.low)
                else:
                    new_high = min(prev.high, current.high)
                    new_low = min(prev.low, current.low)
                merged = KLine(idx=prev.idx, open=prev.open, high=new_high,
                              low=new_low, close=current.close, date=current.date,
                              volume=prev.volume + current.volume)
                result[-1] = merged
        else:
            if direction is None:
                direction = 'up' if current.high > prev.high else 'down'
            result.append(current)
    return result
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```

---

## 批次2: 结构层修复

**前置条件:** 批次0 + 批次1

### 2a: 移除 _evolve_zhongshu 的 'expand' 分支

- [ ] **Step 1: 修改 _evolve_zhongshu**

```python
@staticmethod
def _evolve_zhongshu(zs: Zhongshu, seg: Segment) -> str:
    """判断中枢演化方向。
    
    Returns:
        'extend' → 线段完全在中枢区间内或部分超出（区间不变）
        'detach' → 完全不重叠，中枢破坏
    """
    seg_r = seg.range
    # 完全在区间内或部分超出 → 延伸（区间不变）
    if seg_r['low'] <= zs.high and seg_r['high'] >= zs.low:
        return 'extend'
    # 完全不重叠 → 中枢破坏
    return 'detach'
```

- [ ] **Step 2: 在 _evolve_pending 中移除 expand 处理**

```python
# 原 expand 分支(line 891)移除，expand_zhongshu 方法保留但不从此处调用
# 只保留 extend 和 detach:
if evolution == 'extend':
    zs.end_idx = seg.end_idx
    zs.end_date = seg.end_date
    if zs.segments is not None:
        zs.segments = zs.segments + [seg]
    j += 1
elif evolution == 'detach':
    # ... 原有中枢破坏逻辑 ...
```

- [ ] **Step 3: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/engine/framework/chanlun_strategy.py
```


### 2b: 输出层使用子中枢

- [ ] **Step 1: 修改 _compute_chanlun_signal**

在 `signal_computation_service.py` 中，`latest_zhongshu` 获取逻辑后增加：

```python
# 当最新中枢为 expanded 时，从 sub_zhongshu_list 取最近的标准中枢
if latest_zhongshu and latest_zhongshu.type == 'expanded':
    sub_list = latest_zhongshu.sub_zhongshu_list
    if sub_list:
        # 取最近一个标准中枢（列表中最后一个）
        normal_zs = [zs for zs in sub_list if zs.type == 'normal']
        if normal_zs:
            latest_zhongshu = normal_zs[-1]
```

- [ ] **Step 2: 编译**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && .venv/bin/python3 -m py_compile backend/app/services/signal_computation_service.py
```


### 2c: near_levels_filtered 基准切换

在 `_build_filtered_levels`（`chanlun_strategy.py:109`）中，当 zhongshu 为 expanded 时，从子中枢列表中提取：

```python
def _build_filtered_levels(zhongshu_list, latest_close):
    # ... 原有逻辑，但是输入 zhongshu_list 过滤 expanded 中枢：
    refined = []
    for zs in zhongshu_list:
        if zs.type == 'expanded' and zs.sub_zhongshu_list:
            # 展开为子中枢
            for sub_zs in zs.sub_zhongshu_list:
                refined.append(sub_zs)
        else:
            refined.append(zs)
    # 对 refined 继续执行原有过滤逻辑
```

---

## 批次3: 工程层接入——长线先行

**前置条件:** P-1 + 批次0 + 批次1 + 批次2

- [ ] **3a: SignalComputationService 传入周线+日线+60分钟数据**

```python
# 在 _compute_chanlun_signal 中获取三个级别数据
daily_df = self.data_manager.get_kline_data(ts_code, period='D')
weekly_df = self.data_manager.get_kline_data(ts_code, period='W')
hourly_df = self.data_manager.get_kline_data(ts_code, period='60m')

df_dict = {'daily': daily_df, 'weekly': weekly_df, 'hourly': hourly_df}
analyzer = MultiLevelChanlunAnalyzer()
result = analyzer.analyze(df_dict)
```

- [ ] **3b: 调用 MultiLevelChanlunAnalyzer**

调用已有的 `MultiLevelChanlunAnalyzer` 实现（`chanlun_multi_level.py`），传入三级别数据。

- [ ] **3c: status_recognition 增加 multi_level 字段**

在返回值中添加 `multi_level` 结构，包含各级别的方向/中枢/位置。

- [ ] **3d: T8 验证器从占位改为真实检查**

修改 `chanlun_strategy.py:2858` 中的 `_check_t8`，从占位改为对比周线/日线方向。

---

## 批次4: 信号层增强

**前置条件:** 批次2

- [ ] **4a: DivergenceDetector 增加力度比较法**

在 `DivergenceDetector` 中添加 `_check_strength_method()`，计算两段DIF高度比：

```python
def _check_strength_method(self, segment1, segment2, dif_values) -> bool:
    """力度比较法辅助验证"""
    h1 = abs(max(dif_values[segment1.start:segment1.end]) - 
             min(dif_values[segment1.start:segment1.end]))
    h2 = abs(max(dif_values[segment2.start:segment2.end]) -
             min(dif_values[segment2.start:segment2.end]))
    return h2 < h1 * 0.75
```

- [ ] **4b: 背驰输出增加 dual_confirmed 字段**

在 `Divergence` 中添加 `dual_confirmed` 字段，标记是否双方法同时确认。

---

## 批次5: 中线扩展

**前置条件:** 批次3

- 接入30分钟+5分钟K线数据
- 新增"中线分析"模式（背景=日线、决策=30分钟、执行=5分钟）
- 笔参数配置：30分钟用宽笔（min_klines=3）

---

## 批次6: 短线扩展

**前置条件:** 批次5

- 接入1分钟K线数据
- 新增"短线分析"模式（背景=30分钟、决策=5分钟、执行=1分钟）
- 笔参数配置：5分钟用宽笔（min_klines=3）+ 确认过滤
