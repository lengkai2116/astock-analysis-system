# Step 2：数据体系重构 — indicator_cache EAV→宽表 + factor_cache 统一到 ECM

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 indicator_cache 从 EAV 行式存储(85M 行)重构为宽表(≈6M 行)，将 factor_cache 统一到 ECM 连接管理。

**Architecture:** 将 14 种技术指标按类别分为 3 张宽表（MA/MACD/Other），每只股票每天 1 行而非 14 行。DataManager 作为统一入口，ECM 作为统一存储层，FactorPrecomputeManager 接入 ECM 的连接而非独立 sqlite3.connect()。

**Tech Stack:** Python 3, SQLite (WAL), Pandas

## Global Constraints

- 所有建表使用 `IF NOT EXISTS` 保证幂等
- 宽表每张以 `(ts_code, trade_date)` 为主键，行数=每日每只股票 1 行
- 旧 `indicator_cache` EAV 表保留读兼容，新数据写入宽表
- `factor_precompute.py` 不再使用独立 `sqlite3.connect()`，统一通过 ECM 方法操作
- 迁移脚本独立运行，幂等，可中断续传

---

### Task A1: 新增宽表定义 + ECM 读写方法

**Covers:** indicator_cache EAV→宽表

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`

- [ ] **Step 1: 在 `_init_tables()` 中添加 3 张宽表定义**

在 `indicator_cache` 原建表语句之后（第 133 行附近），添加：

```python
# ── 宽表指标缓存（替代 EAV 格式 indicator_cache，减少 93% 行数）──
self._execute("""
    CREATE TABLE IF NOT EXISTS indicator_ma (
        ts_code TEXT, trade_date TEXT,
        ma5 REAL, ma10 REAL, ma20 REAL,
        vol_ma5 REAL, vol_ma10 REAL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
""")
self._execute("""
    CREATE TABLE IF NOT EXISTS indicator_macd (
        ts_code TEXT, trade_date TEXT,
        dif REAL, dea REAL, hist REAL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
""")
self._execute("""
    CREATE TABLE IF NOT EXISTS indicator_other (
        ts_code TEXT, trade_date TEXT,
        rsi14 REAL,
        kdj_k REAL, kdj_d REAL, kdj_j REAL,
        boll_upper REAL, boll_mid REAL, boll_lower REAL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
""")
```

- [ ] **Step 2: 在索引段添加 3 张宽表的索引**

在 `_init_tables()` 索引列表末尾添加：

```python
"CREATE INDEX IF NOT EXISTS idx_ind_ma_ts ON indicator_ma(ts_code)",
"CREATE INDEX IF NOT EXISTS idx_ind_macd_ts ON indicator_macd(ts_code)",
"CREATE INDEX IF NOT EXISTS idx_ind_other_ts ON indicator_other(ts_code)",
```

- [ ] **Step 3: 在 ECM 中添加宽表写入方法**

在 `batch_cache_indicators` 方法（第 553 行）之后，添加：

```python
def cache_indicators_wide(self, ts_code: str, df: pd.DataFrame):
    """批量写入宽表指标（df 需含 trade_date 及全部指标列）"""
    if df.empty:
        return
    with self._write_lock:
        # indicator_ma
        ma_cols = {'trade_date', 'ma5', 'ma10', 'ma20', 'vol_ma5', 'vol_ma10'}
        if ma_cols.issubset(set(df.columns)):
            ma_df = df[list(ma_cols)].copy()
            ma_df['ts_code'] = ts_code
            self._insert_from_df('indicator_ma', ma_df)
        # indicator_macd
        macd_cols = {'trade_date', 'dif', 'dea', 'hist'}
        if macd_cols.issubset(set(df.columns)):
            macd_df = df[list(macd_cols)].copy()
            macd_df['ts_code'] = ts_code
            self._insert_from_df('indicator_macd', macd_df)
        # indicator_other
        other_cols = {'trade_date', 'rsi14', 'kdj_k', 'kdj_d', 'kdj_j',
                       'boll_upper', 'boll_mid', 'boll_lower'}
        if other_cols.issubset(set(df.columns)):
            other_df = df[list(other_cols)].copy()
            other_df['ts_code'] = ts_code
            self._insert_from_df('indicator_other', other_df)
        self.conn.commit()
