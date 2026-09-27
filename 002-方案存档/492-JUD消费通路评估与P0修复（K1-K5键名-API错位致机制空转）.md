# 492号 ｜ JUD 消费通路评估与 P0 修复（五处键名/API 错位致机制空转）

**版本**：v1.0（2026-09-27）
**定位**：JUD 改造阶段的**评估 + P0 事实层修复**号。承接 489/490/491（SIG→JUD 契约链路），首次对「JUD 自身」的五条消费通路、定位符合度与 Wiki 知识库一致性做全面核查，并实施 P0 批次修复。
**知识库权威源**：`/Users/kalence/Desktop/未命名文件夹/A股研究/wiki/concepts`（854 篇）。
**基线**：HEAD `887e3ea`（= origin/main）→ 本号 P0 实施后 `a599779`。
**性质**：§一~§五 为**只读核查**（含 4 次只读动态探针）；§六 为**已实施**修复；§七~§八 为待办与登记。

---

## 一、JUD 五条消费通路（实测拓扑）

SIG 产出唯一入口 = `strategy_signal_detail.dim_results_json`
（键：`signal/structure/volume_price/chip_fund/emotion/risk/valuation/signal_analysis`）。

```
dim_results_json ──► StatusEngine.evaluate(ts_code, dim_results)
 ├─① dim8 总结  Dim8SummaryEngine.evaluate → dim_engine_results['summary']
 ├─② legacy dims 层  _convert_to_dims_format → dims(+light 由 light_derive 派生)
 │              → _apply_l0 → _aggregate → dim_states / status_bar / opportunity_state
 ├─③ v390 主管线  _aggregate_v390 → L1 dim_adapter → L2 reliability_assessor
 │              → L3 consensus_engine → L4 conflict_matrix → L5 factor_arbiter → L6 advice_engine
 ├─④ _detect_registered_signals → hits → status_snapshot.signals（列）
 └─⑤ 落库回灌  cross_validate 读 dim_engine_results → 机会图谱诊断弹窗
```

**落库**：`status_snapshot`（分库 snapshot_cache.db），列含
`dim_states/status_bar/opportunity_state/consensus_rate/direction/l0/advice_params/dim_engine_results/signals`。
**前端读取**：`routes/strategy_analyze.py` → `status_verdict`（白名单，**不含 dim_engine_results**）+ `seven_dim_report` + `status_snapshot`。

---

## 二、通路合理性评估（问题 P1~P4）

| # | 问题 | 证据 | 质量影响 | 级别 |
|---|---|---|---|---|
| **P1** | ① 与 ③ **各自实现共识/冲突/状态条，口径不同** | dim8 共识=灯色×置信度（`dim8_summary_engine._calc_consensus_rate:198`）；v390 共识=族可靠性×STATE_WEIGHTS（`consensus_engine.compute`）。dim8 8 态状态条（`_derive_status_bar`）vs `status_engine._status_bar` 5 态 | 同票双结论；前端 status_bar（②）与 opportunity_state（③）可矛盾 | 🔴 |
| **P2** | ② 与 ③ **无因果关系** | ② 的 `dims.light` 全由 `light_derive` 派生；v390 不读 dims。`_apply_l0(dims)` 形参实测未被使用 | 展示结论与判定结论各自独立 | 🟠 |
| **P3** | ③ 内部 **3 处参数形同虚设** | 见 §六 K1/K2/K3 | 判定管线未按设计生效 | 🔴 |
| **P4** | ④ 产物**无消费者**；⑤ **重复 evaluate** | `status_snapshot.signals` 全仓无读取方；`cross_validate._get_status_verdict` 内部实时重算（违背 373 号「优先读快照」） | 无效落库 + 性能/一致性风险 | 🟡 |

**结论**：通路划分方向正确，但**非单一判定链**。建议明确 ①/②=展示层、③=判定层的单一边界（或让 ② 消费 ③ 结果）。**属 P1 结构问题，未在本号实施**（见 §七）。

---

## 三、消费悬空/降级可对接性

- **可接（能力缺口，未实施，见 §八）**：dim3 `health_score`/`judgment.score` → L2 量价可靠性第二源；dim6 `liquidity_avg_amount_wan`/`circ_mv_wan` → L2/L6。
- **可接（降级/失效，本号已实施）**：K1~K5（§六）。
- **不必接（语义冗余）**：dim2 `vs_chip`/`buy_sell_points`/judgment.`position`、dim5 `stock`、dim6 `atr_14d`/`event_count`/`event_summary`/`support_resistance`、dim7 judgment 嵌套副本。
- **注意**：489 的「dim3 direction 恒 0 / dim5 strength 恒 0 / dim7 direction 恒 0 / L2 三维恒 0.5」**经 490/491 已不成立**，勿按旧结论重复补产出。

