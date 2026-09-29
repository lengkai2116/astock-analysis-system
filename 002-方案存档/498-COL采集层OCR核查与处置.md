# 498号｜COL 采集层 OCR 核查与处置

**版本**：v1.7（2026-09-29；**批次1~5 已实施**，代码已改、未推送，详见 §十一~§十五。余批次/延后项见下）
**v1.7 批次5 实施（2026-09-29）**：用户指示「开始实施批次5」→ 低危/死代码清理 **#46**（日志括号）/ **#47**（死状态 `_SYNCED_TODAY`）/ **#48**（死函数 `_check_daily_sync_backfill`）/ **#49**（`_seen` 加 20000 上限）/ **#50**（重复 logger）/ **#55**（死常量 `_FLUSH_BATCH_SIZE`）/ **#56**（无效 global `_last_sector_ts`）；**延后 #8/#13**（tushare_provider 重复段，独立 refactor）/**#52/#53**（功能扩展/低危）。改动 3 文件；定向回归 52 passed、ruff 零新增。
**v1.6 批次4 实施（2026-09-29）**：用户指示「开始实施批次4」→ 范围拍板＝**事实子集** → 分钟时间基准 **#4**（午休映射）/**#14**（北京时间）/**#40**（交易日陈旧判定）、降级/静默吞 **#43/#30/#33/#51/#44/#32**、分库读告警 **#21/#23**、源健康事实侧 **#15/#5/#6**；**#7 未做**（偏「果」留拍板），#31/#41/#42 延后。改动 6 文件；探针全绿、定向回归 50 passed、ruff 零新增。
**v1.5 批次3 实施（2026-09-29）**：用户指示「开始实施批次3」→ 实施 **#16/#17**（mootdx `_prev_prices`/`_source_stats`/`_active_source` 加锁）、**#18**（fallback 单例 RLock）、**#19**（daemon+provider 两处 Tushare 限流器加锁）、**#20**（分库连接缓存双检锁）、**#24**（`init_sharding` close_all 旧实例）、**#26**（`_unmapped_warned` 加锁）；**#22 经实证否定**（SELECT 不开启事务）；#23 低优先登记。改动 5 文件；并发探针 6/6 绿、`test_426_*` 33 passed、ruff 零新增。
**v1.4 批次2 实施（2026-09-29）**：用户指示「开始实施批次2」→ 范围拍板＝**核心三项**（§六-2/§六-3 留待单独批）→ 实施 **#11**（`data_sources.yaml` `git mv` 至 `backend/config/` + 限流/优先级接线，**零行为变更**）、**#35/#34**（`tushare_provider._load_token` 删个人硬编码路径 + `.env` 读取保护）。改动 4 文件；`test_431_g2_config_loading` 19 passed、ruff 零新增。
**v1.3 批次1 实施（2026-09-29）**：用户指示「开始实施批次1」→ 实施 **#3 三源 volume 归「手」**（实证新浪字段8=股）、**#12 daemon 请求预算解耦**（`processed=0`）、**#2 查错库**（改分库读 `_query_shard`）；**#2 核实更正**＝`ensure_minute_data` 系**死代码**（全仓零调用 + 总库无该表），非 §一 所述「当前生效」。改动 3 文件 + 探针 1；17 passed、ruff 零新增。
**v1.2 拍板回填（2026-09-29）**：三项待拍板口径经说明+建议后由用户**逐项选定**——**Q1＝A 统一「手」**（修正 v1.0 初判「股」：跨表锚＝日线 `vol`=Tushare 手 / AKShare「总手」/ 周线由 minute 聚合）、**Q2＝A 分阶段接线为权威**（先迁 `backend/config/` + 接限流/优先级，降级链与采集时段单独批）、**Q3＝A 删除 `MinuteDataManager`**（职责已被 292 红线架构取代，接线反回退）。详见 §八；三项**均属因/契约/结构层**（无需独立「果」号）。
**v1.1 修正说明（2026-09-29）**：经回核 OCR 原始输出（`/tmp/ocr_col/app_group.txt` 54 条 + `daemon.txt` 6 条 = **60 条**）与真实代码，初版 v1.0 存在**遗漏与计数错误**：
1. **条目数订正**：v1.0 §三~§五 仅编号 **35 项**（高危 12 / 中危 15 / 低危 8），且部分条目仅在"另有…"行以文字带过；本档按 OCR 原始输出**逐条补齐并编号**为 **56 项**（高危 **15** / 中危 **30** / 低危 **11**），OCR 全部 60 条**无遗漏**（同因/同位置归并，见 §一末）。
2. **补编号的高危 3 项**：#13 `tushare_provider:223-237` 不可达死块、#14 `mootdx_collector:150` 进程本地时间基准、#15 `data_source_manager:74-75` 自恢复口径失效。
3. **补编号/上提的中危项**（v1.0 表内仅 15 项，余散落于"另有…"行或曾以高危/低危计）：#19 限流器无锁(并入 daemon #19)、#22 分库隐式事务、#24 `init_sharding` 未 close、#26 `_unmapped_warned` 无锁、#29 急切日志、#31 全市场快照重复下载、#34 `.env` 读取无保护、#35 个人硬编码路径(由低危上提为 security·medium)、#36~#39 `minute_data_manager` 降级频率/slot/`inf`/volume 键(原为"另有"行)、#40 日历日陈旧判定(原为"另有"行)、#41 聚合 O(history)、#42 逐股宽 except、#43 腾讯源截断(bug·high，并入 §四)、#45 硬编码 `/tmp`(由低危上提为 maint·medium)。
4. **补编号的低危项**：#49 `_seen` 无界增长、#51 吞 mootdx 探测、#52 `_get_stock_name` 硬编码 20 码(原为"另有"行)、#53 分钟空日期、#54 trade-time 解析脆弱。
5. **补实证锚点**：`mootdx_collector:633`（腾讯源 volume）。**代码/方案本体一字未改，仅订正本档。**
**来源**：2026-09-29 用户要求「调用 OCR 对系统的 COL 部分代码配置情况进行检查，对发现的代码问题在对话框内说明，不要修改方案和代码」；对话框内核查报告出具后，用户要求「落成《COL 采集层 OCR 核查与处置》方案文档，按项目要求编号存档」。本档＝该报告的正式归档 + 处置方案（供拍板）。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek `deepseek-chat`）分两段全量扫描 COL 层，共 **60 条发现**，**逐条人工核实**（OCR 按文件/片段审查，存在上下文误报，全部对照真实代码核对，误报/设计意图单列 §七）。
**范围（COL＝第1层采集层）**：`backend/data_daemon.py`（采集段：`_batch_*` / `_backfill_*` / `run_integrity_check` / `_check_data_*` / sync_requests 消费 / 分钟回填 / 优先级调度）+ `backend/app/data/` 全层（写入网关 `enhanced_cache_manager`、分库路由 `sharding_manager`、源管理 `data_source_manager` / `fallback_manager`、分钟通道 `minute_backfill` / `minute_data_manager`、三源适配器 `tushare_provider` / `akshare_provider` / `akshare_collector` / `mootdx_collector`）。
**侧重**：代码内配置使用（硬编码 / env 键 / 默认值兜底 / 路由表 / 阈值）× 与 `backend/config`、`.env` 的一致性 + 采集正确性。
**基线**：HEAD `2bf9916`（= origin/main；工作树 clean，仅 `data/account_risk_status.json` 未跟踪＝daemon 运行产物）；daemon 运行中（看守 `start_daemon.sh`）。
**边界（445 调整后口径）**：事实/契约层（因）**该改就改**；判定阈值/权重/方向语义（果）**须独立号 + 依据 + 验证**。本档多为因/契约/结构层；**含「果」成分的口径项（体积单位基准、孤儿配置去留、潜伏模块去留）已在 §八 标为待拍板，不在本档决断**。
**OCR 会话**：`395f8657-f3a9-4385-9851-150352078fef`（app/data 10 文件，54 条）；`0aa2c029-60d1-495c-aa09-61ce9f7522bd`（data_daemon.py，6 条）。

