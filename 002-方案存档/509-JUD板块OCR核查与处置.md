---

# 509号｜JUD 板块 OCR 核查与处置

**版本**：v1.8（2026-10-08；只读核查档 + 执行计划 + **批次1~7 已实施**；拍板 Q1~Q5 全决）
**v1.0（2026-10-06）**：只读核查档落档。OCR 4 段扫 ≈105 条 → 人工实证归并；未改任何代码/配置/方案。
**v1.1（2026-10-06）**：用户「结合 509 制定详细执行计划」→ 拍板 **Q1=修（换独立信号源）/ Q2=保留符号语义 / Q3=无条件降 wait / Q4=先量化再修**（Q5 按推荐默认登记，批次4 前再确认）→ 落 §九 详细执行计划（7 批 + 依赖 + 验证 + 提交）。仍**未改任何代码**。
**v1.2（2026-10-08）**：**批次3 已实施**（#J18~#J27 建议/展示层，commit `63b20d8`）：4 文件改动 + 探针 `tests/test_509_jud_batch3.py`（12 断言）+ 适配 `test_507_batch7`（fake 强度按代码号与分批无关）；全量回归 **2158 passed / 2 skipped / 9 xfailed 零失败**；ruff 零新增；daemon 已停跑后重启。**批次0 文档提交** `2bdc05b`。
**v1.3（2026-10-08）**：**批次5 已实施**（#J28~#J31 回测，commit `70f79db`）：`backtest_minimal.py` 4 项（全胜 profit_factor=None / equity 仅持仓日复利 / 前向窗口真实日历+索引 / close_prices 键归一）+ 探针 `tests/test_509_jud_batch5.py`（5 断言）；全量回归 **2163 passed / 2 skipped / 9 xfailed 零失败**；ruff 零新增。
**v1.4（2026-10-08）**：**批次7 已实施**（§五 低危清理，commit `ee12746`）：12 文件改动（#J1 `_r` 死分支删 / RR_GATE 常量化 / 死参移除 / 函数内 import 上移 / 静默 except 加日志 / NaN 守卫 / SQL 绑定参 / watchlist 除零·竞态·批量取名 / strategy_analyze 单次解析·数值化·惰性日志 / radar L4 缓存 / docstring 语义）+ 探针 `tests/test_509_jud_batch7.py`（13 断言）+ 适配 test_493/test_494 旧签名；全量回归 **2176 passed / 2 skipped / 9 xfailed 零失败**；ruff 零新增。
**v1.5（2026-10-08）**：**批次6 已实施**（daemon JUD 工序段 #J43~#J46，commit `9ca793f`）：`data_daemon.py` 4 项（#J43 原子切换 RENAME 备份→live→删备份 / #J44 treemap close 缺失守卫 / #J45 富化循环定位日志 / #J46 OUT-CHECK once-guard）+ 探针 `tests/test_509_jud_batch6.py`（5 断言，AST/源码级）；全量回归 **2181 passed / 2 skipped / 9 xfailed 零失败**；ruff data_daemon 零新增（40 均基线既有）。
**v1.6（2026-10-08）**：**批次1 已实施**（判定链语义/量纲 #J2/#J3/#J4/#J5/#J7/#J8，commit `8e65e61`）：**探针量化先行**（`scripts/_509_b1_probe.py`：signal_strength 0-100 域实证 min0/max92 / 空头共识 75.12%（4173/5555）/ decay 实测 max=22 全 healthy / maintenance 100% healthy）→ 4 文件改动（#J2 分级 80/60/40/20 / #J3 日环比 ±10 / #J4 键 `decayed→broken` / #J5 情绪方向冲突比较 / #J7 去 clamp 保留符号、负分落 avoid / #J8 评分标定 0-100 全域）+ 探针 `tests/test_509_jud_batch1.py`（10 断言）+ 适配 `test_495_b2` 门禁 H3 域（[-100,100]）+ 适配 `test_509_jud_batch3` #J19 分值；**全市场重跑 5554 只门禁全 PASS、五档分布零漂移**（avoid 83.3 同基线，enter 0.2/light 0.3/wait 10.5/reduce 5.6）；全量回归 **2191 passed / 2 skipped / 9 xfailed 零失败**。
**v1.7（2026-10-08）**：**批次2 已实施**（判定链健壮性 #J6/#J9/#J10/#J11/#J12/#J13/#J14/#J15/#J16/#J17，commit `33cb9f1`）：**#J14 探针量化先行 + 用户拍板方案 B**（OCR 原判「total_dim_count 缺失维弱化闸门」与数据流不符——convert_to_factors 恒返回 13 键；真缺陷=辅助维恒中性抬高 neutral_ratio → 闸门过度触发压扁幅值，786→236、约 550 只恢复）→ 5 文件改动（#J6 dim4 补产 `retail_tendency` 枚举+C4+ 改读 / #J9 legacy 平票判 neutral / #J10 L0a int 守卫 / #J11 _apply_l0 asof_date 透传 / #J12 json 守卫 / #J13 全中性族判 neutral / #J14 neutral_ratio 只计 7 主维 / #J15 weights=None→1.0 / #J16 周线无条件降 wait+删死函数 / #J17 wait 强制降级 45.0）+ 探针 24 断言（j6/j14/j16/misc）+ 适配 test_490/test_492/test_494 旧行为断言；**全市场重跑 5554 只门禁全 PASS**（avoid 83.3→80.6 容差内，#J14 幅值恢复所致）；全量回归 **2215 passed / 2 skipped / 9 xfailed 零失败**。
**v1.8（2026-10-08）**：**批次4 已实施**（接口/写路径/单例 #J32~#J42，**Q5 拍板=严格月份边界 + 6% 未舍入比较**）：5 文件改动（opportunity_library #J34 先校验后 setattr（lib_level 域校验前置）/ #J35 数值列强制 cast·拒 null / #J36 commit 包 try/except+rollback / #J37 search 转义 %·_ + 分页硬上限 100；watchlist #J38 mf_sorted 无条件先初始化 / #J39 `_get_cache()` 模块级单例；opportunity_atlas #J40 惰性单例加双检锁；strategy_analyze #J41 deep_chip 统一仅存 float / #J42 `_detect_market_state` 改读真实 `market_state` 字段（原个股状态冒充）；account_risk_status #J32 连亏严格月份边界+零盈亏跳过不 break / #J33 6% 未舍入比较（`math.isclose` 容差）舍入仅留展示）+ 探针 `tests/test_509_jud_batch4.py`（17 断言）+ 适配 test_493（纯函数行为不变回归）；全量回归 **2232 passed / 2 skipped / 9 xfailed 零失败**；ruff 零新增；daemon 停后跑已重启。
**来源**：2026-10-06 用户要求「调用 OCR 对系统中 **JUD 板块** 的所有实际代码进行检查，问题在对话框内详细说明，不要修改方案和代码」→ 对话框报告出具后，用户「开号落档，展开核查档草稿」→ 落本档。
**方法**：`ocr scan`（alibaba/open-code-review，DeepSeek `deepseek-chat`，`--max-tokens 200000`）按功能分 **4 段** 扫描 JUD 板块，共 **≈105 条原始发现**，**逐条人工核实**（对照真实代码/调用图；OCR 存在上下文/伪影误报，误报/设计意图/待确认单列 §六）。
**基线**：HEAD `e35b722`（= origin/main）；工作树仅 `data/account_risk_status.json` 未跟踪＝daemon 运行产物。生效配置 `status_engine.yaml`：`jud_engine_version="v390"`。
**与 507 的关系**：507 号（SIG 层 OCR）曾把 JUD 判定栈文件一并扫过（侧重「SIG 计算 × JUD 消费面」）。本号按用户拍板**重新扫、独立成 JUD 专项发现**，§八列与 507 的交集项（不重复计）。
**原始产物**：`/tmp/jud_ocr/{A_judge_core,B_advice,C_validate_iface,D_daemon}.txt`（OCR 会话结果；D 段为 `data_daemon.py:5513-6316 + 6928-7012` 提取的临时文件）。

