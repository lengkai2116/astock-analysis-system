# 464 号｜dim4 在 dim8 现状描述中的输出定稿（筹码成本 + 资金博弈）

> **🔖 dim8 细化基准**：本文档为 **dim4 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim4 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、437 总纲第二层（筹码成本 + 资金博弈两维）、437-A §2.4（fund_chip 段 = dim4，D1 内分两小节）、`464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）.md` §一/§二（逐键深挖）展开，逐键拍板采用/不采用/去重/边界/补产出。
>
> **范围**：只定"dim4 产出哪些、用什么话术、归哪个维、补哪些透传项"；**不改任何引擎判定逻辑**（445 冻结基准）；补产出项登记待开实施号。
>
> **状态**：✅ **定稿**（2026-09-22 六步流程完成；第三步四项拍板 + 第四步映射）。
> **前置**：批次1/2/3 + 464-17 + 464-13 实施已全闭环；本定稿承接 `dim4-impl-resume`。
> **实例贯穿**：茅台 600519.SH（distributing 置信 0.29，audit 4/5）+ 万科 000002.SZ（lifting 0.22，2/5），2026-09-18 交易日。

---

## 〇、核心原则（对齐 dim2/dim3 + 444：现状=因，绝不是果）

- **现状（因）= 被满足的具体条件/实例 + 结构化键值**（audit.conditions + status_description 结构化键）。
- **dim8 归集 = 实例→话术**，不是 plain 拼接；**plain 已删**（§12.1，dim2/dim3 一致）。
- **评分/合成/灯色键归 JUD**：continuous_value / overall_direction / light / crowding_score / direction 判定——dim2 structure_health_score、dim3 health_score/pattern_score 同构，均归 JUD。
- **透传优先、不重算**：多数"因"（数值/明细）引擎已算出但未进 status_description——补产出透传，不另起计算。

---

## 一、dim4 全量最细分析结论输出项（茅台/万科真实实例）+ 逐键深挖

> 实例：茅台 600519.SH `phase=distributing(出货期)置信0.29 audit 4/5(主力阶段✗)`；万科 000002.SZ `phase=lifting(拉升期)0.22 audit 2/5`。深挖见 `464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）.md` §四（十一项核查发现）与 §二（8 维共识）。

| # | 输出键 | 是果/是因 | 分析逻辑（规则标准实证） | 深挖要点（2026-09-22） |
|---|---|---|---|---|
| 1 | `phase` + `phase_vote_ratio` | **果** + 因 | `PhaseDetectionEngine.compute_tags`（L391）8 维加权共识 `_consensus`（L721）：chip/fund/stage/asr/trend/ssrp/chan 7 维投票 + 权重 + 环境因子 + 主力在场软修正（464-17） | 果=阶段名；**因=vote_ratio 各维投票明细**（compute_tags 已算、evaluate 丢弃） |
| 2 | `fund_flow` + `net_lg_5d`/强度 | **果** + 因 | `_assess_fund_flow`（L5739）+ PhaseEngine 覆盖（L5908）+ 464-8 tags 对称补 outflow / 464-9 moneyflow_df 优先 / 464-15 net_lg_5d 万元→亿 | 果=流向；**因=net_lg_5d 大单净额数值**（`_dim_fund` L511 已算、evaluate 丢弃） |
| 3 | `cost_structure` | **因** | `_assess_cost_structure`（L5745）：chip_concentration + ASR + CYQKL + profit_ratio；464-11 删 quality 死计算 | detail 拼接字符串含全部数值（"筹码X，ASR=18，CYQKL=5.2，获利盘12%"）——可直接供叙事 |
| 4 | `signal` | **因** | `_assess_signal`（L5783）读 tags `buy_sell_point` → 一/二/三买一/二/三卖；464-16 补 third_sell | 信号词即"因"；**缺 price/confidence**（需补，见补产出④） |
| 5 | `retail_institution` | **果（弱）** | `_assess_retail_institution`（L5836）读 **tags** `main_force_phase`/`fund_flow`（非 evaluate 覆盖值） | ⚠️ 与 phase 不同源（tags vs evaluate 覆盖），潜在不一致；保留补充句 |
| 6 | `margin` | **因** | `_assess_margin`（L5843）：tags margin_change_5d（恒缺）→ margin_df rzye 现算 5 日变化 ±10% | detail 含 +x% 数值——可直接供叙事 |
| 7 | `crowding` + `crowding_score` | **果（含分数）** | `CrowdingFactor.evaluate`（L5231）三信号（融资/换手/波动）3 维制；464-6 融资维复活 + 464-3 换手接线 | 果=等级+分数；**因=details 三信号明细**（margin_ratio/turnover_state/volatility_state/evidence，evaluate 只取 3 字段、details 丢弃）；`crowding_score` 合成归 JUD |
| 8 | `fund_price_divergence` + `_status` + `_risk` | **因** | `_assess_fund_price_divergence`（L5793）：资金方向 × 价格方向交叉；446-D11 补产出 | label/risk 已完整——可直接供叙事 |
| 9 | `plain` | — | `_fund_chip_plain` 拼接 | ❌ **删除**（§12.1） |
| — | `judgment` 6 键 | **果/评分/灯色** | phase/direction/light/overall_light/overall_direction/continuous_value | **全归 JUD**；direction 与 fund_flow 去重 |
| — | `audit.conditions` 5 条 | **每条=一条分析逻辑实例（dim8 主原料）** | 主力阶段/资金流向/筹码集中/拥挤度合理/无危险背离 | 5 条照录 evidence |

