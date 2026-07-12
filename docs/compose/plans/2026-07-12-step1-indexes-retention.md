# Step 1：添加缺失索引 + 数据保留策略 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `indicator_cache`(85M行) 和 `factor_cache`(37M行) 添加次级索引匹配查询模式，并添加数据保留策略阻止两表的无限制增长。

**Architecture:** ECM (`enhanced_cache_manager.py`) 管理 `indicator_cache` 表结构及其清理方法；`factor_precompute.py` 通过独立连接管理 `factor_cache`，两个地方各自添加索引和清理方法。`data_daemon.py` 的 `_run_data_cleanup()` 统一调度清理任务。

**Tech Stack:** Python 3, SQLite (WAL), Pandas

## Global Constraints

- 所有 SQLite 索引使用 `IF NOT EXISTS` 保证幂等
- 日期清理按 `trade_date`（交易日）字段，`NOT` `cached_at`
- `factor_cache` 的索引需要通过 ECM 的 `_init_tables()` 来创建（而非独立连接），因为 `factor_precompute.py` 的连接每次打开使用后关闭，无法持久化索引创建
- 清理逻辑遵循 `_run_data_cleanup()` 已有模式：各表独立方法、单独 try/except

---

### Task 1: indicator_cache + factor_cache 添加次级索引

**Covers:** 269号评估 §四-第一步

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py:128-133` — 在 `_init_tables()` 索引段添加两条 CREATE INDEX
- Modify: `backend/app/data/enhanced_cache_manager.py:116-429` — `_init_tables()` 方法

**Interfaces:**
- Consumes: ECM 已有 `_init_tables()` 中的索引创建循环（392-428行）
- Produces: 两个新的 SQLite 索引被创建

- [ ] **Step 1: 在 `_init_tables()` 的索引列表中添加 `indicator_cache` 的次级索引**

在 `enhanced_cache_manager.py` 第 423 行（`idx_index_member_code` 之后），插入两条新索引 SQL：

```python
"CREATE INDEX IF NOT EXISTS idx_indicator_ts_name ON indicator_cache(ts_code, indicator_name)",
"CREATE INDEX IF NOT EXISTS idx_factor_ts_name ON factor_cache(ts_code, factor_name)",
```

这两条索引解决了：
- `indicator_cache`：`get_indicator_data()` 查询 `WHERE ts_code=? AND indicator_name=?` 可以用到完整复合索引，不再需要遍历所有 `trade_date`
- `factor_cache`：效果同上的查询模式

**注意：** `factor_cache` 表由 `factor_precompute.py` 通过独立连接创建，但 ECM 的 `_init_tables()` 也执行 `CREATE TABLE IF NOT EXISTS` 不会重复建表。在 ECM 侧建索引是安全的。

- [ ] **Step 2: 运行 Makefile 检查 lint**

```bash
make lint
```

预期：无新增 lint 错误。

---

### Task 2: indicator_cache 添加数据保留方法

**Covers:** 269号评估 §四-第一步

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py:1339` — 在 `clean_minute_cache` 后添加新方法
- Modify: `backend/data_daemon.py:1017-1053` — 在 `_run_data_cleanup()` 中添加调用

**Interfaces:**
- Produces: `EnhancedCacheManager.clean_indicator_cache(cutoff)` — 清理早于截止日期的数据
- Consumes: 被 `_run_data_cleanup()` 调用，按 trade_date 字段清理

- [ ] **Step 3: 在 ECM 中添加 `clean_indicator_cache` 方法**

在 `enhanced_cache_manager.py:1343`（`clean_minute_cache` 之后，`vacuum_db` 之前），添加：

```python
def clean_indicator_cache(self, cutoff: str):
    """清理 indicator_cache 中早于 cutoff 的记录（cutoff 格式 YYYYMMDD）"""
    self._execute("DELETE FROM indicator_cache WHERE trade_date < ?", [cutoff])
    self.conn.commit()
    logger.info(f"清理 indicator_cache (cutoff={cutoff})")
```

