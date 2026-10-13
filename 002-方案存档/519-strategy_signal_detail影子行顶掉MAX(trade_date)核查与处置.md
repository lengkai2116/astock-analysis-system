# 519号｜strategy_signal_detail 骨架行（影子行）顶掉 MAX(trade_date) 核查与处置（单只预计算 OR REPLACE 抹掉 JUD 产物）

> **版本**：v1.1（2026-10-13 只读核查 + **拍板 A+B+C 并实施 + 定向验证通过**）
> **性质**：数据口径缺陷 + 写语义缺陷（骨架行顶掉 `MAX(trade_date)`；并会**覆盖已判定产物**）
> **触发**：2026-10-13 全量回归核查 skipped 由 2 漂到 8（6×`test_495_b2_jud_market_gate`）
> **关联**：518（读连接改动**无关**）；495-B2（门禁脚本）；514/515（同为 daemon 侧数据完整性议题）
> **核查时刻**：2026-10-13 21:4x（只读）；实施同日晚

---

## 一、现象（实证）

- **全量回归 skipped 由 2 → 8**：新增 6 项全为 `tests/test_495_b2_jud_market_gate.py` 的「无真实 SIG 数据」skip；另 2 项 `test_services.py` 为稳定 skip（与本题无关）。
- **表状态**（`data/duckdb/snapshot_cache.db` 的 `strategy_signal_detail`）：
  - `2026-10-12` = 5561 行 / **5557 行 `dim_results_json` 非空**（真实全量日）；
  - `2026-10-13` = **1 行且 `dim_results_json` 为 NULL** ⇒ 影子行 `(000001.SZ, 2026-10-13, cached_at=2026-10-13 21:30:15)`。
- **机制**：消费方通用取数＝先 `SELECT MAX(trade_date)`、再要求该日 `dim_results_json IS NOT NULL` ⇒ 10-13 那 1 行 json 为 NULL ⇒ **该日 0 行 → 判「无数据」→ skip / 空样本**。（ECM 读路径 `get_latest_signal_detail` 带 `ORDER BY DESC`＋可选 `require_payload` 过滤、`get_signal_detail` 用显式 `(ts_code, trade_date)`——**不受影响**。）
- **时间线**：第 1 次回归（20:33:48）为 2 skipped → daemon 首次消费 `sync_requests: type=precompute_strategy ts_code=000001.SZ`（20:35:54）→ 第 2 次回归（21:23:43）为 8 skipped。**与 518 读连接改动无关**（读写连接数据一致，已验证）。

## 二、代码机制（实证）

`strategy_signal_detail` 有 **3 条写路径**：

| # | 路径 | 写入列 | 触发 |
|---|---|---|---|
| 1 | `data_daemon._precompute_single`（`:5320`）→ `ECM.cache_signal_detail`（`app/data/enhanced_cache_manager.py:2699`） | **5 列**（signal_json/schema_version/cached_at，**不含** seven_dim_json/dim_results_json） | `sync_requests type=precompute_strategy`（自选股 `app/routes/watchlist.py:381`／策略分析 `app/routes/strategy_analyze.py:740`） |
| 2 | `data_daemon._write_factor_signals`（`:2980`）→ 同 `cache_signal_detail` | **5 列** | SIG 计算全失败时的因子兜底 |
| 3 | `data_daemon._precompute_strategy_signals`（`:7288`）→ `_batch_write_signal_detail` | **7 列**（含 seven_dim_json/dim_results_json） | EOD 全市场 SIG 步骤（10-13 当前 `pending`） |

- `trade_date` 来源＝`result.to_dict()['trade_date']`（＝**当前交易日 2026-10-13**，因 `daily_cache`/`daily_basic_cache`/`pre_feat_cache` 均已到 10-13）；`cache_signal_detail` 缺省回退 `datetime.now().strftime('%Y%m%d')`。⇒ **trade_date 本身正确**，绝非异常日期。
- 表 `DDL`：`PRIMARY KEY (ts_code, trade_date)`（`enhanced_cache_manager.py:954`）⇒ 可用 `ON CONFLICT` 精确修复。

### 关键：`INSERT OR REPLACE` 会抹掉 JUD 产物（比「顶掉 MAX」更严重）

`cache_signal_detail` 原写 SQL＝`INSERT OR REPLACE ... (ts_code, trade_date, signal_json, schema_version, cached_at)`，**只给 5 列**。SQLite 的 `INSERT OR REPLACE` 语义＝**删旧行 + 插新行**，未给出的列回默认 ⇒ **`seven_dim_json`/`dim_results_json` 被置 NULL**。

⇒ **日终 SIG/JUD 把 10-13 的产物填好之后，任一 `precompute_strategy`（自选股/策略分析请求）都会把该 `(ts_code, 当日)` 行的 JUD 产物抹掉**——不只是「顶掉 MAX」，而是**覆盖已判定数据**。

## 三、影响面（消费方）

`MAX(trade_date)` 未带 `dim_results_json IS NOT NULL` 过滤者（会被骨架行误伤）：

| 位置 | 用途 |
|---|---|
| `backend/tests/test_495_b2_jud_market_gate.py:44` | `_load_sample`（6 skips 之源） |
| `backend/scripts/_495_b2_jud_market_gate.py:63` | 门禁 `_latest_trade_date` |
| `backend/scripts/_495_b6_b3_probe.py:27` | B3 探针 |
| `backend/test_395_real_data.py:18` | 395 号真实数据脚本 |
| `backend/app/routes/health.py:343` | `/api/v3/health/data-freshness`（latest 报 10-13/1 行，误导） |

