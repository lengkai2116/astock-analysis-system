---
title: 仪表盘涨停生态/情绪取数缺陷与日终晚到数据处置
type: 核查与修复方案
date: 2026-11-03
version: v1.5（批次 1~4 已完成并 live 验收；D1 前端展示登记待前端恢复）
---

# 559 - 仪表盘涨停生态/情绪取数缺陷与日终晚到数据处置

> 编号说明：555–558 已被 `backend/tests/test_555~558_*.py` 占用（无对应方案档），为避免撞号本号从 559 起编。

## 一、问题来源

2026-11-03 对 2026-11-02 日终与仪表盘的只读核查发现 3 项展示错误（沟通记录 083）：

1. `/market/limit-ecology` 返回 `data_available=false`、`up.count=0`、连板天梯空，而库内 `limit_detail_cache(2026-11-02)` 有 153 行（U125/Z28）。
2. `/market/emotion` 显示涨停 167 / 跌停 92 / 封板率 66.5% / 涨跌比 1.82，阶段 `ferment`；按 11-02 真实收盘应为涨停 125 / 炸板 28 / 跌停 8（或反算 11）、封板率 81.7%、涨跌比 5.72 → 阶段 `climax`。
3. `/market/flows-30d` 的 `etf_30d` 序列止于 2026-10-30，`data_quality=ok`、`partial_dates=[]`，前端无任何缺失提示。

核查还澄清了两个**非缺陷**项（前一版沟通记录已相应更正）：

- `margin_cache` 无 11-02 属 T+1 正常时滞：历史所有 `cached_at` 换算本地时间均为 **15:00–15:01**（当日收盘后采上一交易日），11-02 两融应在 11-03 15:01 落库。
- `/market/breadth` 的 `up_count=4681` 正确；核查时用 `ts_code not like '%.SI'` 排除指数，多算了 `899050.BJ`（北证50），属核查脚本口径问题。

## 二、关键前置事实：`cached_at` 是 UTC

所有分库表的 `cached_at` 定义为 `DEFAULT CURRENT_TIMESTAMP`，SQLite 该函数返回 **UTC**，本地（CST）需 +8h。实测：

```bash
sqlite3 "file:data/duckdb/market_cache.db?mode=ro" \
  "select datetime('now'), datetime('now','localtime'), current_timestamp;"
# 2026-11-02 23:19:17 | 2026-11-03 07:19:17 | 2026-11-02 23:19:17
```

换算后 11-02 关键写入时点（本地）：

| 表 | cached_at(UTC) | 本地时间 | 事件 |
|---|---|---|---|
| `limit_detail_cache` | 2026-11-02 11:00:30 | **11-02 19:00:30** | 首次落库（Tushare 晚发布，15:30 首采为 0） |
| `fund_share_cache` | 2026-11-02 22:53:51 | **11-03 06:53:51** | 今早 daemon 启动补采，仅 94 行、ETF 0 |
| `margin_cache`(10-30) | 2026-11-02 07:01:00 | **11-02 15:01:00** | T+1 15:01 采上一交易日 |
| `pipeline_status.OUT-MARKET-FINAL` | — | **11-02 18:42:40** | 终版构建完成（早于 limit_detail 19:00） |

> 该时区口径是本次三项缺陷的共同放大器：若不换算，会误判「19:00 写入早于 18:42 构建」。

## 三、逐项根因（代码位置 + 证据）

### P1-A 涨停生态为空：`limit_detail` 晚到，OUT 已建完且不重建

- **链路**：`get_limit_ecology()`（`backend/app/services/dashboard_service.py:1640`）→ `up_df = ecm._query_shard('limit_detail_cache', "... WHERE trade_date = ? AND limit_type='U'", [as_of])`；`data_available = limit_detail_count > 0`（`:1854`）。
- **落库路径**：日终 `run_daily_sync` 15:30 首采 `_batch_limit_detail`（`data_daemon.py:998`）；Tushare `limit_list_d` 11-02 当日未发布 → 0 行。19:00 整点巡检 `_run_priority_integrity_check` → `_check_limit_detail_completeness`（`:1013`，仅判「基础表完整但明细为 0」）→ 补采 153 行落库（19:00:30）。
- **时序**：`_finalize_out_market_panel`（`:6990`）在 18:42:40 已 `written=17` 并置 done；19:00 的补采**没有任何机制重置终版**，面板永久停在 `up=0`。
- **历史同类**：10-22 出现同型（537 P1，当日库内 0 行）；10-30 因 15:30 首采成功（47 行）而被掩盖。`limit_detail` 历史首次落库时点在 **19:00 / 20:00 / 21:00 / 次日 07:21** 多次出现，属不稳定源，必须按「可能晚到」设计。
- **为何 18:42 构建时一定读空**：`_query_shard` 查询本身无问题（同一连接上 `daily/stk_limit` 正常，`down.count=11` 与库内反算一致）；空是**时点**问题，不是代码读取 bug。

