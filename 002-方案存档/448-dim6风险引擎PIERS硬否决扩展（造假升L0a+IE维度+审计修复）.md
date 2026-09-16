---
title: dim6 风险引擎 PIERS 硬否决扩展（造假升 L0a + I/E 维度 + 审计修复）
type: 方案（B 类引擎逻辑偏差，评估 + 已实施）
date: 2026-09-16
version: v0.2
status: ✅ 已实施（L0a pathA 硬否决 + E 高杠杆 + audit 假检查修复，单测 9 passed + 回归 28 passed + 真实链路 40 OK）
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号是 445 §6.3 B 类第三号（dim6 风险）
  - 444-SIG现状描述的事实层构建与显现——SIG 只分析+现状描述，JUD 判定灯色
  - 335-L0风险分级——L0a 硬否决 / L0b 软约束 / L0c 持有期的现有实现
  - 349-维度判定标准核查报告——直接先例
---

# 448 — dim6 风险引擎 PIERS 硬否决扩展

## 起因（445 §6.1 dim6 偏差 + 用户拍板开号）

445 号六维评估对 dim6 风险引擎判定：

| 偏差 | 445 判定 | 本号处置范围 |
|---|---|---|
| **造假仅软约束**（KB 要求永久黑名单） | 🔴 | **升 L0a 硬否决（JUD 侧）+ 确认 fraud_sign 真实可产** |
| **PIERS I/E/S 三维缺失**（商业模式/高杠杆/迭代行业） | 🔴 | **dim6 侧补可量化维度 + 现状条件产出** |
| **audit「无高风险事件」恒真假检查**（severity 从不产「极高」） | 🔴 | **审计条件修复** |
| 波动率当风险源（与「波动=机会」相悖） | 🔴 | 仅登记，不本号处置（见 445 §6.3） |
| 流动性口径不符（换手<1% vs KB 成交额>5000万+流通市值>30亿） | 🔴 | 仅登记，不本号处置（445 C 类/另号） |

## 权威基线（外部 wiki，445 已确认权威）

### PIERS 框架（`wiki/concepts/PIERS框架.md`）
五大否决维度：
- **P - 造假企业**：财报异常/频繁换审计/关联交易复杂/实控人声誉存疑；一旦被立案或媒体质疑**直接进黑名单**
- **I - 糟糕商业模式**：护城河薄弱/行业竞争恶化/技术迭代过快/客户集中度过高（「乏味丑陋落后但有定价权」可例外）
- **E - 高杠杆**：资产负债率过高/短期债务占比大/现金流不足以覆盖利息（结合 ROCE/营运资本覆盖率判断）
- **R - 管理层利益错位**：大股东频繁减持/股权质押比例过高/薪酬与业绩脱钩
- **S - 快速迭代/难以预测行业**：技术路线不明/受监管影响大/商业模式未被验证

**核心原则**：
- **永久性**：触发任何一条硬性否决 → 股票**永久进入黑名单**
- **不可覆盖**：硬性否决不可被第四层动态自适应调节覆盖
- **冰箱里没有糖果**：剔除后无论股价如何上涨均不重新纳入

### SIG/JUD 边界（444 拍板共识）
- **dim6（SIG 组件）**：只产**分析结论 + 现状条件**（PIERS 维度是否触发、各维度触发条件），不产判定灯色。
- **L0a 硬否决（JUD 侧/StatusEngine）**：对 SIG 产出的造假/退市等**硬风险事件做判定否决**——这才是判定职责。

## dim6 / L0a 现状（代码级已核）

### dim6_risk_engine.py（SIG 侧）
- `_assess_risk_level`（L196）：`catalyst_event in EVENT_RISK_SET`（含 fraud_sign/regulatory/delist_risk/goodwill_risk）**只计入 `high_count` 软加权**（≥2→高、==1→中）——不是硬否决；注释明确「L0 硬否决由 StatusEngine 统一处置，本引擎不参与」（L271）。
- `_list_risk_factors`（L295）：fraud_sign/regulatory 等映射到事件因子 severity=高。
- **audit「无高风险事件」恒真假检查**（L1235-1237）：条件 `satisfied = not any(f.get('severity') in ('极高',) for f in risk_factors)`，但所有事件因子 severity 均为「高」，**『极高』永不出现在 risk_factors → 该条件恒 satisfied=True → 恒真**（假检查）。
- **PIERS I/E/S/R 未接入**：引擎只认风险标签（risk_level/volatility_level/fina_health/catalyst_event/main_force_phase/turnover_rate），无数商业模式/杠杆/质押/减持量化维度。

