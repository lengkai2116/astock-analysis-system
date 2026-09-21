---
title: 464-17 主力识别核查（capital_nature 打点 + main_force_presence 证据 + 阶段引擎主力锁定前置）
type: 核查方案（2026-09-21 由 464-13 拍板拆分——先立新号核查主力识别根基，464-13 置信门槛随核查结论一起定）
date: 2026-09-21
version: v1.1（2026-09-21 三方向拍板 + 实施完成）
status: ✅ 已实施（三方向全部落地，135 测试全绿；464-13 置信门槛待 daemon 重算后重估）
related:
  - 464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）——464-13 由本号承接（置信门槛后置）
  - 313-统一阶段判定引擎设计——main_force_presence「行为证据主导」设计源
  - 298-统一阶段判定引擎设计——阶段引擎四规则设计源
  - 460-取数一致性 / 442-SIG富字段系统性缺失——capital_nature 链路背景
---

# 464-17｜主力识别核查（464-13 前置）

> **背景**：464-13（audit「主力阶段」置信门槛）拍板时用户提出核心质疑——"主力阶段识别的前提是是否锁定为主力；主力能否精准识别是关键，如果主力识别有问题，阶段就不会对"。要求先核实系统主力识别实际配置。**拍板结论：先立本号核查主力识别，464-13 置信门槛随本号结论一起定（不孤立拍板）**。

## 一、数据实证（2026-09-18 全市场 5550 只，pre_feat depth 组直读）

| 字段 | 分布 | 问题 |
|---|---|---|
| `capital_nature` | **hot_money 5334 (96%) / institutional 仅 69 (1.2%) / unknown 147** | 主力资金属性识别区分度**基本失效** |
| `main_force_presence` | **'none' 5550/5550 (100%)** | 主力在场证据**从未触发** |
| 阶段判定 vs 主力证据 | **4572 只有阶段判定，100% 无主力在场证据** | 阶段引擎在无主力锁定前置下产 building/lifting/distributing |

## 二、代码链核查（已确认）

1. **capital_nature 生产**（framework `MainForceScorer.get_tags` → data_daemon:3480 depth ②）：`_score_lhb` 打分后——`>=0.5→institutional / >=0.2→hot_money / >-0.5→hot_money / else→unknown`。**无龙虎榜数据 lhb_score≈0 → 落 hot_money**（2026-08-10 修复"轻微怀疑给 hot_money 保留区分度"所致）→ 96% 全标游资。龙虎榜本属稀疏数据（437-A 实证 ~90% 无记录），"无证据"被误标为"游资"而非"unknown"。
2. **main_force_presence 生产**（data_daemon `_compute_main_force_presence` :4657）：三种行为证据——①LHB 近 30 日有席位→strong；②股东户数环比减少≥5%→moderate；③融资余额 30 日增幅>50%→risk。**全部极严格/依赖稀疏数据** → 全市场 none。
3. **main_force_presence 消费**：仅 3 处且全是 `=='none'` 的风险提示条件（status_engine:696 / arbiter:251 / conflict_matrix:218，均"获利盘≥80% + 无主力在场 → 接续乏力风险"）。**从不作为阶段判定的前置锁定**；且因恒 none，该风险条件退化为只看获利盘（死条件）。
4. **阶段引擎（PhaseDetectionEngine 8 维共识）**：dims = chip/fund/stage/asr/trend/ssrp/chan，**无"主力在场"维度/门槛** → 对任意股票（含无主力可识别的）都产阶段结论。

## 三、核查/修复方向（待推进，判定逻辑属 445 冻结须逐项拍板）

1. **capital_nature 打点失真**：是否把"无 LHB 证据"从 hot_money 改为 unknown（恢复区分度），仅在有明确席位/资金特征时标 institutional/hot_money。涉及 `_score_lhb` 阈值与"无数据兜底"语义。
2. **main_force_presence 证据不触发**：三种证据的数据覆盖（LHB 稀疏、股东户数采集、融资暴增阈值）+ 是否补充"温和证据"档位（如筹码集中度、连续放量）使 moderate 可达，而非全 none。
3. **阶段引擎是否加"主力锁定"前置**：若修复后仍无主力可识别（presence='none'）→ 阶段结论是否降级为 unknown/低置信（而非硬给 building/lifting/distributing）。这是阶段语义的根本修正，影响面最大，须用户拍板。
4. **464-13 置信门槛**：随上述结论一起定（若阶段仅在有主力时产出，置信门槛问题自然弱化）。

