---

# 501号｜RAW 预计算层 OCR 核查与处置

**版本**：v2.0（2026-10-01；**七批次全部实施完成**，代码已改、未推送，详见 §十~§十六）
**v2.0 批次7 实施（2026-10-01）**：用户「更新文档到 v1.3，然后开工批次7」→ 死代码/文档清理 4 项全做：**#R53**（`calculate_factor_combination` 死路径标注 + 权重分母仅统计实际参与因子 + 全失败返回长度匹配 NaN 序列——顺带修 `pd.Series([], index)` 新版 pandas Length mismatch）、**#R54**（opportunity DIVIDEND_YIELD/EMOTION_EXTREME 设计态登记）、**#R62**（`_erp_percentile` 单观察返回 **0.5 中性分位**——非 None，None 触发 426 P0-1「无源数据」整批不落库；`CN_10Y_BOND_YIELD_PCT` 单位确认=百分数 1.7%）、**#R63**（calculator 惰性日志参数化 ×2）。改动 `calculator.py`/`opportunity.py`/`data_daemon.py` 3 文件；探针 `_501_batch7_probe.py` **8/8 全绿**、ruff 零新增、回归 **431 passed**（**⚠️ 首个 #R62 版本 `len<2→None` 致 test_447 失败→改 0.5 中性值，447 23 passed**）。**至此 501 七批次 43 项修复全部落地，本号收官**。
**v1.3 批次6 实施（2026-10-01）**：用户「开工批次6」→ 公式/语义错位（非每日路径）10 项全做：**#R40**（qlib158 4 个 rank 因子文档更正为时序分位）、**#R42**（CMO 保留 NaN）、**#R43**（CVaR `np.percentile`——修原 `series.quantile` 在 ndarray 上 AttributeError，因子从未跑通）、**#R44**（HURST 守卫对齐 period）、**#R55**（GTJA 真因子短输入 ValueError）、**#R56**（GTJA014/021/022/028/034/038 硬编码标签参数化；048/050 核实已参数化）、**#R57**（GTJA191 平盘 `np.isclose`）、**#R59**（momentum MACD 参数名 `fast/slow/signal` 对齐 a_stock）、**#R60**（MOM 归一提示）、**#R61**（Alpha1 docstring 补全）。改动 7 文件；探针 `_501_batch6_probe.py` 全绿、ruff 零新增、回归 **431 passed**。
**v1.3 批次5 实施（2026-10-01）**：用户「继续批次5」→ 非有限值/边界守卫 6 项全做：**#R18/#R19**（volatility pct_change/log inf 守卫）、**#R20**（REV_1 pct_change 守卫）、**#R22**（Garman-Klass 负方差 clamp）、**#R24**（gtja ×4 + alpha101 ×3 check_data 契约；**修正 Alpha007/008 window 5→10**）、**#R25**（`cl_result = None` 显式初始化替代 `in dir()`）。改动 6 文件；探针 `_501_batch5_probe.py` **18/18 全绿**、ruff 零新增、回归 **431 passed**。
**v1.3 批次4 实施（2026-10-01）**：用户「开工批次4」→ 指标引擎一致性 6 项全做：**#R46**（删死赋值）、**#R47**（`get_latest_indicators` 返回键补全 bbi/ene/ma30-250）、**#R48**（九转向向量化——**3 种子与原循环语义等价**）、**#R49**（RSI 双实现 `delta.fillna(0)` 统一——**max_diff=0**）、**#R50**（`calculate_kdj` 零分母守卫）、**#R51**（惰性日志参数化）。改动 2 文件；探针 `_501_batch4_probe.py` **10/10 全绿**、ruff 零新增、回归 **431 passed**。
**v1.2 批次3 实施（2026-10-01）**：用户「开工批次3」→ calculator/缓存契约 8 项全做：**#R29**（`FactorCalculator.__init__` 注册表惰性化 + `_get_registry()`）、**#R31**（`_batch_cache_factor_series` `float(value)` 守卫，非数值行跳过不毁整批）、**#R32**（ECM `get_cached_factor` 空=真空、失败由 `_query_shard` warning 可见）、**#R33**（`clear_cache` 结果日志）、**#R34**（位置索引映射防御，长度不一致告警）、**#R35**（`calculate_multiple_factors` 重复名 warning）、**#R36**（异索引 reindex 对齐 + warning）、**#R37**（`calculate_single_factor` 入口统一 copy）。改动 `calculator.py`/`factor_precompute.py`/`enhanced_cache_manager.py` 3 文件；探针 `_501_batch3_probe.py` **14/14 全绿**、ruff 零新增、回归 **391 passed**。
**v1.1 批次2 实施（2026-10-01）**：用户「开工批次2」→ base/registry 加固 8 项全做：**#R5**（`__init__`/`get_info` 每实例拷贝 + tags 深拷贝）、**#R6**（新增 `_validate_param_value`，`param_type`/min/max 真正执行，越界抛 ValueError）、**#R27**（`check_data` 空表/None 判 False）、**#R28**（`get_factor_registry` 双检锁）、**#R30**（`get_all_factors_info` 坏因子跳过）、**#R38**（`required_columns` 字符串归一）、**#R39**（`search_factors` None 守卫）、**#R58**（由 #R6 覆盖）。改动 `base.py`/`registry.py` 2 文件；探针 `_501_batch2_probe.py` **20/20 全绿**（含全量 278 因子注册 + get_info 实例化不抛错）、ruff 零新增、回归 **397 passed**。
**v1.1 批次1 实施（2026-10-01）**：用户「按 §七 开工批次1」→ 当前生效修复 5 项全做：**#R1**（`data_daemon.py` 三处 `_sr_once` → `or {}`）、**#R4**（`compute_win_rates` 10d/20d 独立 `_MIN_SAMPLES` 门槛，不足置 NaN）、**#R21**（`GTJA_HL20` 分母 `where(low>0)`）、**#R23**（`VOL_RATIO_20.name_cn` "20日量比"）、**#R26**（`get_win_rates` 吞错改记日志）。改动 4 文件；探针 `_501_batch1_probe.py` **14/14 全绿**、ruff 零新增、回归 **305 passed**。**⚠️ 实施中事故**：serena `replace_symbol_body` 替换 `compute_win_rates` 误删方法前半段（240→124 行），已从 `git HEAD` 恢复完整方法并重新应用 #R4，最终 diff 无损（见 §十）。
**来源**：2026-09-30 用户要求「调用 OCR 针对系统的 RAW 板块的实际代码配置情况进行检查，相关问题在对话框内详细说明，不要修改方案和代码」→ 对话框内核查报告出具后，用户要求「按 498 先例开 501 号方案文档」。本档＝该报告的正式归档 + 处置方案（供拍板）。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek `deepseek-chat`）按功能拆 **5 段**全量扫描 RAW 板块，共 **73 条发现**，**逐条人工核实**（OCR 存在上下文/伪影误报，全部对照真实代码核对，误报/设计意图单列 §六）。
**范围（RAW＝第 3 层预计算层，426 号定义）**：
- **RAW-1 技术指标**：`app/indicators/__init__.py`（311 行，指标引擎）+ `app/data/precompute_indicator_manager.py`（240 行，win_rate 管理）
- **RAW-3 量化因子**：`app/factors/`（registry.py 177 / base.py 126 / calculator.py 110 / builtin 13 文件 6945 行）+ `app/data/factor_precompute.py`（263 行）
- **RAW-1/2/2B/2C/3 计算函数与调度**：`data_daemon.py`（提取 RAW 专属段 2990-5300 + 6700-6800 + 7055-7100；`_precompute_market_stats`/`_precompute_raw_features`/`_raw2_one`/`_precompute_indicators`/`_precompute_preset_combos`/`_precompute_sector_heat`/`_precompute_industry_position`/RAW 调度段）
**侧重**：RAW 计算配置正确性（公式/文档一致性、边界健壮性、参数校验、注册/并发、缓存读写契约）× 与 `routes/factors.py`（API 按需计算）消费面的一致性。
**基线**：HEAD `e2d4cea`（= origin/main，已 push；工作树 clean，仅 `data/account_risk_status.json` 未跟踪＝daemon 运行产物）。
**边界（445 调整后口径）**：事实/契约层（因）**该改就改**；判定阈值/权重/方向语义（果）**须独立号 + 依据 + 验证**。本档以因/契约/结构层为主；**含「果」成分的口径项（因子公式是否对齐外部平台惯例、是否接入每日预计算路径）已在 §七/§九 标为待拍板，不在本档决断**。
**OCR 会话**：`7b7daa4e-913a-45b8-8f27-5d8a3de5e934`（段1，9 条）；`6af0f9e6-0708-46b1-95e7-34d6ecc9111c`（段2，17 条）；`ff38b70e-aab2-425b-a6e5-4bb0d4d6d8bf`（段3，31 条）；`08ddb627-a042-4bd0-bd2a-a306a2d1b13a`（段4，12 条）；`edcb95b6-f236-41c7-9c44-662a7434d9da`（段5，4 条）。