### StatusEngine._apply_l0（JUD 侧）
- L0a 硬否决（L526-530）：仅当 `catalyst_event in _l0_cfg.get('hard_risks') or ['regulatory']` 触发 hard_veto。
- **config/status_engine.yaml:25 `hard_risks: [regulatory]` 只登记监管立案**——fraud_sign（造假）/delist_risk（退市）**未纳入硬否决**，正对应「造假仅软约束」。

## 数据链路核查（已完成，2026-09-16 Explore 子代理全量核查）

### 1. catalyst_event / fraud_sign 生产链路（关键发现）
- **生产者**：data_daemon.py `_update_with_event_tags()`（L3799-3806）→ `EventMonitor.compute_tags()`（event_monitor.py:934）→ `detect_all()`（L803-931）跑 21 类检测器 → 取「|direction| 最大事件」判定 `catalyst_event` 单值（L900-906）→ 写入 `pre_feat_cache.event`（features 五个字段：catalyst_event/catalyst_impact/event_composite_score/event_details/event_risk_factors）。
- **数据源**：各检测器从本地表读（自动采集）——fraud_sign 用 fina_indicator+income+cashflow+balancesheet（L241-243）；regulatory 用 sentiment_pool_cache（L361）；delist_risk 用 daily/daily_basic（L391）；st_warning 用 Stock ORM 名称（L423）。
- **fraud_sign 真实可产（已证明）**：`_detect_fraud_sign()`（L236-297）四项异常（营收连2年降/经营现金流负/ROE<0/负债率>90%），命中≥2 → detected=True(direction=-2)。生产库 event_details 含 **1043 行 fraud_sign**（如「ROE=-0.8%<0; 资产负债率>92% >90%」）。
- **但 catalyst_event 单值从不为 fraud_sign**：取 max-abs，fraud_sign(-2) 常被 breakout/regulatory/lhb 同权或更大覆盖 → **opportunity_tags_cache.catalyst_event 全历史仅 none 9317 / breakout 1135 / regulatory 405 / lhb 208 / concept 79**，无 fraud_sign。
- **推断（核心）**：L0a 读 catalyst_event 单值 → **简单把 fraud_sign 加入 yaml hard_risks 无效**；需让 fraud_sign 进入 L0 可判定的信号通道。

### 2. PIERS 各维数据可用性
| 维度 | 数据基础 | 证据 |
|---|---|---|
| **E 高杠杆** | ✅ **可直接接入** | debt_to_assets 覆盖率 22296/22407；roce 已落库（dim4 `_check_roce`/ROCEIndicator、dim7 `_fina_health` 已消费）；current_ratio/quick_ratio 有（21875 行）；balancesheet 可算总负债率。**尚无利息覆盖/短期债务专项** |
| **R 利益错位** | ❌ **无底层数据** | `_detect_pledge_risk`/`_detect_holder_reduce` 注释"pledge_stat/stk_holdertrade 表未入库，返回未检测"；全库无 `pro.pledge_stat/stk_holdertrade`。margin_cache（两融）已采集可佐证融资风险 |
| **I 商业模式 / S 迭代行业** | ❌ **无数据源** | `_check_industry_risk`（dim4:4883）注释"当前无行业分类数据API 默认通过"；无商业模式/迭代风险标签产出 |
| **P 造假** | ✅ 自动检测可产（见上） | event_details 1043 行实证 |

### 3. dim6 / L0a 现状（补充行号）
- dim6 `_assess_risk_level`（L227-282）6 源计数；`evaluate`（L1085-1098）读 tags.event_details，event_risks 非空会把 risk_info **强升为高红**（L1108-1112）。
- `_apply_l0`（L519-564）：目前 L0a 仅 `catalyst_event in yaml.hard_risks=['regulatory']`；L536-539 中 `catalyst_event=='fraud_sign'` 仅软约束 fina_weak(×0.5)。**即即便 fraud_sign 到 tags 层也只是 L0b 软约束，非硬否决**。
- audit「无高风险事件」（L1222）恒真——severity 全"高"无"极高"。

### 4. 测试覆盖（缺口）
- 现有：test_t67_event_light（手动 set catalyst_event）／test_t66_consensus_tie（投票票源）／test_321_arbiter（仅 regulatory→avoid）／test_fix_315_316／test_317／test_273a_implementation（ROCE/负债率构造式）。
- **无任何测试覆盖 dim6 `_assess_risk_level` / `_apply_l0` L0a / PIERS 真实数据触发 / fraud_sign→L0a 硬否决链路**。

## 处置设计（已拍板 + 已实施，2026-09-16）