**不受影响**：ECM `get_latest_signal_detail`（`ORDER BY DESC` + 可选 `require_payload` 过滤）、`get_signal_detail`（显式 `(ts_code, trade_date)`）。

## 四、根因定性

1. **消费侧口径**：以「最新交易日 ∧ `dim_results_json` 非空」为「有 SIG/JUD 数据」的判据，但取「最新交易日」时未带非空过滤 ⇒ 骨架行顶掉。
2. **写侧语义**：`cache_signal_detail` 用 `INSERT OR REPLACE` 只给 SIG 列，**回置** JUD 列为 NULL ⇒ 会覆盖已判定产物（真隐患，且必现复发：daemon 重启后 `precompute_strategy` 即重写骨架行，2026-10-13 实证 `cached_at` 由 21:26:10 → 21:30:15）。

## 五、处置方案与拍板

| 方案 | 内容 |
|---|---|
| **A 写方治本** | `cache_signal_detail` 写语义由 `INSERT OR REPLACE` 改为 **UPSERT**（`ON CONFLICT(ts_code, trade_date) DO UPDATE`），只更新 SIG 列，**保留** seven_dim_json/dim_results_json。 |
| **B 消费侧加固** | 上表 5 处 `MAX(trade_date)` → `MAX(trade_date) ... WHERE dim_results_json IS NOT NULL`（health 用子查询，`cnt` 仍为全表行数）。 |
| **C 清理现状** | 删除当前骨架行（一次性；仅 A 能防复发）。 |

**拍板（2026-10-13）＝双管 A+B+C。** 理由：单侧 B 只治取数口径、放任写侧覆盖隐患；单侧 A 无法立即使当前消费方恢复正常；C 清掉历史遗留。

## 六、实施记录（v1.1，2026-10-13）

- **A 写方**：`app/data/enhanced_cache_manager.py` `cache_signal_detail` 改
  `INSERT INTO strategy_signal_detail (ts_code, trade_date, signal_json, schema_version, cached_at) VALUES (?, ?, ?, 1, datetime('now','localtime')) ON CONFLICT(ts_code, trade_date) DO UPDATE SET signal_json=excluded.signal_json, schema_version=excluded.schema_version, cached_at=excluded.cached_at`
  （docstring 补 519 号说明）。
- **B 消费侧**：5 处加 `WHERE dim_results_json IS NOT NULL` 过滤——`tests/test_495_b2_jud_market_gate.py`、`scripts/_495_b2_jud_market_gate.py`、`scripts/_495_b6_b3_probe.py`（子查询）、`test_395_real_data.py`（子查询）、`app/routes/health.py`（`latest` 走子查询、`cnt` 保持全表口径）。
- **C 清理**：新增探针 `backend/scripts/_519_shadow_row_probe.py`（默认只读报告；`--clean` 删除；**保守判据**＝「骨架日」当日行数 < 100 且当天无任何 `dim_results_json` 非空行，避免误删全量日内个别计算失败的合法行）。已执行 `--clean` 删除 10-13 骨架行 1 条。
- **测试**：新增 `backend/tests/test_519_signal_detail_upsert_preserve.py`（4 用例：UPSERT 源码断言 / 保留 JUD 产物（功能）/ 无既有行时插入骨架行 / 5 处消费侧过滤断言）。

## 七、验证（定向）

- `py_compile` 8 文件 **OK**。
- `ruff` 改动文件**零新增**（`enhanced_cache_manager.py` 3 条 E702、`test_395_real_data.py` 5 条 F541 均为 HEAD 既有基线，已逐一对照 `git show HEAD:` 确认）。
- `tests/test_519_signal_detail_upsert_preserve.py` **4 passed**。
- **实机（C 清理后）**：探针 `--clean` 幂等（第二次运行 0 条），`MAX(trade_date)` 由 10-13 回落 **2026-10-12**；`tests/test_495_b2_jud_market_gate.py` 由 **6 skipped → 6 passed**（30.07s，读真实 10-12 数据）。
- **A 生效条件**：写方改动需 **daemon 重启**加载（当前 daemon 46238 运行旧代码，正跑 10-13 EOD，未重启以免中断）。

## 八、遗留

1. **A 尚未在运行态生效**：daemon 46238 为旧代码；待 10-13 EOD 完成或下次自然重启后加载（届时单只预计算不再抹掉 JUD 产物）。
2. **骨料行复现**：A 只保证「不覆盖既有 JUD 产物」；在 JUD 未跑的日期，单只预计算**仍会写骨架行**（设计如此，无消费价值但无害）。消费方已由 B 加固。
3. **`_batch_write_signal_detail`（EOD 全市场 SIG）** 仍为 `INSERT OR REPLACE` 全 7 列——**不在本次范围**（SIG 是 `dim_results_json` 的正常生产者，替换语义正确）。

## 附：取证 / 复现命令

```bash
# 影子行报告（只读）
python backend/scripts/_519_shadow_row_probe.py
# 清理骨架日影子行（写库，保守判据）
python backend/scripts/_519_shadow_row_probe.py --clean
# 直接核验：近两日按日汇总
sqlite3 data/duckdb/snapshot_cache.db \
  "SELECT trade_date, COUNT(*), SUM(dim_results_json IS NOT NULL) FROM strategy_signal_detail \
   WHERE trade_date>='2026-10-11' GROUP BY trade_date"
```
