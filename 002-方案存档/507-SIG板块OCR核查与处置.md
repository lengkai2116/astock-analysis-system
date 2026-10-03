---

# 507号｜SIG 板块 OCR 核查与处置

**版本**：v1.0（2026-10-03；**只读核查档，未改任何代码/配置**）
**来源**：2026-10-03 用户要求「调用 OCR 对系统中的 SIG 板块的实际代码进行扫描检查，发现的问题进行核查并在对话框内进行说明，不要修改方案和代码」→ 对话框内核查报告出具后，用户要求「开 507 号，先落核查档」。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek `deepseek-chat`，`--max-tokens 200000`）全量扫描 SIG 层，**逐条人工核实**（OCR 存在上下文/伪影误报，全部对照真实代码/调用图核对，误报/设计意图/待确认单列 §六）。
**范围（SIG＝第 5 层，COL→RAW→SIG→JUD→OUT）**：代码根 `backend/app/opportunity_atlas/`，共 **33 文件 / 24.5k 行**：
- **七维引擎**：`dimensions/dim1_signal_engine.py`(457) / `dim2_structure_engine.py`(662) / `dim3_vp_engine.py`(462) / `dim4_chip_fund_engine.py`(6202) / `dim5_emotion_engine.py`(660) / `dim6_risk_engine.py`(581) / `dim7_valuation_engine.py`(797) / `dim8_summary_engine.py`(1777)
- **适配/聚合/决策栈**：`dim_adapter.py`(750) / `status_engine.py`(1472) / `consensus_engine.py`(396) / `conflict_matrix.py`(347) / `arbiter.py`(305) / `factor_arbiter.py`(250) / `cross_validate.py`(1955) / `light_derive.py`(231)
- **建议/展示/服务**：`advice_engine.py`(815) / `advice_builder.py`(690) / `radar_service.py`(277) / `event_monitor.py`(1038) / `tag_extractor.py`(256)
- **支撑/工具**：`phase_detector.py`(773) / `valuation_estimator.py`(1022) / `potential_engine.py`(549) / `reliability_assessor.py`(370) / `signal_analyzer.py`(649) / `time_rhythm_engine.py`(103) / `emotion_temperature.py`(142) / `backtest_minimal.py`(267) / `dimensions/enum_cn_map.py`(94) / `dimensions/shared_vol_ratio.py`(46) / `dimensions/shared_support_resistance.py`(118) / `dimensions/__init__.py`(24)
**分段**：**主段 30 文件**（`ocr scan --repo . --path backend/app/opportunity_atlas`）→ 144 条；**dim4 单独分块**（6202 行超 OCR 单文件上限，按类边界切 4 段外部临时文件后扫描）→ 36 条。合计 **180 条原始发现**。
**侧重**：SIG 计算配置正确性（公式/语义一致性、边界健壮性、静默失效、契约漂移、死代码）× 与 JUD 消费面（`dim_results_json`/`seven_dim_json`）及前端的口径一致性。
**基线**：HEAD `37c610c`（= origin/main）；工作树仅 `data/account_risk_status.json` 未跟踪＝daemon 运行产物。
**边界（2026-09-30 用户订正口径）**：真「果」层锁定限制**已失效**——凡影响系统运行的错误均须修正，不再区分因/果、不必独立号拍板。本档仍按只读核查归档；实施按批次另行开工。
**OCR 会话**：主段 `fe4cdffb-51c1-4894-b308-2f3a175a3b67`（144 条）；dim4 分块 `07c86089-fc35-48bd-9edf-98e3a1eb7d3d`（36 条）。

---

## 一、核查背景与总体结论

- SIG 是管道第 5 步（COL→RAW→SIG→JUD→OUT），负责**股票现状描述**：7 个维度引擎独立分析输出 `{status_description, judgment, audit}`，dim8 汇总整理，`dim_adapter.convert_to_factors` 产出 13 维因子供 JUD 消费。生产链路：`data_daemon._precompute_strategy_signals` → `StatusEngine.evaluate(ts_code)` → 7 引擎 `evaluate` → `dim_results_json`/`seven_dim_json`/`signal_json` 落 `strategy_signal_detail`。
- 本次 OCR 全量扫 + 人工核实结论：
  - **180 条原始发现 → 归并约 95~110 项**（P1 高危 ≈10 / P2 中危 ≈45 / P3 低危·死代码·防御 ≈45）+ **排除项**（误报 + 待确认，§六）；
  - **SIG 生效链路无 P0**：`status_engine.evaluate` → 7 引擎 `evaluate` → `dim_adapter.convert_to_factors` → 落库，未发现会导致崩溃或全市场性数据错误的缺陷；
  - **最大共性风险＝「静默失效」**：`except Exception: pass` 或仅 `logger.debug` 的兜底 + 精确字符串/键匹配，使**规则永不触发**或**永远走错分支而不报错**——这是本次发现的最主要共性，`dim_adapter.py:740` 的注释自曝曾因此长期掩盖一个 `NameError`；
  - **确凿生效缺陷**：dim3 `logger` 未定义（except 分支 `logger.warning` 抛 `NameError`）、emotion_temperature `limit_up_count` None→0、phase_detector 维度6 SSRP 恒不投票（权重 2.5 空转）、consensus_engine 中性维计数对 dict 值失效；
  - **确凿潜伏缺陷 + 死代码**：dim4 ASR 单位 bug、dim4 前置过滤器群缺 `BenchmarkService` 导入、dim4 `get_risk_tags` 读不存在的 `roce` 键、`backtest_minimal` 无日期参数致前视偏差、`radar_service` 排序前截断；
  - 与 489/490/491/492（SIG-JUD 消费契约）、464（dim8 定稿）、501/502（RAW 预计算）重叠项：**已标注，不重复计**。