---

## 一、核查背景与总体结论

JUD 板块＝系统第 4 层（COL→RAW→SIG→**JUD**→OUT）的**判定与操作建议层**：`StatusEngine.evaluate` → （v390）`_aggregate_v390` L1 `dim_adapter.convert_to_factors` → L2 `reliability_assessor` → L3 `consensus_engine` → L4 `conflict_matrix` → L5 `factor_arbiter` → L6 `advice_engine` → `_assemble` 落 `status_snapshot`/`treemap_snapshot`；旁路 `cross_validate`（弹窗/日环比）、`radar_service`（雷达/看板/通知）、`signal_analyzer`（信号属性/衰减/审计）等。

- **JUD 生效链路无 P0**：`_aggregate_v390`（L1→L6）→ `_assemble` → 落库，未发现会导致崩溃或全市场性数据错误的缺陷。
- **最大共性风险＝「静默失效」**：`except: pass` / `except: logger.debug` 在判定链密集存在，使**规则永不触发**或**永远走错分支而不报错**（与 507 对 SIG 的结论同源）。
- **确凿语义类缺陷 3 处**：判据方向反转 / 量纲错位 / 死分支（#J2/#J3 量纲、#J6 死规则、#J7 符号截断）。
- **确凿静默数据缺陷 4 处**：#J4 键错、#J11/#J41 类型混入、#J44 除零守卫失效。
- **多处属「口径存疑，须业务拍板」**（§七 5 项）。

**分布（已实证 + 归类）**：🔴 高危 **8** · 🟠 中危 **≈34**（含专有 + 低危清单归并）· 🟡 低危/死代码/文档 **≈15** · ⚪ 误报/设计意图 **≈4** · ⚠️ 待拍板 **5**。

---

## 二、范围与分段

| 段 | 文件 | 行数 | OCR 条数 |
|----|------|------|----------|
| **A 判定链核心** | `status_engine.py` / `consensus_engine.py` / `conflict_matrix.py` / `reliability_assessor.py` / `dim_adapter.py` / `factor_arbiter.py` / `arbiter.py` | ≈3.6k | 21 |
| **B 建议/展示层** | `advice_engine.py` / `advice_builder.py` / `potential_engine.py` / `signal_analyzer.py` / `radar_service.py` / `light_derive.py` / `time_rhythm_engine.py` | ≈3.1k | 25 |
| **C 回测/契约 + 接口/配置** | `cross_validate.py` / `backtest_minimal.py` / `tag_extractor.py` / `routes/{strategy_analyze,opportunity_atlas,opportunity_library,watchlist}.py` / `services/{status_config,account_risk_status}.py` / `config/status_engine.yaml` | ≈6.5k | 53 |
| **D daemon JUD 工序段** | `data_daemon.py:5513-6316`（`_jud_enrich_with_meta`/`_build_treemap_snapshot`/`_out_transmit_seven_dim`/`_backfill_seven_dim_jud`/`_build_status_snapshot`）+ `:6928-7012`（`_jud_build`/`_out_build`/`_verify_out_completeness`） | 892 | 6 |
| | **合计** | ≈14k | **≈105** |

**归并口径**：同一处代码可被多条 OCR 命中（如静默 except 遍布多文件），故按「位置/主题」编号，条数 ≠ OCR 原始条数。

---

## 三、🔴 高危（已实证）

### #J1 `routes/strategy_analyze.py:1036` — `_r` 未定义（死分支内 NameError）
`_status_row['advice_params'] = _r.get('advice_params') if _r is not None else None`。全文件 `\b_r\b` **仅此一处**、从无赋值。
- **实证**：`grep -n "\b_r\b"` 仅命中 1036；`ast.parse` OK（运行时才炸）。
- **实测影响＝死分支**：`_status_row`（:810 构建）**恒定含** `'advice_params'` 键 → `if 'advice_params' not in _status_row:` 恒假 → `_r` 永不求值。
- **方向**：删 `_r` 表达式（或补真实源 `_pr`/`_verdict`）。

### #J2 `cross_validate.py:1193` — `signal_strength` 量纲错位（0-10 vs 0-100）
`_build_opportunity_summary` 分级 `>=8 A+ / >=6 A / >=4 B / >=2 C / else D`。
- **实证**：同文件 `_lookup_vote`（:1078）注释自述「signal_strength 改为 **0-100**（旧 0-10 的 ×10 迁移）」；`potential_engine.compute_potential` 实际产 0-100。
- **后果**：**全市场恒 A+**，A/B/C/D 分支不可达。
- **方向**：阈值改 80/60/40/20。

### #J3 `cross_validate.py:1824` — 同源量纲错位（日环比阈值）
`signal_strength` 日变化 `abs(delta) >= 1.0 → normal`。0-100 量纲下 ±1 为噪声 → **刷屏**。
- **方向**：阈值对齐 0-100（约 ≥10）。

### #J4 `reliability_assessor.py:69` — decay 键错位，`broken` 永不映射
`_assess_signal` 映射 `{'healthy':0.8,'fading':0.5,'decayed':0.2}`。
- **实证**：生产者 `signal_analyzer.py:646` 产 `{'maintenance':{'status': maintenance['decay_status']}}`；`decay_status` 取自 `detect_decay`→`overall_status`，值域＝`DECAY_LEVELS = {healthy, fading, **broken**}`（:55-58）——**从未产 `decayed`**。
- **后果**：`broken`（已失效）信号静默落 0.5 默认，**削弱 dim1 可靠性**（L2→L3 加权）。
- **方向**：键改 `'broken'`（保留 `decayed` 仅当存在历史别名）。

### #J5 `factor_arbiter.py:197` — Step 5 情绪极端修正 if/elif 分支等价（死分支＋与 docstring 矛盾）
`if emotion_direction == 1: final_score *= 0.85 … elif == -1: final_score *= 0.85` —— 两分支**完全相同**，方向判断无效果。
- **实证**：docstring 称「冰点+看多 / 正向+看空」两相反场景，但按逆势口径 `direction=+1` 即看多（ice）、`-1` 即看空（positive），二者本为同一「极端情绪」；且 `final_score` 恒非负（见 #J7），**永远不可能出现「看空但极端热」**。
- **方向**：收敛为单分支 + 单一证据；或改「情绪方向 vs 建议方向」显式反转比较。

### #J6 `conflict_matrix.py:185` — C4+ fatal 规则恒不可达（死代码）
`if '主力出货' in retail_institution and dim4_phase in ('building','lifting'): fatal`。
- **实证**：`dim4_chip_fund_engine.py:1024` `retail_inst = _assess_retail_institution(_retail_phase, _retail_flow)`；`_retail_phase` 与 `phase_info['phase']`（即 `judgment.phase`）**同源赋值**（:996/:1002）；`_assess_retail_institution`（:920）仅当 phase=`distributing` 出「主力出货」→ 条件与 `dim4_phase∈(building,lifting)` **互斥** → fatal 永不触发。
- **方向**：改从独立枚举字段取散户/机构倾向（勿用展示文本），或如 C2 般登记删除。

### #J7 `factor_arbiter.py:184` — `consensus_rate` 带符号却 clamp 到 [0,1]（方向信息丢失）
Step 2：`consensus_rate = max(0.0, min(1.0, consensus_rate))`。
- **实证**：`consensus_engine.compute` 返回**带符号 [-1,1]**（`if bear_score > bull_score: raw_consensus_rate = -raw_consensus_rate`；497 批次2 已确认「带符号且幅值恒≥0.5」）。**空头共识（负值）被截为 0** → `base_score=0` → `final_score≈0`。
- **后果**：空头股 `final_score` 语义失真（成因是「方向被抹除」而非「共识弱」）；并连带 #J5 的「看空+极端热」分支永不可达。
- **方向**：明确 final_score 方向语义（保留符号 / 取幅值 / 空头另走降级）——见 §七 Q2。