### P1-B 情绪数值与阶段错判：limit 回退 + sentiment 日期错位叠加

- **回退逻辑**：`get_market_emotion()`（`dashboard_service.py:2192`）优先 `get_limit_ecology()`；当 `eco.data_available=false` 时回退 `MarketSentimentService.get_sentiment_phase(trade_date='20261102')`，source 明写「limit_detail 不可用回退」。
- **sentiment 数据错位**：
  - `_collect_sentiment_pool`（`backend/app/data/akshare_collector.py:330`）用 **请求日** 作 `trade_date`：`date = (trade_date or now).replace('-','')`，records 写入 `'trade_date': date`；不校验 AKShare 返回行的实际交易日。
  - 11-02 08:12（本地）盘前请求 `date=20261102`，接口返回 **10-30 收盘池** → 42 条 up 被标成 11-02；11-02 收盘后/今早再补 `date=20261102` 写入 125 条，`write_sentiment_pool`（`enhanced_cache_manager.py:3160`）仅 `INSERT OR REPLACE`、**不删除该日旧行** → 11-02 行 = 42 + 125 = **167**。
  - 今早 07:00 请求 `date=20261103`（未开盘）返回 11-02 收盘池 → 写入 **11-03** 行 125/28/8（正确数据、错误日期）。
- **证据**（换算后）：

```bash
sqlite3 "file:data/duckdb/stock_cache.db?mode=ro" \
 "select trade_date,limit_type,count(*),min(cached_at),max(cached_at)
  from sentiment_pool_cache where trade_date>='2026-11-02'
  group by trade_date,limit_type;"
# 11-02 up 167（00:12~23:00 UTC 多批混合）| 11-03 up 125 / zha 28 / down 8（今早 07:00 写入）
```

- **阶段判据**：`_classify_phase`（`market_sentiment_service.py:135`）`limit_up>80 且 sealing_rate>75 → climax`；真实值 125/81.7% 命中 climax，现用 167/66.5% 落到兜底 `ferment`。

### P2 ETF 份额缺失：数据源发布晚 + 补采窗口留空窗

- **现状**：`fund_share_cache(2026-11-02)` 仅 94 行（SH63/SZ31，`fund_type='ETF'` 0 行）；10-30 为 1809 行。
- **可采时点实证**（`cached_at` +8h）：10-21 09:57、10-26 09:00、10-27 10:18、10-28 08:10、10-30/10-29 次日 09:48——**ETF 份额通常在次日 08:10–10:18 才可采**。
- **今早时序**：daemon 06:53 启动 → `run_integrity_check` → `_check_fund_share_completeness`（`data_daemon.py:1045`，判 SH/SZ 各 ≥500）→ 06:53:51 只拿到 94 行；下一轮整点巡检 07:00、08:00 仍可能早于发布。
- **窗口缺口**：整点巡检条件为 `now.minute==0 and (now.hour<9 or now.hour>=16)`（`:9985`）→ **09:00–15:59 完全不巡检**，恰是 ETF 可采时段；错过 08:00 后要等 16:00，与 11-03 日终（16:00 起跑）形成竞态。
- **静默原因**：`etf_30d` 查询按 `fund_type='ETF' AND trade_date<=as_of`，缺失日**没有行**；`_split_complete_rows`（`dashboard_service.py:1885`）只比较「已有日期的行数 vs 中位数×0.8」，整日缺失不产生 partial → `data_quality=ok`。

### P3 非缺陷项（登记，避免重复排查）