- **本档归并口径**：同一处代码可被多条 OCR 命中（如 dim4 ASR 单位同时被「dim4 段」与「phase_detector」命中、静默 except 遍布十余文件），故按「位置/主题」编号，条数 ≠ OCR 原始条数。

---

## 二、发现总览

| 级别 | 项数（估） | 主题 |
|------|------|------|
| 🔴 P1 高危（当前生效 / 一触发即错 / 静默吞掉关键判定） | ≈10 | dim3 `logger` 未定义、emotion_temperature None→0、phase_detector SSRP 恒空、consensus_engine 中性 dict 计数失效、dim6 ST 升格被吞、backtest 前视偏差、dim4 ASR 单位、dim4 缺导入、dim4 `roce` 键错、radar 排序前截断 |
| 🟠 P2 中危（生效低影响 / 边界 / 契约漂移 / 静默失败） | ≈45 | 静默 except 集群、精确字符串/键匹配致规则不触发、不可达分支、0/NaN/None 混同、dim4 策略执行状态、契约/签名漂移 |
| 🟡 P3 低危 / 死代码 / 防御 | ≈45 | 计算即丢弃的裸表达式、死局部/死参数/死导入、文档注释失真、惰性日志/性能、模块级可变缓存 |
| ⚪ 排除（误报 / 设计意图 / 待确认） | ≈6 | light_derive `risk` vs `risk_engine`（误报）、dim1 行尾 `?`（伪影）、dim7 `dev>30` 符号（待确认）、light_derive dict 分支（待确认）等 |

> 「✅实证」＝本次已对照真实代码/调用图确认；「OCR-only」＝OCR 提出但实施前须再核（本档已尽量收敛）。

---

## 三、🔴 P1 高危（已实证）

### #S1 `dimensions/dim3_vp_engine.py:114` — 模块级 `logger` 未定义，except 分支抛 `NameError`（当前生效）
- 模块仅 `import logging`（:13），**无** `logger = logging.getLogger(__name__)`（对比 `dim2_structure_engine.py:27` 有定义）；`DataAwareMixin` 亦不提供。
- `evaluate()` 内 `PatternEngine.evaluate(df)` 异常时走 `except Exception as e: logger.warning(...)`（:114）——该行自身抛 `NameError: name 'logger' is not defined`，**冒出 evaluate**，与「失败降级、单引擎异常不影响其他引擎」的设计完全相反。
- **实证**：grep 全文件仅此一处 `logger.`，无任何 `logger =` 定义。
- **方向**：补模块级 `logger = logging.getLogger(__name__)`（并改惰性 `%s`）。

### #S2 `emotion_temperature.py:135` — `limit_up_count=None` 被强制为 0（最看空），与 docstring 中性契约相悖（当前生效）
- docstring 明写 `limit_up_count: None → 该项中性（50）`；实现 `limit_up_count if isinstance(limit_up_count, int) else 0`——`None`/非 int 一律 → **0（最看空）**，把缺失数据静默压向最看空端。
- 生产者 `status_engine._market_level_temperature` 在数据缺失/非 int 时**确实传 `None`**。
- **实证**：`:125-142` 逐行；`calc_emotion_temperature` 无 `None` 分支（默认 0）。
- **方向**：None → 中性 50。