### #J8 `signal_analyzer.py:165` — 衰减评分上限 ≈54，`broken`(70-100) 与 `fading` 上段不可达
`overall_score = Σ scores[dim]×DECAY_WEIGHTS[dim]`；各维上限：price_trend≤50(×.30)+volume_price≤60(×.25)+volume_energy≤50(×.20)+chip_change≤60(×.15)+main_force≤50(×.10) ≈ **54**。
- **后果**：`DECAY_LEVELS['broken']=(70,100)` **永不可达**，`fading`(40-69) 顶段亦不可达 → 「已失效」永不报告（并连带 #J4 的 `broken` 分支本就取不到）。
- **方向**：各维评分展开至 0-100 全域，或按可达区间重定 `DECAY_LEVELS`。

---

## 四、🟠 中危（已实证）

### 4.1 判定链核心（A 段）
- **#J9 `status_engine.py:997`** — `elif bull == bear and bull > 0:` **不可达**（前序 `if total_w > 0` 要求 `bull+bear>0`，恒先命中）；且首分支 bull==bear 时返回 `direction='bearish'`（平票判空），须确认。
- **#J10 `status_engine.py:827`** — `int(e.get('direction', 0))` 在 L0a 硬否决循环中**无 try 守卫**（对比同函数下方 ST 块有守卫）；`direction` 为 `'st'`/`''` 时抛 `ValueError` → **整个 `_apply_l0` 中断**（失 hard_veto/软风险/仓位上限）。
- **#J11 `status_engine.py:880`** — `_apply_l0` 回退读 `self.dm.cache.get_pre_feat(ts_code)`（**无 `trade_date`**）→ 回测 `asof_date` 下 L0 门禁（情绪上限/低流动性/持有期）**引入前视偏差**，违背 507 批次7 #S6 引入 `asof_date` 的初衷。
- **#J12 `status_engine.py:1325`** — `json.loads(result['advice_params'])` **无 try/except**；异常将中断整个 `_assemble`，丢弃整行 status_snapshot。
- **#J13 `consensus_engine.py:203`** — 族内全中性时 `bull_entries`/`bear_entries` 均空，tie-break 置 `majority_dir='bull'` → `group_details[...]['direction']` 把**中性族误标为 bull**。
- **#J14 `consensus_engine.py:336`** — `total_dim_count += 1` 置于 `score is None` 检查**之前** → 缺失维抬高分母、分子只计存在维 → `neutral_ratio` 偏低 → 中性上限弱化（**与 507 #S4 同类但点位不同**，见 §八）。
- **#J15 `consensus_engine.py:275`** — `weights=None` 时 `_family_regime_weight` 返回 0.1 兜底，`bull_score`/`bear_score` 被 **×0.1 缩放**，docstring 承诺的「退化为纯 STATE_WEIGHTS」不成立。
- **#J16 `factor_arbiter.py:227`** — Step 7 大级别否决仅当 `_daily_is_bullish(dims_factor)` 为真才降级；周线 `down` 但结构/量价平或负时 **`enter/light` 得以保留**，与「周线向下即丢弃买点」不符。
- **#J17 `factor_arbiter.py:151`** — 强制降级返回 `opportunity_state='wait'` 却 `final_score=0.0`（wait 正常对应 45-64 段），内部矛盾，可误导前端。

### 4.2 建议/展示层（B 段）
- **#J18 `signal_analyzer.py:326`** — `verified` 在 `day>=3 and distance_pct>0` 时**自动置 True**，无外部确认源；该值被 `classify_attribute`(right_confirmed)/`build_audit`/`signal_plain` 用于**门控/定性**。语义应为独立字段 `auto_verified`。
- **#J19 `signal_analyzer.py:139`** — `volume_ratio` 缺失默认 **1.0** → 落 `else → 健康(10 分)`，把「缺数据」报成「量能健康」。
- **#J20 `advice_engine.py:28`** — `_safe_float` 仅捕 `TypeError/ValueError`，`float("nan")/("inf")` 成功 → NaN 穿过 `max(...,0.0)`/`round` → 脏值落库。建议加 `math.isfinite` 守卫。
- **#J21 `advice_engine.py:626` / `:767`** — L0c 持仓期门与软风险仓位调整均为 **`except: pass`**；失败 → 「已延伸信号」仍被当新买点（不降级）、软风险上限**静默放宽**（fail-open，与风控相反）。
- **#J22 `advice_engine.py:497`** — `dims.get('factor', {})` 仅键缺失兜底；`dimensions['factor'] is None` 时 `.get('conflict_items')` 抛 `AttributeError`（同文件他处用 `(x or {})`）。
- **#J23 `radar_service.py:83`** — `cache.get_tags_batch(candidates)` 单条 SQL `IN(...)`，候选数千时占位符爆炸 → 异常吞掉 → **空雷达**。建议分块。
- **#J24 `radar_service.py:241`** — `_evaluate_push_level`：未知 `level` 映射 index 99，**永不超过默认 'normal'** → 高严重度变更被静默降级。建议未知值保守（log+fallback）或显式失败。
- **#J25 `radar_service.py:135`** — `get_watchboard` 的 `name_map = {tc: self._get_stock_name(tc) for tc in ts_codes}` 逐只取名（N+1），**恰是雷达 Top-N 注释声称已消除的模式**。
- **#J26 `time_rhythm_engine.py:72`** — `ref_low/high/mid` 取**近 30 根**，收敛循环走 **60 根** → 第 31-60 根与陈旧 ±5% 带比对 → `consolidation_days` 过/欠计，节奏误判。
- **#J27 `time_rhythm_engine.py:71`** — `threshold = ref_mid*0.05`，`ref_mid<=0` 时阈值 ≤0 → 横盘日恒 0 → 静默误标。建议加 `ref_mid<=0` 守卫。

### 4.3 回测/契约/接口（C 段）
- **#J28 `backtest_minimal.py:143`** — 全胜时 `avg_loss=0` → `profit_factor` 返回 **0.0**（最差），实为**最优**；调参指标误导。
- **#J29 `backtest_minimal.py:146`** — equity curve 对**每一天**复利（含 wait/avoid/reduce 无仓位日）→ `max_drawdown` 实为全窗口 buy&hold 回撤，非策略回撤。
- **#J30 `backtest_minimal.py:123`** — `future_dates` 从 `state_dates`（evaluate 成功日）取，非真实交易日历；某日异常丢弃后 +5 日窗口跨越的真实交易日数不一致（且 O(n²)）。
- **#J31 `backtest_minimal.py:116`** — `close_prices` 键用原始 `trade_date`，而 `daily_returns`/`entry_date` 用 `str(...)[:10]`；列若为 int（`20260901`）则 `close_prices.get` 恒 None → **全部交易被跳过**，胜率/盈亏比静默为 0。
- **#J32 `services/account_risk_status.py:127`** — 连亏序列 `_sells` **无月份边界过滤**（含全部历史卖出），上一月建立的连亏仍可触发本月 `monthly_halt=True`；且遇 `pnl>=0` 即 `break`（零盈亏卖出**错误中断**连亏计数）。
- **#J33 `services/account_risk_status.py:78`** — `loss_pct = round(-month_pnl/asset, 6)` **先舍入再与 0.06 比较** → 边界值可翻转（假停/漏停）。
- **#J34 `routes/opportunity_library.py:125`** — 更新路径**先 `setattr` 后校验** `lib_level`；非法值返回 400 但 ORM 实例已 dirty，**下一次任意请求的 commit 会持久化非法值**（数据损坏路径）。
- **#J35 `routes/opportunity_library.py:87`** — 白名单字段**无类型/None 校验**：`{"lib_level": null}` 可清空列并绕过非法值守卫（falsy），dict/list/str 灌入数值列 → 静默损坏或 flush 报错。
- **#J36 `routes/opportunity_library.py:107`** — 写端点 commit **无 try/except+rollback** → 失败后 session 进入 `PendingRollbackError`，**同 worker 后续请求级联失败**。
- **#J37 `routes/opportunity_library.py:53`** — `search` 未转义 SQL 通配符（`%`/`_`）→ 搜索静默全表返回；且**无分页**（`query.all()`）。
- **#J38 `routes/watchlist.py:230`** — `mf_sorted` 首定义在 `if len(df_mf)>1:`（:211）内，而 `if len(mf_sorted)>=5:`（:230）用**另一独立条件**。**实测可达**：`len(df_mf)==1` 且 `circ_mv>0` 时 `len(mf_sorted)` 抛 `NameError` → 被 `except`（:236）吞 → 该股**全部资金流数据静默丢失**。（注：`if len(df_mf)>1` 与 `circ_mv>0` 两处均会赋值，只有「恰 1 行且 circ_mv>0」落入该窗口。）
- **#J39 `routes/watchlist.py:22`** — `_get_cache()` 每次 `TieredMemoryCache()`（**实测 `memory_cache.py` 无 `__new__`/单例**，:35）→ 每次请求新建空缓存 → **报价缓存永不生效**。
- **#J40 `routes/opportunity_atlas.py:26`** — `_data_manager`/`_tm_cache` 惰性单例 check-then-set **无锁**；多线程 WSGI 下可双构造（DataManager 双开 SQLite、缓存状态丢失）。
- **#J41 `routes/strategy_analyze.py:465`** — `deep_chip[k] = float(tags[k])` 与 `except` 存原始串混存；下游 `deep_chip.get('concentration',0)*100` → str*float **TypeError**。建议统一仅存 float 或格式化加数值守卫。
- **#J42 `routes/strategy_analyze.py:1286`** — `_detect_market_state` 取**任一信号**的 `state` 当「市场状态」喂 `aggregate_v2`（个股策略态冒充市场上下文）。

