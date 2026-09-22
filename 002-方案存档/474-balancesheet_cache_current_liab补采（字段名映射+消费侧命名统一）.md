# 474号｜balancesheet_cache current_liab 补采（缺字段名映射 + 消费侧命名统一）

## 起因
472 号记录「标准 ROCE（EBIT/(总资产-流动负债)）需补采 `current_liab` 列」。经 474 前置核查（473 号 dim6 收尾时的数据侧落点定位），确认**根因并非数据源缺失，而是缓存写入层缺 Tushare 字段名→表列名映射**：

- Tushare `balancesheet` 接口返回 **`total_current_liab`**（流动负债合计）与 **`total_current_assets`**（流动资产合计），而缓存表/白名单列名是 **`current_liab`/`current_assets`**。
- 对照：`income_cache` 入库有显式 `_COL_MAP`（`n_income→net_profit` 等，`enhanced_cache_manager.py:2099`）；而 `cache_balancesheet_data`（`enhanced_cache_manager.py:2124`）**完全没有映射**，直接 `_insert_from_df`。
- `_insert_from_df` 的动态列过滤（shard_cols 子集）会**丢弃表中不存在的列** → Tushare 的 `total_current_liab` 因列名不匹配被静默丢弃 → 缓存 `current_liab`/`current_assets` 恒 NULL。
- 消费侧命名混乱：`dim4_chip_fund_engine.py:4671` 与 `chip_pre_filter.py:787` 用 **`current_liabilities`**（复数），表实际列名是 **`current_liab`** → 即便补采，标准 ROCE 分母 `total_assets - current_liabilities` 仍恒取 0。

## 修复（A 方案：加映射 + 命名统一）
1. **写入层补映射**（`data_daemon.py` / `enhanced_cache_manager.py` `cache_balancesheet_data`）：入库前 rename `total_current_liab→current_liab`、`total_current_assets→current_assets`（`money_cap`/`total_equity` 等 Tushare 同名列无需映射）。
2. **消费侧命名统一**：`dim4_chip_fund_engine.py:4671` 与 `chip_pre_filter.py:787` 的 `current_liabilities` → `current_liab`（对齐表列名）。
3. 全量重采 `balancesheet_cache`（`_batch_balancesheet` 全量触发，472 已证改 RAW/数据层需手动重算重采）。

## 待办/记录
- 标准 ROCE 主口径从「EBIT/净资产(总资产-总负债)」升级为「EBIT/(总资产-流动负债)」——待补采后 472 口径是否需要切换为独立决策项。