### #S3 `phase_detector.py:241` — 维度6 SSRP 在生产中恒不投票（权重 2.5 空转）
- `PhaseDetectionEngine._dim_ssrp` 读 `extra_tags.get("ssrp")`；但唯一生产调用方 `data_daemon.py:4121-4128` 构造的 `_extra` **只放** `buy_sell_point` / `main_force_presence`，**从不放 `ssrp`**（SSRP 被写入 `chip_fund` 特征 `data_daemon:4325`，非 `extra_tags`）。
- 故 `_dim_ssrp` 生产恒返回 `{}`；该维在 `_consensus` 权重表 `{"trend":1.5,"ssrp":2.5,"chan":2.0}` 中**权重最高（2.5）**，却从不投票——共识权重结构被静默扭曲。
- **实证**：grep `data_daemon` 内 `ssrp` 仅出现在 chip_fund 特征赋值处；`_extra` 构造点无 `ssrp`。
- **方向**：在调用点把 `ssrp` 注入 `extra_tags`，或改从正确缓存源读取。

### #S4 `consensus_engine.py:336-345` — 中性维计数对 dict 值失效，`neutral_ratio` 偏低（当前生效）
- 同族抽取块（:288-305）明确处理 `dims_factor` 值**可能是 dict**（`dim_val.get('direction')`）；但中性计数块对 `dims_factor.get(dim)` 直接 `float(score)`——对 dict 抛 `TypeError` 被吞，→ **dict 形态的维永不被计为中性**。
- 后果：`neutral_dim_count` 少计 → `neutral_ratio` 偏低 → 中性占比上限（>0.6）**可能不触发**，L3 聚合的门控静默弱化。`dims_factor`（由 `dim_adapter.convert_to_factors` 产出）正是 `{dim: {direction, strength, evidence}}` 嵌套态。
- **方向**：dict 值先取 `direction` 再判中性（镜像 :294-300 抽取块）。

### #S5 `dimensions/dim6_risk_engine.py:416` — ST 预警升格可被静默降级（当前生效）
- `_sev = '极高' if int(ev.get('direction', 0)) <= ST_WARNING_EXTREME_DIR else '高'`——`direction` 为 `None`/非数字串时 `int()` 抛错，被 :435 的 `except Exception as e: logger.debug(...)` 吞掉，**整块事件风险/升格（极高）丢失**；而 JUD 硬否决正依赖此升格（453 号 ST 分档、448 号 PIERS）。
- **实证**：事件块 try 从 :388 起，:416 在其内；`except` 仅 `logger.debug`（:435）。
- **方向**：`int(float(...))` + 守卫；日志升 `warning`。

### #S6 `backtest_minimal.py:81` — 回测逐日调 `evaluate(ts_code)` 无日期参数，前视偏差（模块不在日终管道）
- `StatusEngine.evaluate(self, ts_code, dim_results=None)`（`status_engine.py:245`）**无日期参数**、读「当前」tags/signals/市场数据；回测循环对每历史行调 `engine.evaluate(ts_code)` → 每行返回**同一「当前」状态** → 全部指标（收益/夏普/IC）**无效**。
- 另：`param_stability_check` 用 `os.environ` 传参（非线程安全 + 若引擎调用时不重读则无效）。
- **实证**：`backtest_minimal.py:77-90` 循环 + `status_engine.py:245` 签名。
- **方向**：回测须对历史切片求值（传入 date-scoped `dim_results` 或时间感知数据源）；参数显式传入而非走 env。

### #S7 `dimensions/dim4_chip_fund_engine.py:1069`（同 `phase_detector.py:578`）— ASR 单位 bug：0~1 比例比 0~100 阈值
- `_chip_distribution_analysis` 局部 `asr` 是 **0~1 比例**（`sum(...)/total_chips`），紧随的信号分支却比 **0~100 阈值**（`asr > 90` / `asr < 15` / `asr > 30`）。→ `asr>90`、`asr>30` **永不成立**，`asr<15`（原意「低浮筹」）近乎**恒成立**，信号坍缩至 BUILDING/WASHING，DISTRIBUTING 永不产出。
- **关键限定**：`result['signal']` 的唯一消费者 `_asr_to_phase` **已无调用方（死方法）**；生效消费者 `dim4._dim_asr` 与 `phase_detector._dim_asr` 读的是 `result['asr']`（已 `round(asr*100,2)`），并各自用 **0~100 阈值**（`dim4:594` / `phase_detector:194`）。→ **生产无实际影响**，属确凿的潜伏 bug + 死代码。
- **实证**：`:1050-1062`（asr 计算 + `result["asr"]=asr*100`）+ `:1069-1078`（0~100 阈值）+ `_dim_asr:585`。
- **方向**：分支改用 `asr*100`（或删死方法）。

