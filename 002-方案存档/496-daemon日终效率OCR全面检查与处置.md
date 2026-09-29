# 496号｜daemon 日终效率 OCR 全面检查与处置

**状态**：v1.0（2026-09-29）——第一批（三件 + 问题4/5 + OCR 三项）与第二批（#1/#2/#3/#9/#10）已实施；其余列入 §三 待办。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek deepseek-chat）按功能拆 5 段全量扫描 data_daemon.py（7912 行）+ sharding_manager.py，34+ 条发现经**人工核实**（拆分片段存在上下文误报，逐条对照真实代码）。

---

## §一 已实施（勿重做）

| 项 | commit | 说明 |
|---|---|---|
| fina_indicator 不下传 start_date/end_date | f0cdd1c | 接口不支持日期参数 → 恒空风暴 + 配额浪费 |
| `_target_fin_period` 9~10 月目标期改 06-30 | f0cdd1c | 原误推 09-30 → 覆盖判定恒 False → COL-7 全量重拉 90min |
| sync_requests 过期积压清理 | f0cdd1c | per_stock/precompute_raw/indicators/full_* 13299 条标记 done |
| RAW-2 线程池并行（4 并发） | 13cc780 | 5557 只单线程 31min → ~8min |
| 启动前置 `_wait_db_unlock` | 13cc780 | 独立连接 BEGIN IMMEDIATE 探测，消灭启动锁风暴 |
| RAW-2 `_raw2_one` trade_date 竞态 | d74f532 | 并行下 nonlocal 共享 cell → 改局部 td |
| RAW-2 写库失败与特征失败分开统计 | d74f532 | except 收窄至 fut.result |
| `_wait_db_unlock` 分库清单补 system_cache/market_snapshot | d74f532 | sharding 注册分库补全 |
| **#1** RAW-2 `calc_support_resistance` 每只只算一次 | 5193306 | 原衍生/risk_ext/structure_ext 三处重复，全市场 ×3 |
| **#2** `get_indicators_wide` 复用预热 indicator_ma_dict | 5193306 | miss 才查库 |
| **#3** `_update_account_risk_status` 缓存模块级 Flask app | 5193306 | 原每 10 分钟 create_app 重建 |
| **#9** `_write_factor_signals` failed 初始化 | 5193306 | 原 NameError 吞兜底整段中止 |
| **#10** treemap `_tm_conn` 连接失败 guard | 5193306 | 原异常路径 UnboundLocalError |

---

## §二 本次 OCR 全量发现（含已核实证据）

### 🔴 高影响（日终耗时）
- #1 ✅ calc_support_resistance 3 处重复（4010/4080/4323）——已修
- #2 ✅ get_indicators_wide 2 次（3586 预热 + 3783 内）——已修
- #3 ✅ create_app 每 10 分钟重建（7547 + 主循环 7861）——已修

### 🟠 中影响（管道旁路 / 周期开销）
- #5 `_maybe_monthly_ic_recalc` 主循环每 30s tick 解析 2 个 JSON（7852）——建议改日粒度节流
- #6 treemap 快照逐行 INSERT ~5557 次（5586）——建议 executemany + 单事务
- #7 `_batch_backfill_minute_kline` 每轮重查 `SELECT DISTINCT ts_code` 全表扫（8 轮）——建议增量维护
- #8 `_query_table` 吞异常返回 0（1940）——DB 故障误触发全量补采，建议区分失败/空

