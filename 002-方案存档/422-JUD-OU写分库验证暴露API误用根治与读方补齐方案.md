---
title: JUD/OUT 写分库验证暴露 API 误用根治与读方补齐方案
type: 验证报告 + 修订实施记录
date: 2026-09-10
version: v1.0
status: ✅ 已验证闭环
related:
  - 292-全局数据体系权威架构说明（2026-07-23版）
  - 357-分库迁移（strategy_signal_detail 迁入 snapshot_cache.db，355号注记）
  - 375-机会图谱弹窗内容核查与SIG-JUD管道诊断报告（T1已实施）
  - 421-SIG信号写库路径对齐与失败暴露根治方案（R1-R4 已实施）
---

# 422 — JUD/OUT 写分库验证暴露 API 误用根治与读方补齐方案

> **背景**：2026-09-10 按启动验证清单重跑 20260909 管道，验证昨日（09-09 §6）
> "JUD/OUT/treemap 写分库修复"。第一轮重跑日志报 JUD/OUT done，但
> **分库 snapshot_cache.db 未被写入**——昨日修复存在致命 API 误用，
> 实际写入生成野文件。本方案记录根因、根治与读方补齐，全部已验证闭环。

---

## 一、根因（昨日"写分库修复"的致命缺陷）

`sharding_manager.get_connection(db_name)` 的参数是**分库文件名**
（如 `snapshot_cache.db`），**不是表名**。昨日修复的 4 处新代码直接传表名：

```python
# ❌ 昨日误用：生成野文件 data/duckdb/status_snapshot（无 .db 后缀）
_snap_conn = sharding_manager.get_connection('status_snapshot')

# ✅ 正确两段式（全库既有正确范例 304/413/1316/3640 行）
_snap_conn = sharding_manager.get_connection(
    sharding_manager.get_db_for_table('status_snapshot'))   # → snapshot_cache.db
```

**后果**：JUD/OUT 的 status/treemap 写入落到以表名命名的独立 SQLite 文件
（`data/duckdb/status_snapshot` 290MB、`treemap_snapshot` 8.7MB），
分库权威副本未被更新 → **读写分叉依旧存在**（读方 sharding 路由读分库旧批次）。

**昨日验证盲区**：仅 grep 确认"无 `_ecm.conn` 写 status_snapshot"（写方不再走主库），
未校验**连接目标文件**——API 误用生成的野文件恰好满足"不再写主库"的表面条件。

---

## 二、修复清单（全部已验证）

### R1 写路径 4 处 API 误用（data_daemon.py）

| 行 | 函数 | 修复 |
|----|------|------|
| 3989 | `_build_treemap_snapshot` | `get_connection(get_db_for_table('treemap_snapshot'))` |
| 4133 | `_out_transmit_seven_dim` | `get_connection(get_db_for_table('status_snapshot'))` |
| 4349 | `_build_status_snapshot` | 同上 |
| 4885 | `_verify_out_completeness` | 同上 |

### R2 treemap 归档列错位（野文件运行掩盖）

`INSERT OR REPLACE INTO treemap_snapshot_history SELECT * FROM treemap_snapshot`
失败：历史表残留旧列 `seven_dim_report`（370号S6 已废弃），48 列 vs 源表 47 列。
→ 改为**显式列名** `_tm_cols`（47 列，废弃列留空）。

### R3 OUT watchlist 变更检测读主库（3 处）

`_out_transmit_seven_dim` 自选股段 `prev_date`/`cur`/`prev` 三处读
`status_snapshot` 仍走 `_ecm.conn`（主库）→ 切 `_snap_conn`（分库）。
（`watchlist_status_diff` 表本身保留主库，路由 None=主库，正确。）

### R4 R4a 读方迁移补齐（8 处，主库 `_query_df`/`read_conn` → 分库）