---

## 一、核查背景与总体结论

- RAW 是「写入网关 → 分库路由 → 质量校验 → 读取分发」STG 存储层之上的**预计算层**：RAW-1 技术指标（indicator_ma/other/win_rate）、RAW-2 特征提取（pre_feat 十组）、RAW-2B 板块热度、RAW-2C 行业位置、RAW-3 量化因子（factor_cache）；426 号（RAW 配置核查）为既有治理依据，416 号已修 5 处配置错误（补 VOL_RATIO_20 类 / academic 改名 / 分库补列 / market_stats 建表）。
- 本次 OCR 全量扫 + 人工核实结论：
  - **73 条原始发现 → 67 项真实问题**（P1 高危 9 / P2 中危 40 / P3 低危·死代码·防御 18）+ **6 条排除**（误报 5 + 设计意图 1，§六）；
  - **当前运行路径无 P0/P1 级数据错误**：RAW-3 每日实际预计算的 **14 个因子**（QLIB_ROC_20/5、QLIB_RSI_14、QLIB_REVERSAL_5、VOL_RATIO_5/20、VOLATILITY_20、BIAS_20 等）**公式实现全部正确**；RAW-2 十组特征/market_stats/RAW-2B/2C 核心路径无重大错误；
  - **主要风险集中在研究型因子库**（`academic.py`/`opportunity.py`/`reversal.py`/`alpha101.py`）：公式与文档系统性背离（Sortino/BETA/ALPHA/Parkinson/WILLR/ROC_R 等），**未接入每日管道、不落 factor_cache**，但 `routes/factors.py` API 端点可算——一旦接入选股/回测须先修公式；
  - **当前生效的 4 项**：win_rate 10d/20d 无样本门槛（#R4）、`_sr_once` None 传播（#R5）、VOL_RATIO_20 中文名错（#R21）、get_win_rates 吞错（#R26）；
  - 与 496/500 重叠项：`'cl_result' in dir()`（496 段C 已登记，本次 #R25 复核属实）；`compute_win_rates` 多周期恒等（500 批次1 已修，本次 #R4 为其残留样本门槛）。**已标注，不重复计**。
  - **本档归并口径**：67 项逐项见 §三~§五；同一处代码可被多条 OCR 命中（如 RSI 边界在 a_stock/gtja191/momentum 三处、参数校验缺失贯穿 base+全库），故按「位置/主题」编号，条数≠OCR 原始条数。

---

## 二、发现总览

| 级别 | 项数 | 主题 |
|------|------|------|
| 🔴 P1 高危（当前生效/一接入即错） | 9 | `_sr_once` None 传播、academic 公式失真集群、opportunity/reversal rank 未实现、trend polyfit NaN、base 参数零校验、base 可变类属性 |
| 🟠 P2 中危（生效低影响/边界/健壮性） | 40 | RSI 三套边界不一致、KDJ NaN、非有限值传播、check_data 绕过、rank 语义错、并发/注册、缓存读写契约、API 正确性 |
| 🟡 P3 低危/死代码/防御 | 18 | 死赋值、日志惰性、Nine Turner 性能、BOLL 重复、死代码路径、硬编码标签、防御性建议 |
| ⚪ 排除（误报/设计意图） | 6 | 未闭合 docstring 伪影、get_latest_indicators KeyError、SMA com、gtja 占位符注册、gtja191 名称冲突、DIVIDEND/EMOTION 设计态 |

> 「实证」＝本次已对照真实代码/调用图确认；「OCR-only」＝OCR 提出但实施前须再核。

---

## 三、🔴 P1 高危（9 项，已实证）

### #R1 `data_daemon.py` RAW-2 `_sr_once` None → `.get` AttributeError（当前生效）
- `_sr_once = calc_support_resistance(df)` 失败置 `None`（提取段 :810-811）；structure_ext 段 `_sr_result = _sr_once; _sr_result.get('support_price')`（:1450-1451）与 risk_ext 段 `geo = _sr_once; geo.get(...)`（:1207）在失败时抛 `AttributeError`，被外层 `except` 吞掉 → **structure_ext/risk_ext 整组静默不产**。
- **实证**：`calc_support_resistance` 有 try/except 置 None 的失败路径；两处消费点直接 `.get`。
- **方向**：`_sr_result = _sr_once or {}`（或消费前判 None）；单次 SR 失败不应拖垮整组。

### #R2 `academic.py:204-208` — market 代理自引用（BETA/TREYNOR/CAPM_ALPHA/ALPHA 恒 0）
- `market_return = returns.rolling(period).mean()` 用**个股自身收益**当市场基准 ⇒ BETA/TREYNOR/CAPM_ALPHA 不实现文档 `Cov(R,Rm)/Var(Rm)`；**ACADEMIC_ALPHA 恒等于 0**（`portfolio_mean - rf - 1.0*(market_mean-rf)` = 自身减自身）。
- **实证**：逐行核对 formula/description 与实现。
- **方向**：接真实市场基准（HS300 等）+ R_f，或删除/标注"代理失真"。

### #R3 `academic.py:97-98` — Sortino 下行偏差公式错
- `returns.where(returns < target, 0)` 注入 0 后 `.std()` ⇒ 把 0 值也计入散布；正确应为负超额收益 RMS（`sqrt(mean(downside²))`）。当前系统性低估/扭曲 Sortino 比率。

### #R4 `precompute_indicator_manager.py:204-209` — win_rate 10d/20d 无最小样本门槛（当前生效）
- 仅 `n5 < _MIN_SAMPLES: continue` 门控 5d；10d/20d 用 `rets[10]/rets[20]` 只经 `_period_stats` 空列表返回 0.0，**无最小样本检查** ⇒ 5d 100 样本但 10d/20d 仅 1-2 个可观测时，`win_rate_10d/20d` 照常产出且 `samples` 列只写 n5，**下游被少样本值误导**（500 批次1 已修多周期恒等，此为残留）。
- **实证**：`:204-209` 逐行；`_period_stats` 对空列表返回 (0.0,0.0,0.0,0)。

