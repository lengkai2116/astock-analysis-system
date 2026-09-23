# 464 号｜dim6 在 dim8 现状描述中的输出定稿（风险边界 + 价格位置）

> **🔖 dim8 细化基准**：本文档为 **dim6 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim6 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、437-A §2.5（价格位置段 `risk` ← dim6）展开，逐键深挖 + 逐键拍板（采用/去重/仅 JUD）+ 话术模板 + 补产出项登记。
>
> **范围**：只定"dim6 产出哪些、用什么话术、归哪个维、补哪些透传项"；**不改任何引擎判定逻辑**（445 冻结基准）；补产出项登记待开实施号。
>
> **状态**：✅ **定稿**（2026-09-23 六步流程完成；第三步逐键拍板 **1A/2A/3A/4B** + 第四步四项拍板 ①分小节 ②§三-4 判定已闭环 ③采纳 T/E 修订 ④话术模板通过）。
> **前置**：470/471 dim6 死代码清理、448 PIERS 硬否决、452 流动性双门槛/波动率摘除、453 st_warning 分档、459 事件升格口径、473 debt_to_assets 补产、474 ROCE 主口径切换——均已闭环；本定稿基于清理后现状代码（582 行）实测。
> **实例贯穿**：茅台 600519.SH（`risk_level=高`／2 高风险源／audit 3/5）＋ 万科 000002.SZ（财务 fail + 事件升格／audit 3/5），2026-09-23 daemon 停止态真实 `StatusEngine.evaluate` 全链路，8 股全跑通无 FATAL（探针 `backend/scripts/_dim6_definition_probe.py` / `_dim6_tags_probe.py`）。

---

## 〇、核心原则（对齐 dim2/dim3/dim4/dim5 + 444：现状=因，绝不是果）

- **现状（因）= 被满足的具体条件/实例 + 结构化键值**（`audit.conditions` + `status_description` 结构化键）。
- **dim8 归集 = 实例→话术**，不是 plain 拼接；**plain 已删**（`3bdc1be`，dim6 无 `plain`/`_risk_plain`——464 §5.1 列该项已过时）。
- **评分/合成/灯色键归 JUD**：`risk_light` + `judgment` 全 6 键（level/risk_level/light/overall_light/overall_direction/continuous_value）；dim6 `continuous_value=min(rr/3,1)` 与 dim2/3/4 评分键同构。
- **透传优先、不重算**：多数"因"（风险源明细/几何化/事件/流动性）引擎已算出但未透传 → 补产出透传（P1/P2）。
- **维度归 437 第二层**：dim6 = **价格位置**（契约键 `risk`，段标题「风险边界状态」）；风险等级/风险因素/事件/波动/流动性作为该段风险侧内容随段输出。

---

## 一、dim6 全量最细分析结论输出项（茅台/万科真实实例）

> 实例 = 2026-09-23 daemon 停止态真实 `StatusEngine.evaluate(ts_code)` 输出（`dim_engine_results['risk']`），8 股对照。

### 1.1 三层全键清单（对照现状代码 `dim6_risk_engine.py:evaluate`）