### 4.4 daemon JUD 工序段（D 段）
- **#J43 `data_daemon.py:~5869`（D:352）** — treemap `DROP TABLE` + `ALTER … RENAME` **两条独立 DDL**（SQLite 各自动提交）；DROP 成功而 RENAME 失败 → **live 表消失、只剩 `_new`**，下游 OUT/QA/前端无快照表。status_snapshot 同模式。建议显式事务或先备份。
- **#J44 `data_daemon.py:~5827`（D:314）** — `max(_safe_float(d.get('close')), 1e-9)`：daemon 的 `_safe_float`（:6317）缺失**返回 `None`** → `max(None,1e-9)` 抛 `TypeError`，被行级 except 吞 → **停牌股静默丢出 treemap**。
- **#J45 `data_daemon.py:~5554`（D:97）** — 逐股富集循环末端 `except: continue` + 内层多处 `except: pass` → 只能靠 `enriched/len(codes)` 计数观察，**无法定位哪只股为何失败**。
- **#J46 `data_daemon.py:6969`（D:848）** — `_verify_out_completeness` 在 OUT done 后**每次驱动都重跑**且**不 return**，无幂等标记（与 QA-CHECK 同轮重复）。

---

## 五、🟡 低危 / 死代码 / 文档（未逐行复核，清单）

- **死代码/裸表达式**：`strategy_analyze.py:746`（`_find_signal(signals,'因子')` 等结果丢弃）、`factor_arbiter.py:145`（`fatal_list and len(fatal_list)>0` 冗余）、`advice_builder.py:21`（`RR_GATE`/`ATR_MULT`/`TARGET_TIERS` 定义但 R:R 门用字面量 `2.0`）、`advice_engine.py:40`（`_apply_stop_and_tiers` 的 `dim_results` 死参）。
- **函数内 import**：`dim_adapter.py:210`（`import re`）、`light_derive.py:133`（`import math`）、`advice_engine.py:214`（本地 import）。
- **静默 except 集群**：`dim_adapter.py:258`、`status_engine.py:196`（情绪池/低流动性读）、`potential_engine.py:110`（earn/fund 截面构建无日志，与 val 块不一致）、`time_rhythm_engine.py:98`（debug）、`tag_extractor.py:58`（pre_feat 回退）、`backtest_minimal.py:97`。
- **性能**：`watchlist.py:430`（`get_cached_daily_data` 逐只 N+1）、`watchlist.py:67`（循环内 import `_get_cache_level`）、`strategy_analyze.py:852`（`dim_states` 重复 `json.loads`）、`radar_service.py:179`（每次 `L4CrossValidator()` 新实例，`get_notifications` 逐项 `diagnose` 无缓存）、`tag_extractor.py:38`（每 extractor 新建 `DataManager`）。
- **文档失真**：`factor_arbiter.py`/`reliability_assessor.py:251`（ATR 阈值 docstring 仍写小数域，实为百分数 → 见 495-B3）；`reliability_assessor.py:257` 注释（507 #S21 已修守卫，注释未同步）。
- **潜在 NaN**：`potential_engine.py:151`（`float('nan')` 通过 try/except → 污染 signal_strength → 非法 JSON `NaN`）。
- **SQL 拼接**：`potential_engine.py:321`（`LIMIT %d` 非绑定参，当前不可注入但应改参）。
- **其它**：`watchlist.py:151`（`pct_chg==-100` 除零 + `0.0` 被当缺失）、`watchlist.py:351`（add 竞态）、`watchlist.py:374`（`Watchlist.query.get` 弃用）、`watchlist.py:439`（daily df 无 name 列 → 看板名空）、`watchlist.py:406`（`dm.cache._query_df` 越层私有 API）、`tag_extractor.py:244`（margin↔close 按字符串 `trade_date` 等值连接，格式不一致则全 miss）、`tag_extractor.py:220`（`tail(5)` 取「最近 5 个非 NaN 值」非「最近 5 交易日」）、`tag_extractor.py:132`（筹码用全历史非近窗）。

---

## 六、⚪ 已排除（误报 / 设计意图 / 待确认）

| 项 | OCR 断言 | 本次核实 |
|----|---------|---------|
| `data_daemon.py:5564` `_compute_opportunity_meta(tags)` 返回值被丢弃 | 静默 no-op，机会元信息未落 | **误报**：该函数（`data_daemon.py:4999`）**原地 `tags.update(profile/type_result/ev/entry/exit)`**，本就无 return——OCR 未读到函数体 |
| `strategy_analyze.py:1036` `_r` NameError | 丢弃整段 verdict（高危） | **降级为死分支**（见 #J1）：`_status_row` 恒含 `advice_params`，该行永不执行 |
| `routes/opportunity_atlas.py:34` `_get_memory_cache` 每次新建缓存 | 缓存不生效 | **误报**：`_get_memory_cache` 有模块级 `_tm_cache` 单例（:34-40）；**真缺陷在 `watchlist._get_cache`**（#J39，无单例） |
| `backtest_minimal.py` `close_col` 缺失 → `KeyError` | 崩溃 | **设计意图**：`if close_col else {}` 使无 close 列时退化空（#J31 键类型问题另计，成立） |
| `strategy_analyze.py:514` `lock_up_ratio: … and 55.0 or 35.0` | 编造数值 | **确凿但属展示层占位**（硬编码 55/35，非实算）——非判定链，列此供登记 |

---

## 七、待业务/口径拍板（5 项）—— **拍板记录（2026-10-06）**

> **Q1~Q4 用户已拍板**（2026-10-06）；**Q5 暂按推荐默认登记**，批次4 开工前再确认。