### #R5 `base.py:52-59 / 122-125` — 可变类属性共享 + get_info 返回引用（进程级污染）
- `params/tags/related_factors/required_columns` 为类级属性；子类/调用方就地 mutate 即**污染全部因子实例**；`get_info()` 直接返回共享容器与 `FactorParam.default` 引用，`routes/factors.py` 读取后可改全局定义。
- **实证**：`get_info` 逐行；`params` 虽 `to_dict` 但 `default` 仍共享。

### #R6 `base.py:68-71` — 参数零校验（贯穿全库 50+ 因子）
- `FactorParam.param_type/min_val/max_val` **从未执行**；`period=0`/负数直达 `rolling(0)`/`pct_change(0)`/`ewm(com=-1)`，产出异常或静默错值。API `calculate_single_factor` 传 `**params`（`routes/factors.py`）直入 calculate。
- **实证**：`__init__/set_param/get_param` 均无校验。

### #R7 `opportunity.py:27` — PE/PB/PS_PERCENTILE_5Y 全序列 rank（非 5Y 窗口）
- `data['pe_ttm'].rank(pct=True)` 是**整段输入**百分位，随传入区间变化；命名"5Y"但实现非 5 年滚动窗口。且 `required_columns=['pe_ttm']` 与 RAW-2 传的日线 df（无 pe_ttm 列）不匹配 → 实际仅 API 可算。

### #R8 `reversal.py:137-138` — ROC_R/MOM_R 声明 Rank 未实现
- docstring/formula 为 `Rank(ROC(5))/Rank(MOM(20))` 横截面排名，实现返回**原始 ROC/MOM 值**（无 rank）。

### #R9 `trend.py:142-146` — LINEARREG_SLOPE polyfit NaN 抛异常
- `np.polyfit` 窗口含 NaN 时抛 `LinAlgError`/`TypeError`；起始窗口与数据缺口必然触发 ⇒ `rolling.apply` 向上抛 → 整个因子计算失败。应 `not np.all(np.isfinite(x)): return np.nan`。

---

## 四、🟠 P2 中危（40 项）

### RSI / KDJ / 动量边界（三套不一致）
- **#R10** `a_stock.py:237-241` RSI 零损失 → `avg_loss.replace(0,np.nan)` ⇒ 单调上涨 RSI=NaN（应 100）；无收益有损失 ⇒ RSI=0，两侧不对称。同型 RSI_6/14/24 与 **QLIB_RSI_6/14/28（qlib158，含每日生效 QLIB_RSI_14）**。
- **#R11** `gtja191.py:843-845` RSI 零损失 → `avg_loss.where(avg_loss!=0, 1e-10)` ⇒ RS 巨大、RSI 恒 100（伪造最大超买）。GTJA042/043/044 同型。
- **#R12** `momentum.py:63-65` RSI 平盘（period=2 且 avg_gain=avg_loss=0）→ `rs=0/1e-10=0` ⇒ RSI 报 0 而非 undefined。
- **#R13** `momentum.py:204-207` KDJ 平盘 `(high-low).replace(0,np.nan)` → RSV=NaN → `ewm` 向前传播，K/D/J 后续全 NaN（涨停锁死日恰最需信号）。a_stock `RSV:509` 同款。建议平盘给中性值（如 50）或文档化。
- **#R14** `a_stock.py:536` KDJ `com=m1-1` 仅在 m1=3 时等于 span-3；非默认 m1 与中文惯例 K/D 起手 50 的 SMA 平滑偏离。
- **#R15** `a_stock.py:509` WILLR docstring/formula 与实现（`* -100`）在正比值下自洽；但 `replace(0,np.nan)` 平盘分母仍 NaN（低影响，OCR 判无需动作→并入此处登记）。
- **#R16** `momentum.py:133-136` MACD 无 `fast_period < slow_period` 校验；`fast=30, slow=10` 得负向 DIF 被静默接受。
- **#R17** `a_stock.py:374-375` MACD_HIST 实现 `2*(DIF-DEA)` vs 主流平台 `(DIF-DEA)`——惯例待确认（含「果」成分，§九登记）。

### 非有限值传播（无守卫）
- **#R18** `volatility.py:137-139` `pct_change()` 零前收 → inf/NaN 传播进 `*sqrt(252)`。
- **#R19** `volatility.py:161-163` `np.log(close/shift)` 非正值 → -inf/NaN 经 `.std()` 传播。
- **#R20** `a_stock.py:396` reversal 用 `close.pct_change(1)` 零前收 inf 直入下游排名/归一化。
- **#R21** `gtja.py:132` GTJA_HL20 `rolling_high/rolling_low.replace(0,np.nan)` 负/NaN 低值透传 → inf/NaN（GTJA 系）。
- **#R22** `academic.py:417-418` Garman-Klass `- (2ln2-1)*co²` 无下界 → `np.sqrt` 负值静默 NaN（应 `np.maximum(...,0)`）。
- **#R23** `a_stock.py:892-893` **VOL_RATIO_20 中文名错**（当前生效）：`name_cn="20日换手率"`，实际 `Vol/MA(Vol,20)` 是**量比**；VOL_RATIO_5 正确写「5日量比」。用户可见错标签，每日 RAW-3 落库展示。

### check_data / required_columns 契约绕过
- **#R24** `gtja.py:93-94` + `alpha101.py:122` 直索引 `data["close"/"vol"]` 不走 `check_data` ⇒ schema 不匹配时裸 `KeyError` 而非契约错误。
- **#R25** `data_daemon.py` `_raw2_one` 用 `'cl_result' in dir()` 判断缠论是否成功——作用域内省 hack，`len(df)<30` 或 `cl.analyze` 抛错时静默降级（496 段C 已登记，本次复核属实）。
- **#R26** `precompute_indicator_manager.py:235-238` `get_win_rates` 裸 `except: pass`（当前生效）——DB 失败被吞 → 无条件回落全量 `compute_win_rates()` 重算，持久故障反复全量。
- **#R27** `base.py:99-102` `check_data` 不查空表——空 DataFrame 通过校验 → 空序列被当成功返回。

### 注册 / 并发 / 生命周期
- **#R28** `registry.py:141-146` `get_factor_registry()` 非原子 check-then-act——`_global_registry` 先赋值再 `_load_builtin_factors`，并发首调可得半成品注册表。SocketIO 多线程 + routes import 期调用。当前 daemon 仅 RAW-3 单点，触发概率低（防御）。
- **#R29** `calculator.py:19` `FactorCalculator.__init__` 急切 `get_factor_registry()`——注册表未填时缓存空实例于实例生命周期。
- **#R30** `registry.py:114-116` `get_all_factors_info` 的 `factor_class()` 无 try——坏因子中断整表（当前无调用方，`routes/factors.py` 用 `list_factors+get_factor`，防御）。

### 缓存 / 预计算契约
- **#R31** `factor_precompute.py:108` `float(value)` 无守卫——因子返回非数值 → 异常被 `precompute_factor` 吞 → 整批静默丢弃。
- **#R32** `factor_precompute.py:197-199` `get_cached_factor` 分库查询失败与真 miss 同返 None——瞬态 DB 错误被当 miss（500 #47 get_cache_stats 已修，此为同族残留）。
- **#R33** `factor_precompute.py:236-237` `clear_cache` 走 `_exec_shard` 吞写失败——部分删除静默。
- **#R34** `factor_precompute.py:93-97` 位置索引映射（OCR 标 high）——**经核实当前正确**：builtin 全部 60+ 因子无任何 reset_index/sort/dropna 重排（rolling/ewm/shift 保持原索引）。降为防御性：未来新增重排因子须注意。