---

## 四、JUD 定位符合度（①现状判定 ②操作建议）

**结构符合**：① = dim_states / status_bar / opportunity_state / final_score / semantic_type / consensus_rate / conflict_evidence；② = L6 `compute_advice`（仓位/止损/目标/盈亏比/失效条件）。

**缺口**（对照 Wiki《操作建议卡》10 字段）：

| Wiki 字段 | v390-L6 | 缺口 |
|---|---|---|
| ①操作动作 | opportunity_state + 前端 `_map_action_label` 5 档 | ✅ |
| ②信号灯 | 无（灯在展示层） | 🟡 |
| ③入场区间 | `entry_zone`（**曾被白名单截断**，K4 已修） | ✅ |
| ④建议仓位 | `max_position_ratio` + `risk_budget_position`（**曾恒 None**，K1 已修） | ✅ |
| ⑤第一/第二目标 | `target_price` 单目标 | ⚠️ 缺第二目标 |
| ⑥止损位 | `stop_loss_price`（=dim6 支撑位） | ✅ |
| ⑦预期持有 | **缺失**（`_build_expected_holding` 存在但 L6 未调用） | ❌ |
| ⑧触发条件 | **缺失** | ❌ |
| ⑨失效条件 | `invalidation_conditions` | ✅ |
| ⑩置信度与依据 | 无（在展示层 `advice_builder`） | ⚠️ |

**另有**：完整建议由前端 `advice_builder.build_operation_advice` 用**实时五维**（非 v390 判定）补齐 → **建议与判定「半脱钩」**。

---

## 五、Wiki 知识库对照

### 5.1 符合（骨架对齐，勿改）
多指标共识 ≥2/3（`enter_threshold=0.67`）、红绿灯三色（`light_derive`）、信号降级（≥2 维反向→观望）、PIERS 硬否决、结构止损、BOCIASI 快慢线共振确认、情绪仓位联动参数（值逐条对齐 yaml）。

### 5.2 缺口（含本号已修）
| # | Wiki 要求 | 系统现状 |
|---|---|---|
| **W1** | 情绪周期决定仓位上限与状态权重 | **三处键错位**（K2/K3）——**本号已修** |
| **W3** | 市场状态依赖加权法生效 | `weights` 形参未被使用——**本号已修**（K3） |
| **W4** | 2% 风险预算（朗德里公式） | 恒失效（K1）——**本号已修** |
| **W5** | 操作归一化 80/65/45/30/0 档 | 系统档位 70/55/30（「果」侧，见 §八 P2） |
| **W6** | 月度风险预算 6% | v390 无实现 |
| **W7** | 操作建议卡第⑦/⑧字段 | L6 未产 |
| **W11** | 多周期「大级别优先」裁决 | 有一致性加成，无大级别否决 |
| **W13** | 分批止盈 50/30/20、结构/ATR 取较高值 | v390 无分批止盈 |
| **W16** | 综合状态条四档（规则引擎派生） | 状态条双口径（P1） |
| **W10** | 判定有效性需 50+ 样本回测 | v390 无真实数据端到端验证（test 全 mock） |

### 5.3 Wiki 自标内部矛盾（引用须注意）
① 高潮期 80% 上限 vs 减仓 2-3 成；② 冰点「逆向重仓」vs「10%/空仓」；③ 信号生命周期措辞冲突。

### 5.4 Wiki 明确「未找到」（**不应作核查基准**）
「机会分级」独立体系；「高共识+接近前高」裁决规则（系统 `semantic_type='追高警示型'` 为自创）；「共识度→仓位」公式；「红绿灯↔PIERS 否决」映射表。

---

## 六、P0 实施：K1~K5（已提交 `a599779`）

用户对两处判定语义点的拍板：
- **K2/K3 情绪阶段口径 = 「就近归并现有键」**（sprout→recovery、ferment→positive、regression/neutral→normal；不新增键、不改既有权重值）；
- **K3 市场状态权重 = 「接线融合（激活既有设计分支）」**（先例 490）。