**status_description（28 键）**

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `risk_level` | 低/中/高/极高 | `_assess_risk_level`：4 基础源计数（缠论 `risk_level=HIGH`／财务 `fina_health=fail`／事件 `catalyst_event∈EVENT_RISK_SET`／主力 `main_force_phase=distributing`）+ 流动性触发（452 双门槛）；≥2 高／1 中／0 低；事件升格（459：存在 severity 高/极高事件 → 升「高」）；PIERS 硬否决（448：fraud_sign/delist_risk）与 ST 退市（453）→「极高」 |
| 2 | `risk_detail` | 计数或事件说明 | `f'{n}个高风险源'` / 事件升格覆写 `f'事件风险：{factor}'` / PIERS 硬否决说明 |
| 3 | `risk_light` | green/yellow/red | level→light 映射 |
| 4 | `risk_factors` | 明细列表 `类别：因子（严重度）` | `_list_risk_factors`（缠论/财务/主力/流动性/估值/获利盘）+ `event_risks` + PIERS-E（473 tags 预计算优先） |
| 5 | `piers_leverage` | `{debt_to_assets, roce}`（未触发=空） | `_assess_piers_leverage`（448/473）：dta>70% 或 roce<15%（且≠0） |
| 6-10 | `support_price`／`resistance_price`／`dist_to_support_pct`／`dist_to_resistance_pct`／`dist_to_prev_high_pct` | 几何化价位与距离 | `calc_geometric` → `shared.calc_support_resistance` SSOT（461-11，本函数为兼容委托层）；优先 tags 预计算 risk_ext |
| 11 | `signal_days` | 站上前 60 日高点天数 | 同上（tags 预计算，现状多缺，见 P6） |
| 12 | `rr_value`／`rr_level`／`rr_assessment` | 盈亏比数值+分级+文案 | `_assess_rr`：<1R 不值得交易／1-2R 可考虑／2-3R 较好／>3R 优质 |
| 13-16 | `volatility_level`／`atr_14d`／`atr_pct`／`volatility_percentile` | 波动率档+ATR+分位 | `_calc_volatility`（461-4，未年化 20 日 std×100 判档 high>4/medium>2/low）；452 已从风险源摘除，仅参考 |
| 17-20 | `liquidity_risk`／`liquidity_detail`／`liquidity_avg_amount_wan`／`liquidity_circ_mv_wan` | 流动性触发+明细 | `_assess_liquidity`（452 KB 双门槛：日均成交额<5000 万 或 流通市值<30 亿）；数据不足默认不触发（443 保守） |
| 21 | `invalidation` | 失效/止损条件（str 列表） | `_build_invalidation`：跌破防守位(priority 1)／情绪 ebb·climax(2)／右侧否决(3) |
| 22-24 | `event_count`／`event_details`（前 5 dict）／`event_summary`（前 5 str） | 事件风险详情 | tags `event_details`（RAW-2 预计算）；event_details 含 event_type/description/direction/confidence/event_date |
| 25 | `risk_evidence` | 证据摘要串 | 等级+防守位+压力位+盈亏比+波动率+高风险因素+事件 |
| 26 | `support_resistance` | 防守/压力文案串 | 几何化价位拼串 |

**judgment（6 键）**：`level`／`risk_level`（与 status 重复）／`light`／`overall_light`（与 light 同值）／`overall_direction`（高/极高→-1、低→+1、中→0）／`continuous_value`（`min(rr/3,1)`，无 rr→0.5）。

**audit（5 条件 + 3 汇总）**：①风险等级（低或中）②盈亏比（≥2R）③流动性（成交额>5000万 且 流通市值>30亿）④无高风险事件（实现 = 无 `severity=='极高'`）⑤防守位有效；+ `satisfied_count`／`total_count`／`confidence`。

> ⚠️ **与 464 §5.1 的差异**：§5.1 第 11 项 `plain`（`_risk_plain`）**已不存在**（`3bdc1be` 各维 plain 删除收尾）；§5.1 第 8 项 `invalidation` 的「右侧否决 = 404 已知死代码」判断**不成立**（见 §二 发现⑦）。

### 1.2 完整实例（两股对照）

**600519.SH 贵州茅台**（`risk_level=高`）
- `risk_detail="2个高风险源"`；`risk_factors=["缠论：缠论风险高（高）","主力：主力出货（中）","事件风险：holder_concentration（中）"]`
- `piers_leverage={}`；`support_price=1166.33`／`resistance_price=1284.79`（距 -6.98%／+2.47%）；`dist_to_prev_high_pct=-6.35`；`signal_days=null`
- `rr_value=0.35`（不值得交易）；`volatility_level=low`（ATR 17.83、占比 1.42%、分位 8%）
- `liquidity_risk=false`／`liquidity_detail="流动性达标"`（avg 308809.1 万、circ_mv 156735231.0 万）
- `invalidation=["收盘跌破1166.33元","右侧确认转否决"]`；`event_count=1`（holder_concentration，direction -1，confidence 0.44，2026-06-30）
- judgment `{level:高, light:red, overall_direction:-1, continuous_value:0.1167}`；audit **3/5（0.6）**——风险等级✗、盈亏比✗，其余✓

