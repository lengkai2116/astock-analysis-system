---
title: 553-数据源能力评估与日终按源就绪定序（TdxQuant/同花顺/mootdx/Tushare）
type: 方案
date: 2026-10-29
status: 已开号（只读研究完成；机制待实施；553-A/B/C/D 待拍板）
depends:
  - 552（日终跨夜治理 A/B/C/E）
  - 543/548（日终完成保障、数据日解析）
  - 425/426（采集优先级与管道驱动）
---

# 553｜数据源能力评估与日终按源就绪定序

## 一、背景与问题

2026-10-28 日终，552 号四件套全部生效：552-A 于 **16:32:47** 探测到当日日线并提前起跑，552-B 15:35 独立同步财务，552-C RAW-2 六子进程 **446.3s**（旧实现 8333s），全链路 **16:32:47→19:15:40 = 2h42m53s**，不跨夜。

但同一天暴露了一个更基础的问题：

- `pipeline_status(20261028)` 的 **COL-1~5 在 16:33:20 全部标 done**（detail="数据已完整，采集跳过"），实际 `daily_basic_cache/moneyflow_cache/stk_limit_cache` 的 10-28 行直到 **20:01** 才由完整性检查补入；
- 后果：RAW-2 沿用 10-27 估值（`000001.SZ` 两日 valuation 完全相同）、OUT 缺 `market_overview_panel`（16/17）、QA 报三表 `0/5291`（**真告警**）、`OUT-MARKET-CHECK` failed、看门狗 20:46/21:16 持续告警。

用户 2026-10-29 口径：**不要把起跑写死在 18:00**；先核实各数据源「当日数据什么时候才有」，再按就绪顺序依次启动。

本方案要解决两件事：

1. 用实证数据回答「各源最早可采时点」；
2. 把日终从「时钟驱动」改为「数据就绪驱动」，并把 COL 跳过判据改成「本表本日行数达标才 done」。

同时评估三类替代/补充数据源：通达信 mootdx、同花顺公开端点、通达信 TdxQuant。

## 二、实证：各源当日数据可采时点

`cached_at` 是采集器**写入时间**（库内存 UTC，按 +8h 折 CST），只能证明「该时刻已可采」，是上界而非首达时刻。

| 数据源 | 最早写入（CST） | 说明 |
|---|---|---|
| Tushare `daily` | **2026-10-28 16:32:47** | 552-A 16:30 探测即返回 5570 行 |
| `daily_basic` | **2026-10-23 16:07:15** | 5572 行 |
| `moneyflow` | **2026-10-23 16:07:17** | 5577 行 |
| `stk_limit` | **2026-10-21 15:03:35** | 5654 行（涨跌停价盘前可得） |
| `lhb` 龙虎榜 | 多数日 18:01；10-23 20:08 | 交易所披露偏晚，不宜做关键路径 |
| `margin` 两融 | 次一交易日 15:00 | T+1 结构，不应阻塞当日 |
| `concept` 概念 | 无日期，随时 | AKShare |

**结论**：18:00 是历史定时，不是源发布时点；`stk_limit` 15:03、`daily` ≤16:30、`daily_basic/moneyflow` ≤16:07 均已实证可采，起跑可以大幅提前。

**精确首达时刻**用当日只读探针实测（已落地）：
`backend/scripts/_552_source_probe.py`
- 15:00 起每 5 分钟一轮，至 20:30 或关键四表+同花顺日线全就绪提前结束；
- 只读：不写库、不 import `data_daemon`、不 `create_app`、不起采集器；
- 输出 `logs/source_probe_20261029.{log,jsonl}` 与 `_summary.json`（首达时刻）；
- 阈值 `max(4000, 10-28 行数×95%)`：daily 5325 / daily_basic 5291 / moneyflow 5297 / stk_limit 5370。

## 三、数据源能力评估

### 3.1 Tushare（当前主源）