### #S8 `dimensions/dim4_chip_fund_engine.py:3901` / `:4104` — 前置过滤器群引用未导入的 `BenchmarkService`（潜伏，在死代码块）
- `MarketEnvironmentFilter.__init__`（:3901）/`CircuitBreaker.__init__`（:4039）用 `BenchmarkService()`，**全模块无导入、无定义**（`DataManager` 靠函数内局部 import 侥幸）；`ChipPreFilter.__init__`（:4308）构造二者。
- **关键限定**：这些类（dim4 尾部 `MarketEnvironmentFilter`/`CircuitBreaker`/`EligibilityFilter`/`LiquidityFilter`/`MarketCapAdapter`/`ChipPreFilter`）与 `app/engine/framework/chip_pre_filter.py` 是**平行副本**；生产 `pipeline.py`/`routes` 走 framework 版，dim4 副本**无外部调用方**。→ 潜伏 `NameError`，一被引用即错。
- **实证**：`grep BenchmarkService` 全仓仅 dim4 这两处（类定义在 `app/services/benchmark_service.py`，dim4 未 import）。
- **方向**：补 `from app.services.benchmark_service import BenchmarkService`（或整体删死副本）。

### #S9 `dimensions/dim4_chip_fund_engine.py:4857` — `get_risk_tags` 读不存在的 `roce` 键（方法无调用方）
- `roce = latest.get('roce', 0) or 0`，而 `fina_indicator_cache` 暴露的是 **`roe`**（同文件 `_check_roce` 读的即 `fi['roe']`，:4671）。→ `roce` 恒 0 → `roce_pass` 恒 False、`fina_health` 恒 fall/suspicious。
- **关键限定**：`get_risk_tags` **全仓无调用方**（死方法；同名生效副本在 `framework/chip_pre_filter.py:959`）。
- **方向**：键名改 `roe`（或删死方法）。

### #S10 `radar_service.py:79` — `candidates[:200]` 在**排序之前**截断，Top-N 承诺失效
- 先 `candidates[:200]` 取前 200，再按 `signal_strength` 排序 → 信号强度高但排位 200 之后的股票被静默排除，「按信号强度取 Top N」的雷达目的落空；且循环内 `_get_stock_name` 逐只 N+1 查名。
- **实证**：`:79-85` 逐行。
- **方向**：排序后再截断（或把排序下推到查询）。

---

## 四、🟠 P2 中危（生效低影响 / 边界 / 契约漂移 / 静默失败）

### 4.1 静默 `except` 集群（吞掉失败、降级为中性默认值而无日志）
> OCR 在十余文件中反复命中，是本层最大共性。**当前生效程度不等**：多数为「降级为中性/空」而非崩溃。

| 文件 | 位置 | 说明 |
|------|------|------|
| `dim_adapter.py:740` | signal_confirm 兜底 | 广泛 `except` 吞掉 `ImportError/NameError/属性错配`；注释自曝 K5 前曾长期掩盖 `NameError` |
| `dimensions/dim2_structure_engine.py:174` | 结构健康度 | `except Exception: pass`，核心评分失败无痕 |
| `dimensions/dim5_emotion_engine.py:466` | BOCIASI/象限/板块/情绪/融资 | 多处 `except: pass` → 降 NEUTRAL；:568 `ecm` 若前序抛错则**未绑定**，`ecm.get_cached_margin(...) if ecm else None` 抛 `NameError` 再被吞 → 融资输入静默丢失 |
| `dimensions/dim6_risk_engine.py:435` | 事件风险块 | 仅 `logger.debug`（见 #S5） |
| `dimensions/dim7_valuation_engine.py:321` | 两个分位构建器 | `except: pass`，基准表填不上 → `_compute_potential` 静默走 0.5 中性 |
| `dimensions/dim8_summary_engine.py:1289` | 6 个环境定位 helper | `except Exception: return ''`，数据源坏了永远静默降级 |
| `tag_extractor.py:223` | moneyflow/margin/daily 缓存读 | `except: pass` |
| `cross_validate.py:83` | dim 引擎读/板块/日线/快照 | 裸 `except: pass` |
| `radar_service.py:62` | 雷达/看板 | 数据层故障伪装成「空雷达」 |
| `time_rhythm_engine.py:100` | 带宽/整段 | `except`: debug 吞错 → 'unknown' |