**000002.SZ 万科A**（`risk_level=高`）
- `risk_detail="事件风险：longhubang"`（**被事件升格路径覆写**，非计数文案）
- `risk_factors` 6 条：`财务：财务异常（高）`／`估值：估值过高（中）`／`事件风险：longhubang（高）`／`事件风险：breakout（中）`／`PIERS-E：高杠杆（资产负债率74%>70%）（中）`／`PIERS-E：资本回报率偏低（ROCE -17.8%<15%）（中）`
- `piers_leverage={debt_to_assets:73.51, roce:-17.77}`；`support=3.24`／`resistance=3.89`（距 -15.0%／+2.1%）；`rr_value=0.14`；`signal_days=1`
- `volatility_level=medium`（ATR 0.136、占比 3.58%、分位 92%）；`liquidity_risk=false`（avg 75360.6 万、circ_mv 3701458.1 万）
- `event_count=2`（longhubang d+2 净买 12449 万／breakout d+1）；`invalidation=["收盘跌破3.24元"]`
- judgment `{高, red, -1, 0.0467}`；audit **3/5（0.6）**

**8 股分布**：`risk_level` = 2 高（茅台、万科）+ 6 低；`piers_leverage` 非空 5 只（招行/平安/平安银行/比亚迪/中芯）；audit 5/5 共 4 只（宁德/平安银行/招行等）。

---

## 二、逐键深挖（因）与核查发现

### 2.1 风险源触发矩阵（8 股真实 tags → 果键推导链）

| 股票 | 缠论 `risk_level` | 财务 `fina_health` | 事件 `catalyst_event` | 主力 `main_force_phase` | 流动性 | high_count | 事件升格 | 最终 level |
|---|---|---|---|---|---|---|---|---|
| 600519 茅台 | **HIGH** | pass | concept（∉集） | **distributing** | 达标 | **2** | holder_conc.(中) 不升 | **高** |
| 000002 万科 | LOW | **fail** | lhb（∉集） | lifting | 达标 | 1→中 | longhubang(**高**) 升 | **高** |
| 601318 平安 | LOW | suspicious | none | lifting | 达标 | 0 | 无 | 低 |
| 300750 宁德 | LOW | pass | none | washing | 达标 | 0 | 无 | 低 |
| 002594 比亚迪 | LOW | suspicious | none | unknown | 达标 | 0 | 无 | 低 |
| 000001 平安银行 | LOW | suspicious | none | lifting | 达标 | 0 | 无 | 低 |
| 600036 招行 | LOW | pass | none | lifting | 达标 | 0 | 无 | 低 |
| 688981 中芯 | LOW | suspicious | none | building | 达标 | 0 | 无 | 低 |

> `EVENT_RISK_SET = {fraud_sign, regulatory, delist_risk, goodwill_risk, st_warning}`——茅台 `concept`、万科 `lhb` 均**不属**该类，故「事件风险」源在计数中判低；万科升「高」来自 `event_risk_factors` 的 `longhubang(高)` 升格路径（459）。

### 2.2 逐键深挖表