- 覆盖：日线、每日指标、资金流、涨跌停价、龙虎榜、两融、财务、指数等，是**基本面/资金流/龙虎榜的唯一现成来源**。
- 时效：见 §二，16:07~16:30 可采。
- 风险：单点依赖；接口发布时点可能漂移；免费配额有限。

### 3.2 通达信 mootdx 0.11.7（当前实时/分钟）

| 模式 | 构造 | 能力 | 实测 |
|---|---|---|---|
| **std**（现用） | `Quotes.factory()`；默认 `server=None, bestip=False, timeout=15, heartbeat=False, auto_retry=True` | `quotes/bars/minute(s)/transaction(s)/finance/block/xdxr/stocks/index/F10` | 可用；项目仅用 `stocks()`/`minutes()`/`index()`，盘中实时另走新浪/腾讯/东财三路 HTTP |
| **ext** | `Quotes.factory(market='ext', timeout=6)` | 扩展市场（期货/期权/港美股） | **本机 120s 无返回**，不可用 |

**可调优项**（只改善稳定性，不改变可采时点）：
`bestip=True`（自动选最快 TDX 服务器）、`heartbeat=True`、显式 `server=[...]` 多服务器 + `reconnect()`、`timeout` 15s→8s。

**结论**：通达信侧不存在「另一种连接方式拿到不同类型数据」的增量；std 已覆盖 A 股全部类型，ext 是扩展市场且本机不可用。

### 3.3 同花顺公开端点（免鉴权，实测可用）

| 端点 | 内容 | 实测 |
|---|---|---|
| `v6/realhead/hs_<code>/defer/last.js` | 实时快照（价格、买卖盘、成交额） | 200，JSONP 可解析 |
| `v6/time/hs_<code>/last.js` | 当日分时（0930–1500 逐分钟，含 `date`） | 200，含 20261028 全天 |
| `v6/line/hs_<code>/01/last.js` | 日线 140 根（date/OHLC/volume/amount/换手） | **129ms**，末根已含 20261028 |

- **不含**：基本面（PE/PB/市值）、资金流、龙虎榜、两融。
- `quantapi.10jqka.com.cn`：同花顺数据接口（QuantAPI）门户，需账号/API Key，**不能匿名取数**。
- `fuyao.aicubes.cn`：同一 CDN 页面（与 quantapi 同解析到 60.204.3.68），**不是行情 API**。

**结论**：同花顺适合做 daily/分钟/实时的**兜底与交叉校验**（延迟低、稳定性好），不能替代 Tushare 的基本面/资金流。

### 3.4 通达信 TdxQuant（help.tdx.com.cn/quant，全量研读）

**平台定位**：财富趋势（通达信）的 Python 量化框架，覆盖策略研发→回测→模拟→实盘。

**两种运行模式**：

| 模式 | 依赖 | 取数入口 | 能力边界 |
|---|---|---|---|
| **tqcenter** | 必须先开支持 TQ 的通达信终端（金融终端/专业研究/量化模拟/期货通） | `from tqcenter import tq; tq.initialize(__file__)` | 行情+交易+公式执行+客户端交互 |
| **tqserver / TdxAiData** | `pip install tdxaidata`；跨平台（`.dll/.dylib/.so`）；需 `TdxAiData.ini` 配置**数据服务 Key**（商城会员中心创建） | `from tdxaidata import tqs` | 只做数据查询与订阅；无交易、无公式执行、无客户端交互 |