---

## 一、核查背景与总体结论

- COL 是「采集 → 规范化 → 清洗 → 写入」的第1层；355（采集层核查）/369（四项修订）/417（深度清洗增强）为既有治理依据，417 的 4 项深度清洗增强**已实施**。
- 本次 OCR 全量扫 + 人工核实结论：
  - **60 条发现中，15 条高危已逐行实证**（含 **2 条「配置已失效」类**：孤儿配置、请求饥饿）；
  - 2 条属**设计意图/弱推理**（§七），不计为缺陷；
  - **当前生效**的数据正确性缺陷：**#3 volume 单位不一致**、**#12 sync_requests 请求饥饿**；**#2 查错库**经实施期复核**更正为潜伏（`ensure_minute_data` 全仓无调用方＝死代码，一调即抛 `no such table`）**——见 §十一；
  - **潜伏**类：`MinuteDataManager` 全仓**零消费方**，其内缺陷（#1/#9、#36~#39 等）当前不影响运行，但一旦接线即带错运行；
  - 与 496 号重叠项（`_query_table` 吞异常、分钟回填缺失集增量、pct_chg 板块判定、treemap 连接 guard）**已实施，不重复计入**。
  - **本档归并口径**：56 项（高危 15 / 中危 30 / 低危 11）逐项见 §三~§五，覆盖 OCR 全部 60 条；**同一处代码可能同时被多条 OCR 命中**（如 `_do_flush_one` 同时涉时间基准、静默吞异常、`_prev_prices` 无锁；`tushare_provider` 重复方法与不可达块同族），故**项数少于 OCR 原始 60 条**。

---

## 二、发现总览

| 级别 | 项数 | 主题 |
|------|------|------|
| 🔴 高危（正确性/配置失效） | 15 | 分支永不执行、查错库、跨源单位不一致、时间戳错位、健康记账缺失、无界递归、降级链绕过、重复方法覆盖、缓存键缺窗口、市场硬编码、孤儿配置、请求饥饿、不可达死块、进程本地时间基准、自恢复口径失效 |
| 🟠 中危（并发/健壮性/配置漂移） | 30 | 共享可变全局无锁、分库连接竞态/读路径静默/隐式事务/迁移静默、fallback 语义缺陷、分腿失败整体丢弃、整轮被单坏值毁、腾讯源截断、陈旧判定用日历日、聚合 O(history)、静默吞 flush、分钟降级频率反混、`.env` 读取无保护、个人硬编码路径 |
| 🟡 低危/死代码 | 11 | 日志括号不平衡、死状态/死函数/死常量/无效 global、硬编码 `/tmp`、重复 logger、分钟 trade-time 解析脆弱、静默吞 mootdx 探测 |
| ⚪ 误报/设计意图 | 2 | 代理清除（项目刻意策略）、fallback 滞回（弱推理） |

> 「实证」＝本次已对照真实代码/复现确认；「OCR-only」＝OCR 提出但**未逐行复核**，实施前须再核。

---

## 三、🔴 高危（P1，15 项，已实证）

### #1 `minute_data_manager.py:72` — Tushare 分钟分支永不执行（潜伏）
- `self._has_tushare_high` 初值 `None`（`:29`），`:72` `if self._has_tushare_high:` 对 `None` 为假；唯一的赋/判入口 `_check_tushare_permission()`（`:31`）**全仓无调用方** ⇒ 每个请求都静默降级到 AKShare。
- **实证**：`grep _check_tushare_permission` 仅命中定义行；`_has_tushare_high` 无任何外部写入。
- **潜伏性**：`MinuteDataManager` 全仓无 import/使用方（grep 零命中）⇒ 当前不影响运行。
- **方向**：接线时把 `:72` 改为惰性 `self._check_tushare_permission()`；或（若确认不用）删模块。

### #2 `minute_backfill.py:442-445` — 查错库（当前生效）
- `minute_kline_cache` 经 `sharding_manager` 路由至 `market_cache.db`（`_table_to_db` 已登记），但 `ensure_minute_data` 用 `ecm_local.conn`（**总库** `stock_cache.db`；ECM 在建表期也建了同名空表，`enhanced_cache_manager.py:757`）→ `COUNT(*)` 恒 0 → "缺失判定"恒真 → **每轮全量重拉 1min 历史**。
- **实证**：sharding L76 `'minute_kline_cache': 'market_cache.db'`；ECM 写路径走 `_insert_from_df`→分库，读路径却直连总库。
- **影响**：COL-7（分钟回填）效率与配额；"只处理缺失股"优化完全失效。

### #3 `mootdx_collector.py:538 / 633 / 741` — 三源 `volume` 单位不一致（当前生效）
- 新浪 `values[8] × 100`（`:538`，Sina 成交量本就为「股」，多乘 100）、腾讯 `values[6] × 100`（`:633`，「手」→股，正确）、东财 `f5`（`:741`，「手」）**未 ×100** ⇒ 同一 `volume` 字段三种语义。
- **影响**：降级切源时快照量能**跳变 100 倍**，污染量比 / 换手率 / 资金流等下游。
- **实证**：`:538`、`:633`、`:741` 三处逐行核对；`_fetch_sina` 注释自证"全量并行覆盖"但未解决单位。
- **口径待拍板**：统一基准取「股」还是「手」（§八 Q1）。

### #4 `minute_backfill.py:112-113` — 1min 时间戳忽略午休（潜伏/潜在生效）
- `hour = 9 + (idx + 30) // 60`（`idx` 实为 `iterrows()` 标签，非整数）⇒ 第 119 根映射 11:29（应 11:30），第 120+ 根**穿过 11:30–13:00 不存在区间**，全部下午 `trade_time`/`trade_date` 错位。
- **实证**：函数 `_get_mootdx_minutes_safe` 逐行确认；A股上午/下午各 120 根。

### #5 `data_source_manager.py:344-349` — 时间感知快路径不记账
- 盘中强制偏好 AKShare 分支直接调 provider 并返回，**不调用** `record_success/record_failure/_evaluate_status`，失败仅 `continue` ⇒ 首选源的成功/延迟/失败全不可见，降级判定与前端状态快照失真。