| 键 | 定性 | 茅台实例 | 万科实例 | 原料（因） | 透传完备性 |
|---|---|---|---|---|---|
| `risk_level` | **果** | 高 | 高 | high_count=2 / 1+事件升格 | ✅ |
| `risk_detail` | **果**（派生） | `2个高风险源` | `事件风险：longhubang` | 计数／事件升格／PIERS 三路文案 | ⚠️ 升格覆盖计数（发现④） |
| `risk_light` | **果**（映射） | red | red | level→light | 归 JUD |
| `risk_factors` | **因+果** | 缠论高、主力出货、holder_concentration(中) | 财务异常(高)、估值过高(中)、longhubang(高)、breakout(中)、PIERS-E×2(中) | `_list_risk_factors`+event_risks+PIERS-E | ⚠️ 兜底与 PIERS-E 并存矛盾（发现③） |
| `piers_leverage` | **因**（透传） | `{}` | `{dta:73.51, roce:-17.77}` | tags.debt_to_assets/roce（473 预计算优先） | ⚠️ 未触发丢弃 metrics（发现②） |
| `support_price`/`resistance_price` | **因**（透传） | 1166.33/1284.79 | 3.24/3.89 | tags risk_ext（=shared SSOT） | ✅ |
| `dist_to_support_pct`/`dist_to_resistance_pct`/`dist_to_prev_high_pct` | **因**（透传） | -6.98/2.47/-6.35 | -15.0/2.1/-2.06 | 同上 | ✅（符号约定未文字化） |
| `signal_days` | **因** | null | 1 | tags.signal_days | ⚠️ 8 股 7 只 null，供给侧未产（发现⑥） |
| `rr_value`/`rr_level`/`rr_assessment` | **因→果** | 0.35/不值得交易/盈亏比0.35<1R | 0.14/不值得交易 | geo.risk_reward→`_assess_rr` | ✅ |
| `volatility_level`/`atr_14d`/`atr_pct`/`volatility_percentile` | **因**（透传） | low/17.83/1.42/0.079 | medium/0.136/3.58/0.922 | tags 预计算（461-4） | ✅ |
| `liquidity_risk`/`liquidity_detail`/`liquidity_avg_amount_wan`/`liquidity_circ_mv_wan` | **因**（透传） | false/流动性达标/308809.1/156735231.0 | false/达标/75360.6/3701458.1 | daily.amount(千元)/10 + basic.circ_mv(万元) | ✅ |
| `invalidation` | **因**（条件串） | 收盘跌破1166.33元；右侧确认转否决 | 收盘跌破3.24元 | support_price+sentiment_phase+right_side_confirm | ⚠️ priority-3 实命中（发现⑦） |
| `event_count`/`event_details`/`event_summary` | **因**（透传） | 1/holder_concentration(-1,0.44) | 2/longhubang(+2)、breakout(+1) | tags.event_details（RAW-2） | ✅（count 真总数，details 裁前 5） |
| `risk_evidence` | **果**（合成串） | 等级+防守位+压力位+盈亏比+波动+因子+事件 | 同构 | 各键拼接 | 冗余串 |
| `support_resistance` | **果**（文案块） | 防守位1166.33元（距现价-6.98）… | … | support/resistance+dist | ⚠️ 无 % 号；与数值键重复 |
| `judgment.*` | **果**（归 JUD） | 高/red/-1/0.1167 | 高/red/-1/0.0467 | = status.risk_level + min(rr/3,1) | 归 JUD |
| `audit.conditions`（5 条） | **因**（核心原料） | 3/5：风险等级✗高、盈亏比✗0.35、流动性✓、无高风险事件✓、防守位✓ | 3/5：风险等级✗高、盈亏比✗0.14、流动性✓、无高风险事件✓、防守位✓ | 各条件 actual/threshold 实例化 | ✅（§12.1 原料载体） |

### 2.3 核查发现（9 项，已逐项处置入 §三/§六）