- 运行环境：64 位 Python 3.7–3.14（建议 3.13）。
- 本地 HTTP：`POST http://127.0.0.1:17709/`，`method`=函数名、`params`=参数，返回 JSON（`result.Value.<code>` 含 OHLCV/Amount/Date/ForwardFactor 及分页字段）；前提是客户端已开。
- 数据覆盖：A 股/港股/美股/新三板行情与财务；ETF/LOF/REITs；沪深京/板块/港股/中证国证指数与成分股；通达信行业/概念/风格板块；六大期货交易所；宏观（`.HG`）；可转债/个股期权；`download_file` 数据文件包（含龙虎榜、限售解禁、经营分析、舆情，按版本增加）。
- 周期：`1m/5m/15m/30m/1h/1d/1w/1mon/1q/1y`，云端公式专用 `5s/10s/15s/20s/fst/auc`；复权 `none/front/back`，同时返回 `ForwardFactor`。
- 函数（文档可确认）：
  - 通用：`download_file`、`get_market_data`、`get_market_snapshot(_batch)`、`get_stock_info(_batch)`、`get_more_info(_batch)`、`get_pricevol`、`get_zdt_data`、`get_exday_data`、`get_divid_factors`、`get_relation`、`get_trading_dates`、`get_ipo_info`、`get_gb_info(_by_date)`、`get_financial_data(_by_date)`、`get_gpjy_value(_by_date)`、`get_bkjy_value(_by_date)`、`get_scjy_value(_by_date)`、`get_gp_one_data`、`formula_process_mul_xg/zb/exp`、`formula_by_src/file`、`get_trackzs_etf_info`、`get_kzz_info(_batch)`。
  - tqserver 特有：`get_global_data`、`get_misc_data`、`get_tick_data`、`get_minute_data`、`get_zzgz_stocklist`、`get_call_auction(_batch)`、`get_domain_sorthq`、`subscribe/unsubscribe`。
  - 交易：`order_stock`、`cancel_order_stock`、`query_stock_asset/orders/positions`、`stock_account`、`send_user_block`、`send_warn`、`exec_to_tdx`。
- 常量：市场后缀（`.SZ/.SH/.BJ/.NQ/.SHO/.SZO/.HK/.US/.CSI/.CNI/.SSI/.HG/.CFF/.CZC/.DCE/.SHF/.GFE/.INE/.HI/.OF/.SGE/…`）、复权、周期、`order_type`（0–206）、`price_type`（自填/市价/涨停/跌停）、委托状态（0–5）。
- Lambda 平台：回调 `init/before_trading/handle_bar/after_trading/on_strategy_end/on_order/on_trade`；**禁止 import**、禁止文件/网络/进程/系统操作、pandas/NumPy 仅内存计算；请求体 `req/symbols/blocks/start_date/end_date/frequency/initial_cash`；有防未来函数规则。
- AI Skills：`tdx-tq-local.zip`、`tdx-aidata.zip`、`tdx-lambda.zip`，供 WorkBuddy/TRAE Work/CodeX/TdxClaw 安装。
- 版本：2026-01-17 正式发布 → 2026-10-23 v1.3.1；关键节点：2026-09-04 支持 tqserver 后台模式；2026-07-10 `download_file` 支持龙虎榜；2026-03-20 交易函数；2026-01-31 公式调用；2026-10-16 `formula_by_src/file`；2026-10-23 5s/10s/15s/fst/auc 公式计算（**10-16/10-23 标注仅内测版**）。
- 文档缺口：`财务类数据`、`通用函数`、`分类/板块成份股`、`自选股/自定义板块`、`ETF/可转债/期货数据`、`场景化示例`、`调用通达信公式`、`交易函数`、`TdxAiData特有函数` 共 9 页只有标题（正文未发布）；站点**未写各接口数据更新时间、TdxAiData Key 计价/配额、tqcenter 是否支持 macOS 客户端**。

**结论**：TdxQuant 是唯一能提供「通达信公式引擎 + Level-2 资金 + 竞价 + 分笔 + 港股/美股/期货/期权/宏观」的源，但需要客户端或付费 Key；对当前 Mac 常驻 daemon 而言，`tqserver` 跨平台但需 Key，`tqcenter` 依赖客户端（Windows 为主）。

## 四、对比与结论