参照已有 `clean_stk_limit_cache` 的模式，按 `trade_date` 字段清理。85M 行的表删除旧数据可能需要几分钟，但 SQLite 的 DELETE 在 WAL 模式下不阻塞读。

- [ ] **Step 4: 在 `_run_data_cleanup` 中添加调用**

在 `backend/data_daemon.py:1044`（`clean_minute_cache` 之后），添加：

```python
try:
    _ecm.clean_indicator_cache(one_year_ago)
except Exception as e:
    logger.warning(f"清理 indicator_cache 失败: {e}")
```

`one_year_ago` 已在函数顶部定义（`cutoff = 365 days ago`），复用即可。指标数据保留 1 年对于 A 股技术分析（常用 5-250 日均线）是足够的窗口。

- [ ] **Step 5: 运行 Makefile 检查**

```bash
make lint && make typecheck
```

---

### Task 3: factor_cache 添加数据保留方法

**Covers:** 269号评估 §四-第一步

**Files:**
- Modify: `backend/app/data/factor_precompute.py` — 添加 `clean_old_data` 方法
- Modify: `backend/data_daemon.py:1017-1053` — 在 `_run_data_cleanup()` 中添加调用

**Interfaces:**
- Produces: `FactorPrecomputeManager.clean_old_data(cutoff)` — 清理早于截止日期因子数据
- Consumes: 被 `_run_data_cleanup()` 调用

- [ ] **Step 6: 在 FactorPrecomputeManager 中添加清理方法**

在 `factor_precompute.py` 末尾（`clear_cache` 方法之后），添加：

```python
def clean_old_data(self, cutoff: str):
    """清理 factor_cache 中早于 cutoff 的记录"""
    conn = sqlite3.connect(self._db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM factor_cache WHERE trade_date < ?", [cutoff])
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"清理 factor_cache (cutoff={cutoff}): {deleted} 行")
        return deleted
    except Exception as e:
        logger.warning(f"清理 factor_cache 失败: {e}")
        return 0
    finally:
        conn.close()
```

- [ ] **Step 7: 在 `_run_data_cleanup` 中添加调用**

在 `data_daemon.py:1044`（上一步的 `clean_indicator_cache` 块之后），添加：

```python
try:
    from app.data.factor_precompute import FactorPrecomputeManager
    fpm = FactorPrecomputeManager(_ecm)
    fpm.clean_old_data(one_year_ago)
except Exception as e:
    logger.warning(f"清理 factor_cache 失败: {e}")
```

- [ ] **Step 8: 运行 Makefile 检查**

```bash
make lint && make typecheck
```

---

### Task 4: 验证 + VACUUM

**Covers:** 全程验证

**Files:** (无代码修改)

- [ ] **Step 9: 验证索引创建**

启动 Python 并验证索引已创建：

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/duckdb/stock_cache.db')
cursor = conn.execute(\"SELECT name FROM sqlite_master WHERE type='index' ORDER BY name\")
for r in cursor.fetchall():
    print(r[0])
conn.close()
"
```

预期输出中包含：
- `idx_indicator_ts_name`
- `idx_factor_ts_name`

- [ ] **Step 10: 验证清理方法可用**

```bash
python3 -c "
from app.data.enhanced_cache_manager import get_ecm_instance
from app.data.factor_precompute import FactorPrecomputeManager
from datetime import datetime, timedelta
ecm = get_ecm_instance()
cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
ecm.clean_indicator_cache(cutoff)
print('indicator_cache 清理方法 OK')
fpm = FactorPrecomputeManager(ecm)
fpm.clean_old_data(cutoff)
print('factor_cache 清理方法 OK')
"
```

- [ ] **Step 11: VACUUM（可选，仅在数据量缩减明显时执行）**

如果清理后数据量显著减少，执行 VACUUM 回收磁盘空间：

```python
ecm.vacuum_db()
```

**注意：** VACUUM 需要两倍于 DB 大小的磁盘空间，建议在非交易时段执行。

- [ ] **Step 12: 验证数据库大小变化**

```bash
ls -lh data/duckdb/stock_cache.db
```
