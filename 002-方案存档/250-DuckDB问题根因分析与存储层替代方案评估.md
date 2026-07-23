---
title: DuckDB 问题根因分析与存储层替代方案评估
type: 技术评估报告
date: 2026-07-06
status: ⏹️ 已过时（已被292号方案替代。SQLite WAL 已替换 DuckDB，操作完成）
superseded_by: 292
---

# DuckDB 问题根因分析与存储层替代方案评估

> **背景：** DuckDB 作为全局数据体系的盘后缓存层，持续出现文件锁冲突、序列化损坏、备份文件膨胀等问题。当前 `stock_cache.db` (434MB) 已完全损坏无法连接，系统降级到内存模式运行。
>
> **范围：** 本报告评估 DuckDB 在当前系统中的角色、问题的根因、以及所有可行的替代方案，推荐最优解。

---

## 一、DuckDB 在当前体系中的角色

### 1.1 存储的数据

| 表名 | 大小 | 数据源 | 写入频率 | 消费者数量 | 重要性 |
|------|------|--------|---------|-----------|--------|
| `daily_cache` | 最大 | Tushare daily | 日终 1次 | ~10 模块 | ⭐⭐⭐ 核心 |
| `daily_basic_cache` | 大 | Tushare daily_basic | 日终 1次 | ~5 模块 | ⭐⭐⭐ 核心 |
| `moneyflow_cache` | 中 | Tushare moneyflow | 日终 1次 | ~3 模块 | ⭐⭐ 重要 |
| `indicator_cache` | 中 | 本地预计算 | 按需 | ~3 模块 | ⭐⭐ 重要 |
| `chip_distribution_cache` | 中 | 本地计算 | 按需 | 1 模块 | ⭐ 专用 |
| `win_rate_cache` | 小 | 策略回测 | 按需 | 1 模块 | ⭐ 专用 |
| `as_*` 表 (6张) | ~已废弃 | AKShare(已断) | 不再写入 | 0 | ❌ 废弃 |

### 1.2 数据流向

```
Tushare API (日终)
    ↓  scheduler_manager 每天 15:30 触发同步
DuckDB *_cache (434MB 单文件)
    ↓  DataManager / get_ecm_instance()
策略引擎 · 选股系统 · 仪表盘 · 技术指标 · 回测系统
```

DuckDB 本质上是 **Tushare 数据的本地缓存**，用于：
1. 避免每日重复调用 Tushare API（200次/分钟限制）
2. 提供比 API 更快的本地查询响应
3. 作为离线数据的持久化存储

---

## 二、问题根因分析

### 2.1 直接原因链

```
Flask debug=True 热重载
    → 新进程启动，旧进程未完全释放 DuckDB 文件锁
    → ECM.__init__() 尝试 connect() → 锁冲突
    → 备份损坏文件 → 重试 → 再次失败 → 内存模式
    → 每次热重载产生一个 434MB .corrupted 文件
```

### 2.2 四个独立问题

| # | 问题 | 根因 | 影响范围 |
|---|------|------|---------|
| **A** | 文件锁冲突 | DuckDB 是单写者数据库，Flask 热重载产生旧 PID 持有锁 | 每次重启都可能触发 |
| **B** | 序列化损坏 | 进程被 SIGKILL 时写入尚未完成，下次连接时反序列化失败 | 需要手动恢复 |
| **C** | 备份膨胀 | `_rotate_corrupted_backup` 未实施，corrupted 文件永不清理 | 每次故障 +434MB |
| **D** | 多实例冲突 | `chip_distribution_service.py`、`factor_precompute.py`、`routes/factors.py` 直接 `new EnhancedCacheManager()` 而非 `get_ecm_instance()` | 多写者争抢锁 |

### 2.3 现有修复的不足

242号方案和当前 ECM 已实施的部分修复：
- ✅ `_kill_stale_duckdb_pids()` — kill 旧 PID
- ✅ `_clean_stale_duckdb_locks()` — 清理 .wal/.tmp
- ✅ 重试机制 + 指数退避
- ❌ **仍未实施**：corrupted 文件数量限制（当前 0 限制）
- ❌ **仍未实施**：全局单例模式强制（部分模块直接 new ECM）
- ❌ **仍未实施**：生产环境禁用热重载（`FLASK_ENV=production` 在 .env 中已设置但未强制）

---

## 三、替代方案评估

### 方案 A：修复 DuckDB（修复现有方案）

| 维度 | 评估 |
|------|------|
| **工作量** | 低～中（修改 ECM ~200 行，清理 corrupted 文件 ~5 分钟） |
| **风险** | 低（代码改动小，不影响接口） |
| **优点** | 保留列式存储优势；对大量历史数据的分析查询性能好；零迁移成本 |
| **缺点** | 文件锁问题只能缓解无法根治（DuckDB 设计如此）；单写者限制始终存在 |
| **需做改动** | ① 限制 corrupted 文件为 3 个 ② 强制 `get_ecm_instance()` 单例 ③ 连接前检查 `FLASK_ENV` ④ 写操作使用临时文件 + 原子交换 |

**结论：** 可行，但 DuckDB 的文件锁问题是其单进程架构的固有限制，只能缓解无法根治。

### 方案 B：SQLite WAL 模式替代（推荐）