### #6 `data_source_manager.py:294-297` — 降级无界递归
- 失败后 `_update_active_source()` 再 `return self.get_data(...)`，无重试/深度上限 ⇒ 所有源持续失败时 `RecursionError`。

### #7 `fallback_manager.py:103-105` — 未注册源默认「健康」
- `_is_source_healthy` 对不在 `_health_status` 的源返回 `True`，而链中 `sina_http/tencent_http/cache` 等从未注册 ⇒ 坏源被当健康源选中，**降级机制被静默绕过**。

### #8 `tushare_provider.py:288-300 + 423-425` — 6 方法整段重复定义 + 坏日志
- `get_index_daily/stk_limit/moneyflow/top_list/top_inst/daily_basic` 各出现两次（229↔330、239↔340、250↔351、261↔362、272↔373、288↔389），后份静默覆盖前份；第二份 `get_daily_basic` 用 `r"...{e}"` 原始串（`:423-425`）且 `except Exception:` **未 `as e`**（潜在 NameError）。
- **实证**：行号成对 + `sed 415-425`。

### #9 `minute_data_manager.py:65` — 缓存键缺日期窗口（潜伏）
- `cache_key = f"minute:{ts_code}:{freq}"` 不含 `start/end/days_back` ⇒ 一个窗口的结果被返回给任意其它窗口。

### #10 `akshare_provider.py:400-405` — 硬编码 `market='sh'`
- `_parse_ts_code` 已返回正确前缀却弃用，写死 `market='sh'` ⇒ 深市(000/002/300)、北交所股票资金流查错市场，返回空/错。

### #11 `config/data_sources.yaml` — 孤儿配置（配置已失效）
- 唯一引用是 `config_manager.init_config()`，而 `config_manager` 模块**全仓无 import**（`grep "import config_manager\|init_config"` 零命中，除自身）；且文件陈旧失真（写 `daily_cache primary=tushare, fallback=null`，实际盘中有 AKShare/QMT 降级；`rate_limit: 5` 无人读，真实限流＝daemon `_TS_MIN_INTERVAL=0.2` 硬编码）。
- 真实源优先级硬编码在 `app/__init__.py:336-350`。
- **口径待拍板**：删 / 接线为权威（§八 Q2）。

### #12 `data_daemon.py:6357-6358` — sync_requests 请求饥饿（当前生效；OCR 原评 medium，本档按影响面提为高危）
- `processed = _fin_done + _stk_done` 预置 finance/stk_holder 计数；积压大时 `processed` 在通用循环开始前已 ≥ `MAX_PER_TICK(=50)` ⇒ 首条非 fin/stk 请求即被 `if processed >= MAX_PER_TICK: break` **饿死**，`full_daily/full_moneyflow/per_stock/adj_factor/concept` 等只要积压未清就永不处理。
- **实证**：`_consume_sync_requests_batch` 逐行；预算对半分配（`_half=25`，合计最多 50）与通用请求**共享同一计数器**。

### #13 `tushare_provider.py:223-237` — 不可达死块（`return` 之后）
- 该块位于第一段 `get_daily_basic` 的 `return`/`except` **之后**，永不执行；且引用 `trade_date`，与本方法（只取 `daily_basic`）语义不符。与 **#8** 同属"tushare_provider 重复/死代码"族，实施时一并处理。

### #14 `mootdx_collector.py:150` — 分钟聚合使用进程本地时间基准
- `_feed_minute_aggregator` 用 `datetime.now()` 生成 `minute_key`，`_do_flush_one` 用 `now.strftime('%Y-%m-%d')` 写 `trade_date`/`trade_time`；而本项目交易时段判断（`app.utils.trading_hours`）刻意用 `datetime.utcnow() + 8h` 的北京时间。**部署机时区非 UTC+8（Docker 常见 UTC）时**，分钟 K 线的 key/`trade_date`/`timestamp` 按 UTC 落库 → 分钟线日期错位（北京 09:00–16:00 跨 UTC 日界）。与 **#4** 同属"分钟时间基准"族。
- **实证**：`:149` `now = datetime.now()`；`_do_flush_one(:214)` `trade_date = now.strftime('%Y-%m-%d')`；本文件另有 `:546/658/755` `datetime.now().isoformat()` timestamp 同源。**建议统一走 `trading_hours._now()`**。

### #15 `data_source_manager.py:74-75` — 自恢复口径失效（累计计数冒名连续计数）
- 自动恢复用**累计生命周期**计数器 `self.successes`（硬编码 `>= 3`）而非连续成功数，且从未引用配置项 `self.auto_recovery_successes`（`:130`）⇒ 该配置**调了无效**；一个已有 3 次历史成功的源，**单次成功**即翻回 NORMAL，与注释"连续 3 次成功自动恢复"矛盾。
- **实证**：`:74` `if self.successes >= 3:`；`record_failure` 只自增 `consecutive_failures`，**无 `consecutive_successes`**；`auto_recovery_successes=3` 定义于 `:130` 却无消费方。

---

## 四、🟠 中危（P2，30 项）

> 注：本表按"位置族"分组，含 **3 项 OCR 原评 high 者**（#19 双限流器、#43 腾讯源截断、及 #35 系 security·medium）；#12（OCR 原评 medium）因影响面已上提至 §三。级别列标注 OCR 原始判定，处置优先级以 §八 批次为准。