### 🟡 正确性 / 稳定性
- #11 `_market_stats_cache` 后台线程写、无锁、整表清空——建议原子替换
- #12 `_jud_meta_cache` clear-then-fill 无锁——建议局部构建后原子赋值
- #13 信号验证 `chk_price` 未防护（None → TypeError 中止循环）
- #14 sharding_manager `get_table_row_count` 拼接表名（SQL 注入面）——建议表名白名单
- #15 ±20% `pct_chg` 质量检查误报（ST 5%/创业板 20%/首日无限制）——建议按板块区分
- 段 C：`vps._detect_kline_patterns(df)` 每只计算但**从不消费**（死调用，建议删除）
- 段 C：`'cl_result' in dir()` 脆弱存在性检查（建议初始化 sentinel）
- 段 E：`pd` 未模块级绑定（`pd.to_datetime` 依赖前序 import，潜在 NameError）
- 段 E：信号验证双 sqlite 连接无 try/finally（异常路径泄漏）
- 段 E：`_maybe_monthly_ic_recalc`/`_update_account_risk_status` 计时器重建（#3 已修账户钩子）
- 段 A：`_fina_indicator` 方案2 `pro.stock_basic(...)` 绕过 `_ts` 限流/超时保护（潜在 daemon 挂起）
- 段 A：`_backfill_moneyflow` 跨分库不匹配静默吞（existing 恒 0）
- 段 A：条件 f-string 日志括号不平衡（n_skip 时多一个 `)`）
- 段 A：`_compute_relative_strength` 全量重算无增量（run_daily_sync 路径）
- 段 B：`failed` 未初始化（_write_factor_signals，已修 #9）
- 段 B：±20% pct_chg 误报（同 #15）
- 段 D：treemap N+1/逐行 INSERT（同 #6）；`_jud_meta_cache`（同 #12）

---

## §三 剩余待办（未实施，待拍板）

### 批次 A（聚焦，**已全部实施 2c2890d**）
| 项 | 改动 | 状态 |
|---|---|---|
| #6 treemap 逐行 INSERT → executemany + 单事务 | `_build_treemap_snapshot` 写路径 | ✅ |
| #5 IC 重估日粒度节流 | 主循环 `_maybe_monthly_ic_recalc`（模块级 `_ic_recalc_check_date`） | ✅ |
| 段 C 删死调用 `vps._detect_kline_patterns(df)` | `_raw2_one`（结果从不消费，3850 注释自证） | ✅ |
| #13 chk_price guard | 信号验证循环 | ✅ |

### 批次 B（正确性，建议独立核查）
- #8 `_query_table` 区分失败/空（涉及全链路补采触发语义，需谨慎）
- #14 sharding 表名白名单（安全，涉契约）
- #11/#12 无锁共享状态原子化（`_market_stats_cache`/`_jud_meta_cache`）
- 段 A `_fina_indicator` 方案2 回归 `_ts` 包装
- 段 E 连接泄漏 try/finally、pd 绑定、日志括号

### 批次 C（观察/低优先）
- #7 分钟回填增量、±20% 阈值按板块、`_backfill_moneyflow` 吞异常、`_compute_relative_strength` 增量

---

## §四 验收口径
- 每批实施后跑 `test_428_gap_fixes.py`（现 26 passed）+ 相关回归；
- 日终效率对比：目标 COL-7（90min→分钟级）+ RAW-2（31min→8min→去重后再压）+ SIG/JUD 稳定；
- 全量 pytest 批量污染为既有问题（跑全量需 `--ignore='$TMPDIR'` + 停 daemon）。

---

## §五 C1~C4 日终核验结果（2026-09-29，09-28 管道 16/16 done 后）✅ 全过

探针 `scripts/_496_c1c4_probe.py`（已提交）。

| 项 | 基线（495 批次2） | 核验结果（09-28） | 结论 |
|---|---|---|---|
| **C1** K4 `entry_zone` 回升 | 0%（RAW-2 未刷新） | advice_params 含键 5049 只；抽样 1000 只 **914 非空（~91%）**，target_zone 同步 | ✅ 达成 |
| **C2** `signals` 落库 | 待日终 | **5553/5553 全落库**（样本=注册信号数组） | ✅ 达成 |
| **C3** `sentiment_phase` | ebb 5544 只（池空 fallback） | **5553/5553 = ferment**（488-2 采集修复 + RAW-2 主源重算归一） | ✅ 达成 |
| **C4** 479-3 状态机口径 | 观察项 | vp_state_label/vp_rule 非空 **5539/5553（99.7%）**，8 态分布合理（价跌量缩 3055/底背离 1161/强势 737…） | ✅ 观察通过 |

**运行态**：daemon 已于 10:28 重启加载全部新代码（看守+实例新 PID，主循环正常，无 database is locked / 无 fina 空返回风暴）；09-28 日终管道 16/16 done（OUT 10:07 / QA 10:17）。