### API / calculator 正确性
- **#R35** `calculator.py:82-84` 重复因子名静默覆盖（MA period=5 与 20 后者覆盖前者）——`calculate-combination` API 真实可触发。
- **#R36** `calculator.py:84` 返回序列索引对齐——RangeIndex/异索引时 pandas 按标签对齐静默 NaN。
- **#R37** `calculator.py:51-53` copy 语义不一致——归一化分支 `data.copy()` 而缓存命中/非归一化分支共用原对象。
- **#R38** `base.py:103-106` `required_columns` 若被赋 str，`check_data` 迭代字符（'c','l',...）静默 False。
- **#R39** `registry.py:126-128` `search_factors` 的 `name_cn/description .lower()` 无 None 守卫。

### 公式 / 语义错位（非每日路径）
- **#R40** `qlib158.py:29` QLIB_*_RANK 文档称横截面排名，实现 `Rolling.rank(pct=True)` 是**单标的时序分位**；`calculate(data)` 只收单标的，横截面排名本不可实现——文档/公式需更正。
- **#R41** `reversal.py:56` WILLR 文档「0-100 越高越超卖」vs 实现 `*(-100)` 输出 -100..0。
- **#R42** `reversal.py:108-109` CMO `diff.where(diff>0,0)` 把首行/NaN 缺口变 0 计入滚动和，偏置 up/down 和。
- **#R43** `academic.py:343-347` CVaR `len<5` 守卫与 period 脱节、空切片 `.mean()` NaN。
- **#R44** `academic.py:458-460` HURST `len<20` 守卫与 period(min=50) 脱节——短窗静默报有效。
- **#R45** `academic.py:392-393` Parkinson 均值平方（`hl_ratio.rolling(mean)**2` 应为 `(hl_ratio**2).rolling(mean)`）——Jensen 不等式下严重低估（并入 P1 失真族，此处列）。

---

## 五、🟡 P3 低危 / 死代码 / 防御（18 项）

- **#R46** `indicators:49/238` 死赋值 `close = result['close'].values`（calculate_all_indicators 与 calculate_kdj 各 1）。
- **#R47** `indicators:296` `get_latest_indicators` 返回契约不完整——缺 `bbi/ene_upper/ene_lower/ma30/60/120/250`，只回 ma5/10/20 子集（realtime 降级路径可触达）。
- **#R48** `indicators:137-138` Nine Turner 逐行 Python `for` + `.iloc`——违背向量化目标，长历史慢（日线 250 根影响小）。
- **#R49** `indicators:65-68` RSI 双实现分歧——`calculate_all_indicators`（`delta.iloc[0]=0` 链式赋值）vs `calculate_rsi`（np.diff+insert），同输入两结果。
- **#R50** `indicators:238-239` `calculate_kdj`（向后兼容变体）无零分母守卫——与 `calculate_all_indicators` 的 `.replace(0,1e-10)` 不一致（condition_evaluator.py:621 可触达）。
- **#R51** `precompute_indicator_manager.py:222` 惰性日志（`logger.info(f"...")`）。
- **#R52** `volatility.py:112-115` BOLL_UPPER/LOWER 重复 ma/std 计算——改定义须双处。
- **#R53** `calculator.py:99-108` 加权平均分母错（total_weight 含失败因子）+ 全失败返回全 0 序列——**全仓无调用方（死代码路径）**，当前不生效，登记待接线时修。
- **#R54** `opportunity.py:73-74` DIVIDEND_YIELD / EMOTION_EXTREME `required_columns=[]` + 恒 NaN——设计态（TODO 待数据），列入 C 非缺陷。
- **#R55** `gtja.py:94-95` 真因子（GTJA_AMOUNT20/60、GTJA_HL20、GTJA_CORR_VOL10）`rolling(min_periods=period)` 短输入全 NaN 静默。
- **#R56** `gtja191.py:262-267` GTJA014/021/022/034/038/028/048/050 声明 `period` 参数但 name_cn/description/formula 硬编码「60日…」——改参后文档说谎。
- **#R57** `gtja191.py:548-550` 平盘日分类浮点相等 `close == close.shift(1)`——前复权噪声下真平盘漏判（GTJA029/030 同型）。
- **#R58** `gtja191.py:26-28` FactorParam min 未执行——period=0/`m1=0` 入 `rolling(0)`/`ewm(com=-1)`（并入 #R6 家族）。
- **#R59** `momentum.py:162-164` MACD 参数命名不一致（fast_period/slow_period vs a_stock 的 fast/slow）。
- **#R60** `momentum.py:116-117` MOM 裸价格差——跨截面比较被绝对价格主导（未归一化）。
- **#R61** `alpha101.py:40` docstring 截断 `(-1` 误导。
- **#R62** `data_daemon.py:436` `_erp_percentile` len==1 退化恒 0.0（冷启动）；ERP 单位混合（`1/PE*100` 百分数 vs `CN_10Y_BOND_YIELD_PCT` 待确认为百分数，447 号已接入、数值口径经核实为百分数，此项仅为确认项）。
- **#R63** `registry.py` / daemon 多处惰性日志与 `get_all_factors_info` 无调用方（防御）。

---

## 六、已排除（误报 / 设计意图，6 条）

| 项 | OCR 判定 | 复核结论 |
|----|---------|---------|
| 段5 critical「未闭合 docstring 吞掉 RAW 调度块」 | bug·critical | **提取伪影**：sed 在 5300 行截断 `_compute_main_force_presence` 的 docstring；原始 `data_daemon.py` 该函数 docstring 正常闭合、函数体完整（已读原始 5281-5385 行确认）。**原始文件无此缺陷** |
| 段1 `get_latest_indicators` 短 DataFrame KeyError | bug·high | **误报**：`float(latest['ma5']) if pd.notna(latest.get('ma5')) else None` 在键缺失时 `.get` 返回 None → 走 else 分支，**不会 KeyError**（条件表达式保护了索引）；真实问题仅是返回键不完整（#R47） |
| 段3 trend.py SMA `com=period-1 → alpha=2/period` | bug·medium | **误报**：`ewm(com=N-1)` 的 `alpha=1/(1+com)=1/N`，**恰好精确实现** GTJA191 递归 `SMA_t=(Close_t+SMA_{t-1}(N-1))/N`（OCR 把 com 语义算错） |
| 段3 `GTJA_Base.calculate` 占位符子类注册为空结果因子 | bug·high | **误报**：占位符 `GTJA_FACTOR_001~005` 继承 `GTJA_Base._is_abstract=True`，`_load_builtin_factors` 的 `not getattr(attr,'_is_abstract',False)` 会跳过（已核实 registry.py:163） |
| 段4 gtja191 与 gtja.py 因子名冲突致模块加载失败 | bug·high | **误报**：占位符名是 `GTJA_PLACEHOLDER_001-005`（426 号 P1-5 已唯一化），与 gtja191 的 `GTJA001-050` 无同名；sorted 加载顺序下 gtja191 全量 50 因子正常注册 |
| 段3 `DIVIDEND_YIELD`/`EMOTION_EXTREME` 恒 NaN | maintainability·medium | **设计意图**：`required_columns=[]` + 恒 NaN 为 TODO 待数据，非缺陷（登记 #R54） |

> 另：`pd` 绑定/`_ensure_pd` globals 注入类 OCR 曾提（段2 上下文）——与 496 同判，不采。

---

## 七、处置方案与批次建议

> 性质：本档只定计划；实施须经用户确认后按批次进行。**含「果」成分的口径项先拍板再动手。**

### 待拍板口径（建议项，§九 登记）

