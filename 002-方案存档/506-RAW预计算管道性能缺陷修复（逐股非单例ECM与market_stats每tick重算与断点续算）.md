# 506号｜RAW 预计算管道性能缺陷修复（逐股非单例 ECM + market_stats 每 tick 重算 + 无断点续算）

> **版本**：v1.0（2026-10-02 只读核查确诊 + 五项修复实施 + 探针 9/9）
> **前置**：用户「核实昨日跑的 RAW 后台预计算是否完成」→ 发现 09-30 RAW-2 反复跑不完、耗时异常 → 要求代码层 + 管道核查 → 确诊并全量解决。
> **关联**：505 号（RAW 步骤线程累积，428 P1-2 慢场景自激振荡）已修「多轮并发线程累积」；506 号修「单轮内的结构性慢」——两者叠加才是 09-30 跑不完的完整原因。

---

## 一、缺陷核查（2026-10-02 实证）

**现象**
- 09-30 单轮 RAW-2 反复跑不完：`factor_cache`(09-30) distinct 股票数整个上午**恒 4126**（完整参照 5532，缺 ~1400 只），`cached_at` 持续刷新＝每轮都在重写已有股票。
- 单只耗时从基线 ~0.34s（2026-09-29 代码注释）恶化到 **2.4~9 s/只**；主循环 tick 由 30s 膨胀到 **47~95s**。
- 10-01 单只超时约 1000 条（18-23 点），10-02 上午 74 条；10-01 出现 **836 次 `database is locked`**。
- 昨日（10-01）夜间那轮 RAW-2 于 **2026-10-02 00:25 被停止信号中断**，停在约 2500/5559；`RAW-2/3 → done` 标记从未出现。

**根因（实证）——RAW-2 逐股路径构造非单例 ECM**

```
_raw2_one(code)                                   # data_daemon.py，每只股票1次
 └─ PhaseDetectionEngine().compute_tags(code, df) # 逐股新建引擎
     └─ _dim_chip → _run_trading_phase_detector_v2
         └─ ChipIndicators()                       # phase_detector.py（逐股构造）
             └─ ChipDistributionService()          # chip_indicators.py:19 默认参数
                 └─ EnhancedCacheManager()         # chip_distribution_service.py → 非单例！
                     └─ _init_tables()             # 全量 DDL + 5 连接 + 补列迁移 + 34 表空壳扫描/DROP
```

- 实证：`ChipIndicators()` 连造 3 次得 **3 个不同 ECM 实例 id**（4458693648 / 4584800848 / 4458692816）；单只 `compute_tags` 实测构造 ECM **1 次** → 全市场 ≈5559 次/轮。
- 对应日志「总库空壳表自清理: DROP 34 张」（`_init_tables` 末尾，`enhanced_cache_manager.py:1263`）：**10-01 共 8379 次**（15 点单小时 1752 次），10-02 已 337 次。
- 每次构造打开的 5 个连接中 `conn`（可写）叠加，是 `database is locked` 的直接来源。

**次因 A——`_precompute_market_stats` 每 tick 重跑**

- 该函数位于 `_drive_pipeline` RAW 段（RAW 每 tick 都进入 → 每 tick 跑一次），含分库统计读 + `cache_market_stats` 落库。
- 实测：**10-01 共 218 次**、10-02 单轮 45+ 次（约每 47~95s 一次）。

**次因 B——RAW-2/RAW-3 无断点续算**

- `_precompute_raw_features` / `_precompute_preset_combos` 每轮从 `codes[0]` 顺序全量重跑；慢场景/多轮下已算股票反复重算、缺口股票永远排不到 → 4126 卡死。

**死代码**：`phase_detector.py` 的 `_run_trading_phase_detector`（同样 `ChipIndicators()`）零调用方（实际走 `_run_trading_phase_detector_v2`），属历史死路径 + 性能陷阱。

## 二、拍板记录（2026-10-02，用户「务必全量解决相关问题」）

| 项 | 决策 |
|----|------|
| 范围 | 全量解决核查出的 RAW 管道性能缺陷（F1~F5），开正式方案号存档 |
| 修复策略 | 根治非单例 ECM 构造（F1 幂等 + F2 单例化）＋ 节流（F3）＋ 断点续算（F5）＋ 清死代码（F4） |
| 是否停 daemon | 是（写库/建表路径改动，需重启加载；研发现阶段 daemon 可随时停） |

## 三、修复设计（F1~F5，全部已实施）