| 项 | 缺陷根因 | 修复 |
|---|---|---|
| **K1** | `advice_engine.py:64-75` 回退 `_dm.cache.get_latest_daily`（**ECM 无此方法、全仓零定义**）→ `risk_budget_position` 恒 None；且 `_assemble` 白名单不含 `risk_budget_position` | 改为**纯计算层**（entry_price 由 `status_engine._aggregate_v390` 经 `self.dm.get_cached_daily_data` 取好后传入，与 `:560` 同源）；白名单补 `risk_budget_position` |
| **K2** | `status_engine.py:671` 读 `tags['emotion_phase']`（RAW 无生产者，真实键 `sentiment_phase`）→ `emotion_position_cap` 恒 normal=0.60 | 新增 `_normalize_emotion_phase` SSOT；L0b2 改读归一化阶段 |
| **K3** | `consensus_engine.compute` 的 `weights` 形参**函数体内从未被使用** → MARKET_REGIME_WEIGHTS 恒不生效；L3 情绪阶段键错位（同 K2） | 新增 `_family_regime_weight`（维度权重→族权重归并）；`effective_weight = STATE_WEIGHTS[阶段] × 族regime权重`；`weights=None` 时等权退化、与旧行为等价；L3 改用同一 SSOT |
| **K4** | `status_engine.py:1065` `_assemble` advice 白名单不含 `entry_zone`/`target_zone`（L6 已读到 dim3 真实值） | 白名单补两键 |
| **K5** | `dim_adapter.py:613` `classify_attribute(dims, …)` 中 **`dims` 未定义** → 恒 NameError → `signal_confirm` 永久走 except（evidence 恒空、7 类信号属性判定从未参与） | 按各维真实契约键构造 dims（复用 `status_engine._dim_state_for_signal` SSOT，vp 键对齐） |

**验证**：
- 新增 `tests/test_492_jud_k1_k5.py`（11 用例）；
- dim/JUD 定向回归 **329 passed / 0 failed**；ruff 新增代码零告警；py_compile 通过；
- 真实数据 8 股探针 `scripts/_492_jud_k_probe.py`：**K1 7/8**（1 只缺 dim3 区间/止损）、**K2 8/8**、**K3 7/8**、**K4 7/8**、**K5 8/8**。

---

## 七、待办（P1 结构）

1. **消除双判定口径（P1）**：dim8 自算共识/冲突/状态条 vs v390——选定单一权威，或让 ②/dim8 消费 ③ 结果。
2. **通路定位收敛（P4）**：④ `status_snapshot.signals` 或接前端或停落库；⑤ `_get_status_verdict` 改读 `status_snapshot` 成品（不实时重算）；`_apply_l0(dims)` 未用形参清理。
3. **K3 后须全链路复跑**：权重与情绪阶段语义已变，按 445 保留口径须补真实数据端到端验证。

---

## 八、登记（P2 判定阈值/「果」层，须独立号 + 知识库依据 + 全链路验证）

| 项 | 内容 |
|---|---|
| **P2-a** | L5/L6 操作归一化阈值档位对齐 Wiki（80/65/45/30/0）；`factor_arbiter._THRESHOLDS`(70/55/30) 与 `compute_advice`(0.6/0.4/0.1/0) |
| **P2-b** | R:R 门禁：Wiki《R-R筛选规则》要求 **<2:1 放弃**；系统仅 `<1.0` 降 wait（`advice_engine:498`、`apply_advice_params rr_gate=1.0`）；dim6 评级 1R-2R 记「可考虑」 |
| **P2-c** | 冰点语义细分「冰点期 vs 冰点末期」（Wiki 明确冰点末期才是开仓窗） |
| **P2-d** | 月度风险预算 6% 与连续亏损停机（W6） |
| **P2-e** | 分批止盈 50/30/20、结构/ATR 止损取较高值（W13） |
| **P2-f** | 多周期「大级别优先」过滤（W11） |
| **P3** | L6 补齐操作建议卡缺项（②灯/⑤第二目标/⑦预期持有/⑧触发条件/⑩依据与置信度） |
| **P3** | dim3 `health_score`/judgment.`score`、dim6 流动性明细接 L2 |

**「因为/所以」链完整性（437 口径）**：本号 P0 属「因」侧（键名/API/契约），按 445 Freeze-vs-Fact 与「引擎锁定阶段收窄」口径**应修**；§八 P2 属「果」侧（阈值/权重语义），须独立号。

---

## 九、影响面与回滚

- **影响**：JUD v390 判定输出（L3 权重、L0b2 情绪仓位上限）实际生效；`advice_params` 新增 `entry_zone`/`target_zone`/`risk_budget_position`；`signal_confirm` 因子不再恒走兜底。
- **回滚**：`git revert a599779`；K3 `weights=None` 分支保留旧行为等价路径。
- **daemon 运行态**：核查期间曾按研发阶段规则停 daemon（跑真实探针），完成后已恢复（看守 + 单实例）。