| 维度 | Tushare | mootdx std | 同花顺公开 | TdxQuant tqserver | TdxQuant tqcenter |
|---|---|---|---|---|---|
| 日线/分钟 | ✅ | ✅ | ✅（日线/分时） | ✅ | ✅ |
| 基本面/财务 | ✅ | 部分（finance） | ❌ | ✅ | ✅ |
| 资金流/龙虎榜 | ✅ | ⚠️ 需公式/Level-2 | ❌ | ✅（gpjy/exday/公式） | ✅ |
| 实时快照 | ❌ | ✅ | ✅ | ✅（订阅） | ✅ |
| 公式引擎 | ❌ | ❌ | ❌ | ⚠️ 仅计算函数 | ✅ |
| 港股/美股/期货/期权/宏观 | 部分 | ❌（ext 不可用） | ❌ | ✅ | ✅ |
| 部署 | HTTP/Python | TCP 直连 | HTTP | 跨平台 + 付费 Key | 需客户端常开 |
| 当日可采时点 | 16:07~16:30 | 盘中实时 | 盘中/收盘后待测 | **未公开，需实测** | 依赖客户端盘后下载 |

**四条结论**：

1. **没有任何单一源能同时覆盖四张关键表且更早**；Tushare 仍是 `daily_basic/moneyflow/lhb` 的唯一现成来源。
2. **同花顺** `line/time/realhead` 适合做 daily/分钟/实时的**兜底与交叉校验**（129ms、免鉴权），不解决基本面/资金流。
3. **TdxQuant** 能力最强（公式/Level-2/竞价/分笔/港美股），但**集成成本与授权成本最高**；建议先做可行性验证，不直接进主链。
4. **mootdx** 只做稳定性调优（`bestip + heartbeat + 多服务器 + 短超时`），不改变可采时点。

## 五、机制设计：按源就绪定序

### 5.1 探测（只读）

- 15:05 起每 5 分钟探测一次（起点/频率待拍板）；
- 每个源独立探测，不互相阻塞；
- 记录每个源的**首达时刻**，用于后续校准与告警。

### 5.2 就绪阈值

`max(4000, 前一交易日同表行数 × 95%)`；`lhb > 0` 即就绪；`concept` 无日期，按采集成功判定。

### 5.3 采集与 COL 标记（核心修复）

- **删除 COL-1~5 的「无条件标 done」**；
- 改为：`本表本日行数 ≥ 阈值` → 标 done；否则执行采集；采集返回 0 → **保持 pending**，下一 tick 重试；
- 采集函数已返回行数（`_batch_daily/_batch_daily_basic/_batch_moneyflow/_batch_stk_limit/_batch_lhb`），可直接用于判定。

### 5.4 依赖与顺序

```
15:05 起探测
  ├─ stk_limit 就绪 → 采 COL-4
  ├─ daily 就绪     → 采 COL-1
  ├─ daily_basic 就绪 → 采 COL-2
  ├─ moneyflow 就绪  → 采 COL-3
  └─ lhb/概念（非关键）就绪即采，不阻塞
关键四表（COL-1~4）齐 → 进 RAW
margin（T+1）→ 独立补采，不进当日关键路径
```

### 5.5 兜底与缺失策略

- 18:00 仅作兜底，不作统一起跑线；
- 关键源到 18:00 仍缺时的处理（阻塞/开跑/等到 20:00）**待拍板**；
- 非关键源（lhb/概念）不阻塞 RAW（推荐）。

### 5.6 可观测

- 日志打印每个源「首次就绪时间 / 阈值 / 实际行数」；
- 552-E 告警附「当前缺哪个源、预计何时可采」；
- 看门狗按步骤阈值判断，避免把「等源」误报为「停滞」。

### 5.7 多源冗余（可选）

- daily：Tushare 为主，同花顺 `line` 交叉校验/兜底；
- minute：mootdx 为主，同花顺 `time` 兜底；
- realtime：mootdx/新浪/腾讯/东财，同花顺 `realhead` 作第 4 路；
- TdxQuant：仅在获得 Key/客户端后作候选主源评估，不先入主链。

## 六、实施批次