| # | 位置 | 问题 | OCR 级别 | 核实 |
|---|------|------|---------|------|
| 16 | `mootdx_collector.py:118-119` (`_prev_prices`) | `_calc_speed` 由 4 线程并发读改写，无锁；字典**只增不减**、注释承诺的"盘后重置"**不存在** ⇒ 长跑内存泄漏 + 跨日残留致开盘首笔涨速失真 | other·medium | 实证 |
| 17 | `mootdx_collector.py:389-392` (`_source_stats`/`_active_source`) | 采集线程写、API 线程读，无锁 | other·medium | 实证 |
| 18 | `fallback_manager.py:110-114` | 单例 `update_health_status`/`_record_fallback`/history 切片为无锁读改写序列 | bug·medium | OCR-only |
| 19 | `tushare_provider.py:21-22` + `data_daemon.py:93-94` | 模块级限流器 check-sleep-set 无锁；且两处是**两把独立锁**，叠加调用可能突破 5 次/秒 | bug·high / bug·low | 实证 |
| 20 | `sharding_manager.py:154-158` | `get_connection` "检查-建连-入缓存"非原子且 `_connections` 无锁 ⇒ 首次并发各建连接、后者覆盖前者**泄漏句柄** | bug·medium | 实证 |
| 21 | `sharding_manager.py:267-271` / `table_exists` | 未登记表读路径**静默返回空**，与写路径 `_warn_unmapped` 告警口径不一致（426 S1 未覆盖读侧） | bug·medium | 实证 |
| 22 | `sharding_manager.py:273-278` | 缓存连接默认 `isolation_level=''` 隐式事务：只读 `execute_query` 只 execute 不 commit，读事务挂在共享连接上阻塞 WAL checkpoint → WAL 膨胀（health.py 按 WAL 告警） | bug·medium | OCR-only |
| 23 | `sharding_manager.py:186-190` | `_ensure_snapshot_indexes` 建索引/ALTER 迁移失败仅 `logger.debug`，连接随后被缓存 ⇒ 长期停在"部分迁移" | maint·medium | OCR-only |
| 24 | `sharding_manager.py:382-386` | `init_sharding` 替换全局单例时**未 `close_all()` 旧实例** ⇒ 句柄泄漏（daemon 启动 + 测试切沙盒均走此路径） | bug·medium | OCR-only |
| 25 | `sharding_manager.py:346-353` | `get_table_row_count` 表名 f-string 拼接（白名单＝纵深防御，但与"已登记"口径不一致） | security·low | 实证 |
| 26 | `sharding_manager.py:24-32` (`_unmapped_warned`) | 模块级可变集合无锁读改写；长驻进程只增不减 | bug·low | OCR-only |
| 27 | `fallback_manager.py:66-69` | 运行均值公式非真正增量均值；默认 `response_time=0` 把均值拖向 0 | bug·medium | OCR-only |
| 28 | `fallback_manager.py:91-93` | 降级链环/自指无检测，`_record_fallback` 可记 `from == to` | bug·medium | OCR-only |
| 29 | `fallback_manager.py:75-75` | 热路径日志用急切 f-string（低级别时仍格式化） | perf·low | OCR-only |
| 30 | `akshare_provider.py:543-544` (`get_limit_pool`) | 跌停腿失败即整体返回 `{'up':[],'down':[]}`，丢弃已取到的涨停数据（无法区分"单腿失败"与"无数据"） | bug·medium | 实证 |
| 31 | `akshare_provider.py:235-239` | `get_realtime_spot`/`get_batch_quotes` 每次重建全市场快照（逐码调用=全市场重复下载，限流风险） | perf·medium | OCR-only |
| 32 | `akshare_collector.py:203-204` | `int(row.get('上涨家数',0))` 对 `''`/`NaN`/`None` 抛错，被外层 `except` 归零为 `[]` ⇒ **一个坏单元格毁掉整轮**（同类：`akshare_provider` 板块/概念/涨停池） | bug·medium | 实证 |
| 33 | `akshare_collector.py:404-405` | 情绪池全接口失败与"空交易日"**无法区分**（静默返回 0 条；488-2 同型） | bug·medium | 实证 |
| 34 | `tushare_provider.py:76-83` | `_load_token` 读取 `.env` 无异常保护（权限/编码错误会冒泡阻断 provider 构造） | bug·medium | OCR-only |
| 35 | `tushare_provider.py:70-74` | 硬编码个人绝对路径 `/Users/kalence/Desktop/测试/...` 作 token 兜底（换机即失效 + 泄漏本地路径） | security·medium | 实证 |
| 36 | `minute_data_manager.py:150-152` | `get_cached_minute` 降级循环 `[freq,'5min','1min']`：请求 1min 而仅存更粗频率时 `_resample_minute` 返回未变的粗频数据（group_size≤1）⇒ **静默返回错误频率** | bug·medium | OCR-only |
| 37 | `minute_data_manager.py:179` | `_assign_slot` 对盘外/超长分钟可算出负 slot；floor 除法致 30min→60min 跨 session 长度差异时错配 | bug·medium | OCR-only |
| 38 | `minute_data_manager.py:218` | `lv = min(b.get('low', float('inf'))...)` 在组内全缺 `low` 时把 `inf` 泄入聚合 bar | bug·medium | OCR-only |
| 39 | `minute_data_manager.py:219` | `b.get('volume',0) or b.get('vol',0)` 不可靠（零量真值被 `or` 跳过；双列并存时可能取错）；`amount` 缺失时恒写 0（假值） | bug·medium | OCR-only |
| 40 | `minute_backfill.py:234-241` | 陈旧判定用**日历日 `days_since<=5`**（注释写"最近3个交易日"），长假前后误判 | bug·medium | 实证 |
| 41 | `minute_backfill.py:303-305` | `backfill_1min` 读该股**全部 1min 历史**再整段重聚合覆盖各周期（O(history) 且会覆盖其它路径产出的有效聚合） | perf·medium | OCR-only |
| 42 | `minute_backfill.py:314-321` | 逐股 `except Exception` 只记日志继续，`ok += 1` 对"取到 0 行"也自增 ⇒ 系统性故障与"该股无数据"不可区分、成功计数虚高 | maint·medium | 实证 |
| 43 | `mootdx_collector.py:586` | 腾讯备用源仍 `min(len(codes),2000)`（新浪段 `:486-489` 注释已自证"限 2000 致 SH 永不触达"并修为全量并行，腾讯段遗留同缺陷）⇒ 降级到腾讯时沪市静默缺失 | bug·high | 实证 |
| 44 | `mootdx_collector.py:207-210` | `_do_flush_one` 两条写入路径均 `except Exception: pass` 静默吞异常；调用方随即用新窗口覆盖 ⇒ 已完成分钟 K 线**无声丢失**且事后无法察觉 | bug·medium | 实证 |
| 45 | `mootdx_collector.py:866` | `client.minutes(..., dest='/tmp/min_backfill')` 硬编码临时目录（非 POSIX/只读容器下失败） | maint·medium | OCR-only |

---

## 五、🟡 低危 / 死代码（P3，11 项）

| # | 位置 | 问题 | OCR 级别 | 核实 |
|---|------|------|---------|------|
| 46 | `data_daemon.py:1818 / 1852 / 1888` | 日志括号不平衡：`n_skip=0` 时 `else ")"` 分支多一右括号，输出 `…共 N 只))`（`_batch_income_recent`/`_batch_balancesheet`/`_batch_cashflow` 三处同型） | maint·low | **已复现** |
| 47 | `data_daemon.py:2718/2730/2833` | `_SYNCED_TODAY` 只写不读（死状态，暗示"当日幂等"但未生效） | maint·low | 实证 |
| 48 | `data_daemon.py:7591` | `_check_daily_sync_backfill` 定义后**全仓无调用**（仅 `main` 注释提及），docstring 称其为 >15:35 兜底路径 | maint·low | 实证 |
| 49 | `data_daemon.py:63-64` (`_seen`) | 日志去重集合无界增长（键含逐码内容），长驻进程慢性内存泄漏 | perf·low | 实证 |
| 50 | `data_source_manager.py:32` | 重复 `logger = logging.getLogger(__name__)`（`:16` 已有，死赋值） | maint·low | 实证 |
| 51 | `akshare_collector.py:250-258` | mootdx 可用性探测 `except Exception: pass` 静默吞（含 import/程序缺陷）⇒ 永久回退 AKShare 且无诊断 | maint·low | 实证 |
| 52 | `akshare_provider.py:103-105` | `_get_stock_name` 只认 20 个硬编码码，其余返回原始 `ts_code`（而快照已含真实"名称"） | maint·low | 实证 |
| 53 | `akshare_provider.py:368-370` | `get_minute_data` 对 `None` 的 `start_date/end_date` 传空串（AKShare 1min 期望 `'%Y-%m-%d %H:%M:%S'`）→ 结果空/不可预期 | bug·low | 实证 |
| 54 | `minute_data_manager.py:204-205` | trade-time 解析 `tt.split(' ')[1]…` 假设存在 `HH:MM`，畸形时间戳落 `(tt,0,0)` 被宽 except 静默分桶 | maint·low | OCR-only |
| 55 | `mootdx_collector.py:137` | `_FLUSH_BATCH_SIZE` 声明后全文件未引用（死常量） | maint·low | 实证 |
| 56 | `mootdx_collector.py:1021` | `global _last_sector_ts` 声明了从未定义的名字（无效 global） | maint·low | 实证 |