### 4.2 精确字符串 / 键匹配 → 规则永不触发（「静默失效」典型）
- **`conflict_matrix.py:210`（C6/C10）**：依赖 `divergence_type == '趋势背驰'` 精确中文匹配；同文件注释自述 C2/C11 曾因精确匹配永不触发（已修）。**须确认结构引擎 `divergence_type` 实际枚举值**。
- **`conflict_matrix.py:164`**：`_daily_dir/_weekly_dir` 与硬编码中/英字面量比对，`direction_map` 若用 `up/down` 等则规则恒不触发。
- **`dimensions/dim4_chip_fund_engine.py:3626` vs `:3784`**：`_combine_signals` 产出 `action ∈ {BUY, SELL, REDUCE, HOLD}`，而 `SIGNAL_ADJUSTMENT` 键为 `S_BUY/S_WASH_END/S_SELL/...` → `self.SIGNAL_ADJUSTMENT.get(signal_action, 0.0)` **恒 MISS** 取默认 0.0；`BUY` 分支 `position = base * 0.0 = 0.0`，仅因紧随的 `target_position` 覆盖而侥幸正常 → 乘数路径实为死代码。
- **`dimensions/dim5_emotion_engine.py:406`**：四象限明细中文映射键 `'dv_bond'`，而生产者 `bociasi_quadrant._cache` 实键是 **`'dv_bond_diff'`**（`bociasi_quadrant.py:189/193`）→ 股债差明细被**静默丢弃**。
- **`light_derive.py:143`（`_risk_source_is_high` dict 分支）**：dict 形态只读 `'level'`，而 `risk_light` 读 `'risk_level' or 'level'`。**限定**：live 生产者 `dim6:512` 出的是**字符串列表** `"名称：等级"`（字符串分支正确）；dict 分支仅历史/测试构造 → **不一致但低影响**（列 §六 待确认）。

### 4.3 不可达 / 死分支
- **`conflict_matrix.py:325`**：`elif aligned_count == 2`（初现型）不可达——`semantic_type/adjustment` 已预置为该值，其余可达分支在上方处理；`== 2` 精确等号亦漏 0/1/3/5/6。
- **`dimensions/dim3_vp_engine.py:387`**：`breakdown` 分支不可达——满足其条件者已被上方 `selling_pressure`（`<-2.0 and vr>10`）先命中；须重排负分支或收紧前序条件。
- **`dimensions/dim5_emotion_engine.py:286`**：`vp == '严重背离'` 恒假（`vp` 只可能取 '强健康'/'背离'/'中性'/''）。
- **`dimensions/dim4_chip_fund_engine.py:1450` 区**：`vol_status`/`cyqkl_status` 分支——两键在 `calculate_all_indicators` 中**从未写入**（只产 ssrp/asr/concentration/profit_ratio/cyqkl/rsi）→ 打分分支恒不加分。
- **`status_engine.py:1372`**：`generate_seven_dim_from_signals` 标注「已弃用」（signal_json.signals 恒空）却仍保留完整旧体，唯一可达分支是早退 `dim_results` 委托，余下为死代码。
- **`event_monitor.py:944`**：`dim_direction` 兜底分支不可达（invariant 使其永不满足）。

### 4.4 数值安全（0 / NaN / None 混同）
- **`conflict_matrix.py:272`（C13）**：`implied_rr = dist_to_resistance_pct / abs(dist_to_support_pct)` 未显式守卫除数为 0（虽前序 `dist_to_support_pct < 0` 隐含非 0）。
- **`shared_vol_ratio.py:24-46`**：`avg_vol_5d` None/≤0 静默返回 1.0（正常值）；`current_vol` 为 None → TypeError、NaN → 静默；`classify_vol_ratio` 对 NaN 全部比较 False → 落入 `else → '极度缩量'`（误标）。
- **`shared_support_resistance.py:48/50/75`**：`val is not None` 不拦 NaN → NaN MA20/MA60 静默污染支撑位；:83 无上方压力时 `resistance` 回退 `hi60`（可**低于现价**，R:R 失真）；:110 `if support else None` 丢弃**恰好 0.0** 的合法值。
- **`dimensions/dim8_summary_engine.py:1343`**：`last / float(closes.iloc[-21])` 等无零/NaN 守卫（仅查空/长度）；`astype(float)` 会把非数值静默转 NaN。
- **`dimensions/dim6_risk_engine.py:544`**：`continuous_value = round(min(rr_value/3.0, 1.0),4) if rr_value else 0.5`——`rr_value<0` 时负值下传、`rr_value==0` 落 0.5 兜底（语义混淆）。
- **`time_rhythm_engine.py:49/74/98`**：`rolling(20).std()` NaN、30 vs 60 窗口不一致、带宽紧但 `consolidation_days<5` 仍出 'early_consolidation'。
- **`reliability_assessor.py:257`**：`atr_raw` 非数值串时 `_safe_float(...,None)` 得 None，后续 `atr < 3.0` 抛 TypeError，被外层吞 → 整维静默 0.5。
- **`signal_analyzer.py:551`**：`_false_breakout_check` 对缺失上下文字段默认 0 → `passed=False` 强制 HOLD（fail-closed），与 docstring「可选字段」矛盾。