1. **Q1 C4+ 修复或删除** ✅ **拍板＝修（换独立信号源）**：`dim4` 补产独立枚举字段（如 `retail_tendency ∈ {institutional, retail, mixed, unknown}`，勿用展示文本），`conflict_matrix` C4+ 改读该字段；`_retail_phase`/`judgment.phase` 同源问题不再作为判据来源。**实施注**：dim4 属 SIG 层，补产出键后 JUD 消费对齐（同 490 号 A/B/C 类先例），须同步 dim8/前端枚举映射。
2. **Q2 `final_score` 方向语义** ✅ **拍板＝保留符号语义**：`base_score = consensus_rate × 100`（**不 clamp 负值**），负分落 `_map_score_to_state` 的 `<30 → avoid` 档；Step5 情绪极端修正改为「情绪方向 vs 共识方向」显式冲突比较（同步修 #J5）；`state_evidence` 保留 `base_score` 原始符号供前端解读。
3. **Q3 周线否决范围** ✅ **拍板＝无条件降 wait**：周线 `down` 且 `opportunity_state ∈ {enter, light}` 即降 `wait`（**去掉 `_daily_is_bullish` 门**）；日线不看多时本不应 enter/light，保留门会使错误状态存活；符合《分层决策框架》「丢弃买点」语义。
4. **Q4 signal_strength 量纲** ✅ **拍板＝先量化再修**：实施前先探针量化全市场 `signal_strength` 分布（确认 0-100 域、阈值切分合理性），再把 `cross_validate` 分级改 `80/60/40/20`、日环比改 `≥10`。
5. **Q5 月度风险预算** ⏸ **默认登记（批次4 前确认）**：连亏**严格月份边界**（`_sells` 加 `trade_date >= month_start`）+ 6% **未舍入比较**（`math.isclose` 容差，舍入仅留展示）——符合「月度」语义与 493 P2-d「仅产出标记字段」口径。若用户后续选择「跨月延续」则反转。

---

## 八、与 507 号的去重说明

- **完全重叠（不重复计）**：`cross_validate.py:83` 静默 except、`tag_extractor.py:223` 静默 except、`radar_service.py:62`、`time_rhythm_engine.py:100`、`advice_engine.py:631/778`、`potential_engine.py:350/405`、`light_derive.py:109/129`、`backtest_minimal.py:86/113/237`、`arbiter.py:12/194` 文档、`enum_cn_map.py` 等——本档 §五 已归并标注。
- **本号 JUD 专有新增**：
  - `status_engine` 判定链 #J9~#J12；
  - `factor_arbiter` #J5/#J7/#J16/#J17（507 未列此文件）；
  - `consensus_engine` 新点位 #J13~#J15（与 507 #S4 同族不同点位）；
  - `signal_analyzer` 衰减标定 #J8/#J18/#J19；
  - `cross_validate` 量纲 #J2/#J3（507 未列）；
  - `account_risk_status` #J32/#J33（507 未列）；
  - `watchlist` #J38/#J39、`opportunity_library` #J34~#J37、`opportunity_atlas` 路由 #J40；
  - **daemon JUD 工序段全部 6 项 #J43~#J46（507 完全未覆盖）**。

---

## 九、详细执行计划（2026-10-06 落定，待逐批开工）

### 9.1 总体架构与前置铁律

```
批次0 文档提交 → 拍板 Q1~Q4（已决）→ Q5 批次4 前确认
   ↓
批次1 判定链语义/量纲（拍板已过）    ┐
批次2 判定链健壮性（拍板已过）        ├→ 每批：探针测试→定向回归→行为变更项全市场重跑
批次3 建议/展示层（无拍板依赖，可先开）│
批次4 接口/写路径/单例（含 Q5）      ├→ 每批独立 commit（fix(jud): 509批次N）
批次5 回测（非日终管道，可并行）      │
批次6 daemon JUD 工序段             │
批次7 低危清理（可并行收尾）          ┘
```

**执行前置铁律**：①全量回归前必须停 `data_daemon`（含 `start_daemon.sh` 看守，否则卡 ECM 建表写锁）；②行为变更项必须全市场重跑重定基线 + 受影响既有 fixture 同步评估（同 507 #S4 先例）；③批次实施中发现与既有拍板冲突项 → 先暂缓登记（登记-N），不顺手改。

### 9.2 批次0 — 文档提交（无代码）
`docs(comm): 509号 v1.1 核查档 + 执行计划`：提交 `509-JUD板块OCR核查与处置.md` + `001-目录索引.md`（v1.1）。验证：`git status` 仅 2 文档 + daemon 产物。

### 9.3 批次1 — 判定链语义/量纲（拍板 Q2/Q4 已过；行为变更）

| 项 | 位置 | 改动方向 | 行为变更 | 验证 |
|----|------|---------|---------|------|
| #J2 | `cross_validate.py:1193` | 分级阈值 8/6/4/2 → 80/60/40/20（依 Q4，先量化再改） | 展示层（机会概览 grade） | 探针：0-100 各档断言 |
| #J3 | `cross_validate.py:1824` | 日环比阈值 1.0 → ≥10（依 Q4） | 展示层（日环比 monitor） | 探针：delta 分档断言 |
| #J7 | `factor_arbiter.py:184` | 去 clamp：`base_score=consensus_rate×100`（负分落 `<30→avoid`；依 Q2） | **是**（空头股 final_score/状态映射） | 探针空头/中性/多头三例 + 全市场分布对比 |
| #J5 | `factor_arbiter.py:197` | Step5 改「情绪方向 vs 共识方向」冲突比较（依 Q2） | **是** | 探针：情绪极端×方向组合 |
| #J4 | `reliability_assessor.py:69` | 映射键 `decayed`→`broken` | **是**（L2 可靠性→L3 权重） | 探针：构造 broken 断言 0.2 |
| #J8 | `signal_analyzer.py:165` | 衰减评分标定（各维展开 0-100 或重定 DECAY_LEVELS） | **是**（与 #J4 联动生效） | 探针：`broken` 可达性断言 |

**依赖**：#J2/#J3←Q4；#J5/#J7←Q2。**收尾**：全市场重跑 + opportunity_state/final_score 分布前后对比，重定基线；受影响既有测试同步评估。

### 9.4 批次2 — 判定链健壮性（拍板 Q1/Q3 已过）

| 项 | 位置 | 改动方向 | 行为变更 | 验证 |
|----|------|---------|---------|------|
| #J6 | `conflict_matrix.py:185` | dim4 补产独立枚举字段（Q1）+ C4+ 改读 | 否（原死规则，现可达需重定） | 探针：新字段映射触发 C4+ |
| #J16 | `factor_arbiter.py:227` | 周线 down 无条件降 wait（去 `_daily_is_bullish` 门；Q3） | **是**（状态分布） | 探针：周线 down×日线平/负 |
| #J9 | `status_engine.py:997` | 删不可达 elif；平票 direction 显式化 | 否（死分支） | 定向测试 |
| #J10 | `status_engine.py:827` | L0a `int(direction)` 加 try 守卫（对齐 :830 ST 块） | 否（防御） | 探针：非数值 direction |
| #J11 | `status_engine.py:880` | `_apply_l0` 回退读透传 `asof_date`（get_pre_feat/get_cached_daily_basic/get_cached_daily_data） | 仅回测 | 探针：asof_date 下 L0 读历史快照 |
| #J12 | `status_engine.py:1325` | `json.loads(advice_params)` 加 try 守卫 | 否（防御） | 定向 |
| #J13 | `consensus_engine.py:203` | 全中性族显式返回 `neutral`（非 bull） | 否（group_details 展示） | 探针：全中性族方向断言 |
| #J14 | `consensus_engine.py:336` | `total_dim_count` 移到 None 检查后（分母只计存在维） | **是**（中性占比↑→闸门复活，同 507 #S4 性质） | 探针 + 全市场重跑；**须评估是否连带 494 fixture（enter→wait）** |
| #J15 | `consensus_engine.py:275` | weights=None 时族权重归一化（或修 docstring + 说明 bull/bear_score ×0.1） | 是（绝对分） | 定向 |
| #J17 | `factor_arbiter.py:151` | wait+0 分：返回最低 wait 分 45.0 或文档化 0.0 哨兵 | 否（一致性） | 定向 |