## 二、granville/规则来源已封存（本 dim4 特有）

- `phase` 规则链：312（8 维加权共识 + 确认门槛）+ 464-1（枚举统一 lifting）+ 464-17（presence 软修正）+ 464-13（audit 置信门槛≥0.3）。
- `crowding`：464-6（列名对齐 rzye/circ_mv + 3 维制 valid_signals）+ 464-3（换手 turnover_rate 接线）+ 464-7（异常 warning）。
- `fund_flow`：464-8（双源对称补 5d_outflow）+ 464-9（moneyflow_df 优先）+ 464-15（net_lg_5d 万元→亿）。
- `signal`：461-9（chanlun 白名单唯一键）+ 464-16（三卖不被吞）。

## 三、逐键拍板结果（第三步，2026-09-22 四项拍板）

| # | 输出键 | 去向 | dim8 话术模板（万科/茅台示例） | 补产出 |
|---|---|---|---|---|
| 1 | `phase` | **dim8 采用（改因）** | "主力阶段**拉升**（置信0.48，投票:资金流入+成本锚+缠论卖点）" | ①透传 phase_vote_ratio |
| 2 | `fund_flow` | **dim8 采用（补数值因）** | "资金**强流出**（大单5日净额-1.6亿）" | ②透传 net_lg_5d/strength |
| 3 | `cost_structure` | **dim8 主原料（筹码主源）** | "筹码集中，ASR=18，CYQKL=5.2，获利盘12%" | 无 |
| 4 | `signal` | **dim8 采用（补增强）** | "出现**三卖信号**（@1323元，置信0.78）" | ④补 price/confidence（同源 chanlun 明细） |
| 5 | `retail_institution` | **dim8 采用（补充句）** | "散户机构博弈：主力出货（抛压风险）" | 无（保留，与 phase 并列） |
| 6 | `margin` | **dim8 采用** | "融资余额5日**-12%**（散户去杠杆）" | 无 |
| 7 | `crowding` | **dim8 采用（改因）** | "拥挤度**适中**（融资占比1%、换手正常、波动压缩——2/3信号可用）" | ③透传 CrowdingFactor.details |
| 8 | `fund_price_divergence` 三键 | **dim8 采用** | "资金流出+股价上涨（**拉抬出货**散户接盘危险信号）" | 无 |
| 9 | `plain` | ❌ 删除 | — | dim8 改造移除 |
| — | `crowding_score` | 🔒 归 JUD | — | 合成迁 JUD（439 同批） |
| — | `judgment` 6 键 | 🔒 全归 JUD | — | direction 与 fund_flow 去重 |

## 四、audit.conditions → 现状话术（dim8 归集主原料，茅台/万科实例）

dim8 归集时**优先材料 = `audit.conditions[]`**（每条=一条分析逻辑实例 `{name,satisfied,actual,threshold}`），直译现状句；5 条作 evidence：

| audit 条件 | satisfied 判定 | 现状话术（示例） |
|---|---|---|
| 主力阶段 | phase∈三态 且 置信≥0.3（464-13） | "主力阶段明确：出货期，置信0.29（<0.3 未达审计门槛）" |
| 资金流向 | ∈{strong, strong_out}（464-14） | "资金流向明确：强流出" |
| 筹码集中 | **concentrating（收紧后，原 stable 也满足偏宽）** | "筹码集中度：concentrating（收紧判定）" |
| 拥挤度合理 | ∉{HIGH_CROWDING, unknown}（464-6） | "拥挤度适中（MODERATE）非高拥挤" |
| 资金×价格无危险背离 | risk∉{危险}（446-D11） | "资金×价格：同向，无危险背离" |

## 五、跨维去重/协作为规侧

1. **资金流**：主源 **dim4**（437-A D4#3）——dim7 不重复产句。
2. **筹码**：主源 **dim4**（dim2 定稿总则1）——dim2 `vs_chip` 不产话术。
3. **买卖点**：dim4 `signal`（本段资金博弈）与 dim2 `buy_sell_points_detail` **同源 chanlun 明细**——dim8 归集层主述以 dim4 本段为准，dim2 侧供判定；补产出④同源复用不重算。
4. **fund_price_divergence**（446-D11）：归资金博弈子块（因），作 T 主干。

## 六、补产出项汇总（待开实施号）