### 4.5 dim4 策略 / 执行层状态
- **`:473-476`**：软触发（移动止损/时间止损/RSI 止盈/移动止盈）同一根 K 可**各自发出 SELL_50**，无去重/仓位核算 → 累计可 >100%。
- **`:321-327`**：硬止损 `reset()`，而软触发**不重置** state → 同一触发逐根重复、`rsi_high_count` 累加。
- **`:473`**：`execute_batch` 只刷新 `entry_prices`、遗留 `entry_dates` → `holding_days` 漂移（影响 20 日时间止损）。
- **`:1349`**：模块级可变 `_INDUSTRY_MEMO` 无同步、无淘汰（逐股/全市场路径）→ 并发竞态 + 无界增长。

### 4.6 契约 / 签名 / 文档漂移
- **`valuation_estimator.py:696`**：`_fina_health` docstring 写返回 3 元组 `(fina_health, roce_pass, df_fina)`，实为 **4 元组** `(health, roce_pass, roce_na, df_fina)`（调用方均按 4 元组解包）。
- **`valuation_estimator.py:205`**：`build_fcf_percentile(ecm=None)` **接收却忽略 `ecm`**（恒读 `self._get_dm().cache`）→ 调用方传不同路由实例时静默用错数据源。
- **`valuation_estimator.py:726`**：`_fina_health` 里 cashflow 走 `dm.cache.get_cached_cashflow`，兄弟表走 `dm.get_cached_*`，绕过 DataManager 抽象。
- **`arbiter.py:12`**：docstring 仍写「P2 deep → avoid」为硬否决，实现已降级为非阻断提示（335 号 S2.3）→ 误导。
- **`advice_builder.py:196`**：R:R 门只读 `geo['risk_reward']`，而下方止损分层 `_ssot_stop_and_tiers` 是 dim6-first + geo 兜底 → dim6 有 rr 而 geo 无时门静默跳过。
- **`advice_engine.py:631`**：L0c 持仓期门整段 `try/except: pass`（含 `get_signal_registry` 导入/解析失败）→ 静默削弱风控；:778 软风险仓位调整同理。
- **`status_engine.py:835`**：`l0['emotion_position_cap']` 仅在 `_caps` 为真时产出，yaml 缺该键时下游 `advice_engine` 读缺失键；:859 `float(_caps.get('recovery', _caps.get('normal',0.6)))` 若 yaml 某键置 `null` 则 TypeError（`_apply_l0` 无外层 try）。
- **`enum_cn_map.py:28`**：`ma_alignment_cn` docstring 称未知名返回 '均线数据不足'，实际落 `str(value or '')`（可能漏出英文）；:92 `meta.description.split(':',1)[0]` 在无冒号时返回整段描述而非标签。

---

## 五、🟡 P3 低危 / 死代码 / 防御

- **「计算即丢弃」裸表达式**（指示改动未经 lint，`ruff` B018 类可拦）：
  - `conflict_matrix.py:303` `max(len(_directions),1)`
  - `advice_engine.py:305` / `advice_builder.py:641` `sum(1 for x in dirs if x>0)`
  - `radar_service.py:247` `top_summaries[0] if top_summaries else ''`
  - `phase_detector.py:725` `df["close"].values`
  - `dimensions/dim5_emotion_engine.py:226` `slow_result.get('confidence',0.5)`
  - `time_rhythm_engine.py:58` 带宽趋势结果丢弃
  - `dim4` 多处：`:144`（片段）`ok_count/max(total_conditions,1)`、`dim4_part_1552` `indicators.get('concentration')`、`dim4_part_3106` `closes[-5:]`
- **死局部 / 死参数 / 死导入**：`dim_adapter.py:501/606`（`_emo_judg`/`_val_judg`）；`signal_analyzer.py:347/387`（`signal_plain`/`build_audit` 的 `maintenance`）；`dimensions/dim2_structure_engine.py:47`（大段未用 `chanlun_strategy` 导入）+ `:558`（`_assess_vs_zhongshu` 未用 `dims`）；`dimensions/dim7_valuation_engine.py:39`（未用 rating 帮助函数/常量）；`dimensions/shared_vol_ratio.py:9`（定义却未用的 `logger`）；`dimensions/dim3_vp_engine.py:32`（`_load_precomputed_macd`/`_MACD_PRECOMPUTED_CACHE` 死代码、注释重复 :30）。
- **文档 / 注释失真**：`arbiter.py:194` P2、`enum_cn_map.py` 兜底语义、`emotion_temperature` None→中性、`dimensions/dim1_signal_engine.py:243` SQL 排序注释（实际 `ORDER BY ts_code, asof_date DESC, benchmark`）、`valuation_estimator` 元组元数、`status_engine:1372`「已弃用」仍运行、`dim4` 两处 `# 6.` 编号重复。
- **性能**：`dim1`/`status_engine:1038` f-string 早格式化日志应改惰性 `%s`；`shared_support_resistance.py:43` 函数内 `import numpy`；`event_monitor.py:786` `_detect_concept_heat` 逐股全表 `value_counts`（O(股票×概念)）；`radar_service.py:129` N+1 取股名。
- **其它防御**：`backtest_minimal.py:86/113/237`（`consensus_rate` None/日期键归一/os.environ 单线程假设）；`potential_engine.py:350` 截面循环边界 `-horizon-20` 冗余且可致空 list；`potential_engine.py:405` 平滑/clamp 常量与 `DIM_WEIGHTS` 脱钩；`light_derive.py:109/129`（DATA_MISSING 与 yellow 不区分、`summary_light` 未拦 NaN/inf）；`dimensions/dim4` 的 ROCE 双阈值（≥15/≥5 vs ≥20/≥12/≥6/≥0）与 ROE→ROCE 系数（×1.2 vs ×1.5）不一致；`dim4` `_check_roce` **fail-open**（异常返回 `{'passed': True}`，绕过 ROCE<5% 硬剔除）。

