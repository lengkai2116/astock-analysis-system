# 458号：bociasi 慢线分库回退缺陷修复（market_stats 快照缺键触发主库无表静默退化）

> 状态：✅ 已实施 + 全量验证（2026-09-17）

## 一、背景与问题（445 收口后真实数据运行测试暴露）

445 收口 + 457 完成后，进行系统真实数据运行测试（`scripts/sig_full_test.py`，停 daemon）。

**汇总：OK 40 / WARN 0 / FAIL 0**，但完整输出的 stderr 中，**每次 evaluate 都打出**：

```
股债收益差计算失败，回退0.5: no such table: daily_basic_cache
```

（5 只股票 × 5 次，被 OK/WARN/FAIL 汇总计数掩盖——该汇总只统计维级状态，不统计引擎内部回退告警。）

## 二、根因（双重）

### 缺陷 1：主库无分库表——7 个回退方法全部用错 conn
`app/engine/framework/bociasi_quadrant.py` 的 7 个回退方法（`_compute_ma20_ratio / _turnover_percentile / _limit_ratio / _rsi_percentile / _erp_percentile / _dv_bond_diff / _margin_trend`）均用：

```python
conn = self._get_dm().cache.conn   # 主库 → stock_cache.db（总库）
```

但目标表全部已分库（`app/data/sharding_manager.py:73` 路由）：
- `daily_cache` / `daily_basic_cache` / `stk_limit_cache` / `margin_cache` → **market_cache.db**
- `indicator_other` → **compute_cache.db**

主库（总库 stock_cache.db）无这些表 → `conn.execute(...)` 抛 `no such table` → 各方法 `except` 静默回退常量 `0.5`。

### 缺陷 2：注入的 market_stats 快照缺键，触发不可用的回退
dim1 注入 `market_stats`（来自 daemon 的 `pre_feat_cache` 快照）。实测 `000001.SZ` 快照（trade_date 2026-09-14，computed 09-16 09:55）的 `market_stats` **缺 `dv_bond_diff` 键**（当时的预计算尚未带 447 T3a-2 新列/新值）→ 走 `_compute_dv_bond_diff` 回退 → 缺陷 1 → 静默 0.5。

而 `market_stats_cache` 表本身最新行已含 `dv_bond_diff=0.463`——说明 daemon 已能算出，只是**没灌进旧 pre_feat 快照**。

## 三、影响范围

- 命中最直接：dim5 慢线第 3 项 `dv_bond_diff`（§6.2 冻结「dim5 慢线 3 项构成」）→ 慢线得分被常量 0.5 充数，四象限 slow_score 失真。
- 潜在：任一 market_stats 键缺失时，对应快线/慢线子指标也会静默 0.5（`ma20_ratio/turnover_percentile/limit_ratio/rsi_percentile/erp_percentile/margin_trend` 同病）。

## 四、处置（分库路由接入，不触碰判定/阈值）

### R1：bociasi 7 个回退方法改走分库 conn
新增辅助 `_shard_conn(table_name)` → `sharding_manager.get_connection(get_db_for_table(table_name))`，`_limit_ratio` 因 `daily_cache JOIN stk_limit_cache` 两表同库（market_cache.db）取其一即可。

替换全部 `conn = self._get_dm().cache.conn`。

### R2：注入键缺失时不再静默退化到失真常量——保留可计算（数据可及时）
修复后，即使 pre_feat 快照缺键，回退方法也能从分库算得真实值，而非 0.5。

### R3（数据补采，非引擎）：pre_feat 快照再生成
`pre_feat_cache` 缺 `dv_bond_diff` 键的旧快照，由 daemon 下一轮 RAW-2 再生自动补齐（market_stats 现含 dv_bond_diff）。属数据再生，不需改引擎。

## 五、验证

1. 单测：新增 458 测试——mock 主库 conn 抛无表、mock 分库 conn 返回有效行，断言 7 个回退方法经分库查到真实值（不再 0.5）。
2. 回归：`test_447_dim5_emotion_fix.py` + dim5 相关，全绿。
3. 全链路实跑：停 daemon，`scripts/sig_full_test.py`，确认 stderr 不再出现 `no such table: daily_basic_cache`；OK 仍 40/WARN 0/FAIL 0。

## 六、备注

- 本号触碰 §6.2 冻结的 dim5 慢线构成（回退计算路径），按 445 收口约束：改动仅修复**数据读取路由**（分库接入正确），**不改变**判定逻辑/阈值/输出契约（慢线构成、方向、0~1 分位口径均不变）。经 StatusEngine 全链路验证后确认未回退冻结项。

## 工作进度

- [x] 根因定位（分库路由核查 + pre_feat 快照缺键实证）
- [x] R1 分库路由接入（bociasi_quadrant.py 新增 `_shard_conn`，7 回退方法改走分库）
- [x] 单测 458（10 用例）+ 447 dim5 回归 + 419 dim5 合规（契约补 dv_bond_diff 键）
- [x] 全链路实跑：stderr 无 `no such table: daily_basic_cache`，OK 40 / WARN 0 / FAIL 0
- [x] 实证：dv_bond_diff 回退=0.4630（真实值，非 0.5 充数），与 daemon 预计算一致
- [x] 回归：44 passed（458/447/419）+ 55 passed（含引用 bociasi 的 4 集成文件）