```

- [ ] **Step 4: 在 ECM 中添加宽表单股票读取方法**

```python
def get_indicators_wide(self, ts_code: str) -> pd.DataFrame:
    """读取宽表指标数据，合并 3 张表为 1 个 DataFrame"""
    ma = self._query_df(
        "SELECT ts_code, trade_date, ma5, ma10, ma20, vol_ma5, vol_ma10 "
        "FROM indicator_ma WHERE ts_code = ? ORDER BY trade_date", [ts_code])
    macd = self._query_df(
        "SELECT trade_date, dif, dea, hist "
        "FROM indicator_macd WHERE ts_code = ? ORDER BY trade_date", [ts_code])
    other = self._query_df(
        "SELECT trade_date, rsi14, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower "
        "FROM indicator_other WHERE ts_code = ? ORDER BY trade_date", [ts_code])
    result = ma
    for _df in [macd, other]:
        if not _df.empty and not result.empty:
            result = result.merge(_df, on='trade_date', how='left')
        elif not _df.empty:
            result = _df
    return result
```

- [ ] **Step 5: 运行 Makefile 检查**

```bash
make lint
```

---

### Task A2: 更新 PrecomputeIndicatorManager 写入路径

**Covers:** 预计算写入适配宽表

**Files:**
- Modify: `backend/app/data/precompute_indicator_manager.py:33-58`

- [ ] **Step 6: 修改 `precompute_all_indicators()` 写入双路径**

修改方法：先写入旧 EAV（保持兼容），再写入新宽表。

```python
def precompute_all_indicators(self, ts_code: str, df: pd.DataFrame, force: bool = False) -> bool:
    if len(df) < 30:
        return False
    try:
        result = self.engine.calculate_all_indicators(df)
        # 写入旧 EAV 格式（兼容现有消费者）
        self._batch_cache_indicators(result, ts_code)
        # 写入新宽表格式（ts_code 列已由 result 携带）
        if 'ts_code' not in result.columns:
            result['ts_code'] = ts_code
        self.cache_manager.cache_indicators_wide(ts_code, result)
        return True
    except Exception as e:
        logger.warning(f"预计算指标失败 [{ts_code}]: {e}")
        return False