| 批次 | 内容 | 依赖 | 风险 |
|---|---|---|---|
| **553-A** | 逐源探测 + 顺序启动（把 552-A 的单日线探测扩展为多源；15:05 起） | 552 | 中 |
| **553-B** | COL-1~5 跳过判据修正（本表本日行数 ≥ 阈值才 done；空则 pending 重试） | 无 | 低（必须先做） |
| **553-C** | 同花顺兜底接入（daily `line` / minute `time` / realtime `realhead`） | 553-A | 低 |
| **553-D** | TdxQuant 可行性验证（HTTP `127.0.0.1:17709` 或 `tqserver`；需客户端/Key） | 用户授权 | 中（外部依赖） |

**顺序建议**：先 553-B（修根因，防止提前起跑重演 10-28），再 553-A（探测与定序），然后 553-C，最后 553-D。

## 七、验收判据

1. **10-28 重放**：四张关键表未达标时不得标 done；RAW 必须在四表齐全后启动；QA 不再出现三表 `0/5291`；`out_market_panel` 当日 17/17。
2. **探针**：`_summary.json` 的首达时刻与 Tushare/同花顺实测一致，误差 ≤ 1 个探测周期。
3. **不回归**：552-A/B/C/E、543/548 看门狗与终版重建、505/506/518。
4. **时效**：关键四表齐备时间 ≤ 16:30；全链路在 21:15 前完成。

## 八、风险与拍板项

| 编号 | 事项 | 选项 |
|---|---|---|
| Q1 | 探测起点与频率 | 15:05 每 5 分钟（推荐）/ 15:30 每 5 分钟 / 16:30 每 10 分钟 |
| Q2 | 关键源 18:00 仍缺 | 阻塞 RAW + 告警（推荐）/ 用现有数据开跑 / 等到 20:00 再定 |
| Q3 | 非关键源（lhb/概念）是否阻塞 RAW | 不阻塞（推荐）/ 阻塞 |
| Q4 | 是否接入同花顺兜底 | 先接 daily+minute+realtime（推荐）/ 暂不接 |
| Q5 | 是否推进 TdxQuant | 先做只读可行性验证（推荐）/ 暂不评估 |

## 九、附录

### A. 探针脚本

- 路径：`backend/scripts/_552_source_probe.py`
- 运行：`cd backend && .venv/bin/python3 -u scripts/_552_source_probe.py`（15:00 自动开跑）
- 冒烟：`--once`
- 输出：`logs/source_probe_20261029.{log,jsonl}`、`_summary.json`

### B. TdxQuant 站点地图（23 页）

概述（版本更新/安装 Python/安装终端/快速开始/什么是量化交易）、通用函数、行情类信息、财务类数据、分类/板块成份股、自选股/自定义板块、ETF/可转债/期货数据、调用通达信公式、交易函数、HTTP 方式调用、TdxAiData 后台接口、TdxAiData 特有函数、Lambda 专用函数、AI 平台调用、常量枚举、回测及模拟交易、场景化示例、公众号文章例子、常见问题。

### C. 复跑命令

```bash
# 探针冒烟（只读）
cd backend && .venv/bin/python3 -u scripts/_552_source_probe.py --once

# 查看首达时刻
cat logs/source_probe_20261029_summary.json
```

## 十、实施记录（2026-10-29）

### 553-B 已实施（COL 就绪判据）

**改动**（`backend/data_daemon.py`）：

- 新增 `_COL_TABLE/_COL_FLOOR/_COL_RATIO/_COL_CRITICAL/_COL_RETRY_AT` 与四个辅助函数：
  - `_col_row_count(table, date)`：本表本日行数（只读，分库路由）；
  - `_col_prev_count(table, date)`：前一交易日同表行数；
  - `_col_ready_threshold(step_id, date)`：`max(floor, 前日×ratio)`；floor = daily 4000 / basic 4000 / moneyflow 3000 / stk_limit 3000 / lhb 1；ratio = 0.95（lhb 0.5）；
  - `_col_retry_due(pipeline_date, step_id)`：源未发布时 300s 重试冷却。