| 文件 | 位置 | 表 | 修复 |
|------|------|----|------|
| opportunity_atlas/valuation_estimator.py | 169 | treemap | `_query_shard('treemap_snapshot', ...)` |
| opportunity_atlas/cross_validate.py | 83 | status | `_query_shard('status_snapshot', ...)` |
| opportunity_atlas/potential_engine.py | 93 | treemap | `_query_shard('treemap_snapshot', ...)` |
| data/enhanced_cache_manager.py | get_snapshot_max_date | treemap | 分库连接 |
| data/enhanced_cache_manager.py | get_snapshot_data_date | treemap | 分库连接 |
| data/enhanced_cache_manager.py | get_treemap_snapshot 回退 | treemap | `_query_shard` |
| data/enhanced_cache_manager.py | get_status_snapshot_row | status | `_query_shard` |
| routes/strategy_analyze.py | 759 预加载 | status | `_query_shard` |

### R5 主库残留清理（新建 `backend/scripts/migrate_status_treemap_shard.py`）

备份→校验（分库权威 ≥ 主库残留）→ 清空，幂等可回滚：
- 主库 `status_snapshot` 5549→0（备份 `status_snapshot_bak` 5549）
- 主库 `treemap_snapshot` 5544→0（备份 `treemap_snapshot_bak` 5544）

---

## 三、验证结果（2026-09-10）

| 对象 | 修复前 | 修复后 |
|------|--------|--------|
| 分库 status_snapshot | 08-27（5576 旧批次） | **2026-09-10 · 5549** ✅ |
| 分库 treemap_snapshot | 08-27（5578 旧批次） | **2026-09-10 · 5544** ✅ |
| 分库 status_snapshot_history | — | 含 09-10 批次 ✅ |
| 分库 treemap_snapshot_history | — | 含 09-10 批次（显式列名写入正确）✅ |
| 主库 status/treemap | 09-09 残留（5549/5544） | **0 行**（备份可回滚）✅ |
| 读取方路由 | 8 处读主库 | 全分库（`get_snapshot_max_date=2026-09-10` 实测）✅ |
| pipeline_status 20260909 | JUD/OUT pending | SIG/JUD/OUT done ✅ |
| 归档报错 | `48 columns but 47 values` | 无 ✅ |
| 代码质量 | — | py_compile ✅、ruff 改动文件通过 ✅ |
| 测试回归 | — | 670 passed / 2 failed（数据依赖，见遗留） |

---

## 四、遗留问题（待议，非本次阻塞）

1. **测试 2 failed 为数据依赖**（非代码回归）：`strategy_signal_detail` 中 600519 等股票
   `signals` 为空 dict → `_restore_signals_from_cache` 返回 `[]`
   （`test_322::test_read_signal_cached_falls_back_to_latest`、
   `test_320::test_build_p2_signal_summary`）。信号链代码本次未触及。
2. **treemap_snapshot_history 5571 行历史错位脏数据**（rowid 1..5571，snapshot_date 列存
   股票名）——旧归档代码 `SELECT *` 历史遗留，非本次引入；新写入 5544 行正确。
   可选：迁移重建历史表。
3. `_verify_out_completeness` 的 `active_count` 仍读 `_ecm.conn` 的 `daily_cache`
   （分库表）→ OUT-CHECK 被跳过（低影响）。
4. `mark_step_running` 无 commit（管道 running 状态对外不可见，诊断困难）。
5. （可选）dim2/dim3 `_load_precomputed_macd` 直调 DataManager 残留（红线合规性瑕疵）。

---

## 五、关键教训

- **验证"写分库"必须校验连接目标（文件路径）**，不能只 grep 是否调用旧连接。
- `sharding_manager.get_connection()` 参数是分库文件名；表→库映射必须经
  `get_db_for_table()` 转换（两段式），全库统一该模式。
- 读写迁移必须**成对**实施：写方切分库后，所有读方（含回退分支）必须同步切分库，
  否则清理主库残留会静默破坏读方。