---

## 六、配置侧专项（代码 ↔ 配置一致性）

1. **`config/data_sources.yaml` = 孤儿且失真（#11）**：声明了"每数据源 primary/fallback/priority/rate_limit"，但**无消费方**；真实源策略/限流全硬编码在 `app/__init__.py` 与 daemon 常量 ⇒ 两套口径，配置改动不生效。
2. **`DATA_DIR` 默认值多处并存**：`.env`、`start_daemon.sh` 注入、`data_daemon.py:22` `setdefault` 三处**恰好同值**；但 daemon 在 `load_dotenv()` **之前**就 `setdefault`，即 env 已有值则 `.env` 不覆盖。若将来只改 `.env` 的 `DATA_DIR` 而不改 daemon 第 22 行，**daemon 静默沿用旧硬编码路径**（ECM/sharding 走 `os.getenv('DATA_DIR')` 会读到 `.env`，产生分叉）。同类默认值散落在 `enhanced_cache_manager:135/3973/3988`、`minute_backfill:63`、`sharding_manager:55` 等。
3. **阈值/限流/超时全硬编码、无配置文件**：`_TS_MIN_INTERVAL=0.2`、`_TS_CALL_TIMEOUT=15`、`_TS_MINUTE_INTERVAL=60`、`_MARGIN_*`、`_RETENTION_MIN_DAYS`、`_PRIORITY_LEVELS`、`_SYNC_CORE_TYPES` 等写死在 `data_daemon.py`，`backend/config` 下无对应权威项（与 430/431「yaml 唯一权威位置」治理方向不一致）。
4. **代理清除为 import 副作用**（`akshare_provider:21-23`、`akshare_collector:27-30`、`mootdx_collector:31`、`tushare_provider:11`）：模块 import 期 `pop` 代理变量。项目**刻意**为国内直连，但会波及同进程其它库；建议移入 provider 初始化（见 §七）。

---

## 七、已排除（误报 / 设计意图）

| 项 | OCR 判定 | 复核结论 |
|----|---------|---------|
| `akshare_provider.py:21-23` import 期 pop 代理 | maintainability·medium | **项目刻意策略**（国内直连），非缺陷；仅登记"副作用可观测性"建议（并入 §六-4） |
| `fallback_manager.py:73-74` 无滞回/主动恢复 | bug·medium | 推理较弱（该分支仅在 `is_healthy=True` 进入且已恢复）⇒ 仅作提示，不计入 |
| `pd` 绑定 / f-string 括号（daemon） | 496 曾报 | 见 #46——**括号为真缺陷（已复现）**；`pd` 绑定（`_ensure_pd` globals 注入）为**误报**，不采 |

---

## 八、处置方案与批次建议

> 性质：本档只定计划；实施须经用户确认后按批次进行。**含「果」成分的口径项先拍板再动手。**

### 已拍板口径（3 项，2026-09-29 用户逐项选定＝均取推荐）

- **Q1（#3）跨源 `volume` 统一基准 ＝ A 统一「手」** ✅
  - 改法：新浪 `values[8]`（股）**÷100**、腾讯 `values[6]`（手）**去 ×100**、东财 `f5`（手）**不动**。
  - 跨表锚（取证）：日线 `daily_cache.vol`＝Tushare（手）、系统量比 `_compute_volume_ratio` 同表自洽、AKShare 备用分钟 volume＝`总手`（手）、日终回填 Tushare pro_bar（手）；且 dim1 的**周线**有"minute 聚合"与"日线聚合"两路径，唯「手」能保证两路径一致。
  - **修正**：v1.0 §八 Q1 初判「股」为未跨表核实的初值，本版按上述锚**改判「手」**。
  - 性质＝事实/数据获取层（445 边界下该改就改）；验证＝同股同日三源 volume 量级一致 + `minute_kline_cache` 与 `daily_cache.vol` 换算吻合。
- **Q2（#11）孤儿配置 `config/data_sources.yaml` ＝ A 分阶段接线为权威** ✅
  - 第一步：`git mv` 至 `backend/config/`（对齐 430 号权威位置）＋ 接**限流**（`rate_limits.tushare.requests_per_second` → daemon `_TS_MIN_INTERVAL`）与**数据源优先级**（`data_sources.*.priority` → 源注册）两项**可验证**项。
  - 第二步（单独批）：`fallback_strategy`（降级链）/`collection_schedule`（采集时段）接线；届时若触及降级/优先级**语义**须再确认。
  - **前置**：先复核 yaml 与实际运行值的差异——yaml 现`daily_cache fallback=null`/`market_snapshot primary=eastmoney_http` 等**与现网不符**（实际盘中 akshare(-1) 优先、东财 ulist+新浪/腾讯兜底），接线前须先订正，避免把失真值接成权威。
- **Q3（#1/#9/#36~#39）潜伏模块 `MinuteDataManager` ＝ A 删除模块** ✅
  - 理由：其「同步直取 + 自带缓存/降级」模型与 **292 号架构红线（调用层禁止直调数据源；miss 走 `sync_requests` 异步补采）** 冲突；职责已被 dim1 `_get_minute_data`（ECM 缓存优先 + `request_data('per_stock')`）+ daemon 采集/回填覆盖（出处 151 号 P1-1 Phase 3）。
  - **前置**：`grep -rn "MinuteDataManager\|minute_data_manager"` 全仓复扫（scripts/tests/docs）+ 确认无引用后移除；同步清 `#1/#9/#36~#39`。
  - 性质＝结构层。

### 批次划分（建议）

| 批次 | 主题 | 条目 | 说明 |
|------|------|------|------|
| **批次1** | 数据正确性（当前生效） | #2 查错库、#3 单位（依 Q1）、#12 请求饥饿 | 影响面最直接；#12 仅改预算解耦（`processed=0` + fin/stk 独立预算） |
| **批次2** | 配置治理 | #11（依 Q2）、§六-2 `DATA_DIR` 默认值收敛、§六-3 硬编码参数集中、#35 个人硬编码路径、#34 `.env` 读取保护 | 纯因/契约层；涉及 `.env` / daemon / ECM / sharding 多处口径统一 |
| **批次3** | 并发健壮性 | #16/#17/#18/#19 无锁全局与双限流器、#20 连接竞态、#22 隐式事务、#26 `_unmapped_warned`、#24 `init_sharding` close_all | 逐处加锁/收敛；需并发验证 |
| **批次4** | 源管理 / 分钟通道 | #5/#6/#7/#15（源健康与递归）、#14/#4/#40（分钟时间基准）、#30/#31/#33/#43/#44（降级与静默吞）、#21/#23/#36~#39/#41/#42（分库读/分钟链路） | #5/#6/#7/#15 是"降级机制真实性"核心，偏「果」，建议与 JUD 判定链口径对齐后实施 |
| **批次5** | 低危/死代码清理 | #8/#13 重复方法与死块、#46 日志括号、#47/#48 死状态/死函数、#49 `_seen`、#50~#56 | 零行为变更优先；#8 删重复段需回归 provider 全接口 |