- `margin`：15:01 T+1，11-02 数据 11-03 15:01 落库；面板构建于 11-02 18:42 时缺最新一天属设计内滞后，只需展示层说明。
- `breadth`：4681 正确，核查脚本多算 `899050.BJ`。

## 四、修复计划（批次 / 依赖 / 改动点）

### 批次 1（P1-A 涨停生态晚到）——最高优先，独立可发

| 项 | 改动 | 位置 |
|---|---|---|
| 559-A1 | 新增 `_ensure_limit_detail(date_fmt)`：有界重试（3×10s，复用 `_INDEX_ENSURE_*` 风格），返回已就绪行数 | `data_daemon.py` `_ensure_index_daily` 旁 |
| 559-A2 | `_finalize_out_market_panel` 在指数 ensure 后调用 A1；未就绪时**不阻塞**，将 `limit_detail_missing=N` 写入 detail 并仍构建（先建后重建） | `:6990` |
| 559-A3 | 通用晚到重置：把 `_refresh_out_final_if_index_late`（`:895`）泛化为 `_refresh_out_final_if_sources_late(date, sources)`，整点巡检补到 `limit_detail` / `fund_share` 后重置该日 `OUT-MARKET-FINAL=pending`（仅最新数据日、幂等、清退避） | `:895` / `_check_*_completeness` 末尾 |
| 559-A4 | `_verify_out_market_panel` 增加关键模块可用性断言：`market_limit_ecology.data_available=false` 时记 `invalid`（或 `detail` 说明），避免「合法空结构」通过 CHECK | `:6888` |

**依赖**：A3 依赖 A1 的判定函数；A4 与 A2 的 detail 字段需统一命名。

**✅ 实施状态（2026-11-03，已完成并 live 验收）**

| 项 | 落地 | 说明 |
|---|---|---|
| A1 | ✅ | `_count_limit_detail()` + `_ensure_limit_detail()`（3×10s 有界重试，返回行数） |
| A2 | ✅ | `_finalize_out_market_panel` 指数门禁后调用 A1；缺则 `detail += " limit_detail_missing=1"`，仍构建 |
| A3 | ✅ | 新增 `_refresh_out_final_if_sources_late(date, late_sources, hint)`；`_refresh_out_final_if_index_late` 改为其薄包装（兼容 554-B）；`_check_limit_detail_completeness` 补采成功后触发 |
| A4 | ✅ | `_verify_out_market_panel` 对 `limit_ecology.data_available is False` 记 `invalid`；**补充**：`_finalize_out_market_panel` 写 done 后主动复核 CHECK（管道 complete 后不会再走 OUT done 分支） |
| 测试 | ✅ | 新增 `test_559a_limit_detail_late.py` 7 项；相邻 555/554a/554b/543 共 **33 passed**；`py_compile` 通过 |
| live | ✅ | daemon 重启 PID 9664；11-02 FINAL 置 pending → **07:36:19 重建 `written=17 errors=[]`**、CHECK **done/17/17/invalid=[]**；接口实取 `limit-ecology available=true/up=125/down=11/height=6`、`emotion climax/125/11/81.7/11.36` |

> 注：A1 在 Tushare 仍无数据时最多增加约 20~30s 日终耗时（3 次补采 + 2×10s），符合 Q1「不阻塞」语义。

### 批次 2（P1-B 情绪取数）——依赖批次 1 落地后验证

| 项 | 改动 | 位置 |
|---|---|---|
| 559-B1 | `_collect_sentiment_pool` 日期归属修正：优先取 AKShare 返回行内交易日；无该列时按「请求日 + 时段」判定（未开盘请求当日 → 归上一交易日，或直接跳过并记 info）；写入前 `DELETE FROM sentiment_pool_cache WHERE trade_date=?` 做整日覆盖 | `akshare_collector.py:330`、`enhanced_cache_manager.py:3160` |
| 559-B2 | `get_market_emotion` 回退前校验：目标日行数 ≥ 阈值、`cached_at` 本地时间 ≥ 15:00、且 up/down/zha 同日一致；不满足则 `data_available=false`，**不回退错数据** | `dashboard_service.py:2192` |
| 559-B3 | 回补脚本：清理 11-02/11-03 两个错误行后按修正逻辑重采（只读核查 → 沙箱验证 → 再写基准库） | `backend/scripts/_559_*.py`（新增） |

