
---
title: SIG 素材缺口（stk_holder 等大量补采）追查
type: 追查/勘查方案（素材缺口根因定位与处置）
date: 2026-09-15
version: v1.0
status: ✅ 已实施（A 根治 + B 补采 + C 清脏 + D 通道②增强；E 无需改动）
related:
  - 436-SIG文字类输出修复方案（B3 重算日志首次暴露此现象）
  - 419-dim1门禁数据校验/补采通知（缺口症状触发点）
  - 440-SIG素材质量前置修复（素材质量姊妹题）
  - 439-SIG素材摸底与功能区隔核查（素材完整性摸底）
---

# 441 — SIG 素材缺口（stk_holder 等大量补采）追查

> **定位**：436 号 B3 生产重算日志暴露**系统性素材缺口**——SIG 全市场重算触发大量「dim1通知daemon补采」，以 `stk_holder` 为绝对主导（490 条/占 71%）。本号单独开号，量化缺口规模、定位根因、区分「真缺陷 / 假误报 / 正常待办」，供用户拍板处置方式。

---

## 〇、现象（2026-09-15 从 436 B3 重算日志取证）

436 B3 重算 09-14 SIG 全市场 5586 只（`shell-bg_212d63fb.output`，710.7s），日志中 **`dim1通知daemon补采` 共 694 条 / 涉及 506 只**：

| task_type | 计数 | 占比 | 语义 |
|---|---|---|---|
| **stk_holder** | **490** | 71% | 股东人数缺口 |
| precompute_indicators | 56 | 8% | indicator 预计算缺口 |
| precompute_raw | 47 | 7% | pre_feat ext 组缺口 |
| finance_report | 39 | 6% | 财务指标缺口 |
| full_moneyflow | 31 | 4% | 资金流缺口 |
| full_basic | 31 | 4% | 基础数据缺口 |

**触发链路**（非根因，是症状）：`dim1_signal_engine.py:222` — 门禁校验 `missing_tables` 非空 → `_notify_missing_data`（:298）→ 后台线程 `dm.request_data(task_type, ts_code)`（:353）→ daemon 30s 主循环消费 `sync_requests` 补采。**缺失项全为「可选 optional 素材」**（非 required `daily_df`），故不阻塞 SIG 主产出（7 键报告仍 100% 完整），只影响富字段（如 `main_force_presence`）。

---

## 一、stk_holder 缺口量化（只读 DB 证据）

`strategy_signal_detail`（snapshot_cache.db）09-14 目标票 **5586** 只；`stk_holder_cache`（history_cache.db）去重 **5093** 只 → **缺口 499 只（8.9%）**。

### 板块分布（缺口主导：深市主板 + 申万指数）

| 板块 | SIG目标 | stk_holder覆盖 | 缺口 |
|---|---|---|---|
| 000（沪主板指数+老深主板） | 413 | 145 | **268** |
| 001 | 121 | 47 | **74** |
| 002 | 917 | 835 | **82** |
| 801（申万一级指数） | 31 | 0 | **31** |
| 300/301（创业板） | 1404 | 1378 | 14 |
| 600/601/603/605/688（沪主板/科创） | 2311 | 2311 | ~0 |
| 920/899（北交所） | 344 | 334 | 9 |

**关键反证**：缺口列表含 `000001.SH`（上证指数）、`000300.SH`（沪深300）、`399001.SZ`（深证成指）、`801010.SI`（申万行业指数）——**指数标的根本不存在「股东人数」数据**，却被 dim1 门禁误判为「素材缺失」→ 触发无意义补采。指数类缺口约 **40 只**（.SH/.SI/399 样本），属**假误报**。

### 未来脏日期（数据异常）

`stk_holder_cache` 存在 `end_date='2027-06-30'` 的未来行（`002328.SZ`, holder_number=36900，1 行）；`end_date<'2026-01-01'` 共 27574 行（历史残留）。**未来日期是采集写入的脏数据**，可能干扰时效性判断。

---

## 二、根因分析（待进一步确认项标 ⚠）

1. **深市主板真实缺口（000/001/002，~420 只）**：`_batch_stk_holder.py`（data_daemon:1307）批量路径只取**最近一个月** `end_date = now月初-30天` 的 `pro.stk_holdernumber`。Tushare 的 `stk_holdernumber` 批量返回的是**该报告期已披露的公司集合**，深市主板若当期未披露/披露批次错位，则整组不返回 → 缺口。需确认是「Tushare 未披露（正常）」还是「应补未补（缺陷）」。
   ⚠ 需核对：000/001/002 板块在 Tushare `stk_holdernumber` 是否确有数据，还是接口本身不覆盖深市主板股东户数。