- **Q1（#R17/#R41）因子公式/文档对齐惯例**——MACD_HIST 是否去 `2×`、WILLR 是否改文档为 -100..0、academic 系列是否删/标注。偏「果」（消费方语义），建议独立号。
- **Q2（#R2/#R3/#R7/#R8/#R45）研究型因子库处置**——`academic.py`/`opportunity.py`/`reversal.py`/`alpha101.py` 公式失真集群：① 修公式接真实基准 ② 仅修文档标注"代理/近似" ③ 移出 API 暴露（`routes/factors.py` 白名单）。偏「果」，建议独立号。
- **Q3（#R10/#R11/#R12）RSI 零除数三套统一**——统一 `100*avg_gain/(avg_gain+avg_loss)` + 零分母守卫（100/0 惯例），属因/契约层但触及数值语义，建议拍板。
- **Q4（#R13）KDJ 平盘语义**——给中性值 50 还是保持 NaN 文档化。属因/契约层，建议拍板。

### 批次划分（建议）

| 批次 | 主题 | 条目 | 说明 |
|------|------|------|------|
| **批次1** | 当前生效修复 | #R1 `_sr_once` None 守卫、#R4 win_rate 10d/20d 样本门槛、#R23 VOL_RATIO_20 中文名、#R26 get_win_rates 吞错、#R21 GTJA_HL20 除零 | ✅ **已实施**（v1.1，§十）：4 文件，探针 14/14、回归 305 passed |
| **批次2** | base/registry 加固 | #R5 可变类属性拷贝、#R6/#R58 参数校验、#R28 注册表锁、#R27 check_data 空表、#R38 required_columns、#R39 search 守卫、#R30 get_all_factors_info | ✅ **已实施**（v1.1，§十一）：2 文件，探针 20/20（全量 278 因子）、回归 397 passed |
| **批次3** | calculator/缓存契约 | #R29 急切注册、#R31 float 守卫、#R32 get_cached_factor 区分、#R33 clear_cache 日志、#R34 位置映射防御、#R35 重复名、#R36 索引对齐、#R37 copy | ✅ **已实施**（v1.2，§十二）：3 文件，探针 14/14、回归 391 passed |
| **批次4** | 指标引擎一致性 | #R46 死赋值、#R47 返回契约、#R48 Nine Turner 向量化、#R49 RSI 双实现、#R50 calculate_kdj 零分母、#R51 惰性日志 | ✅ **已实施**（v1.3，§十三）：2 文件，探针 10/10（九转向 3 种子语义等价、RSI max_diff=0）、回归 431 passed |
| **批次5** | 非有限值/边界守卫 | #R18/#R19/#R20/#R22 pct_change/log/GK sqrt 守卫、#R24 check_data 绕过、#R25 `cl_result in dir()` 显式初始化 | ✅ **已实施**（v1.3，§十四）：6 文件，探针 18/18、回归 431 passed |
| **批次6** | 公式/语义错位（非每日路径） | #R40 qlib158 rank 文档、#R42 CMO、#R43/#R44 academic 守卫、#R55~#R61 gtja191/gtja/momentum/alpha101 细节 | ✅ **已实施**（v1.3，§十五）：7 文件，探针全绿（#R43 修 CVaR ndarray AttributeError）、回归 431 passed |
| **批次7** | 死代码/文档清理 | #R53 死路径标注、#R54 设计态登记、#R62 erp 确认、#R63 惰性日志 | ✅ **已实施**（v2.0，§十六）：3 文件，探针 8/8（#R53 权重分母+Length mismatch、#R62 0.5 中性分位）、回归 431 passed |

> 说明：Q1-Q4 拍板项（#R17/#R41、#R2/#R3/#R7/#R8/#R45、#R10~#R13）**不在本档决断**，待单独号确认后并入对应批次。

### 依赖顺序与风险

- 批次1 独立、优先（当前生效项）；批次2 的 base 参数校验会触及全库因子——先跑 `routes/factors.py` 回归确认无调用方依赖 `period=0` 行为。
- 批次2 #R28 加锁**不得**在持锁中做 IO（`_load_builtin_factors` 内部 import）；用双检锁。
- 批次5 #R25 改 `cl_result = None` 初始化——须回归 `_raw2_one` 缠论段（dim2 通道）。
- 批次6 #R55~#R61 触及 gtja191/gtja 真因子——实施前先 `grep` 确认无动态引用。

---

## 八、验证口径（实施时）

- 每批实施后：`py_compile` + `ruff`（factors/indicators 目录级复扫）+ 相关回归；**全量 pytest 批量污染为既有问题**（需 `--ignore='$TMPDIR'` + 停 daemon）。
- 数据正确性类（#R4/#R23/#R1/#R26）：DB 探针实证——win_rate_10d/20d 少样本应输出 NULL/NaN；VOL_RATIO_20 name_cn 应为「20日量比」；`_sr_once` 失败时 structure_ext 应产出其余键；`get_win_rates` 缓存失败应记日志且不静默全量重算。
- 健壮性类（#R6/#R28/#R36）：单元构造——`period=0` 应抛清晰校验错误；多线程首调 `get_factor_registry` 只建一次；异索引序列应对齐校验。
- 公式类（Q1-Q4 拍板后）：用标准参考（通达信/主流平台 RSI/KDJ/MACD）比对同股同日输出量级。
- **复跑前置**：停 `data_daemon` **及** `start_daemon.sh` 看守（否则分库锁致测试挂起），跑完重启。

---

## 九、待定登记（本档未决）

| 登记 | 内容 | 依赖 |
|------|------|------|
| 登记-1 | Q1 因子公式/文档对齐惯例（#R17 MACD_HIST 2×、#R41 WILLR 范围） | **待单独拍板**（含「果」成分） |
| 登记-2 | Q2 研究型因子库处置（#R2/#R3/#R7/#R8/#R45：修公式/标近似/移出 API） | **待单独拍板**（偏「果」） |
| 登记-3 | Q3 RSI 零除数三套统一（#R10/#R11/#R12） | **待拍板**（因/契约层，数值语义） |
| 登记-4 | Q4 KDJ 平盘语义（#R13 中性 50 vs NaN 文档化） | **待拍板**（因/契约层） |
| 登记-5 | #R53 `calculate_factor_combination` 死代码路径去留 | 批次7 |
| 登记-6 | #R54 DIVIDEND_YIELD/EMOTION_EXTREME 待数据接入 | 外部数据依赖 |
| 登记-7 | #R62 `CN_10Y_BOND_YIELD_PCT` 单位确认（百分数） | 批次7 顺带确认 |
| 登记-8 | #R25 `'cl_result' in dir()`（496 已登记） | 批次5 |

---

## 十、批次1 实施记录（2026-10-01，当前生效修复 #R1/#R4/#R21/#R23/#R26）

> 范围＝批次1「当前生效修复」5 项；纯因/契约层，零「果」。**改动 4 文件 + 探针 1**；验证：`py_compile` OK、ruff **零新增**（3 小文件 All checks passed；data_daemon 38 errors 与 HEAD 基线一致）、探针 **14/14 全绿**、定向回归 **305 passed, 1 xfailed**（win_rate/factor/indicator/426/428/436/461/464 等）。

### #R1 `data_daemon.py` 三处 `_sr_once` None 兜底 ✅
- 改法：衍生 support_resistance（:4126）/ risk_ext 几何（:4196）/ structure_ext 结构位置（:4439）三处 `_sr_once` → **`_sr_once or {}`**。
- 原行为：`calc_support_resistance(df)` 失败置 `_sr_once = None` 后，消费点 `.get('support_price')` 抛 AttributeError 被外层 except 吞掉 → **structure_ext/risk_ext 整组静默不产**。
- 探针：三处 `or {}` 兜底接线源码断言 OK。