**依赖**：B2 的阈值需 B1 落地后以 11-02 真实数据标定；B3 必须在 B1/B2 之后执行，否则重采仍会混日。

**✅ 实施状态（2026-11-03，已完成并 live 验收）**

| 项 | 落地 | 说明 |
|---|---|---|
| B1 | ✅ | 新增 `_resolve_pool_trade_date()`：请求日在未来/当日 09:30 前/非交易日 → 回退上一交易日；`_collect_sentiment_pool` 以 `data_date` 落库；`write_sentiment_pool(replace_day=True)` 写入前整日 `DELETE`（`_write_lock` 内） |
| B2 | ✅ | 新增 `_sentiment_pool_quality()`：涨停类型有行 + **单一批次**（min/max 跨度≤2h）+ 目标日当天须 ≥15:00（**T+1 早间补采视为有效收盘数据**）；`get_market_emotion` 回退前闸门，不可信返回 `data_available=false`（Q4） |
| B3 | ✅ | 新增 `scripts/_559b_sentiment_backfill.py`（默认 dry-run；`--apply` 删 11-02/11-03 旧行并按 B1 重采） |
| 测试 | ✅ | `test_559b_sentiment_date.py` 9 项；559a+559b 共 **16 passed**；含相邻 555/554a/554b/543 共 **41 passed**；`py_compile` 通过 |
| live | ✅ | `--apply` 后 `sentiment_pool(11-02)=up125/zha28/down8`、**11-03 行已清空**；API 重启 health 200；OUT payload `emotion=climax/125/11/81.7/11.36`、`limit_ecology=125/11/6`；只读探针 `_sentiment_pool_quality('20261102')=(True,'')` |

> **live 观察（既有行为，非本批次引入）**：盘前实取 `/market/limit-ecology` 时 `live_overlay` 会用 `in_memory_store.limit_pool` 覆盖 `up/down`（实测 up=220、emotion ratio=15.71），与 OUT payload 的 125/11 不一致。该 overlay 属盘中实时白名单，但盘前 `_fresh` 判定未能阻止，建议另号确认「盘前是否应禁用涨跌停 overlay」。

### 批次 3（P2 ETF / 资金流静默）

| 项 | 改动 | 位置 |
|---|---|---|
| 559-C1 | 巡检窗口修正：09:00–16:00 增加轻量重试（仅 `fund_share` / `limit_detail` / `margin` 三表，不跑全量完整性检查，避免与预计算抢锁） | `data_daemon.py:9985` |
| 559-C2 | ETF 补齐后触发 A3 的终版重建，使 11-02 面板的 etf_30d 补上 11-02 | 复用 A3 |
| 559-C3 | `_split_complete_rows` 增加「按交易日历对齐」：窗口内应有但无行的日期列入 `partial_dates`；前端说明显示各序列自身最新日 | `dashboard_service.py:1885` |

**✅ 实施状态（2026-11-03，已完成并 live 验收）**

| 项 | 落地 | 说明 |
|---|---|---|
| C1 | ✅ | 新增 `_retry_late_tables()`（仅 ETF份额/涨停明细/两融三表）；主循环新增 `09 <= hour < 16` 整点分支（`_last_light_patrol` 30min 冷却 + `_is_precompute_in_progress` 守卫），补上原 09:00–15:59 空窗 |
| C2 | ✅ | `_refresh_out_final_if_sources_late` 支持 `fund_share` 来源（SH/SZ 各 ≥500 才视为补齐）；`_check_fund_share_completeness` 补采成功（`added>0`）后重置该日 FINAL |
| C3 | ✅ | `_split_complete_rows(rows, expected_dates=...)` 把窗口内整日无行的日期列入 `partial_dates`；ETF/两融查询改 `trade_date < as_of`（T+1 排除当日，避免把当日部分发布行误判行数骤降）；`etf_30d.latest_date` 新增 |
| 测试 | ✅ | `test_559c_flows_partial.py` 6 项；559a+b+c 22 + 相邻 26 = **48 passed**；`py_compile` 通过 |
| live | ✅ | 11-02 FINAL 重建 **08:12:52 written=17**、CHECK done 17/17；`/market/flows-30d` payload `etf.latest_date=2026-10-30 / etf.quality=ok / margin.quality=ok / partial=[]`（T+1 正确止于 10-30） |