## 四、边界与关联
- **不改 464-12/14/10**（本号只承接主力识别 + 464-13）。
- 涉及 SIG 分析结论（阶段）+ JUD 判定输入，须 445 冻结边界内逐项拍板。
- 若确认需"阶段引擎加主力锁定"，将开实施号（464-17 子项或新号）并配套锁定测试 + 真实全链路实证。

---

## 五、实施记录（2026-09-21，v1.1）

**核查补充发现（方向二根因升级）**：`_compute_main_force_presence` 用 `ecm.conn`（**总库** stock_cache.db）直查 lhb_cache/stk_holder_cache/margin_cache——三表全在**分库**（system_cache.db / history_cache.db / market_cache.db），总库无表 → 三个查询全部静默抛 `no such table` 被 `except: pass` 吞掉 → **证据代码从未真正执行 → 全市场恒 none**（非阈值太严）。另实证股东户数环比减少≥5% **真实触发 2142 只**（Q2 半年报期 2026-06-30 vs Q1 2026-03-31 普遍下降，此前 0 只为查询脚本窗口函数 bug）。

### 三方向拍板结论（用户 2026-09-21 拍板）
| 方向 | 拍板 |
|---|---|
| ① capital_nature | 无 LHB 证据（lhb_score==0）→ unknown；>0（真买入）/ <0（假机构嫌疑）→ hot_money；≥0.5 → institutional |
| ②-融资窗口 | 实现对齐注释：30 自然日内最早记录（原取历史最早） |
| ②-股东户数+温和档 | 股东户数保留 ≥5% 阈值（数据修复后自然激活）+ 补筹码集中度档（前十大股东流通占比合计 ≥60% → moderate） |
| ③ 阶段锁定 | 软修正（非硬前置）：presence strong/moderate → 置信 +0.05；none → ×0.8（对齐 capital_nature 先例） |

### 改动清单（135 测试全绿，ruff 改动区无新增）
1. **方向一（双份）**：`chip_strategy.py` + `dim4_chip_fund_engine.py` 的 `get_tags` capital_nature 判定 `lhb_score!=0→hot_money / ==0→unknown`（原 `0.0>-0.5` 致 96% 全标游资）。
2. **方向二**：`data_daemon._compute_main_force_presence` 重写——改走 ECM 分库读方法（get_cached_lhb/margin/stk_holder/top10_holders），融资 30 日窗口对齐注释，补筹码集中度温和档。
3. **方向三（双份）**：`phase_detector.py` + `dim4_chip_fund_engine.py` 的 `_consensus` 加 presence 软修正。
4. **接线**：`data_daemon` depth ③ 在场证据提前到 ① 阶段前计算，presence 塞进 `extra_tags` 供阶段引擎软修正；dim4 侧经 SIG tags 扁平化自动透传。
5. **测试**：新增 `tests/test_464_17.py` 19 用例（三方向 + 双份同步）。

### 修复后 presence 全市场分布（2026-09-18 pre_feat 5550 只，SQL 模拟与代码同口径）
| presence | 只数 | 占比 | 证据 |
|---|---|---|---|
| strong | 546 | 9.8% | LHB 近30日席位 |
| risk | 54 | 1.0% | 融资 30 日窗口暴增>50% |
| moderate | 2677 | 47.8% | 股东户数≥5%（2142）∪ 筹码集中≥60%（1396），去重后 |
| none | 2319 | 41.4% | 无任何在场证据 |

修复后 58.6% 有在场证据（原 0%），三个 `=='none'` 风险消费点（status_engine:696 / arbiter:251 / conflict_matrix:218）复活为有效条件。

### 464-13 置信门槛（待 daemon 重算后定）
原实证（修复前 3962 只）：均值 0.458 / 中位 0.468 / 最低 0.136；≥0.3 拦 28%、≥0.2 拦 5%、≥0.5 拦 59%。
修复后两效应叠加：①capital_nature 96% hot_money→mostly unknown（不再 ×0.8，置信↑）；②presence none 41.4% → ×0.8（置信↓）。净效果待 daemon 用修复后代码重算 pre_feat（已重启，下一轮产出新 depth）后重估门槛。

