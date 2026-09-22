# 474号｜balancesheet_cache current_liab 补采（缺字段名映射 + 消费侧命名统一）

## 起因
472 号记录「标准 ROCE（EBIT/(总资产-流动负债)）需补采 `current_liab` 列」。经 474 前置核查（473 号 dim6 收尾时的数据侧落点定位），确认**根因并非数据源缺失，而是缓存写入层缺 Tushare 字段名→表列名映射**：

- Tushare `balancesheet` 接口返回 **`total_cur_liab`**（流动负债合计）与 **`total_cur_assets`**（流动资产合计），而缓存表/白名单列名是 **`current_liab`/`current_assets`**。
- 对照：`income_cache` 入库有显式 `_COL_MAP`（`n_income→net_profit` 等，`enhanced_cache_manager.py:2099`）；而 `cache_balancesheet_data`（`enhanced_cache_manager.py:2124`）**完全没有映射**，直接 `_insert_from_df`。
- `_insert_from_df` 的动态列过滤（shard_cols 子集）会**丢弃表中不存在的列** → Tushare 的 `total_cur_liab` 因列名不匹配被静默丢弃 → 缓存 `current_liab`/`current_assets` 恒 NULL。
- 消费侧命名混乱：`dim4_chip_fund_engine.py:4671` 与 `chip_pre_filter.py:787` 用 **`current_liabilities`**（复数），表实际列名是 **`current_liab`** → 即便补采，标准 ROCE 分母 `total_assets - current_liabilities` 仍恒取 0。

## 修复（A 方案：加映射 + 命名统一）
1. **写入层补映射**（`data_daemon.py` / `enhanced_cache_manager.py` `cache_balancesheet_data`）：入库前 rename `total_cur_liab→current_liab`、`total_cur_assets→current_assets`（`money_cap`/`total_equity` 等 Tushare 同名列无需映射）。
2. **消费侧命名统一**：`dim4_chip_fund_engine.py:4671` 与 `chip_pre_filter.py:787` 的 `current_liabilities` → `current_liab`（对齐表列名）。
3. 全量重采 `balancesheet_cache`（`_batch_balancesheet` 全量触发，472 已证改 RAW/数据层需手动重算重采）。

## 实施与验证（2026-09-22）
- A 方案落地：`enhanced_cache_manager.py:cache_balancesheet_data` 加入 `_BS_COL_MAP = {'total_cur_liab': 'current_liab', 'total_cur_assets': 'current_assets'}`；`dim4_chip_fund_engine.py:4671`、`chip_pre_filter.py:787` 的 `current_liabilities`(复数) → `current_liab`。
- 提交 `334909c`（初版）；后修正字段名 `total_current_liab`→`total_cur_liab`（Tushare 真实字段名），随本次提交。
- 单测：`tests/test_474_balancesheet_colmap.py` 3 passed（`object.__new__` 绕 `__init__` 避免连库写锁）。消费侧 86 项回归 passed（daemon 停 + 看守停后）。
- 全量重采 `balancesheet_cache`（`scripts/probe_474_recompute.py`，5615 只逐只调 Tushare API ~20min）：
  - 结果：72016 行中 `current_liab` 非空 43997、`current_assets` 非空 43994；覆盖 5480/5577 只 code（97 只为 Tushare 该窗口空返回，属数据源覆盖，非映射问题）。
  - 抽验 000002.SZ `current_liab=553429826936.18`、`current_assets=653024653503.91`（2026-06-30）正确入库。
  - 消费侧标准 ROCE 分支（`dim7_valuation_engine.py:605/623`、`finance_report_service.py:60/77`、`valuation_estimator.py:656/674`）此前因 current_liab=NULL 走净资产近似，现激活「EBIT/(总资产-流动负债)」。
- probe 脚本 `probe_474_recompute.py` 为临时探针，用后已删除；daemon 已恢复。

## 主口径切换（已实施）
- 标准 ROCE 主口径已从「EBIT/净资产(总资产-总负债)」切换为「EBIT/(总资产-流动负债)」。
- 切换点：`data_daemon.py` RAW 预计算 `valuation_ext['roce']`（此前唯一仍用净资产口径处；dim4/dim7/finance_report_service 消费侧早已用流动负债口径）。
- 逻辑：优先 current_liab → EBIT/(总资产-流动负债)；current_liab 缺失回退 total_liab → EBIT/(总资产-总负债)；再缺回退 fina.roe×1.2。
- 回归：52 项（273a/449/448/473）通过。