---

## 六、已排除（误报 / 设计意图 / 待确认）

| 项 | OCR 断言 | 本次核实 |
|----|---------|---------|
| ⚪ `light_derive.risk_light` 只认 `'risk'` 不认 `'risk_engine'` | 规则恒返回 DATA_MISSING | **误报**：生产键就是 `'risk'`（`status_engine.py:453` engine_map、`dim8 dim_map` 同用 `'risk'`），**不存在 `'risk_engine'` 键** |
| ⚪ `dimensions/dim1_signal_engine.py:436` 行尾「`?` 垃圾字符」 | 源码含乱码 | **疑伪影**：`od -c` 未见字面 `?`（CJK 多字节渲染伪影），非真问题 |
| ⚠️ `dimensions/dim7_valuation_engine.py:649` `dev > 30` 处罚「极端泡沫」 | 符号可能反（罚最便宜的票） | **待确认**：`dev` 源自 `tags.valuation_deviation`（`_compute_potential:609`，非 `composite*20`）；`valuation_estimator._level_by_composite` 注释称「composite 大=低估方向」——若 `deviation` 正=低估，则 `dev>30` 罚的恰是最便宜股，**符号可能反。须业务确认符号约定后定级** |
| ⚠️ `light_derive.py:143` dict 分支只读 `'level'` | 漏计高源 | **待确认（低影响）**：live `risk_sources` 是字符串列表（分支正确）；dict 分支仅历史/测试构造 |
| ⚪ `dimensions/dim5`/`dim8` 若干展示口径 | 语义偏差 | **设计意图/既有登记**：479 号 A12 网关、482 展示清理、464 dim8 定稿已覆盖，**不重复计** |
| ⚪ `dimensions/dim4` ASR「三处三义」 | 语义相悖 | **已有 451 号处置**：`_dim_asr` 已按 451 号统一为「高 ASR=蓄势」；残留的 0~100 阈值分支即 #S7（死方法内） |

---

## 七、处置方案与批次建议

> 性质：本档只定计划；实施须经用户确认后按批次进行。**口径项（如 #S7 是否删死方法、`dev>30` 符号、`SIGNAL_ADJUSTMENT` 键对齐方式）建议先拍板再动手。**

### 待拍板口径（建议项，§九 登记）

- **Q1（#S7）dim4 ASR 单位 bug 处置**——① 修死方法内阈值（`asr*100`）② 直接删死方法 `_asr_to_phase` + 相关分支 ③ 两者皆做。偏工程决策。
- **Q2（`dev>30`）dim7 估值偏离符号口径**——`valuation_deviation` 正=低估还是正=高估？决定 `_compute_potential:649` 的 0.3× 惩罚方向是否需取反。**须业务确认**。
- **Q3（`SIGNAL_ADJUSTMENT`）dim4 信号乘数键对齐**——① 改 `_combine_signals` 产出 `S_*` ② 改 `SIGNAL_ADJUSTMENT` 键为动作名 ③ 保留（因 `target_position` 已兜）。偏工程决策。
- **Q4（`light_derive._risk_source_is_high`）dict 分支**——是否补 `'risk_level'` 键回退（当前 live 不受影响）。

### 批次划分（建议）