1. **①`_assess_risk_level.risk_sources` 明细未透传**：5 源 `{name, level}` 明细（缠论/财务/事件/主力/流动性 各自高/低）evaluate 丢弃，仅透传计数文案 → 典型「因已算未透传」（P1）。
2. **②`piers_leverage` 未触发时丢弃 metrics**：茅台 dta=12.81、roce=33.42（均达标）被清空为 `{}`，现状描述无法表达「杠杆/资本回报达标」（P2）。
3. **③兜底「无显著风险」与 PIERS-E 因子并存矛盾**：300750 宁德 `risk_factors=['综合：无显著风险（无）','PIERS-E：资本回报率偏低（ROCE 9.1%<15%）（中）']`——`if not factors` 兜底发生在 PIERS-E extend **之前**（471 只修了 event_risks 场景）（P3）。
4. **④`risk_detail` 被事件升格覆写丢失源计数**：万科原「中（1 源：财务 fail）」升「高」后 detail 变「事件风险：longhubang」，财务异常这个高风险源在 detail 中消失（P4）。
5. **⑤audit④名实不符**：键名「无高风险事件」／threshold「无极高风险」，实现仅查 `severity=='极高'`——万科有 `longhubang(高)` 仍判 ✓（445 遗留，470/471 亦登记）（P5）。
6. **⑥ ~~`signal_days` 供给缺失~~ → 已修正（2026-09-23 补充核查）**：null **非供给缺口**——`shared.calc_support_resistance` 语义为「突破前 60 日高点后的持续交易日数」（`advice_engine.py:208` 文档同），未突破即 None；7 只 null 股 `dist_to_prev_high_pct` 均为负（低于近期高点）语义正确，万科已突破故 `signal_days=1`；daemon `risk_ext` 已正常写入（`data_daemon.py:3655`）。**撤销 P6**。
7. **⑦`right_side_confirm='否决'` 实际可产，与代码注释「死代码」矛盾**：茅台、招行 tags 实测为 `'否决'`，其 `invalidation` 实际命中 priority-3「右侧确认转否决」（`_build_invalidation` 注释称"预计算管道只产 strong_confirm/unconfirmed，此处为死代码"与实测不符）（P7）。
8. **⑧`judgment` 冗余 + 文案重复**：`judgment.risk_level` 与 status 重复、`light`/`overall_light` 同值；`risk_evidence`/`support_resistance` 与各键重复（P8）。
9. **⑨银行 PIERS-E 语义观察**：招行 dta=89.92、平安 89.94、平安银行 91.02 均触发「高杠杆（中）」——银行高负债率属行业常态，KB 口径是否应豁免属 445 域问题（**仅登记，不在本维拍板**）。

### 2.4 补充核查新增发现（2026-09-23 实施前复核）

10. **⑩静默吞异常**：`_assess_liquidity` **两处 bare `except Exception: pass`**（:139/:150，流动性判据可静默失效、退化为"不触发"）；`evaluate` ECM 日线读取失败静默 `df=None`（:365-366）；event 块异常仅 `logger.debug`（:423-424）。对照 **464-7（dim4）已改 `logger.warning` 的先例**（P16）。
11. **⑪geo fallback dict 缺键**：`evaluate` 中 `df` 缺失时的兜底 geo dict 未含 `dist_to_prev_high_pct`（仅 `df` 缺失路径，`.get` 返回 None 无害）；随本批实施顺手补齐。
12. **⑫P1 实施约束（非缺陷）**：事件升格路径 `risk_info = {'level','light','detail'}` **整体替换** → 丢 `risk_sources`；P1 透传须一并改造（保留/合并源明细），否则升格股仍无源明细。
13. **⑬`continuous_value` 边界**：`round(min(rr/3,1),4) if rr_info.get('rr_value') else 0.5` —— `rr==0` 时 falsy 回落 0.5（极端边界，登记不改）。

---

## 三、逐键拍板（最终，已固化为定稿基准）

> 裁定口径：**1A**（`risk_level` 采用）／**2A**（4 个预拼串去重）／**3A**（事件条目归 `event_details` 主源）／**4B**（audit④ 仅对齐文案，不改判据）。

### 3.1 status_description（28 键）

| 键 | 处置 | 说明 |
|---|---|---|
| `risk_level` | **采用** | 主结论；客观陈述（"当前为高风险状态"），不含操作建议（归 JUD） |
| `risk_detail` | **采用 + P4** | 三路文案统一并保留源计数 |
| `risk_light` | **纯契约仅 JUD** | 灯色属 JUD（439 同批） |
| `risk_factors` | **采用（剥离事件条目）+ P12** | 事件条目归 `event_details` 主源 |
| `piers_leverage` | **采用 + P2** | 未触发时也透传 metrics |
| `support_price`／`resistance_price` | **采用（主源归一）** | 绝对价主源=dim6 |
| `dist_to_support_pct`／`dist_to_resistance_pct`／`dist_to_prev_high_pct` | **采用** | 价格位置「因」 |
| `signal_days` | **采用** | 按设计：未突破前 60 日高点则无值（**非缺口**），dim8 在 null 时不产「连续站上高点」句 |
| `rr_value`／`rr_level`／`rr_assessment` | **采用** | `rr_assessment` 承载文案，`rr_value` 供数值表述 |
| `volatility_level`／`atr_14d`／`atr_pct`／`volatility_percentile` | **采用** | 仅参考信息（452 已非风险源） |
| `liquidity_risk`／`liquidity_detail`／`liquidity_avg_amount_wan`／`liquidity_circ_mv_wan` | **采用（合并为一组话术）** | 话术由 detail 承载 + 数值表述 |
| `invalidation` | **采用 + P7** | 止损/失效条件 |
| `event_details` | **采用（事件话术主源）** | 含类型/描述/方向/置信/日期 |
| `event_count` | **去重** | 与 details 同源 |
| `event_summary` | **去重 + P13** | 从 dim8 E 表移除，改用 `event_details` |
| `risk_evidence` | **去重** | 预拼合成串 |
| `support_resistance` | **去重** | 与几何键重复 |