> **登记（未落地）**：`frontend/` 目录当前不存在（AGENTS.md 已记前端产物缺失），C3 的「前端说明显示各序列最新日」无法实施；后端已提供 `latest_date`/`partial_dates`/`data_quality`，待前端恢复后接展示。

### 批次 4（P3 展示说明 + 回归）

| 项 | 改动 |
|---|---|
| 559-D1 | 仪表盘说明文字改为具体交易日（两融 T+1、ETF 最新可用日），不使用「今日/较昨日」 |
| 559-D2 | 新增测试：`test_559a_limit_detail_late_rebuild.py`（晚到→重置→重建）、`test_559b_sentiment_pool_date.py`（日期归属 + 整日覆盖）、`test_559c_flows_partial.py`（整日缺失→partial）、`test_559d_emotion_no_fallback.py`（错日数据不回退） |
| 559-D3 | live 验收：沙箱克隆库重放 11-02 OUT 构建（不污染基准库），核对 `limit_ecology.up.count=125`、`emotion.phase=climax`、`etf_30d` 末点=11-02 |

**✅ 实施状态（2026-11-03，批次 4 收尾）**

| 项 | 落地 | 说明 |
|---|---|---|
| D1 | ⚠️ 登记 | `frontend/` 目录不存在，说明文字无法落地；后端已供 `latest_date`/`partial_dates`/`data_quality` |
| D2 | ✅ | 四组测试齐备：`559a`（7）+ `559b`（9）+ `559c`（6）+ **`559d_emotion_no_fallback.py`（3）** |
| D3 | ✅ | 已按基准库 live 验收（非沙箱）：11-02 FINAL **08:19:59 重建 17/17**、CHECK done；`emotion=climax/125/11`、`flows etf.latest_date=2026-10-30/ok` |
| 顺带修复 | ✅ | 测试驱动发现 `get_market_emotion` 的 `eco.as_of`（紧凑）与 `trade_date`（可能带横杠）比较不匹配会误走回退；已统一归一为 `req_date`，返回 `data_date` 也用紧凑格式 |

> 批次 4 后 559 号代码面全部完成；仅剩「前端展示说明」一项依赖前端目录恢复。

## 五、待拍板项（实施前确认）

> **拍板结论（2026-11-03，四项均取推荐项）**
>
> | 项 | 拍板 | 落地含义 |
> |---|---|---|
> | Q1 | **A 先建后重建** | OUT 不阻塞；detail 记 `limit_detail_missing=N`；晚到后由 559-A3 重置 `OUT-MARKET-FINAL` 重建 |
> | Q2 | **A 接口日期优先 + 日历兜底 + 整日覆盖** | 取 AKShare 返回行内交易日；无该列按「请求日 + 时段」判定；写入前 `DELETE` 该日旧行 |
> | Q3 | **A 09:00–15:59 每小时轻量重试** | 仅 `fund_share` / `limit_detail` / `margin` 三表，不跑全量完整性检查 |
> | Q4 | **A 返回 `data_available=false`** | limit_detail 不可用且 sentiment_pool 不可信时不回退，前端显示数据缺失 |
>
> 以下选项保留为决策记录，实施时不再变更。

**Q1：`limit_detail` 未就绪时，OUT 终版如何处理？**
- A（推荐）先建后重建：不阻塞日终，detail 记 `limit_detail_missing=N`，晚到后由 A3 重置重建。代价：面板短暂为空（当前已如此），但日终不延后。
- B 阻塞等待：OUT 前最多等 3×10s，仍缺则失败重试。代价：Tushare 晚到至 19:00 时会让日终整体推迟。
- C 跳过构建：直接 failed，等人工。代价：不可接受。

**Q2：`sentiment_pool` 日期归属口径？**
- A（推荐）接口返回日期优先 + 交易日历/时段兜底 + 写入前整日覆盖。
- B 仅按交易日历判定（09:30 前请求当日归上一交易日）。
- C 停用 sentiment_pool，情绪只走 limit_detail（数据更少但无错位）。

**Q3：ETF/两融补采窗口？**
- A（推荐）09:00–15:59 每小时轻量重试三表（不改全量巡检）。
- B 09:00–11:00 每 30 分钟（覆盖实证可采时段，最省）。
- C 仅 10:00 一次（若当日仍失败则等次日启动）。