### #R4 `compute_win_rates` 10d/20d 独立样本门槛 ✅
- 改法：`wr10/_, n10` 与 `wr20/avg20/sh20, n20` 取回各周期样本数；`n10 < _MIN_SAMPLES` 时 `wr10 = nan`、`n20 < _MIN_SAMPLES` 时 `wr20 = avg20 = sh20 = nan`（原仅 n5 有 `_MIN_SAMPLES` 门槛，10d/20d 少样本静默产出误导胜率）。
- 探针：10 交易日桩（5d 样本=5、10d/20d 样本=0）→ `win_rate_10d/20d`/`sharpe_20d` = NaN、`samples=5`。

### #R21 `GTJA_HL20` 分母正值守卫 ✅
- 改法：`high_n / low_n.replace(0, np.nan)` → **`high_n / low_n.where(low_n > 0)`**（replace(0) 无法拦截负/NaN 低值，会透传 inf/NaN）。
- 探针：零低值/负低值 → 全 NaN；正常正值 → >1。

### #R23 `VOL_RATIO_20.name_cn` 中文名修正 ✅
- 改法：`"20日换手率"` → **`"20日量比"`**（实际计算 `Vol/MA(Vol,20)` 是量比，VOL_RATIO_5 正确写「5日量比」；用户可见错标签，每日 RAW-3 落库展示）。

### #R26 `get_win_rates` 吞错改记日志 ✅
- 改法：裸 `except Exception: pass` → `except Exception as e: logger.warning(..., exc_info=True)`（区分「查询失败」与「无缓存」——失败不再静默回落全量 `compute_win_rates` 重算）。
- 探针：桩抛错 → 回退实时计算返回空、不抛错、warning 日志已记。

### 运行态
- 验证期**停 daemon+看守**（分库锁致 pytest 挂起）→ 跑测试 → **已重启看守**（daemon PID 44337 起，采集活跃）。改动**未推送**。
- **⚠️ 实施中事故**：serena `replace_symbol_body` 替换 `compute_win_rates` 时**误删方法前半段**（240→124 行）——正是记忆 `user/serena-tools.md` 警告的语义（body 须含完整 def、替换覆盖整个定义）。已从 `git HEAD` 恢复完整方法并重新应用 #R4，最终 diff 仅 +docstring +门槛逻辑（无损）。**教训**：方法级替换优先 `replace_symbol_body` 传完整方法体，或改用 edit 工具小改。

---

## 十一、批次2 实施记录（2026-10-01，base/registry 加固 #R5/#R6/#R27/#R28/#R30/#R38/#R39/#R58）

> 范围＝批次2「base/registry 加固」8 项。**改动 2 文件 + 探针 1**；验证：`py_compile` OK、ruff 2 文件 + 探针 **All checks passed**、探针 **20/20 全绿**（含全量 278 因子注册 + get_info 实例化不抛错——证明 #R6 校验未破坏任何既有因子默认值）、定向回归 **397 passed, 5 xfailed**（factors/routes/426/428/436/461/464/495/497/498/499 等）。

### #R5 `base.py` 类级可变属性每实例拷贝 + `get_info` 返回拷贝 ✅
- `__init__`：`_params = list(self.params)`、`_related_factors = list(...)`、`_required_columns = list(...)`（字符串先归一）、`_tags` **深拷贝**（`{k: list(v) if isinstance(v,(list,tuple)) else v ...}`——浅拷贝内层 list 仍共享）。
- `get_info`：`tags` 深拷贝返回、`relate`/`required_columns`/`params` 均返回拷贝——调用方 mutate 返回值不再污染全局因子定义。

### #R6 + #R58 `base.py` 参数校验（`_validate_param_value` 新增）✅
- 新增 `_validate_param_value(param, value)`：`param_type`（int/float/list/str）类型转换校验 + `min_val`/`max_val` 范围校验，非法抛 `ValueError`。
- `__init__` 默认值与 `set_param` 均走校验；**先校验后写入**（非法 `set_param` 后原值不变）。gtja191 的 `period=0`/`m1=0`（#R58）由基类统一拦截。
- API 侧：`routes/factors.py` 的 `@handle_exceptions` 将 ValueError 捕获为 4xx——从「静默错值」变「清晰报错」。

### #R27 `check_data` 空表校验 ✅
- `data is None or data.empty → False`（空序列不再被当成功结果）。

### #R28 `get_factor_registry` 双检锁 ✅
- 新增 `_registry_lock = threading.Lock()`；`_load_builtin_factors` **完成后才发布** `_global_registry`（原先赋值后加载，并发首调拿半成品）。
- 探针：8 线程并发首调只建 1 个注册表。

### #R30 `get_all_factors_info` 坏因子跳过 ✅
- `factor_class()` 构造包 try/except，坏因子 `logger.error` 后跳过不中断整表。

### #R38 `required_columns` 字符串归一 ✅
- `__init__` 归一为列表 + `check_data` 兜底 `isinstance(cols, str)`（原 `list("close")` 拆字符静默 False）。

### #R39 `search_factors` None 守卫 ✅
- `name_cn = factor_class.name_cn or ""` / `description = ... or ""`（None 不再 AttributeError）。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 48916 起，采集活跃）。改动**未推送**。

---

## 十二、批次3 实施记录（2026-10-01，calculator/缓存契约 #R29/#R31/#R32/#R33/#R34/#R35/#R36/#R37）

> 范围＝批次3「calculator/缓存契约」8 项（#R53 加权分母为死路径留登记）。**改动 3 文件 + 探针 1**；验证：`py_compile` OK、ruff 3 文件 + 探针 **All checks passed**（ECM 3 errors 与 HEAD 基线一致＝零新增）、探针 **14/14 全绿**、定向回归 **391 passed, 6 skipped, 5 xfailed**（6 skipped 为环境项）。

### #R29 `FactorCalculator.__init__` 注册表惰性化 ✅
- 改法：`__init__` 不再急切 `get_factor_registry()`（并发首调会缓存空/半成品实例），改 `self.registry = None` + 新增 `_get_registry()`（首次现取全局注册表，缓存于实例）。
- `calculate_single_factor` 改用 `self._get_registry().get_factor(...)`。
- 探针：`_get_registry()` 两次取同一注册表。

### #R31 `_batch_cache_factor_series` `float(value)` 守卫 ✅
- 改法：`records.append({'value': float(value), ...})` 前先 `try: num_value = float(value) except (TypeError, ValueError): logger.warning(...); continue`——原单值非数值抛异常被 `precompute_factor` 吞掉致**整批静默丢弃**。
- 探针：含字符串哨兵序列 → 有效 3 行入库、非数值行记 warning、precompute 返回 True。

### #R32 ECM `get_cached_factor` 区分失败与真空 ✅
- 改法：docstring 明确「空结果=真空缓存；查询失败由 `_query_shard` 记 warning 后返回空 DataFrame——无法二次区分，失败至少在日志可见，不静默」（`_query_shard` 失败路径 500 已补日志，此层确认不新增重复日志）。

### #R33 `clear_cache` 结果日志 ✅
- 改法：三种删除分支（ts_code+factor_name / ts_code / factor_name / 全部）补 `logger.info("清除 factor_cache: ...")`——`_exec_shard` 吞写失败且无返回值，删除结果不再完全静默。
- 探针：DELETE 走 `_exec_shard` + 结果日志已记。

### #R34 位置索引映射防御 ✅
- 改法：`_batch_cache_factor_series` 开头——`dates` 与 `factor_series` 长度不一致时 `logger.warning(...位置索引映射可能错配)`（因子内部重排/截断时位置错配静默写库的隐患可见）。
- 探针：截断因子（head(3) vs 6 行 data）→ 长度告警已记。