### 3.2 judgment（6 键）→ **全部纯契约仅 JUD**（439 同批）
`level`／`risk_level`／`light`／`overall_light`／`overall_direction`／`continuous_value`。

### 3.3 audit
| 项 | 处置 | 说明 |
|---|---|---|
| `conditions[5]`（name/satisfied/**actual**/threshold） | **采用（核心「因」原料）** | §12.1 原料载体 |
| `satisfied_count`／`total_count`／`confidence` | **采用** | 供 dim8 状态表述 + data_warning |
| audit④「无高风险事件」 | **采用 + P5（窄口径）** | **只对齐文案**，不动判据（4B） |

### 3.4 跨维主源归一（终态）
| 事实 | 主源 | 非主源方 |
|---|---|---|
| 支撑/阻力绝对价、距离、盈亏比 | **dim6** | dim2 只产「中枢区位比例」（dim2 定稿 §六-①） |
| 事件 | **`event_details`** | `risk_factors` 事件条目剥离、`event_summary`/`event_count` 去重 |
| 波动率 | **dim6**（唯一产出维） | 无 |
| 财务健康 `fina_health` | dim6 表述为**风险** | dim7 表述为**估值财务**（437-A §三-2） |
| 437-A §三-4（dim2↔dim6 支撑阻力） | **判定已闭环**（461-11 统一 `shared.calc_support_resistance`） | 仅保留归集去重 |

---

## 四、437 第二层维度映射

### 4.1 字段归属表（dim6 → 437 第二层「价格位置」，契约键 `risk`）

| 键 | 第二层维度 | T/E | 相对 437-A §2.5 的修正 |
|---|---|---|---|
| `risk_level`／`risk_detail` | 价格位置（段主题：风险边界） | T | 一致 |
| `risk_factors` | 价格位置 | E | 一致 |
| `piers_leverage` | 价格位置 | **E（新增）** | 437-A 未列 |
| `support_price`／`resistance_price` | 价格位置（核心） | T | 一致 |
| `dist_to_support_pct`／`dist_to_resistance_pct`／`dist_to_prev_high_pct` | 价格位置 | E | 补 `dist_to_prev_high_pct` |
| `signal_days` | 价格位置 | **E（新增）** | 437-A 未列 |
| `rr_value` | 价格位置 | T | 一致 |
| `rr_level`／`rr_assessment` | 价格位置 | E | 一致 |
| `volatility_level`／`atr_pct`／`volatility_percentile`／`atr_14d` | 价格位置（波动参考） | E | 437-A 写 `volatility_atr` → **实键 `atr_pct`**；补 `volatility_percentile` |
| `liquidity_*`（4 键） | 价格位置 | **E（新增）** | 437-A 未列 |
| `invalidation` | 价格位置 | E | 一致 |
| `event_details` | 价格位置 | E | 事件话术主源 |
| `event_count`／`event_summary`／`risk_evidence`／`support_resistance` | — | **去重不进表** | 争议 2A |
| `plain` | — | **移除** | 引擎已删 |
| `risk_light`／`judgment.*` | **归 JUD** | — | 439 同批 |
| `audit.conditions`／汇总 | 价格位置（**现状=因**核心，验证层） | 验证 | 建议透传 actual/threshold（P9） |

### 4.2 段内结构（对齐 dim4 D1 先例；本次拍板「**分小节**」）