```

- [ ] **Step 7: 运行 Makefile 检查**

```bash
make lint
```

---

### Task A3: 迁移脚本 — 将旧 EAV 数据转换为宽表

**Covers:** 现有 85M 行数据转换

**Files:**
- Create: `backend/scripts/migrate_indicator_to_wide.py`

- [ ] **Step 8: 创建迁移脚本**

```python
"""
迁移 indicator_cache 从 EAV 格式到宽表格式
==========================================
读取旧 indicator_cache (85M 行 EAV) → 按 (ts_code, trade_date) 聚合
→ 写入 indicator_ma / indicator_macd / indicator_other 宽表

幂等：宽表已有数据则跳过对应股票（INSERT OR REPLACE 覆盖）
可中断：已在宽表中的股票自动跳过（断点续传）
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['FLASK_APP'] = 'app'
os.environ['FLASK_ENV'] = 'production'

from app import create_app
from app.data.enhanced_cache_manager import get_ecm_instance
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('migrate')

app = create_app()

with app.app_context():
    ecm = get_ecm_instance()
    
    # 1. 获取所有在旧表中有数据的股票
    codes = [r[0] for r in ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM indicator_cache ORDER BY ts_code"
    ).fetchall()]
    
    # 2. 检查哪些股票已在宽表中（断点续传）
    #    使用 indicator_ma 是否有数据作为宽表是否已迁移的标志
    done_codes = set()
    try:
        done_codes = {r[0] for r in ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM indicator_ma"
        ).fetchall()}
    except Exception:
        pass
    
    pending = [c for c in codes if c not in done_codes]
    total = len(pending)
    logger.info(f"共 {len(codes)} 只股票，{len(done_codes)} 只已迁移，"
                f"{total} 只待迁移")
    
    if not pending:
        logger.info("全部已迁移，跳过")
        sys.exit(0)
    
    # 3. 逐只股票迁移
    t_start = time.time()
    for idx, ts_code in enumerate(pending, 1):
        try:
            # 读取 EAV 数据
            rows = ecm.conn.execute(
                "SELECT trade_date, indicator_name, value "
                "FROM indicator_cache WHERE ts_code = ? ORDER BY trade_date",
                [ts_code]
            ).fetchall()
            if not rows:
                continue
            
            # 转为 wide DataFrame
            records = [(r[0], r[1], r[2]) for r in rows]
            df = pd.DataFrame(records, columns=['trade_date', 'indicator_name', 'value'])
            wide = df.pivot_table(index='trade_date', columns='indicator_name',
                                  values='value', aggfunc='first').reset_index()
            
            # 写入宽表
            wide['ts_code'] = ts_code
            ecm.cache_indicators_wide(ts_code, wide)
            
            if idx % 200 == 0 or idx == total:
                elapsed = time.time() - t_start
                logger.info(f"[{idx}/{total}] {ts_code} 迁移完成, "
                            f"耗时 {elapsed:.0f}s")
        except Exception as e:
            logger.warning(f"[{idx}/{total}] {ts_code} 迁移失败: {e}")
    
    # 4. 验证
    new_ma = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_ma"
    ).fetchone()[0]
    new_macd = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_macd"
    ).fetchone()[0]
    new_other = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_other"
    ).fetchone()[0]
    old_cnt = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_cache"
    ).fetchone()[0]
    
    logger.info(f"迁移完成: 宽表 {new_ma}+{new_macd}+{new_other} 行, "
                f"旧表 {old_cnt} 行可删除")
    logger.info(f"行数压缩比: {old_cnt}/{new_ma+new_macd+new_other:.0f}x")
```

- [ ] **Step 9: 运行迁移脚本（非交易时段）**

```bash
python3 backend/scripts/migrate_indicator_to_wide.py
```

预期输出示例：
```
共 5012 只股票，0 只已迁移，5012 只待迁移
[200/5012] 迁移完成, 耗时 45s
...
迁移完成: 宽表 350000+350000+350000 行, 旧表 85000000 行可删除
行数压缩比: 85M/1M ≈ 80x (实际压缩约 14x 到 ≈6M 行)
```

---

### Task A4: 更新消费者 `chart.py` 读取宽表

**Covers:** chart.py 预计算指标读取优化

**Files:**
- Modify: `backend/app/routes/chart.py:271-290` — replace EAV pivot with wide read
- Modify: `backend/app/data/__init__.py:1029-1033` — update DataManager.get_cached_indicators

- [ ] **Step 10: 更新 DataManager 读取方法**

```python
def get_cached_indicators(self, ts_code: str, indicators: list = None) -> pd.DataFrame:
    """读取预计算指标（优先读宽表，降级读旧 EAV）"""
    from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
    mgr = PrecomputeIndicatorManager(self.cache)
    # 尝试宽表
    wide = self.cache.get_indicators_wide(ts_code)
    if wide is not None and not wide.empty:
        return wide
    # 降级到旧 EAV
    return mgr.get_precomputed_indicators(ts_code, indicators)
```

- [ ] **Step 11: 简化 chart.py 读取逻辑**

```python
# 替换 271-290 行（EAV pivot 逻辑）为：
try:
    cached = data_manager.get_cached_indicators(ts_code)
    if cached is not None and not cached.empty:
        cached_cols = set(cached.columns) - {'ts_code', 'trade_date'}
        needed_sub = set(k for k in requested_indicators if k in SUB_INDICATORS)
        if needed_sub.issubset(cached_cols):
            df = daily_data.merge(cached, on='trade_date', how='left')
            logger.debug(f"使用宽表预计算指标 ({len(cached)} 行)")
except Exception as e:
    logger.debug(f"预计算指标读取失败，回退实时计算: {e}")
```

- [ ] **Step 12: 运行 Makefile 检查**

```bash
make lint
```

---

### Task B1: factor_cache 表定义 + ECM 方法

**Covers:** factor_cache 统一到 ECM

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`

- [ ] **Step 13: 在 `_init_tables()` 中添加 `factor_cache` 表定义**

在 `_init_tables()` 中 `forecast_cache` 表定义后（第 323 行附近）添加：

```python
self._execute("""
    CREATE TABLE IF NOT EXISTS factor_cache (
        ts_code TEXT, trade_date TEXT,
        factor_name TEXT,
        value REAL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date, factor_name)
    )