| 维度 | 评估 |
|------|------|
| **工作量** | 中（重写 ECM ~400 行，涉及所有 SQL 操作的迁移） |
| **风险** | 中低（SQLite 是 Python 标准库，接口经过广泛验证） |
| **优点** | ✅ **无文件锁问题**（WAL 模式支持并发读+单写）<br>✅ Python `sqlite3` 标准库，零额外依赖<br>✅ 单文件管理，备份/迁移简单<br>✅ 成熟的生态，大量最佳实践<br>✅ 可移除 DuckDB 这个 56MB 的 pip 依赖 |
| **缺点** | ❌ 无列式压缩（434MB → 预计 ~500-600MB）<br>❌ 无向量化查询执行（对日线查询影响极小）<br>❌ 需要改写 ECM 中的 DuckDB 特有语法 |
| **SQL 兼容性** | `INSERT OR REPLACE` → `INSERT OR REPLACE` (兼容)<br>`DECIMAL` → `REAL`<br>`VARCHAR` → `TEXT`<br>`REGISTER temp_df` → 需要改为逐行/批量 insert<br>`PRAGMA` 语句不同 |

**结论：** 推荐。SQLite WAL 模式在单用户桌面应用中经过几十年验证，比 DuckDB 更适合这个场景。DuckDB 的列式/向量化优势对 ~400MB 数据和简单日线查询几乎没有实际收益。

### 方案 C：直接查询 Tushare + 内存缓存

| 维度 | 评估 |
|------|------|
| **工作量** | 中（修改 DataManager，增加 TieredMemoryCache 配置） |
| **风险** | 中（依赖 Tushare API 可用性） |
| **优点** | 架构最简单；零持久化存储维护；无锁/无损坏问题 |
| **缺点** | Tushare API 有速率限制（200次/分钟/基本账户）<br>离线不可用<br>每次查询延迟 ~200-500ms（vs 本地 1ms） |
| **适用场景** | 如果 Tushare 积分足够高（5000+），API 限制宽松，此方案可行 |

**结论：** 风险较高，不适合作为主要方案。可作为 DuckDB 损坏期间的降级补充方案。

### 方案 D：PostgreSQL 统一存储

| 维度 | 评估 |
|------|------|
| **工作量** | 高（需要在 PG 中建 10+ 缓存表，改写 ECM） |
| **风险** | 中（PG 已在运行，增加维护复杂度） |
| **优点** | 服务端管理并发；无文件锁问题；业务表和缓存表可 JOIN |
| **缺点** | 增加 PG 负担；缓存数据无需 ACID 事务；PG 本身也是运维负担 |

**结论：** 过度设计。缓存数据不需要 PG 的事务能力，用嵌入式数据库更合适。

---

## 四、推荐方案：B（SQLite WAL 替代 DuckDB）

### 4.1 架构对比

```
当前:                          推荐:
Tushare ─→ DuckDB ─→ 查询      Tushare ─→ SQLite ─→ 查询
             │                              │
        434MB 单文件                   预计 ~550MB 单文件
        ❌ 文件锁频繁                    ✅ WAL 模式无锁
        ❌ corrupted 备份膨胀             ✅ 无此问题
        ⚠️ 需安装 duckdb pip 包          ✅ Python 内置 sqlite3
```

### 4.2 SQLite WAL 模式如何解决 DuckDB 的问题

| DuckDB 问题 | SQLite WAL 解决方案 |
|-------------|-------------------|
| 单写者+单读者 | WAL 模式：**多读者 + 单写者**，读不阻塞写，写不阻塞读 |
| 文件锁冲突导致无法连接 | WAL 模式：读者只读 WAL 文件，不需要主文件锁 |
| 进程被 kill 导致损坏 | SQLite 的 WAL 检查点机制更健壮，意外崩溃可自动恢复 |
| 备份文件膨胀 | SQLite 单文件，不会创建 corrupted 备份 |
| DuckDB 特有语法 | SQLite 使用标准 SQL，兼容性更好 |

### 4.3 迁移工作量评估

| 模块 | 改动量 | 主要变更 |
|------|--------|---------|
| `enhanced_cache_manager.py` | ~500 行/1498 行 | 替换 `duckdb.connect` → `sqlite3.connect`<br>替换 `REGISTER` → 批量 `executemany`<br>替换 DuckDB SQL 方言 → 标准 SQL<br>类型映射：DECIMAL→REAL, VARCHAR→TEXT |
| 其他模块 | 几乎不变 | 查询接口不变，因为 ECM 已经封装了所有 SQL |
| `requirements.txt` | 移除 duckdb | Python 3.11+ 内置 sqlite3 |

### 4.4 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 迁移中数据丢失 | 保留 DuckDB 文件作为备份，迁移完成验证后再删除 |
| SQL 兼容性问题 | SQLite 支持 `INSERT OR REPLACE`、`CREATE INDEX`、`JOIN` 等所有 ECM 使用的 SQL 语法 |
| 性能下降 | SQLite 的日线查询延迟通常 <5ms，对单用户应用可忽略 |
| 并发写冲突 | 日终同步是唯一的写入操作，使用 write lock 即可 |

---

## 五、总结

| 方案 | 工作量 | 风险 | 根治锁问题 | 推荐度 |
|------|--------|------|-----------|--------|
| **A. 修复 DuckDB** | 低 | 低 | ❌ 只能缓解 | ⭐⭐⭐ |
| **B. SQLite WAL** | 中 | 低 | ✅ 根治 | ⭐⭐⭐⭐⭐ |
| **C. 直查 Tushare** | 中 | 高 | ✅ 无存储 | ⭐⭐ |
| **D. PG 统一** | 高 | 中 | ✅ 根治 | ⭐⭐ |

**核心判断：** DuckDB 的列式/向量化优势在 ~400MB 规模的日线缓存场景下没有实际收益，而其文件锁限制却带来了真实的运维痛苦。SQLite WAL 模式更匹配"单用户桌面应用 + 盘后批量写入 + 盘中随机读取"的实际负载模式。