> 说明：#44（静默吞 flush）与 #39/#41/#42 等"数据静默丢失/错配"类虽列于批次4，但**优先级应高于纯低危**，实施时可提前。

### 依赖顺序与风险

- 批次1 独立、优先；批次2 的 `DATA_DIR` 收敛须在批次1 前确认（涉及路径口径，避免迁移期分叉）。
- 批次3 的锁改动**不得**引入持锁长事务（与 496 #11/#12 原子替换经验一致）。
- 批次4 #5/#6/#7/#15 触及"源可用性判定"＝偏「果」，须先拍板（是否把未注册源判为 unhealthy、递归改迭代并抛受控异常）。
- 批次5 #8 删除重复方法段前，先 `grep` 确认无动态引用；日志括号修复照 496 同型处理。

---

## 九、验证口径（实施时）

- 每批实施后：`py_compile` + `ruff`（COL 目录级复扫）+ 相关回归；**全量 pytest 批量污染为既有问题**（需 `--ignore='$TMPDIR'` + 停 daemon）。
- 数据正确性类（#2/#3/#12）：用 DB 探针实证（如 `minute_backfill` 缺失集在修后应"非全量"；`volume` 三源同股同日应一致量级；sync_requests 各类型应均能推进）。
- 效率类：COL-7 分钟回填耗时应下降（#2 修复后不再全量重拉）。
- **复跑前置**：停 `data_daemon` **及** `start_daemon.sh` 看守（否则分库锁致测试挂起），跑完重启。

---

## 十、待定登记（本档未决）

| 登记 | 内容 | 依赖 |
|------|------|------|
| 登记-1 | #3 单位基准（Q1） | ✅ **已决＝统一「手」**（§八）；待实施 |
| 登记-2 | #11 孤儿配置去留（Q2） | ✅ **已决＝分阶段接线**（§八）；接线前须订正 yaml 失真值 |
| 登记-3 | `MinuteDataManager` 去留（Q3） | ✅ **已决＝删除**（§八）；前置＝全仓引用复扫 |
| 登记-4 | §六-2 `DATA_DIR` 默认值三处口径统一 | 批次2 前置 |
| 登记-5 | #35 `tushare_provider` 个人硬编码路径是否删除兜底 | 批次2/5 |
| 登记-6 | §六-4 代理清除是否移入 provider 初始化（可观测性） | 批次2/3 顺带 |
| 登记-7 | #14/#4 分钟时间基准统一（`trading_hours._now()`）是否跨模块统一 | 批次4 |
| 登记-8 | 批次4「源可用性判定」（#5/#6/#7/#15：未注册源判 unhealthy / 递归改迭代抛受控异常）＝偏「果」 | **待单独拍板**（未决） |

---

## 十一、批次1 实施记录（2026-09-29，#2 / #3 / #12）

> 范围＝批次1「数据正确性（当前生效）」；#3 依 Q1 已拍板「手」。**改动 3 文件 + 探针 1**；验证：`py_compile` OK、ruff **零新增**（mootdx/minute_backfill 各 1 既有 / daemon 38→38）、`test_col_cleaning`+`test_461_dim10_volume_ratio_alignment` **17 passed**、探针全绿。

### #12 `data_daemon.py` 请求预算解耦 ✅
- 改法：`processed = _fin_done + _stk_done` → **`processed = 0`**（`_consume_sync_requests_batch`），加 3 行说明注释。fin/stk 预算（`_half` 各半）与通用请求预算**彻底分离**。
- 探针：积压满额时 旧 `processed=50` → 通用请求 **0 done（全饿死）**；新 `processed=0` → **5/5 全推进**。

### #3 `mootdx_collector.py` 三源 volume 归「手」 ✅
- 改法：新浪 `values[8]`（股）`*100`→**`/100`**（`:538`；实证 `amount/vol≈price` 证字段=股）；腾讯 `values[6]`（手）**去 `*100`**（`:633`）；东财 `f5`（手）**不动**（`:741`，补注释）。
- 探针（实证）：新浪字段8（股）/100 后与**日线 `vol`（手）**吻合——茅台 26,366 vs 日线 28,218 手（**盘中≈93%**）、平安 690,979 vs 715,341（**96.6%**）；修正前为 2.6亿/69亿 手（荒谬）。
- 影响面：快照 `volume` 经 `_feed_minute_aggregator`→`minute_kline_cache`（dim1 分钟/周线通路）；修正后与日线 / AKShare「总手」同口径。

### #2 `minute_backfill.py` 查错库 ✅（**核实更正**）
- **重要更正**：`ensure_minute_data` **全仓无调用方**（唯一提及＝2026-07-19 沟通记录；`grep` 全仓 0 调用），且总库 `stock_cache.db` **无** `minute_kline_cache`/`daily_cache` 表（实证命中 0）⇒ 该函数是**死代码且一调即抛 `no such table`**，**并非** 498 号 §一 所述「当前生效」。**498 §一「当前生效」表述据此更正为：潜伏（死代码）**。
- 改法：两处 `ecm_local.conn.execute` → **`ecm_local._query_shard(...)`**（分库读，与 `get_cached_minute_kline` 一致；`COUNT(*) AS n` + `pd` 取数）。
- 探针：分库读 5min（0 行=真实缺失，非查错库）/ 1min（4371、6096 行）正常；总库命中 minute/daily 表 **0**（证原直读必失败）。
- 性质：修「事实/取数」层，非「果」；若后续确认该函数废弃，可另号删除（#2 与 §四 `ensure_minute_data:314-321` 同族）。

### 运行态
- 验证期**停 daemon+看守**（分库锁致 pytest 挂起，研发阶段规则）→ 跑测试 → **已重启看守**（daemon 30s 后自起）。改动**未推送**。

---

## 十二、批次2 实施记录（2026-09-29，配置治理「核心三项」）

> 范围（用户拍板）＝**核心三项**：①Q2 第一步（#11：`data_sources.yaml` 迁 `backend/config/` + 接「限流」与「数据源优先级」）；②#35 `tushare_provider` 删个人硬编码路径；③#34 `.env` 读取保护。**§六-2（DATA_DIR）/§六-3（硬编码参数集中）留待单独批**。改动 4 文件（1 迁位 + 3 代码）；验证：`py_compile` OK、ruff **零新增**、`test_431_g2_config_loading` **19 passed**、探针（`load_yaml`/`_TS_MIN_INTERVAL`/token）全绿。