| 小节 | 字段 |
|---|---|
| **① 价格位置** | `support_price`／`resistance_price`／`dist_*`／`dist_to_prev_high_pct`／`signal_days`／`rr_value`／`rr_level`／`rr_assessment` |
| **② 风险状态** | `risk_level`／`risk_detail`／`risk_factors`／`piers_leverage`／`volatility_*`／`liquidity_*`／`event_details`／`invalidation` |

（对应 437-A §2.5「D1 待拍板是否并入位置子块」→ **拍板：并入，分两小节**，P15。）

### 4.3 dim8 T/E 字段表修订（P14）

```python
# _DIM8_T_SUBJECTS['risk']（主述，字段序即叙事序）——保留
['risk_level', 'support_price', 'resistance_price', 'rr_value', 'rr_level',
 'volatility_level', 'risk_factors']

# _DIM8_E_FIELDS['risk']——修订
['atr_pct', 'volatility_percentile', 'dist_to_support_pct', 'dist_to_resistance_pct',
 'dist_to_prev_high_pct', 'rr_assessment', 'liquidity_detail', 'invalidation',
 'event_details', 'piers_leverage']
#  变更：-event_summary（P13）+event_details +piers_leverage +dist_to_prev_high_pct
#        （event_details 需新增 dict-list 渲染；piers_leverage 需新增 dict 渲染）
```

---

## 五、话术模板（因果链：因为 → 所以 → 验证）

### 5.1 模板

> 【价格位置】当前价格距防守位 **{support}** 元 **{d_sup}%**、距压力位 **{resistance}** 元 **{d_res}%**、距前高 **{d_ph}%**；盈亏比 **{rr}（{rr_level}）**{signal_days 句，若有}。
> 【风险状态】**因为**{风险源已达成条件}，**所以**风险等级为 **{risk_level}**（{risk_detail}）；风险因素：{factors}；{事件句}。波动率 **{vol_level}**（ATR {atr}、占比 {atr_pct}%、历史分位 {pctile}%）。流动性**{达标/不足}**（日均成交额 {amt}、流通市值 {mv}）。失效条件：{invalidation}。
> 【验证】条件稽核 **{satisfied}/{total}**：✗ {未达成项 name}（实际 {actual}，要求 {threshold}）；✓ {达成项}。

### 5.2 茅台填充（600519.SH）

> 【价格位置】距防守位 **1166.33** 元（**-6.98%**）、距压力位 **1284.79** 元（**+2.47%**）、距前高 **-6.35%**；盈亏比 **0.35（不值得交易）**。
> 【风险状态】**因为**缠论风险维度为「高」、主力处于「出货」阶段（共 2 个高风险源），**所以**风险等级为 **高**；风险因素：缠论风险高、主力出货；事件：股东户数增加 22%（分散，2026-06-30，置信 44%）。波动率 **low**（ATR 17.83、占比 1.42%、历史分位 8%）。流动性**达标**（日均成交额 30.88 亿元、流通市值 1.57 万亿元）。失效条件：收盘跌破 1166.33 元；右侧确认转否决。
> 【验证】条件稽核 **3/5**：✗ 风险等级（实际「高」，要求「低或中」）；✗ 盈亏比（实际 0.35，要求 ≥2R）；✓ 流动性、✓ 无高风险事件、✓ 防守位有效。

### 5.3 万科填充（000002.SZ）

> 【价格位置】距防守位 **3.24** 元（**-15.0%**）、距压力位 **3.89** 元（**+2.1%**）、距前高 **-2.06%**；盈亏比 **0.14（<1R）**；连续站上 60 日高点 **1** 天。
> 【风险状态】**因为**财务异常（fail）触发 1 个高风险源后、事件风险「龙虎榜」升格，**所以**风险等级为 **高**；风险因素：财务异常、估值过高、longhubang(高)、breakout(中)、PIERS-E 高杠杆（73.5%>70%）、PIERS-E 资本回报率偏低（ROCE -17.8%<15%）；事件：龙虎榜机构净买 12449 万（+2）、突破站上 60 日线+放量 2.0 倍（+1）。波动率 **medium**（占比 3.58%、分位 92%）。流动性**达标**（日均 7.54 亿元、流通市值 370.1 亿元）。失效条件：收盘跌破 3.24 元。
> 【验证】条件稽核 **3/5**：✗ 风险等级（高）；✗ 盈亏比（0.14，要求 ≥2R）；✓ 流动性、✓ 无高风险事件、✓ 防守位有效。

