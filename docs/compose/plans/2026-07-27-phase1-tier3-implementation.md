# Phase 1 — 第三梯队：P0.4 L2标注 + signal_strength

> **基准文件**：303号§三、292号§5.1

**目标**：在 data_daemon `_run_precompute()` 中新增 L2 标签预计算块，4 引擎聚合产出 signal_strength。

**架构**：在因子预计算之后插入新块 `_precompute_l2_labels()`，不修改现有三个块的代码。

**审阅关注点**：
- signal_strength 不含 catalyst_event 维度（P2.1 未就绪）
- 每 500 只 commit 一次避免长事务
- 各引擎独立 try/except

### Task 1: ECM 建表 + write_tags 方法

**Modify**: `backend/app/data/enhanced_cache_manager.py`

- [ ] 在 `_init_tables()` 的 `finance_report_cache` 之后新增 `opportunity_tags_cache` 表
- [ ] 添加索引 `idx_tags_ts_code` 和 `idx_tags_name`
- [ ] 添加 `write_tags(ts_code, tags, trade_date)` 方法（批处理）

### Task 2: data_daemon `_precompute_l2_labels` + `_run_precompute` 接入

**Modify**: `backend/data_daemon.py`

- [ ] 在 `_run_precompute()` 因子预计算之后插入调用
- [ ] 实现 `_precompute_l2_labels(codes)` 函数