### #11 迁位 + 接线 ✅
- **迁位**：`git mv config/data_sources.yaml backend/config/data_sources.yaml`（对齐 430 号权威位置；根 `config/` 仅剩 prompts/description_config.json）。
- **限流接线**：`data_daemon.py` 新增 `_load_ts_min_interval()`——读 `backend/config/data_sources.yaml` 的 `rate_limits.tushare.requests_per_second`（=5）→ `_TS_MIN_INTERVAL=1/5=0.2`；**与接线前硬编码 0.2 数值一致 ⇒ 零行为变更**；yaml 缺失/异常回退 0.2。
- **优先级接线**：`app/__init__.py` 注册数据源时新增 `_source_priority(source, default)`——按 yaml `data_sources.<table>.priority`（P0→0/P1→1/P2→2/P3→3，最小者）；tushare（P0）→ **0（与接线前 `priority=0` 一致，零行为变更）**。
- **不接线项（避免改行为）**：yaml 的 `fallback_strategy`（降级链实测**从未调用** `init_fallback_chains`——死配置）与 `collection_schedule`（采集时段由 daemon 主循环控制）**均无运行时消费方**，属第二/四步，不在本批。
- 验证：`load_yaml('data_sources.yaml')` 读 `backend/config/` 成功；`_TS_MIN_INTERVAL`=0.2；tushare 优先级=0。

### #35/#34 `tushare_provider._load_token` ✅
- 删除写死的个人绝对路径（`/Users/kalence/Desktop/测试/...` ×3 —— 换机即失效 + 泄漏本地路径），改为**项目根 `.env` 相对路径**（`dirname×3 + '.env'`）兜底；读取加 `try/except` + `encoding='utf-8'`。
- 验证：`.env` 含 `TUSHARE_TOKEN`（1 处）且 `load_dotenv`（`app/__init__.py:10`）先于 provider 构造 ⇒ 主路径为 `os.getenv`，本兜底仅 env 未注入时触发；实测 token 载入（len 56）、`pro` 初始化成功。

### 运行态
- 验证期**停 daemon+看守**（分库锁致 pytest 挂起）→ 跑测试 → **已重启看守**（`start_daemon.sh` + daemon，加载 v1.3/v1.4 全部代码）。改动**未推送**。

---

## 十三、批次3 实施记录（2026-09-29，并发健壮性）

> 范围＝并发/竞态类：#16/#17/#18/#19（共享可变状态无锁）+ #20（分库连接缓存竞态）+ #24（`init_sharding` 未 close 旧实例）+ #26（`_unmapped_warned` 无锁）。**#22 经实证否定**（见下），#23 仅日志降级→顺带低优先。改动 5 文件；验证：`py_compile` OK、ruff **零新增**、并发探针 6/6 全绿、`test_426_*` **33 passed**。

### #16 / #17 `mootdx_collector.py` ✅
- **#16**：新增 `_prev_prices_lock`，`_calc_speed` 的「读 prev + 写 price」原子化（`_fetch_eastmoney` 4 线程并发）。
- **#17**：新增 `_source_stats_lock`；`_record_source_result`（写计数）、`get_source_stats`（读快照）、新增 `_set_active_source`（写 `_active_source`，`fetch` 4 处改走它）全部加锁——采集线程写、API 线程读。
- 探针：#16 4 线程×2000 异常 0；#17 4 线程×5000 计数 **20000/20000 无丢失**。

### #18 `fallback_manager.py` ✅
- 新增 `self._lock = threading.RLock()`（RLock：`get_healthy_source` 内部再调 `_is_source_healthy`/`_record_fallback`）；`register_fallback_chain`/`update_health_status`/`_is_source_healthy`/`_record_fallback`/`get_health_report` 加锁。`update_health_status` 的告警 `logger.warning` 移出临界区（`_unhealthy` 标记）。
- 探针：4 线程×3000 `update_health_status` → `total_failures` **6000/6000 无丢失**。

### #19 `tushare_provider.py` + `data_daemon.py` ✅
- 两处 Tushare 限流器 `_ts_last_call` 的 check-sleep-set 加锁（各自 `_ts_lock`）：`tushare_provider._ts`（线程 import 移至顶部，避免 ruff I001）、`data_daemon._ts`。
- 探针：5 线程并发 `_ts` 总耗时 **0.81s**（串行化正确；无锁会 <0.2s）。

### #20 / #24 / #26 `sharding_manager.py` ✅
- **#20**：新增 `self._conn_lock`，`get_connection` 缓存检查+建连改双检锁（原两线程首次并发各建一条 sqlite 连接、后者覆盖前者泄漏句柄）。
- **#24**：`init_sharding` 替换全局单例前 `_old.close_all()`（daemon 启动 + `conftest` 切沙盒均走此路径）。
- **#26**：`_unmapped_warned` 集合读写加 `_unmapped_warned_lock`（告警 `logger.warning` 移出临界区）。
- 探针：#20 20 线程并发 `get_connection` → **连接对象数=1**（无重复建连）；#24 替换后旧实例 `_connections=0`（已关闭）。

### #22 实证否定（未改） ❌
- 498 号 §四 #22 称「缓存连接默认 `isolation_level=''` 隐式事务：只读 `execute_query` 只 execute 不 commit，读事务挂在共享连接上阻塞 WAL checkpoint」。
- **实测反证**：Python `sqlite3` 默认 `isolation_level=''` 下，**SELECT 不开启事务**（`in_transaction=False` after SELECT；仅 DML 开启）。故 `execute_query` 只读不产生悬挂读事务，**#22 前提不成立** ⇒ 不改。另 `_ensure_snapshot_indexes` 末尾已有 `conn.commit()`（迁移语句会提交）。

### #23 顺带（低优先）
- `_ensure_snapshot_indexes` 建索引/迁移失败原仅 `logger.debug`（易被静默）——`#23` 属可观测性优化；本批未改（无行为影响），登记后续。

### 运行态
- 验证期**停 daemon+看守**（后台看守任务会重启 daemon 致 pytest 挂起，须 `pkill -9` 看守）→ 跑测试 → **已重启看守**（`start_daemon.sh` + daemon，加载至批次3 全部代码）。改动**未推送**。

---

## 十四、批次4 实施记录（2026-09-29，源管理/分钟通道「事实子集」）

> 范围（用户拍板）＝**事实子集**。实做：分钟时间基准（#4/#14/#40）+ 降级/静默吞（#43/#30/#33/#51/#44/#32）+ 分库读告警（#21/#23）+ 源健康**事实侧**加固（#15 连续成功计数、#5 快路径记账、#6 递归上限）。**唯一未做的源可用性判定项＝#7**（未注册源默认 healthy，偏「果」，留待拍板）。**其他延后项**：#31（全市场快照重建，上层 TieredMemoryCache 已 3s TTL 缓解）、#41（`aggregate` O(history)，perf/有 OOM 风险需另评估）、#42（逐股宽 except+ok 虚增，偏统计）。改动 6 文件；验证：`py_compile` OK、ruff **零新增**、探针 `_498_batch4_probe.py` 全绿、定向回归 **50 passed**。