---

## 六、补产出项清单（P1-P15，待开实施号）

### 6.1 dim6 引擎侧（8 项）

| # | 补产出项 | 性质 | 来源发现 |
|---|---|---|---|
| P1 | `_assess_risk_level.risk_sources`（5 源 name/level 明细）透传 | 因已算未透传 | ① |
| P2 | `piers_leverage` 未触发时也透传 `{debt_to_assets, roce}` | 因已算未透传 | ② |
| P3 | 兜底「无显著风险」与 PIERS-E 因子并存矛盾（兜底判定后移） | 一致性缺陷 | ③ |
| P4 | `risk_detail` 三路文案统一 + 保留源计数 | 话术失真 | ④ |
| P5 | audit④ 文案与实现对齐（**不改判据**） | 名实不符（445 遗留） | ⑤ |
| ~~P6~~ | ~~`signal_days` RAW 预计算供给修复~~ → **撤销**（补充核查：null 为语义正确，非缺口） | — | ⑥（已修正） |
| P7 | `right_side_confirm='否决'` 注释订正 / 供给核实 | 文档失真 | ⑦ |
| P8 | judgment 冗余键（`risk_level`/`overall_light`）归 JUD 时统一 | 冗余清理 | ⑧ |
| P16 | `_assess_liquidity` 两处 bare `except: pass` + ECM 读失败静默 → 改 `logger.warning` | 静默吞异常 | ⑩ |

### 6.2 dim8 归集层（7 项，跨维共性）

| # | 补产出项 | 性质 |
|---|---|---|
| P9 | 段内 `audit.conditions` 透传 `actual`/`threshold`（现被裁成 name+satisfied） | 现状本体丢失 |
| P10 | `evidence[:5]` 硬截断致「因」丢失（茅台 13 条候选只显 5 条） | 归集容量缺陷 |
| P11 | dim6 接入中文化网关（`volatility:low/medium` 等英文值） | 展示层英文残留 |
| P12 | `risk_factors` 呈现时剥离事件条目（3A 落地） | 去重 |
| P13 | `event_summary` 移出 E 表 → 事件佐证改用 `event_details`（2A 落地） | 去重 |
| P14 | `risk` 段 T/E 表修订（§4.3） | 字段级编排 |
| P15 | `risk` 段内分「价格位置 / 风险状态」两小节（对齐 dim4 subsections 机制） | 段结构 |

---

## 七、边界与归 JUD 清单

### 7.1 归 JUD（dim8 不归集）
- `risk_light`；`judgment.level` / `risk_level` / `light` / `overall_light` / `overall_direction` / `continuous_value`。
- 评分/合成归 JUD 与 dim2 `structure_health_score`、dim3 `health_score`/`pattern_score`、dim4 `crowding_score` 同构（**439 同批**）。
- 灯色字段暂留 SIG 属 **439 已知中间态**（不视为缺陷，待 JUD 盘查修正阶段统一迁移）。

### 7.2 不产话术（去重）
`risk_evidence`、`support_resistance`、`event_count`、`event_summary`。

### 7.3 本维不采用
`plain`（已删除，`3bdc1be`）；dim8 为唯一叙事口径，各维 plain 不再单独保留。

### 7.4 执行边界
- 本定稿**不改引擎判定逻辑**（445 冻结）；P1-P15 为补产出/呈现项，登记待开实施号。
- 引用本维 dim8 输出时**先查《464-dim8现状描述输出定稿基准索引》**；定稿与现状代码冲突以本定稿为准。

---

**关联文档**：464-dim8现状描述输出定稿基准索引（引用入口）／464-dim2-dim7分析输出项全量梳理（原料）／437-A-dim8归集映射设计（§2.5 价格位置段）／445-dim2-dim7引擎正确性知识库核查（判定基准，勿混）／470/471 dim6 清理、448/452/453/459 dim6 处置。