2. **指数误报（~40 只，明确缺陷）**：dim1 门禁对指数类标的（`.SH` 指数、`.SI`、`.SZ` 指数）也跑 `get_cached_stk_holder` 判空 → 必然缺 → 误发补采。**指数不应有 stk_holder 依赖**。
3. **未来脏日期（1 行，数据写入异常）**：`end_date=2027-06-30`，疑似采集时 `end_dt` 计算或数据源异常回填。
4. **其他类型（precompute_indicators/raw、finance_report、moneyflow/basic）**：56+47+39+31+31=204 条，覆盖 301xxx 及之后批次（SH/北交所）扩展为多类型补采。需区分「重算批次过新/缓存未及」vs「素材真缺」。

---

## 三、处置选项（供用户拍板）

| 方案 | 动作 | 影响面 | 建议 |
|---|---|---|---|
| **A** 指数豁免 | dim1 门禁对指数类标的跳过 stk_holder/lhb 等仅个股适用素材的缺失判定与补采通知 | 消灭 ~40 条假误报中的指数项；需确认指数标的清单判定规则（后缀 `.SI` / `.SH` 指数代码段 / `399*.SZ` / `801*.SI`） | ✅ 低成本、明显正确 |
| **B** stk_holder 批量采集增强 | `_batch_stk_holder` 批量路径按多月份段回溯 / 改按板块覆盖补采，补齐深市主板缺口 | 补 ~420 只缺口；需控制 Tushare 积分/频率 | 需先核对 Tushare 是否真覆盖深市主板（§二-1 ⚠） |
| **C** 脏日期清理 | 删除/修正 `end_date='2027-06-30'` 未来行，规范采集日期上界 | 1 行，低风险 | ✅ 顺手清理 |
| **D** 素材缺口仅告警不补采 | 将可选素材缺口从「补采通知」降级为「QA-CHECK 软告警」，避免 SIG 重算触发海量后台补采 | 降低 daemon 补采风暴；需权衡富字段完整性 | ⚠ 需用户权衡 |
| **E** 追查其他缺口 | 对 precompute_indicator/raw、finance_report、moneyflow/basic 缺口逐类定位 | 覆盖 §二-4 | 建议作为 B3 之后独立勘查 |

> **本文档性质**：追查取证（只读 DB + 日志，**未修改任何代码**）。取证依据：`snapshot_cache.db` / `history_cache.db` 只读查询、`shell-bg_212d63fb.output` 重算日志统计、`dim1_signal_engine.py` 缺失判定与补采通知链路、`data_daemon.py:1307 _batch_stk_holder` 采集语义。
>
> **下一步**：用户拍板处置组合（建议 A + C 先落地，B 需先核对 Tushare 覆盖，D/E 独立评估）。

---

## 四、实施记录（2026-09-15 用户拍板：A + C + B）

**用户裁定**：处置 = **A（指数豁免）+ C（清脏日期）+ B（补采 stk_holder 深市缺口）**；A 落点拍板 = **改 `_get_active_codes`（根治，非 dim1 局部豁免）**。D/E 未选，另行独立评估。

### A. 指数豁免 — 根治（已实施）
**根因修正（比初诊 §三-A 更彻底）**：`_get_active_codes`（`data_daemon.py:4185`）是全管道（RAW/SIG/JUD）统一股票池入口，**原实现直取 `daily_cache` 全部 `ts_code` 未剔指数**（对比 `:490` 相对强弱函数已剔）→ SIG 目标混入 **36 只指数**（31.SI + 000001/000300.SH + 399001/399006.SZ），全部对 stk_holder 误报补采。
- 改动：`_get_active_codes` 剔除 `BROAD_INDEX_CODES ∪ SW_INDEX_CODES` + 通用段规则（`.SI` 后缀 / `399` 开头）。
- 验证：09-14 票池 5586 → **5550**（剔 36 指数），剔除后残留指数为空，不误伤个股。85 passed 全回归。

### B. stk_holder 补采 — 深市缺口（已实施）
**前提核实通过**：Tushare `stk_holdernumber` 对深市主板缺口票**有数据**（000002.SZ 150 行、000006.SZ 121 行）——缺口是**批量按 end_date 只覆盖该报告期公司、深市主板披露错位漏采**，非数据源限制。B 可行。
- 新建 `scripts/_441_backfill_stk_holder.py`（复用 daemon 单只补采路径 `provider.get_stk_holdernumber → cache_stk_holder_data`）。冒烟 3 只通过 → 全量补采 **451 成功 / 9 失败空**。
- 残留 **9 只缺口全为 `920*.BJ` 北交所**（Tushare `stk_holdernumber` 不覆盖这批股东户数记录；对照 334 只北交所已有数据，属个别票无素材）。stk_holder_cache 去重 5093 → **5547**。
- 备份：`history_cache.db.bak_441_20260915`。清除未来脏日期前 09-14 SIG 缺口 499 → 补后 9。