### 分钟时间基准（#4 / #14 / #40）
- **#4** `minute_backfill._get_mootdx_minutes_safe`：`hour = 9 + (idx+30)//60`（未跳午休）→ 按 idx 分段映射（i<120→09:30-11:29；i≥120→13:00+，跳过 11:30-13:00）。探针 idx=119→11:29 / idx=120→**13:00**（旧逻辑 11:30 错）。
- **#14** `mootdx_collector._feed_minute_aggregator`：`datetime.now()` → `trading_hours._now()`（utcnow+8h 北京时间）——防部署机时区非 UTC+8 时 minute_key/trade_date 错位。
- **#40** `minute_backfill.backfill_5min`：陈旧判定由日历日 `days_since<=5` 改**交易日**（`trading_hours.is_holiday`，>3 个交易日才判过旧；日历不可用回退日历日阈值）。

### 源管理/降级/静默吞（#43 / #30 / #33 / #51 / #44 / #32）
- **#43** `mootdx_collector._fetch_tencent`：去 `min(len(codes),2000)` 截断（代码循环 `range(0, len(codes))`）——修沪市（索引 12000+）降级到腾讯时永不触达。
- **#30** `akshare_provider.get_limit_pool`：涨停/跌停两腿各自独立 try——单腿失败不再丢弃另一腿。
- **#33** `akshare_collector._collect_sentiment_pool`：加 `_err_count`，全接口失败与「空交易日」区分（补告警）。
- **#51** `akshare_collector`（分钟线采集）：mootdx 探测 `except Exception: pass` → `logger.warning`（暴露 import/程序缺陷，语义不变）。
- **#44** `mootdx_collector._do_flush_one`：两处 `except: pass`（mem_store / ECM 写入）→ `logger.debug`（已完成分钟 K 线丢失可诊断）。
- **#32** `akshare_collector`：新增 `_safe_int`（`''`/`None`/`NaN`/非数字回退默认），替换板块/概念排行 2 处 `int(row.get(...))`（原一坏单元格毁整轮）。

### 分库读告警（#21 / #23）
- **#21** `sharding_manager.execute_query`/`table_exists`：未登记表读路径补 `_warn_unmapped`（原静默返回 `[]`/`False`，与写路径口径不一致）。
- **#23** `sharding_manager._ensure_snapshot_indexes`：建索引/`signals` 迁移失败 `logger.debug` → `logger.warning`（迁移失败可见）。

### #15 顺带加固（源可用性判定·因侧）
- `data_source_manager.DataSourceHealth`：新增 `consecutive_successes`（成功+1、失败归零）；自动恢复判据由**累计** `successes>=3` 改**连续** `consecutive_successes>=auto_recovery_successes`（阈值经 `register_source` 注入，读 `auto_recovery_successes` 配置）。
- 定性：修复「注释称连续但用累计」的**事实缺陷**（历史有 3 次成功则单次成功即误恢复）；非改判定阈值。探针：累计 6 / 连续 1 时仍 `fallback`，连续 3 次后 `normal`。
- 注：#5（快路径记账）、#6（递归上限）虽属源管理，但**已随本批一并实施**（#5 补 `record_success/failure` 记账、#6 加 `_retry` 深度上限）；**#7（未注册源判 unhealthy）保持原样**（偏「果」，留待拍板）。

### 运行态
- 验证期**停 daemon+看守**（须 `pkill -9 -f start_daemon.sh`，后台看守任务会重启 daemon）→ 跑测试 → **已重启看守**。改动**未推送**。

---

## 十五、批次5 实施记录（2026-09-29，低危/死代码清理）

> 范围＝低危/死代码（零行为变更优先）。实做：#46 日志括号 + #47 死状态 + #48 死函数 + #49 `_seen` 无界 + #50 重复 logger + #55 死常量 + #56 无效 global。**延后**：**#8/#13**（`tushare_provider` 6 方法整段重复 + 不可达死块——删重复段须先确认保留哪份副本并回归 provider 全接口，属独立 refactor，另批）、#52（`_get_stock_name` 20 码硬编码，补全需全量名称映射＝功能扩展）、#53（`get_minute_data` AKShare 分钟日期格式，需 AKShare API 知识且低危）。改动 3 文件；验证：`py_compile` OK、ruff **零新增**、定向回归 **52 passed**。

### 死代码/低危（#46~#50 / #55 / #56）
- **#46** `data_daemon`：3 处财务日志 `…(共 N 只` + (`else ")"`) + `+ ")"` 括号不平衡（`n_skip=0` 输出 `…共 N 只))`）→ 合并为 `+ (f"，跳过 {n_skip} 只已有最新期)" if n_skip else ")")`；探针两情形括号均平衡。
- **#47** `data_daemon`：删只写不读的 `_SYNCED_TODAY`（模块声明 + `global` + 赋值；日终幂等实际由 `_drive_pipeline` step 标记保证）。
- **#48** `data_daemon`：删死函数 `_check_daily_sync_backfill`（全仓零调用，仅 `main` 注释提及）。
- **#49** `data_daemon._DedupLogFilter`：`_seen` 加 `_MAX_SEEN=20000` 上限（键含逐码内容，长驻进程原无界增长），达上限清空重来。
- **#50** `data_source_manager`：删第 32 行重复 `logger = logging.getLogger(__name__)`（顶部 :16 已有）。
- **#55** `mootdx_collector`：删死常量 `_FLUSH_BATCH_SIZE`（全文件未引用）。
- **#56** `mootdx_collector._compute_sector_rankings`：删无效 `global _last_sector_ts`（声明了从未定义的模块变量，实际用函数属性 `._last_ts`）。

### 延后（本批未做）
- **#52**：`akshare_provider._get_stock_name` 只认 20 个硬编码码 → 补全需全量名称映射（功能扩展，非清理），另批。
- **#53**：`akshare_provider.get_minute_data` 对 `None` 日期传空串（AKShare 1min 期望 `'%Y-%m-%d %H:%M:%S'`）→ 需 AKShare API 知识验证，低危。

### 运行态
- 验证期停 daemon+看守 → 跑测试 → **已重启看守**。改动**未推送**。

---

## 附录：OCR 会话与原始清单

- **app/data 段**：session `395f8657-f3a9-4385-9851-150352078fef`，10 文件 / 54 条 / ~1.08M tokens / 1m2s；原始输出保留于 `/tmp/ocr_col/app_group.txt`（临时，未入库）。
- **daemon 段**：session `0aa2c029-60d1-495c-aa09-61ce9f7522bd`，1 文件 / 6 条 / ~2.27M tokens / 1m6s；`/tmp/ocr_col/daemon.txt`。
- `data_daemon.py` 超单文件上限，按 496 号先例以 `--max-tokens 200000` 单独扫描（默认 `too_large` 排除）。
- **覆盖核对**：OCR 全部 60 条已逐条落位——§三 15 项、§四 30 项、§五 11 项（共 56 项，同因/重复处归并）、§七 排除 2 条；无遗漏。