""")
```

**注意：** 此操作幂等。`idx_factor_ts_name` 已在第 1 步添加。

- [ ] **Step 14: 在 ECM 中添加 factor_cache 的 CRUD 方法**

在 `clean_indicator_cache` 方法前添加：

```python
def cache_factor_data(self, records):
    """批量写入因子数据"""
    if not records:
        return
    with self._write_lock:
        self._insert_from_df('factor_cache', pd.DataFrame(records))
        self.conn.commit()

def get_cached_factor(self, ts_code: str, factor_name: str) -> pd.Series:
    """获取单个因子序列"""
    df = self._query_df(
        "SELECT trade_date, value FROM factor_cache "
        "WHERE ts_code = ? AND factor_name = ? ORDER BY trade_date",
        [ts_code, factor_name]
    )
    if df.empty:
        return None
    return pd.Series(df['value'].values, index=df['trade_date'])

def get_cached_factors(self, ts_code: str) -> pd.DataFrame:
    """获取某股票所有因子"""
    return self._query_df(
        "SELECT trade_date, factor_name, value FROM factor_cache "
        "WHERE ts_code = ? ORDER BY trade_date, factor_name",
        [ts_code]
    )

def clean_factor_cache(self, cutoff: str):
    """清理 factor_cache 中早于 cutoff 的记录"""
    self._execute("DELETE FROM factor_cache WHERE trade_date < ?", [cutoff])
    self.conn.commit()
    logger.info(f"清理 factor_cache (cutoff={cutoff})")
```

- [ ] **Step 15: 运行 Makefile 检查**

```bash
make lint
```

---

### Task B2: 更新 FactorPrecomputeManager 使用 ECM 连接

**Covers:** 去除 factor_precompute.py 独立连接

**Files:**
- Modify: `backend/app/data/factor_precompute.py`

- [ ] **Step 16: 移除 `_ensure_cache_table()`，修改所有方法使用 ECM**

```python
def __init__(self, cache_manager: Optional[EnhancedCacheManager] = None):
    self.cache_manager = cache_manager or EnhancedCacheManager()
    self.calculator = FactorCalculator()
    self.registry = get_factor_registry()
    # 不再需要 self._db_path — 统一通过 cache_manager 操作

# 删除 _ensure_cache_table() 方法——表由 ECM 管理

def _bulk_insert_factors(self, records: List[Dict]):
    """批量插入因子数据 — 委托给 ECM"""
    if not records:
        return
    # 统一 trade_date 格式
    for r in records:
        td = r['trade_date']
        if isinstance(td, (datetime, pd.Timestamp)):
            r['trade_date'] = td.strftime('%Y-%m-%d')
    self.cache_manager.cache_factor_data(records)

def get_cached_factor(self, ts_code: str, factor_name: str) -> Optional[pd.Series]:
    return self.cache_manager.get_cached_factor(ts_code, factor_name)

def get_cached_factors(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
    result = pd.DataFrame()
    for name in factor_names:
        series = self.cache_manager.get_cached_factor(ts_code, name)
        if series is not None:
            result[name] = series
    return result

def get_cache_stats(self) -> Dict:
    conn = self.cache_manager.conn  # 直接使用 ECM 连接
    stock_count = conn.execute("SELECT COUNT(DISTINCT ts_code) FROM factor_cache").fetchone()[0] or 0
    factor_count = conn.execute("SELECT COUNT(DISTINCT factor_name) FROM factor_cache").fetchone()[0] or 0
    total_records = conn.execute("SELECT COUNT(*) FROM factor_cache").fetchone()[0] or 0
    last_update = conn.execute("SELECT MAX(cached_at) FROM factor_cache").fetchone()[0]
    return {'stock_count': stock_count, 'factor_count': factor_count,
            'total_records': total_records, 'last_update': last_update}

def clear_cache(self, ts_code=None, factor_name=None):
    if ts_code and factor_name:
        self.cache_manager.conn.execute(
            "DELETE FROM factor_cache WHERE ts_code=? AND factor_name=?", [ts_code, factor_name])
    elif ts_code:
        self.cache_manager.conn.execute("DELETE FROM factor_cache WHERE ts_code=?", [ts_code])
    elif factor_name:
        self.cache_manager.conn.execute("DELETE FROM factor_cache WHERE factor_name=?", [factor_name])
    else:
        self.cache_manager.conn.execute("DELETE FROM factor_cache")
    self.cache_manager.conn.commit()

def clean_old_data(self, cutoff: str):
    """清理 factor_cache — 委托给 ECM"""
    self.cache_manager.clean_factor_cache(cutoff)
```

- [ ] **Step 17: 运行 Makefile 检查**

```bash
make lint && make typecheck
```

---

### Task B3: 验证

**Covers:** 端到端验证

- [ ] **Step 18: 更新 `_run_data_cleanup()` 中的 factor_cache 清理路径**

在 `data_daemon.py` 中，将 FactorPrecomputeManager 清理改为使用 ECM 方法：

```python
try:
    _ecm.clean_factor_cache(one_year_ago)
except Exception as e:
    logger.warning(f"清理 factor_cache 失败: {e}")
```

- [ ] **Step 19: 验证宽表写入和读取**

```bash
python3 -c "
from app.data.enhanced_cache_manager import get_ecm_instance
ecm = get_ecm_instance()
# 验证宽表存在
tables = [r[0] for r in ecm.conn.execute(
    \"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
for t in ['indicator_ma', 'indicator_macd', 'indicator_other', 'factor_cache']:
    assert t in tables, f'{t} 不存在!'
    cnt = ecm.conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {cnt} 行')
print('全部验证通过')
"
```

- [ ] **Step 20: 数据库空间验证**

```bash
ls -lh data/duckdb/stock_cache.db
# 预期：迁移 + 统一后数据库文件有所缩小（后续 VACUUM 效果更明显）
```