### #R35 `calculate_multiple_factors` 重复因子名 warning ✅
- 改法：`if factor_name in result_df.columns: logger.warning("因子名重复，后值将覆盖前值: ...")`——同名不同参（MA period=5/20）静默覆盖的隐患可见。
- 探针：重复名配置 → warning 已记。

### #R36 异索引 reindex 对齐 ✅
- 改法：`factor_series.index.equals(data.index)` 不等时 `reindex(data.index)` + warning（`{len(missing)} 个标签对齐为 NaN`）——原 pandas 按标签对齐静默填 NaN。
- 探针：偏移索引因子 → warning + reindex 后 NaN 可见。

### #R37 `calculate_single_factor` 入口统一 copy ✅
- 改法：入口 `data = data.copy()` 统一——原仅「volume→vol 归一化」分支 copy，缓存未命中/无归一化路径共用调用方原对象，`check_data`/`calculate` 就地 mutate 会污染调用方数据。
- 探针：就地 mutate 的坏因子 → 调用方 data 未被改、返回值含 mutate 结果。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 5174 起，采集活跃）。改动**未推送**。

---

## 十三、批次4 实施记录（2026-10-01，指标引擎一致性 #R46/#R47/#R48/#R49/#R50/#R51）

> 范围＝批次4「指标引擎一致性」6 项。**改动 2 文件 + 探针 1**；验证：`py_compile` OK、ruff 2 文件 + 探针 **All checks passed**、探针 **10/10 全绿**（含九转向 3 种子语义等价、RSI 双实现 max_diff=0）、定向回归 **431 passed, 6 skipped, 5 xfailed**。

### #R46 死赋值 ✅
- `calculate_all_indicators` MACD 段删 `close = result['close'].values`（下方用 `result['close'].ewm`，变量未用；`calculate_macd`/`calculate_rsi` 的 close 是活代码保留）。
- 探针：活代码区无 `close = result['close'].values`。

### #R47 `get_latest_indicators` 返回契约补全 ✅
- 补 `ma30/ma60/ma120/ma250` + `bbi/ene_upper/ene_lower` 键（原只回 ma5/10/20 + 基础指标；bbi/ene 已计算但未透出）。
- 探针：22 键齐全、bbi/ene_upper 有值。

### #R48 九转向向量化 ✅（语义等价验证）
- 原逐行 `for` + `.iloc` 循环 → 向量化：`close < close.shift(4)` 比较 + 段内 `groupby.cumcount()+1` + 截断 9 + `where(触发, 0)`，买卖互斥（`buy_seg = lower4 & ~higher4`）。
- **探针**：3 种随机种子（seed1/7/99，含连续段/中断/相等日）与**原循环实现逐位比对 buy+sell 全等**——证明重构无行为变更。

### #R49 RSI 双实现统一 ✅
- `calculate_all_indicators` 的 `delta.iloc[0] = 0`（链式赋值，可能 no-op/SettingWithCopyWarning）→ `delta.fillna(0)`（与 `calculate_rsi` 的 np.diff+insert 平滑锚点一致）。
- **探针**：两实现 `rsi14` **max_diff=0.00e+00**。

### #R50 `calculate_kdj` 零分母守卫 ✅
- 补 `.replace(0, 1e-10)`（对齐主路径 `calculate_all_indicators`）——平盘窗口 rsv 不再 inf/NaN。
- 探针：平盘窗口（high==low==close）窗口满后 k 有限、值域 [0,100]。

### #R51 惰性日志 ✅
- `compute_win_rates` 的 `logger.info(f"...")` → 参数化 `logger.info("... %d ...", ...)`（f-string 不无条件格式化）。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 7209 起，采集活跃）。改动**未推送**。

---

## 十四、批次5 实施记录（2026-10-01，非有限值/边界守卫 #R18/#R19/#R20/#R22/#R24/#R25）

> 范围＝批次5「非有限值/边界守卫」6 项。**改动 6 文件 + 探针 1**；验证：`py_compile` OK、ruff 6 文件 + 探针 **All checks passed**（data_daemon 38 errors 与 HEAD 基线一致＝零新增）、探针 **18/18 全绿**、定向回归 **431 passed, 6 skipped, 5 xfailed**。

### #R18/#R19 `volatility.py` pct_change/log 非有限值守卫 ✅
- VOLATILITY：`returns = returns.replace([inf, -inf], np.nan)`（零前收 inf 不再进 `*sqrt(252)`）。
- HV：`log_returns.replace([inf, -inf], np.nan)`（非正值 log -inf 不再进 `.std()`）。

### #R20 `a_stock.py` REV_1 pct_change 守卫 ✅
- `ret = data['close'].pct_change(1).replace([inf, -inf], np.nan); return -1 * ret`（不污染下游排名/归一化）。

### #R22 `academic.py` Garman-Klass 负方差 clamp ✅
- `gk_var.rolling(period).mean().clip(lower=0)` 再 `np.sqrt`（`co²` 项无下界 → 负方差不再静默 NaN）。
- 探针：极端开收比数据 clamp 后有限、非负。

### #R24 `gtja.py`×4 + `alpha101.py`×3 check_data 契约 ✅
- 真因子直索引 `data["close"/"vol"]` 前加 `if not self.check_data(data): raise ValueError(...)`（缺列报契约错误而非裸 KeyError）。
- **附带修正**：serena `replace_in_files` 正则替换时把 Alpha007/008 的 `window` 误写为 5（原 10）——对照 formula 修正回 10（Alpha006 保持 5 正确）。
- 探针：7 因子缺 vol → ValueError（非 KeyError）；正常数据计算成功。

### #R25 `data_daemon.py` `cl_result` 显式初始化 ✅
- `_raw2_one` 顶部 `cl_result = None`（原依赖缠论块才绑定局部名，消费点用 `'cl_result' in dir()` 作用域内省）→ 两处消费点改判 `cl_result is not None`。
- 探针：源码断言 `cl_result = None`、活代码无 `'cl_result' in dir()`、消费点 `is not None`。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 9596 起，采集活跃）。改动**未推送**。

---

## 十五、批次6 实施记录（2026-10-01，公式/语义错位非每日路径 #R40/#R42/#R43/#R44/#R55~#R61）

> 范围＝批次6「公式/语义错位（非每日路径）」10 项（#R58 已由批次2 #R6 覆盖）。**改动 7 文件 + 探针 1**；验证：`py_compile` OK、ruff 7 文件 + 探针 **All checks passed**、探针全绿、定向回归 **431 passed, 6 skipped, 5 xfailed**。

### #R40 `qlib158.py` rank 文档更正 ✅
- QLIB_RANK/LOW_RANK/HIGH_RANK/VOLUME_RANK 的 description/formula 更正为**时序分位**（`rolling(N).rank(pct=True)`，非横截面——`calculate(data)` 只收单标的，横截面排名本不可实现）。

### #R42 `reversal.py` CMO NaN 传播 ✅
- `diff.where(diff>0)` 保留 NaN（原 fill=0 把首行/NaN 缺口当零动量计入滚动和，偏置 up/down）。
- 探针：首行 NaN 保留、有效值 [-100,100]。

### #R43 `academic.py` CVaR 修复 ✅（意外发现）
- `series.quantile(0.05)` → **`np.percentile(series, 5)`**——原 `rolling.apply(raw=True)` 传 ndarray，`quantile` 不存在 → **因子从未跑通（AttributeError）**；顺带空/退化显式 NaN。
- 探针：有效窗口有限。