- 重写 COL 循环：
  - 本表本日行数 ≥ 阈值 → 标 done（detail 含实际行数/阈值）；
  - 不足 → 执行采集；采集后复核：
    - 关键表（COL-1~4）仍不足 → 回写 `pending`，detail「采集后仍不足 X/Y 行，下轮重试」；
    - 非关键表（COL-5 龙虎榜）仍不足 → 标 done 不阻塞 RAW（待完整性检查补采）；
  - 冷却期内跳过该表、继续检查后续 COL，各源独立就绪，不再严格串行。
- 保留 COL-6 概念板块独立采集（无日期）。

**测试**：`backend/tests/test_553b_col_readiness.py` **6 passed**（映射、floor/ratio、行数查询、查询失败兜底、冷却）。

**只读核对（10-29 08:08）**：

| 步骤 | 前日(10-28) | 阈值 | 当日(10-29) | 判定 |
|---|---|---|---|---|
| COL-1 daily | 5606 | 5325 | 0 | WAIT |
| COL-2 daily_basic | 5570 | 5291 | 0 | WAIT |
| COL-3 moneyflow | 5576 | 5297 | 0 | WAIT |
| COL-4 stk_limit | 5653 | 5370 | 0 | WAIT |
| COL-5 lhb | 67 | 33 | 0 | WAIT |

**部署**：daemon 已重启（2026-10-29 08:11:33 进入主循环，PID 6798，启动后 0 ERROR）。

**待 live 验收**：今日 15:00+ 日终时观察日志：
- `[管道] COL-x 本表本日 X/Y 行不足，执行采集`；
- 采集后若源未发布，关键表出现 `采集后仍不足 X/Y，保持 pending 等待源发布`，且 5 分钟内不重复打接口；
- 四表达标后才进 RAW；`OUT-MARKET-CHECK` 应为 17/17。

### 553-A/C/D 未实施

- 553-A：逐源探测与顺序启动（探针 `_552_source_probe.py` 已挂 15:00 自动开跑，产出的首达时刻用于校准起点）。
- 553-C：同花顺 `line/time/realhead` 兜底。
- 553-D：TdxQuant 可行性验证（需客户端或 TdxAiData Key）。

### 553-B 增补（2026-10-29）：非关键源 18:30/20:00 重试

针对 COL-5 首次采集遇到源未发布（10-29 16:35 为 0/33，源 18:01 才发布）的问题：

- 新增 `_NONCRITICAL_RETRY_SLOTS = ((18,30),(20,0))` 与 `_maybe_retry_noncritical_cols()`；
- 主循环在 `_drive_pipeline()` 之后调用；到点且行数不足时重采 `_batch_lhb`，**只更新 detail，不改状态、不阻塞 RAW**；每次 tick 只重试一个时点；
- 若数据已被完整性检查补齐（have ≥ need），则校正残留的「采集后 0/N」明细为「复核后 X/Y 行（已就绪）」；
- 测试 `test_553b_noncritical_retry.py` **6 passed**。

**10-29 实测**：20:00 完整性检查已写入 lhb **69 行**（≥33），20:28:10 主循环启动后明细校正为「非关键源，复核后 69/33 行（已就绪）」；`pipeline_status(20261029).COL-5` 保持 `done`，不阻塞后续。

**未实施**：553-A（探测起点前移至 15:05）、553-C（同花顺兜底）、553-D（TdxQuant 验证）。

### 553-A 已实施（2026-10-29）：探测起点前移至 15:05

- `_READY_PROBE_START` 由 (16,30) 改为 **(15,5)**，`_READY_PROBE_INTERVAL` 600→**300s**；
- 新增首次就绪日志：`553-A 首次就绪: daily X/Y 行 @ HH:MM:SS，提前启动日终（逐源采集由 553-B COL 判据推进）`；
- 日线就绪即起跑；**逐源采集由 553-B 的 COL 判据推进**（本表本日行数达标才 done，关键四表齐才进 RAW）；18:00 仅作兜底；
- 探测状态跨日重置（`ready/rows/first_ready_at`），避免沿用前一交易日结果；
- 测试：`test_552_eod_window.py` **9 passed**（含 15:04 不探测、15:05 起探测）；连同 553-B 共 **21 passed**。