| # | 补产出项 | 数据位置 | 涉及改动 | 关联拍板 |
|---|---|---|---|---|
| ① | 透传 `phase_vote_ratio`（各维投票明细）到 status_description | PhaseEngine.compute_tags 已算（L465 JSON），evaluate 丢弃 | dim4 evaluate | 第三步-透传缺口 |
| ② | 透传 `net_lg_5d`/`strength`（5日大单净额数值）到 status_description | `_dim_fund` L511 已算 | dim4 evaluate / _dim_fund 返回值 | 同上 |
| ③ | 透传 `CrowdingFactor.details`（margin_ratio/turnover_state/volatility_state + evidence/valid_signals）到 status_description | CrowdingFactor.evaluate details 已存，evaluate 只取 3 字段 | dim4 evaluate crowding 封装 | 同上 |
| ④ | `signal` 补 price/confidence/reason | `buy_sell_points_detail`（chanlun 结构化明细，dim2 L199 已产出，同源）| dim4 _assess_signal 改读结构化明细 | 第三步-信号增强 |
| ⑤ | audit「筹码集中」收紧为 `concentrating`（原 `stable` 也满足偏宽）+ threshold 文案同步 | `_assess_cost_structure` 返回 concentration + evaluate audit 条件3 | dim4 evaluate audit 条件 + threshold | 第三步-筹码集中判定 |
| — | crowding_score / continuous_value / overall_direction / judgment 全链归 JUD | — | dim8 叙事不产 + JUD（439 同批） | 第二步 |
| — | plain 删除 | dim4 `_fund_chip_plain` | dim8 改造移除 | 第二步 |

> **实施规范**（沿用 461 先例）：①-⑤ 属透传/判定收紧，445 冻结边界内可改（前端数据获取/口径/判定语义）；实施时新增锁定测试 + 全链路回归（含 StatusEngine 真实链路）；⑤属判定逻辑变更须确认 445 边界。dim4→dim8 归集属 464 待办第 4 项（dim8 改造），与其余各维一并落地。

## 七、定稿结论与待办

- **dim4 定稿六步完成**：第一步（全量输出项清单）→ 第二步（逐键深挖，3 透传缺口 + judgment 归 JUD + 观察项）→ 第三步（逐键拍板，四项拍板 + 5 补产出）→ 第四步（映射 437 第二层，筹码成本/资金博弈两小节）→ 第五步（用户拍板）→ 第六步（本文档存档 + 索引登记 + 记忆）。
- **待 open 实施号**：§六 ①-⑤（透传/信号增强/筹码集中收紧）+ 评分迁 JUD（439 同批）。
- **dim4 观察项（定稿标注，后续斟酌）**：retail_institution 与 phase 不同源（tags vs evaluate 覆盖）；fund_price_divergence 兜底无三态（仅 PhaseEngine 失效时触发）；direction 与 fund_flow 同值重复。

## 八、中文标注网关（dim8 展示层，已实施 2026-09-22）

用户反馈 dim8 fund_chip 现状描述混有英文（ASR/CYQKL/PhaseDetector/MODERATE/divergence），不适应不了解指标细节的新用户。在 **dim8 `_to_display_text` 网关**统一中文化展示文案，**不动任何结构化键**（crowding level、divergence_status、audit、judgment 原值保留，439 SIG-JUD 边界内）：

- **指标缩写保留 + 中文释义**：`ASR=42`→`ASR（活跃筹码比率）=42`；`CYQKL=4.1`→`CYQKL（筹码穿透力）=4.1`。
- **拥挤度档位中文**：`MODERATE/MODERATE_CROWDING`→适中、`HIGH_CROWDING`→高、`LOW_CROWDING`→低。
- **PhaseDetector 全中文化**：`PhaseDetector分析`→阶段引擎分析；`PhaseDetector资金流向=5d_outflow`→阶段引擎判定5日净流出（mixed→中性、inflow→5日净流入）。
- **背离状态 status 中文化**（evidence）：`divergence`→背离、`aligned`→同向、`none`→无。
- **作用域**：初版仅 `src_key=='chip_fund'` 段；2026-09-22 同展放宽到所有维段 + summary 段（见下「扩展」）。
- **验证**（600036/000002 真实数据完整链路）：text 全中文，ASR（活跃筹码比率）=42、拥挤度=适中/高、阶段引擎判定5日净流出；audit 仍显 `actual=MODERATE`（原值未动）。
- **扩展（2026-09-22 同日）**：网关从「仅 chip_fund」放宽到**所有维段**（text/evidence/subsections.items），并单独应用至 **summary 段**（独立 `_generate_text` 拼接通路，须单独调用否则平铺仍残留英文）。新增映射：
  - `RPS`→`RPS（相对强弱因子）`（dim3）
  - 缠论方向 `up/down`→`上升/下降`（dim2 chanlun_direction，独立成词替换防误中 d_outflow）
- **验证**（8 股 600036/000002/600519/300750/002594/688981/000001/601318）：text/plain/evidence/subsecitems/summary 全部 CLEAN（无 PhaseDetector/MODERATE/裸 ASR=CYQKL=/up/down/divergence 等英文）；结构化键原值保留。dim5-7 暂未接入（用户备注后续也许）。

---
*本文档为 dim4 定稿存档（代码不改，仅定稿）；§六 补产出项登记待开实施号。本定稿供 464 待办第 4 项（dim8 改造）与各维引擎补产出开工时直接引用为标准。*