| 批次 | 主题 | 条目 | 说明 |
|------|------|------|------|
| **批次1** | 当前生效缺陷 | #S1 dim3 logger、#S2 emotion None→0、#S3 SSRP 接线、#S5 dim6 ST 升格守卫、#S4 consensus 中性 dict | 5 项，生效路径；探针 + 定向回归 |
| **批次2** | 静默 except 补日志 | §4.1 十余处（补 `logger`/改 warning，不改变降级行为） | 机械、低风险；统一 `log_and_swallow` 或逐点补 |
| **批次3** | 键/字符串匹配失效 | #S9 roce→roe、§4.2 `SIGNAL_ADJUSTMENT` 键、`dv_bond`→`dv_bond_diff`、C6/C10 枚举确认 | 须先确认生产者实际枚举 |
| **批次4** | 数值安全 + 不可达分支 | §4.3/§4.4（除零/NaN/None、不可达分支删或修） | 逐点守卫 |
| **批次5** | 契约/文档漂移 | §4.6（元组元数、`ecm` 失效、docstring 同步） | 低风险 |
| **批次6** | 死代码/防御/性能 | §五（删裸表达式/死局部/死导入、惰性日志、死方法）+ §4.5 dim4 执行层状态 | 视 Q1 决定是否删 `_asr_to_phase` 死方法 |
| **批次7** | 潜伏 + 非管道 | #S8 dim4 缺导入、#S6 backtest 前视偏差、#S10 radar 排序前截断 | 非日终管道；可独立 |

### 依赖顺序与风险

- 批次1 优先（当前生效）；#S3 SSRP 接线须同时确认 `extra_tags` 契约与 `phase_detector._dim_ssrp` 读取源。
- 批次2 建议统一封装（如 `log_and_swallow`）以免逐点遗漏，但**不得改变既有降级语义**。
- 批次3 `SIGNAL_ADJUSTMENT`/`dv_bond` 对齐须先 `grep` 确认生产者枚举（`_combine_signals` 动作集、`bociasi_quadrant._cache` 键集）。
- 批次7 #S6/#S8/#S10 均**不在 `data_daemon` 日终链路**，可与其他批次解耦；#S8 若决定保留 dim4 副本须补导入，若删副本须先确认无动态引用。
- 任何触及 `dim4_chip_fund_engine.py`（6202 行）的改动须先 `py_compile` + ruff 目录级复扫。

---

## 八、验证口径（实施时）

- 每批实施后：`py_compile` + `ruff`（opportunity_atlas 目录级复扫，零新增）+ 定向回归；**全量 pytest 须停 `data_daemon` + `start_daemon.sh` 看守**（否则 `stock_cache.db` 写锁致挂起，见 485 先例），跑完重启。
- 数据正确性类（#S2/#S3/#S5/#S4）：DB/探针实证——温度 `None` 应给 50；`_dim_ssrp` 在有 `ssrp` 时应产非空；ST `direction<=-2` 应升「极高」；`neutral_ratio` 对 dict 值应正确计入。
- 静默失效类（#S1/§4.2）：构造触发路径验证异常**可见**（日志出现）且不漏判；键匹配类须以真实引擎输出枚举回放。
- 回测类（#S6）：以历史切片与「当前」状态对比，验证逐日状态不再恒同。
- 复跑前置：停 `data_daemon` **及** `start_daemon.sh` 看守，跑完重启。

---

## 九、待定登记（本档未决）

| 登记 | 内容 | 依赖 |
|------|------|------|
| 登记-1 | Q1 dim4 ASR 单位 bug 处置（修死方法 / 删死方法 / 皆做） | **待拍板** |
| 登记-2 | Q2 `valuation_deviation` 符号口径（决定 `dev>30` 方向） | **待业务确认** |
| 登记-3 | Q3 `SIGNAL_ADJUSTMENT` 键对齐方式 | **待拍板** |
| 登记-4 | Q4 `light_derive._risk_source_is_high` dict 分支补键 | **待拍板**（低影响） |
| 登记-5 | #S3 SSRP 注入 `extra_tags` 的接线方式 | 批次1 |
| 登记-6 | §4.2 `divergence_type` / `_daily_dir` 实际枚举确认 | 批次3 |
| 登记-7 | 与 489/490/491/492/464 重叠项，不重复计入 | 已标注 |

---

## 附录：OCR 会话与原始清单

- 主段 30 文件 → **144 条**，会话 `fe4cdffb-51c1-4894-b308-2f3a175a3b67`（约 6.53M tokens，2m1s）；临时输出 `/tmp/sig_ocr_20261003/seg_main.txt`（+ `.err`）。
- dim4 分 4 块（6202 行超单文件上限，按类边界切 `dim4_part_1_1551/1552_3105/3106_4650/4651_6202.py`）→ **36 条**，会话 `07c86089-fc35-48bd-9edf-98e3a1eb7d3d`（约 1.10M tokens，46s）；临时输出 `/tmp/sig_ocr_20261003/seg_dim4.txt` + 分块 `/tmp/sig_ocr_20261003/dim4chunks/`。
- 合计 **180 条** → 归并约 **95~110 项**（P1 ≈10 / P2 ≈45 / P3 ≈45）+ 6 条排除/待确认；同因同位置归并（静默 except、ASR 单位、键匹配、非有限值等）。
- 本档为**只读核查档 v1.0，未改任何代码/配置，未提交**（工作树仅 daemon 产物 untracked）。