### 核心问题：造假硬否决的「信号通道」
现有 L0a 只读 `catalyst_event` 单值（生产库不为 fraud_sign）→ 简单加 yaml 无效。两条候选路径：
- **路径 A（用户已拍板）**：`_apply_l0` 从 **tags.event_details 直读 fraud_sign/delist_risk** 判硬否决（SIG 产事件事实，JUD 判否决），不依赖 catalyst_event 单值。改动集中、不碰事件标签语义。
- 路径 B（弃用）：改 EventMonitor 让 fraud_sign 在 catalyst_event 单值中优先覆盖——影响面大。

### 一、JUD 侧（路径 A，已实施）：L0a 硬否决扩展
- **config/status_engine.yaml** 增 `l0.event_hard_risks: [fraud_sign, delist_risk]` 登记（对齐 PIERS「永久性/不可覆盖」）。
- **status_engine.py `_apply_l0`**（L526 后）：`if not hard_veto` 时扫描 `tags.event_details`（list[dict]），命中 `event_type in {fraud_sign:'财务造假/重大财务异常', delist_risk:'退市风险'}` → `hard_veto=True` + 对应 `hard_reason`。保留原 regulatory 分支（回归确认不破坏）。

### 二、dim6（SIG 侧，已实施）：E 高杠杆维度 + 审计假检查修复
- **新增 `_assess_piers_leverage(tags, dm, ts_code)`**：读 tags.debt_to_assets/roce → 回退 `dm.get_cached_fina_indicator`；`负债率>70%` 或 `ROCE<15%` 任一触发 → 产 E 维风险因子（severity=中）。SIG 只产现状条件，不否决。
- **`evaluate` 接入**：`risk_factors.extend(leverage['factors'])`；`status_description` 补 `piers_leverage` 指标（供 dim8 现状"因"）。
- **audit 假检查修复**：硬事件（fraud_sign/delist_risk）severity 升「极高」→「无高风险事件」条件（`not any(severity=='极高')`）不再恒真（造假时 satisfied=False）；risk_info 升「极高」红（供 JUD 直观）。
- **R（质押/减持）、I/S（模式/行业）**：无底层数据 → **登记为数据缺口**（后续补采 pledge_stat/stk_holdertrade 或行业 API），本号不做伪造判定。

### 三、验证（已完成）
- **单测 9 passed**（tests/test_448_piers_hard_veto.py）：fraud_sign/delist_risk→hard_veto；goodwill/concept 不误否决；regulatory 回归；E 杠杆三场景（负债率>70% 触发 / ROCE<15% 触发 / 正常不触发）。
- **回归 28 passed**：test_321_arbiter / test_321_s4_snapshot / test_t67_event_light（事件/L0/arbiter 无破坏）。
- **py_compile**：status_engine.py + dim6_risk_engine.py OK。
- **真实链路 sig_full_test 40 OK / 0 WARN / 0 FAIL**。
- **真实库可产性实证**：pre_feat_cache 历史 **935 行 fraud_sign**（每日约 90 只，如 000078.SZ「ROE=-18.1%<0; 资产负债率>92%」；09-14 有 90 只），证明造假检测自动可产；最新日 09-15 恰无 fraud 属正常波动。

## 工作进度记录（2026-09-16）
- [x] 用户拍板开号（445 B 类第三号，dim6 风险）
- [x] PIERS 权威定义确认（五维 + 永久黑名单/不可覆盖）
- [x] dim6/L0a 现状代码级核查（造假仅软约束、audit 恒真、I/E/S 未接入、yaml 仅 regulatory）
- [x] **data_daemon 事件生产链路核查（完成）**：fraud_sign 自动可产（event_details 935 行实证）但 catalyst_event 单值从不为 fraud_sign → 简单加 yaml 无效
- [x] **PIERS I/E/S/R 数据可用性核查（完成）**：E 高杠杆可直接接入；R 质押/减持、I/S 模式/行业 无底层数据（登记缺口）
- [x] **现有测试覆盖核查（完成）**：无 dim6/L0a/PIERS/造假硬否决链路测试 → 本号补 9 项单测
- [x] **用户拍板**：造假硬否决走**路径 A**（event_details 直读）+ E 高杠杆实施、R·I·S 登记缺口
- [x] **实施完成 + 全量验证**：单测 9 + 回归 28 + 真实链路 40 OK
- [ ] 445 交付：dim6 造假硬否决 + PIERS-E 维度 + audit 假检查修复 已闭环（归入引擎正确性基准）

## 约束
- 445 引擎基准约束：只补引擎分析维度/审计，**不破坏**既有判定逻辑与冻结基准（rr<1 降级、事件识别、主力出货、财务健康、情绪联动）——已通过回归验证。
- SIG/JUD 边界：dim6 只产分析+现状条件（含 E 杠杆触发、硬事件 severity），L0a 硬否决属 JUD（StatusEngine）——分别处置、互不混淆。