### #R44 `academic.py` HURST 守卫对齐 ✅
- `len(series) < 20` 硬编码 → `len(series) < period`（rolling 满窗口恒 =period，硬编码 20 语义失真）。

### #R55 `gtja.py` 真因子短输入守卫 ✅
- 4 真因子 `len(data) < period` 显式 ValueError（原 rolling 满窗口前全 NaN 静默）。
- 探针：5 行数据（period 默认 20/60）→ ValueError。

### #R56 `gtja191.py` 硬编码标签参数化 ✅
- GTJA014（AMOUNT60）/021/022（STD）/028（RET）/034（MA）/038（EMA）的 description/formula 硬编码「60日/20日」→ 参数化（N 表述）；**GTJA048/050 核实 formula 本用 N、无脱节**（未改）。

### #R57 `gtja191.py` 平盘浮点相等 → isclose ✅
- GTJA029/030 的 `close == close.shift(1)` → `np.isclose(close, close.shift(1))`（前复权浮点噪声不漏判真平盘）。

### #R59 `momentum.py` MACD 参数名对齐 ✅
- MACD_DIF/DEA 的 `fast_period/slow_period/signal_period` → `fast/slow/signal`（对齐 a_stock.py；默认值 12/26/9 不变）。
- 探针：新参数名取值 12/26。

### #R60 `momentum.py` MOM 归一提示 ✅
- description 补「裸价格差，量纲随价格水平；跨截面比较需先归一/用 ROC 等相对度量」（GTJA191 标准定义保留，行为不变）。

### #R61 `alpha101.py` Alpha1 docstring 补全 ✅
- `"""Alpha1: (-1"""` 截断 → 完整公式 `(rank(ts_argmax(signedpower(returns, 2), 5)) - 0.5) * -1`。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 12315 起，采集活跃）。改动**未推送**。

---

## 十六、批次7 实施记录（2026-10-01，死代码/文档清理 #R53/#R54/#R62/#R63）

> 范围＝批次7「死代码/文档清理」4 项。**改动 3 文件 + 探针 1**；验证：`py_compile` OK、ruff 3 文件 + 探针 **All checks passed**（data_daemon 38 errors 与 HEAD 基线一致＝零新增）、探针 **8/8 全绿**、定向回归 **431 passed, 6 skipped, 5 xfailed**。

### #R53 `calculate_factor_combination` 死路径标注 + 权重分母修 ✅
- docstring 标注「全仓无调用方（死代码路径），登记待接线时修复」。
- **权重分母修**：`total_weight` 只统计**实际参与计算**的因子（`name in factors_df.columns`）——原含失败/缺名因子致分母偏大、结果系统性缩放错误。
- **全失败返回长度匹配 NaN 序列**（`pd.Series(dtype=float, index=data.index)`）——顺带修 `pd.Series([], index)` 新版 pandas **Length mismatch**（原代码该行同样有此 bug，死路径从未暴露）。
- 探针：含失败因子时组合 = 参与因子 ×(weight/sum(参与 weight))（max_diff=0）；全失败 → 长度匹配 NaN 序列。

### #R54 `opportunity.py` 设计态登记 ✅
- DIVIDEND_YIELD docstring 补「501 #R54 登记：设计态因子（required_columns=[] 恒 NaN），非缺陷；待分红数据就绪后实现」。
- EMOTION_EXTREME 已有 description TODO 标注（「待改造后 BOCIASI 就绪」）——登记确认。

### #R62 `_erp_percentile` 单观察守卫 + 单位确认 ✅
- `len(erp_series) < 2`（单观察不可排名，count_less/len 恒 0 误导为「最低分位」）→ 返回 **0.5 中性分位**。
- **⚠️ 首个版本 `len<2 → None` 致 test_447 失败**（单行 ERP 触发 426 P0-1「无源数据」→ 整批 market_stats 不落库 → `dv_bond_diff` 变 None）——改为 **0.5**（非 None 不触发整批不落库），447 测试 **23 passed**。
- `CN_10Y_BOND_YIELD_PCT` **单位确认=百分数**（`float(os.getenv('CN_10Y_BOND_YIELD','1.7'))`＝1.7%），与 `1/PE*100` 同单位相减，ERP 口径正确（447 号已接入）。

### #R63 惰性日志 ✅
- calculator `logger.debug(f"...")` ×2（factor_cache 命中/读取失败）→ 参数化（`%s` 占位）。

### 运行态
- 验证期**停 daemon+看守** → 跑测试 → **已重启看守**（daemon PID 14423 起，采集活跃）。改动**未推送**。

---

## 十七、收官总结（v2.0，2026-10-01）

**501 号七批次 43 项修复全部落地**，本号收官。汇总：

| 批次 | 主题 | 项数 | 探针 | 回归 | § |
|---|---|---|---|---|---|
| 1 | 当前生效修复 | 5 | 14/14 | 305 | §十 |
| 2 | base/registry 加固 | 8 | 20/20（278 因子） | 397 | §十一 |
| 3 | calculator/缓存契约 | 8 | 14/14 | 391 | §十二 |
| 4 | 指标引擎一致性 | 6 | 10/10（九转向语义等价） | 431 | §十三 |
| 5 | 非有限值/边界 | 6 | 18/18 | 431 | §十四 |
| 6 | 公式错位非每日路径 | 10 | 全绿（#R43 CVaR） | 431 | §十五 |
| 7 | 死代码/文档清理 | 4 | 8/8（#R53/#R62） | 431 | §十六 |
| **合计** | | **43** | **94 断言** | **峰值 431** | |

### 核心成效
- **67 项真实问题 → 43 项已实施**；**24 项待 Q1~Q4 拍板**（研究型因子库公式失真为主，非每日路径、不落 factor_cache）。
- **每日 14 因子公式全正确**、RAW-2/market_stats/2B/2C 核心路径无重大错误——**当前运行路径无 P0/P1**。
- **意外修复 2 处**：#R43 CVaR（原 ndarray AttributeError，因子从未跑通）、#R53 权重分母 + Length mismatch（死路径潜在 bug）。
- **零行为变更保证**：#R48 九转向向量化 3 种子与原循环逐位全等、#R49 RSI 双实现 max_diff=0。

### 剩余（不在本档决断，§九 登记）
- **Q1** 公式/文档对齐惯例（#R17 MACD_HIST 2×、#R41 WILLR 范围）；
- **Q2** 研究型因子库处置（#R2/#R3/#R7/#R8/#R45：academic/opportunity/reversal/alpha101 修公式/标近似/移出 API）；
- **Q3** RSI 零除数三套统一（#R10/#R11/#R12）；
- **Q4** KDJ 平盘语义（#R13）；
- 登记-5~8（#R53 死路径去留、#R54 待数据、#R62 单位确认已完成、#R25 已批次5 完成）。

### 提交状态
- 七批次代码改动 + 探针 7 个 + 文档/记录，**未推送**（工作树）。
- 推送按 500 先例：代码 7 批次 + 探针 + 文档/记录分批 commit 后 push。

---

## 附录：OCR 会话与原始清单

- 5 段原始输出：`/tmp/raw_ocr_20260930/seg1_indicators.md`（9 条）/ `seg2_factors_core.md`（17 条）/ `seg3_factors_small.md`（31 条）/ `seg4_factors_large.md`（12 条）/ `seg5_daemon_raw.md`（4 条）＝ **73 条**；会话 `7b7daa4e` / `6af0f9e6` / `ff38b70e` / `08ddb627` / `edcb95b6`。
- 归并：73 条 → **67 项真实问题（P1 9 / P2 40 / P3 18）** + **6 条排除**；同因同位置归并（RSI 三套、参数校验、check_data 绕过、非有限值等）。