### C. 脏日期清理（已实施）
- `stk_holder_cache` 删除 `end_date='2027-06-30'`（`002328.SZ`, holder_number=36900）未来脏行 1 行；该票保留 3 条历史记录不误删。

### 残留与后续
- 北交所 9 只缺口：Tushare 数据源不覆盖，属已知限制；若 daemon 未来支持北交所股东户数再补。
- **D（可选素材缺口软告警化）**、**E（precompute_indicators/raw、finance_report、moneyflow/basic 其他缺口逐类追查）**：用户未选，未实施，单独评估时重开本号或新号。
- 已确认 data_daemon 改动后 85 passed（436 契约 / 423 门禁 / 411 管道 / B3 沙盒）。

---

## 五、D 项追问结论：降级软告警后「补采通道」是否会断（2026-09-15 用户追问）

**用户问题**：可选素材缺失降级为软告警记日志后，系统迁移独立运行情况下，后续是否还会安排补采？

**核查结论：会有两条独立通道，软告警只关掉其中一个**——

1. **通道①（dim1 通知 → sync_requests 后台补采）**：`dim1_signal_engine` 门禁判缺 → `_notify_missing_data` → `dm.request_data(task_type, ts_code)` 写 `sync_requests` → daemon 30s 主循环消费 `_process_sync_requests` 逐只补采。**若 D 落地（降级为日志），此通道关闭**——dim1 不再发补采通知，仅记 QA-CHECK 软告警。

2. **通道②（run_integrity_check 完整性检查兜底）**：daemon **开机/整点巡检** 的 `run_integrity_check` 里 `batch_background = [(stk_holder_cache, _batch_stk_holder), (finance_report_cache, ...)]`——当这些表**为空表**（`COUNT(*)=0`）时触发**批量全市场补采**。此通道**独立于 dim1 通知**，不受 D 降级影响。

**⚠ 关键盲区（须用户知晓）**：通道②只对**空表**启动批量补采。本次缺口是「**非空表但个股级缺失**」（stk_holder_cache 有 5093 只，缺 456 只个股）——通道② **抓不到这种"局部缺失"**，只有通道①（dim1 个股级通知）能补。若 D 落地且只依赖通道②，则「非空表 + 个股缺失」这类缺口在独立运行后**将不再被自动补采**，只能靠重算/巡检人工发现。

**由此修正 D 的权衡**：D 的"降级软告警"会削弱个股级补采能力——**除非同时增强通道②**，使其从"空表检查"升级为"按股覆盖检查"（即完整性检查里也核对每个 active_code 是否在 stk_holder_cache，缺则补）。**若只做 D 不做通道②增强，则迁移独立运行时富字段会持续缺失且无自动补采。**

### D 项落点（用户拍板 2026-09-15：**增强通道②为按股覆盖巡检**，已实施）

**改动**（`data_daemon.py`，99 passed 无回归）：
1. **单只补采辅助提取为模块级**（`_sync_single_finance` / `_sync_single_stk_holder` / `_sync_single_top10_holders`），429号 单只路径与覆盖巡检统一收口（`_consume_sync_requests_batch` 原内联辅助删除复用）。
2. **新增 `_reconcile_cache_coverage(max_codes=40)`**：取全管道股票池（`_get_active_codes`，441号A 已剔指数）→ 对照 `top10_holders_cache` / `stk_holder_cache` / `finance_report_cache` 的 `DISTINCT ts_code` 集合求差集 → 对缺失个股按 **max_codes 上限限流逐只单只补采**（防单 tick 打爆 Tushare 积分，剩余下轮收敛）。
3. **`run_integrity_check` 的 batch_background 增强**：空表仍批量补采；**非空表进入覆盖核对**（三表全空则本轮跳过，避免重复全市场单只补采）。

**只读验证**（真实分库，未真调补采）：active 池 5550 只 → 股东人数 covered 5547 / 缺 **9 只（全为 920*.BJ 北交所，已知 Tushare 限制）**；前十大股东 covered 4427 / 缺 **1324**；扩展财务 covered 5396 / 缺 **162**（001xxx 次新为主）。缺口识别正确，巡检将按上限限流逐步补采。

**一次性全量预补**（2026-09-15 用户拍板执行，`scripts/_441_backfill_coverage.py`）：
- 备份 `history_cache.db.bak_441_d_20260915_161157` → 冒烟 2 只/表验证 → 全量。
- **前十大股东 1321 只全补成功**；**扩展财务 160 只全补成功**；**股东人数 9 只全为 920*.BJ（Tushare 数据源无素材，失败/空 9，非缺陷）**。
- 补后只读验证：前十大股东 covered 5751 / 缺 **0**；扩展财务 covered 5558 / 缺 **0**；股东人数 covered 5547 / 缺 **9（全 920*.BJ）**。三表素材缺口已收敛至仅剩北交所数据源限制项。
- 脚本支持 `--smoke N`/`--table top10|stk|finance|all`/`--no-backup` 复用。