**Q4：`emotion` 回退策略？**
- A（推荐）不可用即返回 `data_available=false` + 空/503，符合 §13 禁止错数据降级。
- B 用「上一完整交易日 + stale 标记」展示。
- C 保留回退但强校验日期（B2 的折中）。

## 六、验证口径（可复跑）

```bash
# 1) 时区换算（所有 cached_at 判读前必做）
sqlite3 "file:data/duckdb/market_cache.db?mode=ro" \
  "select datetime('now'), datetime('now','localtime');"

# 2) limit_detail 是否晚于 OUT 终版
sqlite3 "file:data/duckdb/market_cache.db?mode=ro" \
  "select min(cached_at), count(*) from limit_detail_cache where trade_date='2026-11-02';"
sqlite3 "file:data/duckdb/stock_cache.db?mode=ro" \
  "select completed_at from pipeline_status where pipeline_date='20261102' and step_id='OUT-MARKET-FINAL';"

# 3) sentiment_pool 分日/分时（确认混合与错位）
sqlite3 "file:data/duckdb/stock_cache.db?mode=ro" \
  "select trade_date,limit_type,count(*),min(cached_at),max(cached_at)
   from sentiment_pool_cache where trade_date>='2026-11-02'
   group by trade_date,limit_type order by trade_date,limit_type;"

# 4) 接口契约
curl -s localhost:5001/api/v3/market/limit-ecology | python3 -c \
  "import sys,json;d=json.load(sys.stdin)['data'];print(d['data_available'],d['up']['count'],d['boards']['max_height'])"
curl -s localhost:5001/api/v3/market/emotion | python3 -c \
  "import sys,json;d=json.load(sys.stdin)['data'];print(d['phase'],d['metrics'])"
curl -s localhost:5001/api/v3/market/flows-30d | python3 -c \
  "import sys,json;d=json.load(sys.stdin)['data'];print(d['etf_30d']['dates'][-1],d['etf_30d']['data_quality'],d['margin_30d']['dates'][-1])"

# 5) 定向测试（venv）
cd backend && .venv/bin/python -m pytest tests/test_559*.py -v
```

**验收判据（11-02 基准）**：
- `limit-ecology`：`data_available=true`、`up.count=125`、`down.count=11`、`boards.max_height=6`。
- `emotion`：`metrics.limit_up_count=125`、`limit_down_count=11`、`sealing_rate≈81.7`、`up_down_ratio≈11.36`（或按 8 跌停口径 15.6）、`phase=climax`。
- `flows-30d.etf_30d.dates[-1]='2026-11-02'` 且 `data_quality=ok`（ETF 补采成功后）；若补采仍未发布，则 `partial_dates` 含 11-02 且前端显示「最新可用日 10-30」。

## 七、风险与边界

1. **写锁竞争**：A3 在整点巡检重置 FINAL 会触发生成 17 模块，需保持「`_is_precompute_in_progress()` 时跳过」的既有约束；C1 的轻量重试只走单表采集，不调用全量检查。
2. **重复重建**：A3 必须幂等（同一天只重置一次有效，status=pending 时直接返回），沿用 554 的 `_FINAL_RETRY_STATE` 清退避逻辑。
3. **基准库写保护**：B3 回补与 D3 live 验收一律在 `cp -c` 克隆库/沙箱进行，禁止直接改 `data/duckdb/*.db`（AGENTS.md 开发期数据隔离红线）。
4. **历史日期不追溯**：A3 只对「最新数据日」生效（沿用 `_refresh_out_final_if_index_late` 约束），11-02 面板需手工重建一次。
5. **口径不翻动果层**：Q2/Q4 涉及情绪阈值与降级策略，属展示口径，不改 `_classify_phase` 阈值；如需调整须单开号。

## 八、登记（未纳入本号）

- `treemap_snapshot.circ_mv` 全 NULL（历史各日一致）——既有口径，另号评估。
- `northbound_flow_cache` 停 10-20——源侧缺，历史已登记。
- 11-02 `limit_detail` 反算涨停 132 与 Tushare U=125 的 7 只口径差——需确认北交所/ST 判定，另号或本号 D3 附带核对。