**风险提示**：#J14 与 507 #S4 同族——修复会使「中性占比 >0.6」上限复活，改变 `_aggregate_v390` 输出分布，**须全市场重跑 + 重定基线 + 检查 494 fixture**（先探针量化中性占比现状再决定修法）。

### 9.5 批次3 — 建议/展示层（无拍板依赖，可最先开工）

| 项 | 位置 | 改动方向 |
|----|------|---------|
| #J18 | `signal_analyzer.py:326` | verified 自动提升改独立字段 `auto_verified`（不覆盖调用方确认标记） |
| #J19 | `signal_analyzer.py:139` | volume_ratio 缺失 → 显式 unknown 分支（不落「健康」） |
| #J20 | `advice_engine.py:28` | `_safe_float` 加 `math.isfinite` 守卫（拦 NaN/inf） |
| #J21 | `advice_engine.py:626/767` | 静默 except → warning 日志 + 保守兜底（L0c 门失败不静默放过） |
| #J22 | `advice_engine.py:497` | `(dims.get('factor') or {})` |
| #J23 | `radar_service.py:83` | `get_tags_batch` 候选分块（如 200/批）合并 |
| #J24 | `radar_service.py:241` | 未知 level → log + 保守 fallback（不落 99） |
| #J25 | `radar_service.py:135` | `name_map` 改批量取名（`get_stock_meta_batch`） |
| #J26 | `time_rhythm_engine.py:72` | ref 窗口与循环窗口统一（30 或 60 一致） |
| #J27 | `time_rhythm_engine.py:71` | `ref_mid<=0` 守卫 |

验证：探针 `tests/test_509_jud_batch3.py` + 定向回归（advice_engine/radar/signal_analyzer 相关既有测试）。

### 9.6 批次4 — 接口/写路径/单例（含 Q5）

| 项 | 位置 | 改动方向 |
|----|------|---------|
| #J34 | `opportunity_library.py:125` | 先校验后 setattr（非法值不入 ORM） |
| #J35 | `opportunity_library.py:87` | 白名单字段类型/None 校验（数值列强制 cast、拒 null 于非空列） |
| #J36 | `opportunity_library.py:107` | commit 包 try/except + rollback（防 PendingRollbackError 级联） |
| #J37 | `opportunity_library.py:53` | search 转义 `%`/`_` + 分页（page/page_size 硬上限） |
| #J38 | `watchlist.py:230` | `mf_sorted` 无条件先初始化（`if df_mf.empty` 早退） |
| #J39 | `watchlist.py:22` | `_get_cache()` 改模块级单例（同 `_get_dm` 风格） |
| #J40 | `opportunity_atlas.py:26` | 惰性单例加 `threading.Lock` 双检锁 |
| #J41 | `strategy_analyze.py:465` | deep_chip 统一存 float（或格式化加数值守卫） |
| #J42 | `strategy_analyze.py:1286` | `_detect_market_state` 改真实市场/广度源或标注降级 |
| #J32 | `account_risk_status.py:127` | 连亏序列加 `trade_date >= month_start` 过滤 + 零盈亏跳过不 break（Q5） |
| #J33 | `account_risk_status.py:78` | 未舍入比值比较（`math.isclose` 容差），舍入仅留展示（Q5） |

验证：探针 + 定向（opportunity_library/watchlist/account_risk 既有测试）；Q5 拍板先于 #J32/#J33。

### 9.7 批次5 — 回测（非日终管道，可独立并行）

| 项 | 位置 | 改动方向 |
|----|------|---------|
| #J28 | `backtest_minimal.py:143` | 全胜时 `profit_factor = inf/None`（或兜底大值） |
| #J29 | `backtest_minimal.py:146` | equity 只按实际持仓日复利（enter 至 exit） |
| #J30 | `backtest_minimal.py:123` | `future_dates` 从全量 df 交易日历取 + 预计算索引（消 O(n²)） |
| #J31 | `backtest_minimal.py:116` | `close_prices` 键与 `daily_returns` 同归一（`str(...)[:10]`） |

验证：探针（构造全胜/含 wait 日/日期格式混合三例）+ 定向回归。

### 9.8 批次6 — daemon JUD 工序段

| 项 | 位置 | 改动方向 |
|----|------|---------|
| #J43 | `data_daemon.py:~5869` | treemap/status 表 DROP+RENAME 包显式事务（或先备份再 rename） |
| #J44 | `data_daemon.py:~5827` | treemap close 缺失守卫（`_safe_float(...) or 0` 后判 0 跳过/落 None） |
| #J45 | `data_daemon.py:~5554` | 富集循环异常改 warning（带 code+msg），保留 continue |
| #J46 | `data_daemon.py:6969` | `_verify_out_completeness` 加 once-guard（pipeline_status 已 done 则跳过） |

验证：探针 + `data_daemon` 语法/导入检查（**不在 daemon 运行时做全量回归**）。

### 9.9 批次7 — 低危清理（可并行收尾）

- **死代码/裸表达式**：#J1（`strategy_analyze.py:1036` `_r` 死分支删）、`factor_arbiter.py:145` 冗余条件、`advice_builder.py:21` RR_GATE 引用化、`advice_engine.py:40` 死参。
- **函数内 import**：`dim_adapter.py:210`、`light_derive.py:133`、`advice_engine.py:214`。
- **静默 except 加日志**：`dim_adapter.py:258`、`status_engine.py:196`、`potential_engine.py:110`、`time_rhythm_engine.py:98`、`tag_extractor.py:58`、`backtest_minimal.py:97`。
- **性能**：`watchlist.py:430`（批量 daily）、`strategy_analyze.py:852`（重复 json.loads）、`radar_service.py:179`（L4 实例缓存）、`tag_extractor.py:38`。
- **NaN/SQL/其它**：`potential_engine.py:151`（NaN 守卫）、`potential_engine.py:321`（LIMIT 绑定参）、`watchlist.py:151/351/374/406/439`、`tag_extractor.py:244/220/132`、文档失真（`reliability_assessor.py:251` 等）。
- 验证：每项 `py_compile` + ruff 零新增 + 定向。

### 9.10 验证口径与提交策略

| 环节 | 口径 |
|------|------|
| 每批单元验证 | `py_compile` + `ruff check`（零新增，对照基线：data_daemon 38 / dim6 1 F841） |
| 每批测试 | 新增探针 `tests/test_509_jud_batchN.py`（N=1~7）+ 相关既有测试定向回归 |
| 行为变更项 | **全市场重跑**（daemon JUD 单步或 sig_full_test）+ opportunity_state/final_score/中性占比分布前后对比 + 重定基线 |
| 全量回归 | **先停 `data_daemon`**（含 start_daemon.sh 看守）→ `pytest tests/`（当前基线 2146 passed @508）→ 跑完重启 daemon |
| 提交粒度 | 批次0 `docs(comm)`；每批 `fix(jud): 509批次N …`；收官后一次推送（同 507/508 先例） |
| 冲突登记 | 实施中发现与既有拍板冲突项 → 先暂缓登记（登记-N），不顺手改 |

### 9.11 风险与待定登记

1. **#J14 中性闸门复活**（同 507 #S4 性质）→ 全市场 opportunity_state 分布变化，可能连带 494 fixture（enter→wait）——**最高风险项**，先探针量化再决定。
2. **#J7/#J5 final_score 语义变更** → 前端分数/状态展示变化（Q2 已定保留符号语义）。
3. **#J32 月份边界** → monthly_halt 触发时机变化（Q5 默认登记，批次4 前确认）。
4. **#J43 原子交换** → 涉及日终落库路径，须 daemon 停后验证 + 次日夜盘观察。
5. **Q5**：未拍板，默认「严格月份边界 + 未舍入比较」，批次4 开工前再确认。

---

## 十、维护记录