> **D 与 E 的收口**：D 落地后，个股级富字段缺口（通道②覆盖核对）与非空表残留均可被逐只自动补采，不再依赖 dim1 通知（通道①）。E 类真个股缺口为次新股日线不足（非缺陷），不受本增强影响。`_COVERAGE_RECONCILE` 为需维护清单——新增富字段素材表需同步登记。

> **D 项已闭环（2026-09-15）**：用户拍板采用「增强通道②为按股覆盖巡检」。至此 441 号 A/B/C/D 全部实施，E 无需改动（次新股自然缺口）。残留仅北交所 9 只 Tushare 限制。

---

## 六、E 项追查结论：其他缺口（precompute/finance/moneyflow/basic）逐类定位（2026-09-15 只读核查）

**结论：E 类 204 条补齐通知 = ①指数假误报（已随 441-A 根治）+ ②次新股自然缺口（非缺陷）。无真缺陷待补。**

### 6.1 分类量化（重算日志 09-14 取证）

| task_type | 通知条数 | 指数类（假误报） | 真个股缺口 |
|---|---|---|---|
| precompute_indicators | 56 | 30 | **14** |
| precompute_raw | 47 | 31 | **10** |
| finance_report | 39 | 31 | **4** |
| full_moneyflow | 31 | 31 | 0 |
| full_basic | 31 | 31 | 0 |
| **合计** | **204** | **154** | **18 只去重** |

指数类判据完全对齐 441-A 剔除集（`.SI` + `000001.SH`/`000300.SH` + `399001/399006.SZ` + `899050.BJ`），**与 stk_holder 假误报同一根因**——`_get_active_codes` 曾把 36 只指数混入 SIG 目标。**A 落地后 SIG 不再对指数跑 dim1 门禁，这批 154 条假误报已根治**，无需单独处置。

### 6.2 真个股缺口（18 只去重）—— 次新股自然缺口，非缺陷

只读核查（`_441_e_audit_readonly.py`）确认：这 18 只**全部为 2026-07-30 之后上市的次新股**，日线行数 **6~33 行（无一 ≥60）**：

| ts_code | 首日 | 行数 | ts_code | 首日 | 行数 |
|---|---|---|---|---|---|
| 603448.SH | 09-07 | 6 | 688826.SH | 08-18 | 20 |
| 301688.SZ | 09-02 | 9 | 301655.SZ | 08-20 | 18 |
| 301697.SZ | 09-01 | 10 | 688835.SH | 08-25 | 15 |
| 601123.SH | 09-01 | 10 | 301677.SZ | 07-30 | 33 |
| 301707.SZ | 08-07 | 27 | 688828.SH | 08-11 | 25 |
| 301717.SZ | 08-11 | 25 | 001232.SZ | 08-04 | 30 |
| 603468.SH | 08-06 | 28 | 688836.SH | 08-19 | 19 |

**根因**：
1. **precompute_indicators 14 只** → `_precompute_indicators`（data_daemon.py）按 414号 R6 阈值 **`len(df)>=60` 才计算指标**（确保 MA60/MACD 有效）。次新股日线不足 60 行 → **被跳过属正常设计**，非缺陷。随持有期增长补齐到 60 行后自动可得。
2. **precompute_raw 10 只** → `pre_feat_cache` 当前**全部已覆盖**（0 缺）。预计算 RAW-2 对次新股是走通的，日志中的 10 条为当轮缓存未及时，已由管道补上。
3. **finance_report 4 只** → 同 14 只次新股（301688/301697/601123/603448 交集），`fina_indicator_cache` 缺即日线不足 60 行的同批新股。个股级单只补采（429号）对它们已能覆盖财务主表，指标级依赖日线长度属正常。

### 6.3 通道②补采覆盖面（E 项对照 D 前提）
`run_integrity_check` 的 `batch_background` 覆盖 `finanace_report_cache`（空表触发）；`precompute_*` / `moneyflow` / `basic` **不在 batch_background 内**，由 P3 管道（`RAW_STEPS`）统一预计算 + `full_moneyflow/full_basic` 走 sync_request 分支。**与 D 盲区一致**：个股级富字段缺口仍依赖 dim1 通知（通道①）。

> **E 处置**：**无需改动**。指数假误报已由 A 根治；真个股缺口为次新股日线不足的自然现象，随上市时间自动缓解，非系统缺陷。
> **只读证据**：全部来自 DB 只读查询（`indicator_ma`/`pre_feat_cache`/`fina_indicator_cache`/`daily_cache` 分库），未修改任何数据；核查脚本 `scripts/_441_e_audit_readonly.py`（可复跑，幂等）。