- **F1 `_init_tables` 按 db_path 幂等**（`enhanced_cache_manager.py`）：模块级 `_tables_initialized_paths: set`；`__init__` 中仅当 `self.db_path not in _tables_initialized_paths` 才调用 `_init_tables` 并登记。按 db_path 而非全局布尔——测试常以不同 `DATA_DIR` 临时库构造 ECM，须各自建表。**效果**：同库第二个 ECM 起跳过全部建表/迁移/空壳扫描。
- **F2 非单例默认构造改单例**：
  - `chip_distribution_service.py` `ChipDistributionService.__init__`：`cache_manager or get_ecm_instance()`；
  - `factor_precompute.py` `FactorPrecomputeManager.__init__`：同上；
  - `routes/factors.py` 模块级 `cache_manager = get_ecm_instance()`。
  - **效果**：RAW-2 逐股构造不再新建 ECM（实测 50 次构造 → ECM 构造 1 次、单例 id 唯一、0.0002s/次）。
- **F3 `_precompute_market_stats` 当日节流**（`data_daemon.py`）：新增模块级 `_market_stats_last_done_date` + 函数签名 `force: bool = False`；入口若「非 force 且上次成功日期==本次目标日期且内存缓存非空」直接 return；成功落库后记录日期。**效果**：同一交易日只算一次（原 218 次/日 → 1 次/日）。`_market_stats_cache` 非空条件兼顾脚本回补与测试反复调用。
- **F4 删死代码**（`phase_detector.py`）：删除 `_run_trading_phase_detector`（零调用方）。
- **F5 RAW-2/3 断点续算**（`data_daemon.py`）：`_precompute_preset_combos` / `_precompute_raw_features` 开头查 `daily_cache` 最新交易日，取 `factor_cache` / `pre_feat_cache` 该日已有股票集合，从 `codes` 中剔除 → 只算缺口。**效果**：直接解 4126 卡死，慢场景可多轮收敛。

**不变**：RAW-1/2/3 并行、写库主线程、单股 `_run_with_timeout`（RAW-2 60s / RAW-3 30s）、`INSERT OR REPLACE` 幂等、505 号 fut.done 等待制、426 续算语义。

## 四、验证口径

- **行为测试** `tests/test_506_raw_pipeline_perf.py` **9/9**：F1 同库三次构造仅一次 `_init_tables`；F2 chip/factor 服务默认共享单例；F3 同日第二次跳过 + `force=True` 绕开 + 新日期正常；F4 `_run_trading_phase_detector` 已删除、`_v2` 保留；F5 源码含断点续算 + 已完成股票被跳过。
- **定向回归**：`test_428_gap_fixes` / `test_426_phase3_schedule` / `test_426_p0_correctness` / `test_447_dim5_emotion_fix` / `test_kline_pattern_wiring` **99 passed**。
- **505 管道探针** `scripts/_505_raw_round_probe.py` **11/11**（状态机未受影响）。
- **全量回归**：`tests/` 目录（详见 §六 实施记录）。
- **ruff**：data_daemon 基线 **38 errors 零新增**。
- **实机**：重启 daemon → 观察单只 RAW-2 耗时回落、`总库空壳表自清理` 仅启动一次、tick 回到 30s、`factor_cache`(09-30) distinct 由 4126 向 5532 收敛、`RAW-3 断点续算: 跳过已完成 …` 日志出现。

## 五、沟通记录

- **2026-10-02 核查**：用户「核实昨日跑的 RAW 后台预计算是否完成」→ 只读核查（日志/落库/进程）确认未完成 + 耗时异常 → 用户「这个预估耗时太长了，存在不正常的情况，需要你进行代码层面及预计算管道的核查」→ 定位根因（逐股非单例 ECM + market_stats 每 tick + 无断点续算）→ 用户「将所有问题逐一核实并开正式方案号存档，务必全量解决相关问题」→ 本档 v1.0 + F1~F5 实施。

## 六、实施记录

**2026-10-02（v1.0 全部实施）**

| 文件 | 改动 |
|------|------|
| `app/data/enhanced_cache_manager.py` | F1：`_tables_initialized_paths` + `__init__` 按 db_path 幂等 |
| `app/data/chip_distribution_service.py` | F2：`get_ecm_instance()` 默认单例（含 import） |
| `app/data/factor_precompute.py` | F2：`get_ecm_instance()` 默认单例（含 import） |
| `app/routes/factors.py` | F2：模块级 `cache_manager = get_ecm_instance()` |
| `data_daemon.py` | F3：`_market_stats_last_done_date` + `force` 参数 + 入口节流 + 成功记录；F5：RAW-2/3 断点续算 |
| `app/opportunity_atlas/phase_detector.py` | F4：删死代码 `_run_trading_phase_detector`（44 行） |
| `tests/test_506_raw_pipeline_perf.py` | 新增：F1~F5 验证 9 例 |

**验证**：py_compile 全绿；506 探针 9/9；定向 99 passed；505 管道探针 11/11；ruff data_daemon 38 errors（=基线，零新增）；全量 `tests/` 回归见下。

> **待续**：实机验证（停 daemon → 重启加载 → 观察 09-30 补齐至 5532 + 耗时回落 + tick 恢复）。实施后 09-30 缺口股票将在单轮内被补齐（断点续算），不再反复重算 4126。