- **v1.0（2026-10-06）**：只读核查档落档。OCR 4 段扫 ≈105 条 → 人工实证归并；未改任何代码/配置/方案。
- **v1.1（2026-10-06）**：用户「结合 509 制定详细执行计划」→ 拍板 Q1~Q4（Q5 默认登记）→ 落 §九 详细执行计划（9.1~9.11）+ §七 拍板记录。仍**未改任何代码/配置/方案**。
- **v1.2（2026-10-08）批次3 实施**（commit `63b20d8`）：
  - **批次0**：文档提交 `2bdc05b`（509 v1.1 + 索引）。
  - **#J18** `signal_analyzer.calc_lifecycle_stage` 自动验证 → 新增 `auto_verified` 来源标记（verified 语义不变）；
  - **#J19** `detect_decay` volume_ratio 缺失/为空 → 显式未知 20（原默认 1.0 误报健康）；
  - **#J20** `advice_engine._safe_float` 拦 NaN/inf（`math.isfinite`）；
  - **#J21** L0c 门 + 软风险仓位 静默 `except: pass` → `warning` 日志（语义不降级）；
  - **#J22** `_build_advice_card_fields` factor=None 兜底 `(dims.get('factor') or {})`；
  - **#J23** `radar_service.get_radar_signals` get_tags_batch 分块 200 合并（候选上千占位符超限）；
  - **#J24** `_evaluate_push_level` 未知 level → 显式告警按 normal 参与（原静默 99 永不升顶）；
  - **#J25** `get_watchboard` 批量取名 `get_stock_meta_batch`（消逐只 N+1，失败回退逐只）；
  - **#J26/#J27** `time_rhythm_engine` 参考区间与比对窗口统一近 30 根 + `ref_mid<=0` 守卫；
  - **探针** `tests/test_509_jud_batch3.py`（12 断言）；**适配** `test_507_batch7`（#J23 分块后 fake 强度须按股票代码而非批内索引）；
  - **验证**：`py_compile` OK、ruff 零新增（含 507 遗留 F841/I001 顺手清理）、定向 23 passed、**全量 2158 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.3（2026-10-08）批次5 实施**（commit `70f79db`）：
  - **#J28** 全胜（无亏损）`profit_factor=None`（理想无穷），区分「无交易 0.0」（原恒 0.0 误示最差）；
  - **#J29** equity curve 只在持仓日（enter/light）复利，空仓（wait/avoid/reduce）日净值不变——消除 buy&hold 全窗口回撤失真；
  - **#J30** 前向窗口按**真实交易日历**（全量 df，含 evaluate 失败日）取第 5 个交易日，不再依赖 state_dates（evaluate 成功日）；预计算索引消 O(n²)；
  - **#J31** `close_prices` 键与 `daily_returns`/`entry_date` 同归一（`str(...)[:10]`）——trade_date 为 Timestamp/int 时不再全部交易被跳过；
  - **探针** `tests/test_509_jud_batch5.py`（5 断言，mock StatusEngine）；
  - **验证**：ruff 零新增、定向 18 passed + 4 xfailed（既有）、**全量 2163 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.4（2026-10-08）批次7 实施**（commit `ee12746`）——§五 低危清理清单：
  - **#J1** `strategy_analyze` `_r` 死分支删除（不可达 NameError 残留）；
  - **死代码/裸表达式**：`factor_arbiter` 冗余 `and len(...)>0` 删、`advice_builder` R:R 门字面量 2.0 → `RR_GATE` 常量、`advice_engine._apply_stop_and_tiers` 死参 `dim_results` 移除（连带适配 test_493/test_494 旧签名）、`strategy_analyze` 裸表达式 `_find_signal('因子')` 删 + 重复 `logger` 删；
  - **函数内 import 上移**：`dim_adapter` `import re`、`light_derive` `import math`、`advice_engine` `_weekly_dir_from_multi_level`；
  - **静默 except 加日志**：`dim_adapter` 周线读、`status_engine` 市场池、`potential_engine` earn·fund 截面、`tag_extractor` pre_feat 兜底；
  - **NaN/SQL/其它**：`potential_engine` val/roe NaN·inf 守卫 + `LIMIT` 绑定参、`watchlist` pre_close 除零守卫 + `query.get→db.session.get` + add 并发竞态回滚 + dashboard 批量取名（daily df 无 name 列）、`strategy_analyze` dim_states 单次解析 + deep_chip concentration 数值化 + 惰性日志、`radar_service` L4 实例缓存、`reliability_assessor` docstring ATR 阈值语义修正；
  - **探针** `tests/test_509_jud_batch7.py`（13 断言）；
  - **验证**：ruff 零新增、定向 67 passed、**全量 2176 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.5（2026-10-08）批次6 实施**（commit `9ca793f`）——daemon JUD 工序段：
  - **#J43** `_build_treemap_snapshot`/`_build_status_snapshot` 原子切换：`DROP+RENAME` 两条独立 DDL（DROP 成功而 RENAME 失败会丢 live 表）→ **RENAME 备份 → RENAME live → 删备份**（任一步失败旧表仍可恢复，首次无旧表 try 兜底）；
  - **#J44** treemap `close` 缺失（停牌等）时 daemon `_safe_float` 返回 None → `max(None, 1e-9)` 抛 TypeError 被吞 → 该股**静默丢出 treemap**；改为先取 `_close_f`、None 时 amplitude 落 None（保留该股行）；
  - **#J45** `_jud_enrich_with_meta` 逐股富化 3 处内层静默 `except`（opportunity_meta/right_side_confirm/potential）+ 外层 `continue` 加**带 ts_code 的 warning/debug 定位日志**；
  - **#J46** `_verify_out_completeness` once-guard：pipeline_status 本日已 `OUT-CHECK done` 则跳过（原每次驱动重跑全表 COUNT）；
  - **探针** `tests/test_509_jud_batch6.py`（5 断言，AST/源码级——daemon 运行期不做全量回归）；
  - **验证**：py_compile OK、ruff data_daemon 零新增（40 均基线既有）、**全量 2181 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.6（2026-10-08）批次1 实施**（commit `8e65e61`）——判定链语义/量纲（行为变更批）：
  - **探针量化先行**（`scripts/_509_b1_probe.py`，Q4「先量化再修」）：① signal_strength **0-100 域实证**（11144 条 min0/max92/mean28.7；现状分级恒 A+ 52.4% vs 拟改 7.0%）→ **#J2 改 80/60/40/20**；② **空头共识 75.12%**（4173/5555，域 [-1,-0.5]，final_score==0 达 73.57%）→ **#J7 去 clamp**；③ decay 实测 **max=22 全 healthy**（broken 不可达实证）→ **#J8 评分标定**；④ maintenance.status **100% healthy**（'decayed' 键命中 0）→ **#J4 键错位实证**；
  - **#J2** `cross_validate._build_opportunity_summary` 分级 8/6/4/2→80/60/40/20；
  - **#J3** 日环比 signal_strength 阈值 ±1.0→±10.0（0-10 量纲残留）；
  - **#J4** `reliability_assessor._assess_signal` 映射键 `decayed`→`broken`（Q2 拍板后 broken 可达才生效，与 #J8 同批）;
  - **#J5** `factor_arbiter` Step5 情绪极端修正：原两分支等价 ×0.85 → **显式「情绪方向 vs 共识方向」冲突比较**（方向一致不修正；Q2 拍板）；
  - **#J7** `factor_arbiter` Step2 去 clamp `[0,1]` **保留符号语义**：`base_score=consensus_rate×100`，负分落 `<30→avoid`；末段只钳上限 ≤100（不再 max(0,...)）；
  - **#J8** `signal_analyzer.detect_decay` 各维评分展开 **0-100 全域**（price_trend 0/35/80、volume_price 20/50/100、volume_energy 15/35/55/85、chip_change 10/35/100、main_force 10/40/90）→ overall 上限约 96，**broken(70+) 可达**；
  - **适配**：`test_495_b2_jud_market_gate` H3 final_score 域 `[0,100]→[-100,100]`（脚本+测试同步）、`test_509_jud_batch3` #J19 分值 20/50/10→35/85/15；
  - **全市场重跑**（495-B2 门禁，5554 只）：**门禁全 PASS**；**五档分布零漂移**（avoid 83.3 同基线，enter 0.2/light 0.3/wait 10.5/reduce 5.6）——#J7 语义修正未改状态分布（空头本就在 avoid），仅 final_score 由 0 变负（前端语义正确化）；
  - **探针** `tests/test_509_jud_batch1.py`（10 断言：#J2 档位边界 / #J3 源码阈值 / #J4 broken=0.2 / #J7 负分 avoid·正分 enter / #J5 冲突罚·一致不罚·弱情绪不罚 / #J8 broken 可达·healthy 低分）；
  - **验证**：ruff 零新增、全量 **2191 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.7（2026-10-08）批次2 实施**（commit `33cb9f1`）——判定链健壮性（10 项）：
  - **#J14 探针量化先行**（`scripts/_509_j14_probe.py`，全市场 5554 只）：**OCR 原判与数据流不符**——`convert_to_factors` 恒返回 13 键（辅助维恒有产出 direction=0），`score is None` 永不触发，「total_dim_count 缺失维弱化闸门」不成立；**真缺陷**=6 辅助维（time/position/signal_confirm/finance/event/factor）恒中性计入 neutral_ratio 分母 → 闸门（>0.6 cap 0.5）过度触发、共识幅值被压扁（>0.6 触发 786 只，排除辅助维后 236 只，约 550 只 consensus_rate 被压到 ±0.5）；**用户拍板方案 B**；
  - **#J6**（Q1 拍板）：dim4 补产**独立枚举 `retail_tendency`**（distribution/institutional/neutral，phase×fund_flow 组合判定），conflict **C4+ 改读该字段**（原 retail_institution 展示文本与 phase 同源互斥致规则恒不可达）——跨 SIG 补产出（同 490 先例）；
  - **#J9**：legacy `_aggregate` 平票（bull==bear>0）判 **neutral**（原恒 'bearish' + `elif bull==bear and bull>0` 死分支合并）；
  - **#J10**：`_apply_l0` L0a `int(e.get('direction'))` 加 try 守卫（非数值不再中断整个 L0）；
  - **#J11**：`_apply_l0` 新增 **asof_date** 透传，回退读 get_pre_feat/get_cached_daily_basic 按日期（回测消除前视）；
  - **#J12**：`_assemble` `json.loads(advice_params)` 加守卫（非 JSON 重建空 dict 不中断）；
  - **#J13**：`merge_family` 全中性族判 **neutral**（原 tie-break `bull_strength>=bear_strength` 恒真误标 bull）；
  - **#J14**：neutral_ratio **只统计 7 主判定维**（signal/structure/vp/chip_fund/emotion/risk/valuation）；辅助维仍参与族方向归并、不计中性占比；`total_dim_count` 同步移到 None 检查后；
  - **#J15**：`_family_regime_weight` weights=None/空 → **1.0**（原 0.1 使 bull/bear_score ×0.1 缩放，docstring「退化纯 STATE_WEIGHTS」不符；仅影响回退路径）；
  - **#J16**（Q3 拍板）：周线 down 且 enter/light → **无条件降 wait**（去 `_daily_is_bullish` 门 + 删死函数）；
  - **#J17**：fatal_to_veto 强制降级 wait 用 **45.0**（wait 档下界；原 0.0=avoid 档内部矛盾）；
  - **探针** `tests/test_509_jud_batch2_{j6,j14,j16,misc}.py`（24 断言）；**适配** test_490（C4+ 加 retail_tendency）/test_492（_apply_l0 签名）/test_494（周线无条件降）旧行为断言；
  - **全市场重跑** 5554 只门禁全 PASS（avoid 83.3→80.6 容差内，#J14 幅值恢复：约 550 只从 avoid 回升 wait/reduce/enter）；
  - **验证**：ruff 零新增、全量 **2215 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **v1.8（2026-10-08）批次4 实施**（commit `7acf6b5`，接口/写路径/单例）——**Q5 已拍板**（2026-10-08 用户「按默认推荐开工批次4」= 严格月份边界 + 6% 未舍入比较）：
  - **#J34** `opportunity_library` update **先校验后 setattr**：`_coerce_field` 将 lib_level **域校验前置**（null/非法档位在 setattr 前拦截，非法值不入 ORM；原 setattr 后校验→400 时 ORM 已 dirty，下一次任意请求 commit 会持久化非法值）；
  - **#J35** `opportunity_library` 白名单字段**类型/None 校验**：数值列（Integer/Float 共 13 列）强制 cast、拒 null/bool/dict/list；字符串列非 None 统一转 str；lib_level null 拒（原 `{"lib_level": null}` falsy 绕过守卫清空列）；
  - **#J36** `opportunity_library` 三写端点（create/update/delete）commit 包 **try/except + rollback**（防 PendingRollbackError 级联污染同 worker 后续请求）；
  - **#J37** `opportunity_library` list search **转义 `%`/`_`**（`ilike(..., escape='\\')`）+ **分页**（page/page_size，page_size 硬上限 100，返回 total 为过滤后总数）；
  - **#J38** `watchlist` `mf_sorted` **无条件先初始化**（`df_mf` 非空即 `sort_values`；原仅 len>1 分支定义，恰 1 行且 circ_mv>0 时 `len(mf_sorted)` 抛 NameError 被吞→该股资金流全量静默丢失）；
  - **#J39** `watchlist` `_get_cache()` 改**模块级单例**（原每次 `TieredMemoryCache()` 新建空缓存→报价缓存永不生效）；
  - **#J40** `opportunity_atlas` 惰性单例（`get_data_manager`/`_get_memory_cache`）加 **`threading.Lock` 双检锁**（原 check-then-set 无锁，多线程 WSGI 下可双构造）；
  - **#J41** `strategy_analyze` deep_chip **统一仅存 float**（无法数值化不混存原值；原 except 存原始串→下游 `*100` str*float TypeError；批次7 消费端守卫保留）；
  - **#J42** `strategy_analyze` `_detect_market_state` **改读真实 `market_state` 字段**（信号顶层，SignalComputationService 由大盘指数识别；多数投票，与 ai_analysis 一致）；无真实源 → 诚实 `UNKNOWN`（原取 `status_recognition.state` 个股策略态冒充市场上下文）；
  - **#J32**（Q5）`account_risk_status` 连亏序列 **严格月份边界**（`_sells` 加 `trade_date >= month_start` 过滤）+ **零盈亏跳过不 break**（原 `pnl>=0` 即 break 错误中断连亏计数）；
  - **#J33**（Q5）`account_risk_status` **6% 未舍入比较**（`raw_loss_pct = -month_pnl/asset` 直接与上限比较 + `math.isclose` 容差兜浮点误差；舍入仅留展示——原先 `round(...,6)` 再比较，边界值可翻转假停/漏停）；
  - **探针** `tests/test_509_jud_batch4.py`（17 断言：#J33 未舍入不误停·精确6%回归·isclose 边界 / #J32 零盈亏不 break（mock Trade）+ 月份边界源码断言 / #J35/#J34 `_coerce_field` 数值·字符串·lib_level 域校验 / #J36 rollback 源码断言 / #J37 转义+分页源码断言 / #J39 单例 / #J38 单行 moneyflow 资金流不丢 / #J40 双检锁单例+源码 / #J41 deep_chip float-only / #J42 多数投票+诚实降级）；**适配** test_493（纯函数行为不变回归，13 断言全绿）；
  - **验证**：ruff 零新增、全量 **2232 passed / 2 skipped / 9 xfailed 零失败**（daemon 停后跑，已重启）。
- **🏁 509 号全面收官**：批次0~7 全部实施（本号核查范围所有确凿缺陷已闭环），v1.8 落档 + 索引登记 + 已推送。**遗留候选（非本号范围）**：`generate_seven_dim_from_signals` 旧体（删需同步改 test_436）、前端阶段 479-7 / 439-A-2、508 后续。