**10-29 探针依据**：stk_limit 15:00:07、moneyflow 15:45:20、daily/daily_basic 15:50:21、lhb 18:01:38。据此预计明日 **15:50 前后起跑**（较 10-29 的 16:33 再早约 43 分钟），全链路约 2h32m ⇒ **约 18:22 完成**。

**部署**：daemon 已重启（2026-10-29 20:41:47 进入主循环，PID 31472，0 ERROR）。

**待 live 验收**：明日 15:05 起观察 `553-A 首次就绪` 日志与实际起跑时间。

**未实施**：553-C（同花顺 `time/realhead` 兜底，不接 `line`）、553-D（TdxQuant 验证）。

### 553-C 已实施（2026-10-29）：同花顺 time/realhead 兜底

**范围**：只接 `time`（分时）与 `realhead`（单只快照），**不接 `line`**（10-29 实测 20:28 仍未出现当日 bar，比 Tushare 15:50 晚 4.5h+）。

**新增** `backend/app/data/ths_provider.py`：

- `fetch_intraday_minutes(ts_code, date_str)`：解析 `time` 端点（`HHMM,price,amount,avg_price,volume`）→ `minute_kline_cache` 结构（`trade_date/trade_time/open/high/low/close/volume/amount`）；分时每分钟仅一个价格，故 OHLC 同值；日期不匹配返回空。
- `fetch_snapshot_raw(ts_code)`：`realhead` 原始 items（字段为数字键，语义随页面版本变化）；**逐只 HTTP，仅用于单只/交互兜底，不接入全市场 5s 轮询**。

**接入**（采集层，`data_daemon._batch_backfill_minute_kline`）：

- `ts.pro_bar` 返回空/异常时，调用 `fetch_intraday_minutes` 兜底，显式写 `freq='1min'`；
- 每轮最多兜底 200 只、每只间隔 0.05s，避免打爆源；
- 日志新增「同花顺兜底 X/Y」。

**验证**：

- `test_553c_ths_provider.py` **4 passed**（分时解析、日期不匹配、HTTP 失败、realhead 解析）。
- 只读实测：`fetch_intraday_minutes('000001.SZ','2026-10-29')` 返回 **242 根**，`09:30` 价格 11.30/量 910,800/额 10,292,040，字段正确。
- daemon 已重启（2026-10-29 21:06:50 进入主循环，PID 32970，0 ERROR）。

**待 live 验收**：需遇到 `pro_bar` 分钟缺口的交易日，观察 `[分钟回填] 第N轮完成 …（同花顺兜底 X/Y）`。

**未实施**：553-D（TdxQuant 验证）。

### 553-D 探测结果（2026-10-29）：BLOCKED（缺前提，探针已就绪）

**前提核查**：

- tqcenter：`http://127.0.0.1:17709/` 连接拒绝（Errno 61）；
- tqserver：venv 无 `tdxaidata`；`TdxAiData.ini` 在项目根 / backend / `~/` 三处均不存在；
- 环境变量无 `TDX*` / `TQ_*`。

**落地**：`backend/scripts/_553d_tdxquant_probe.py`（stdlib、只读、不写库）

- 先探测客户端 HTTP（get_market_data 最小请求），再查 `tdxaidata` 包与 `TdxAiData.ini`；
- `decide(client, server)` 纯函数决定 `client / tqserver / blocked`；
- 当前输出 `mode=blocked`、exit 2；
- `test_553d_tdxquant_probe.py` **3 passed**。

**解锁条件**：

- 路径 A：安装并启动支持 TQ 的通达信终端，确认 17709 可访问；
- 路径 B：`pip install tdxaidata`，并在 `TdxAiData.ini` 配置数据服务 Key；
- 解锁后重跑探针（exit 0），再用 `get_market_data` 取 `000001.SZ` 日线，对比 Tushare/mootdx 的字段与当日可采时点。

**结论**：553-D 目前不具备实跑条件，不纳入主链；同花顺 `line` 已实测当日 20:28 未更新，同样不纳入。
