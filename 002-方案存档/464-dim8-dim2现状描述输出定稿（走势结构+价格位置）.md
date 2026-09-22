# 464 号｜dim2 在 dim8 现状描述中的输出定稿（走势结构 + 价格位置）

> **🔖 dim8 细化基准**：本文档为 **dim2 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim2 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、§十（逐键话术评估）、437 总纲第二层（走势结构/价格位置两维）展开，逐键拍板采用/不采用/去重/边界，作为 dim8 归集与 JUD 消费的统一依据。
>
> **状态**：✅ 定稿（2026-09-20 用户拍板三项 + 边界确认）；**2026-09-21 按 dim3 六步流程复核修订**（见 §七）。
> **范围**：只定"dim2 产出哪些、用什么话术、归哪个维"；**不改任何代码**（改造动作属 464 待办第 4 项 dim8 改造 / 待开实施号）。
> **实例贯穿**：茅台 600519.SH（2026-09-18 交易日真实 dim2 evaluate 输出）。

---

## 〇、三条总则（用户拍板）

1. **筹码主源为 dim4** —— dim2 的 `vs_chip`（获利盘/集中度）**不用于 dim8 产话术**，筹码现状一律由 dim4「筹码成本」维产出；dim2 vs_chip 仅供内部参考或删除。
2. **价格位置需与 dim6 组合** —— 需说明"现价在当前中枢的**区位比例**"；已核验 **dim2 与 dim6 的支撑/压力同源**（共用 `shared_support_resistance.calc_support_resistance`，461-11 SSOT），**无数值冲突**，归集时合并去重、不重复产。
3. **确认边界** —— 见 §四（不采用键去留 / JUD 契约 / 删除范围）。

---

## 一、dim2 全量最细分析结论输出项（茅台真实实例）

| # | 输出键 | 茅台真实实例值 | 对应分析逻辑（audit 条件/规则） |
|---|---|---|---|
| 1 | `vs_zhongshu` | 价格在中枢内部(1250.10~1292.70，2026-05-27~09-08) | 463 有效中枢 + 前复权；audit「价格vs中枢」 |
| 2 | `vs_ma` | 均线交织 | MA5/10/20/60 排列 |
| 3 | `vs_support_resistance` | 距支撑1151元(-8.4%)/压力1282元(+2.0%) | 461-11 shared SSOT 支撑阻力 |
| 4 | `vs_chip` | 筹码稳定，获利盘11% | 筹码集中度 + 获利盘（445-A3） |
| 5 | `vs_indicator` | 均线纠缠，RSI 34 中性 | 均线态 + RSI 分档（461-1） |
| 6 | `chanlun_direction` | down | 446/463 价格 vs 有效中枢主判据 |
| 7 | `trend_basis` | 价格在中枢内部-中枢下移 | 趋势判定依据（因果链的"因"） |
| 8 | `chanlun_strength`=`structure_health_score` | 38 | 466 结构健康度（11 定理+趋势背驰修正） |
| 9 | `buy_sell_points` | ["first_sell 0.78@1323"] | 前3买卖点（字符串） |
| 10 | `multi_level_direction_text` | 周线/日线同步下降 | 457 多周期区间套 |
| 11 | `level_cross_score` | 0.52 | 日/周/月三级交叉校验 |
| 12 | `chanlun_phase` | 健康（11定理>0.6） | 11 定理≥0.6 判健康 |
| 13 | `trend_structure_signal`/`ts_strength` | none / 0.1 | 三假设→123_buy_breakout |
| 14 | `buy_sell_points_detail` | 1条(first_sell 0.78@1323) | 结构化买卖点明细 |
| 15 | `stage_name` | 下降 | trend→上升/下降/盘整 |
| 16 | `divergence`/`_type`/`_strength` | 顶背驰/中枢背驰/0.78 | 背驰方向+类型+强度 |
| 17 | `plain` | 各键白话拼接 | §12.1：**删除** |
| — | `audit.conditions` | 5条（趋势/中枢✓，健康/背驰/买点✗） | **每条=一条分析逻辑实例（dim8 主原料）** |

---

## 二、采用项 → 归集映射（437 第二层维 + 话术标准）

### ✅ 归「走势结构」维（dim2 主维，437 §四）

| 输出键 | 茅台话术（示例） | 描述标准 |
|---|---|---|
| `chanlun_direction`(果) + `trend_basis`(因) | "缠论方向**下降**（依据：价格在中枢内部-中枢下移）" | **因果链核心**；先因（依据）后果（方向） |
| `stage_name` | 段落标题 "走势结构：下降" | 结构态标签，作段落标题 |
| `vs_zhongshu` | "价格位于日线中枢**内部**（1250.10~1292.70，2026-05-27~09-08）" | 定性位置直述 |
| `vs_ma` | "均线交织（方向未定）" | 均线态主源 |
| `vs_indicator`（仅 RSI 分档） | "RSI 34 中性" | **只取 RSI**；均线段去重（主源 vs_ma） |
| ~~`structure_health_score`~~ | **归 JUD（2026-09-21 复核修订）**——合成评分不产话术 | **⚠️ 原定稿"结构健康度 38/100（不足）"撤除**；dim8 呈现"因"= 11 定理明细 + score 合成 details（见 §七-①） |
| `buy_sell_points_detail` | "确认一卖信号于 1323 元（置信 0.78，**依据：上涨趋势背驰-中枢背驰**）" | 买卖点结构化明细主源；**补 reason（判定条件=因）**，2026-09-21 修订 |
| `multi_level_direction_text` | "周线/日线同步下降，多周期方向一致" | 区间套印证（方向一致性） |
| `divergence` + `_type` + `_strength` | "出现**顶背驰**（中枢背驰，强度 0.78，**依据：价格离开中枢上方后回调跌回中枢内、力度法双确认**）" | 方向+类型+强度 合并一句；**补 details/dual_confirmed（检测条件=因）**，2026-09-21 修订 |

### ✅ 归「价格位置」维（dim6 主源 + dim2 补充 + 中枢区位比例）

| 输出键 | 茅台话术（示例） | 描述标准 |
|---|---|---|
| `vs_support_resistance` | "距支撑 1151 元(-8.4%)，距压力 1282 元(+2.0%)" | **主源 dim6**；dim2 供距离百分比补充；**同源合并去重**（见 §三-2） |
| **中枢区位比例（待补产出）** | "现价位于日线中枢 [50%] 处"（示例比例） | **现状未产出**：`vs_zhongshu` 只产定性"上方/内部/下方"，需 dim2 **补产出定量区位比例** `(price - zs_low) / (zs_high - zs_low)`；此为"价格位置维"与 dim6 组合的关键补充项 |

---

## 三、去重 / 归集协作规则

1. **筹码**：dim2 `vs_chip` **不产话术**，筹码现状由 dim4 归「筹码成本」维唯一产出。dim2 侧 `vs_chip` 键保留（供内部/audit 参考）但 dim8 不读取。
2. **支撑/压力（价格位置）**：dim2 与 dim6 **同源**（shared.calc_support_resistance SSOT），茅台实测同值无冲突。dim8 归集时：
   - **绝对价/距离**：以 **dim6（risk 段）** 为主源产出支撑/压力；
   - **dim2 vs_support_resistance** 仅作交叉印证，不重复产句；
   - **中枢区位比例**（dim2 补产出）作为"价格位置"维的独立叙述点，与 dim6 支撑压力互补，不冲突。
3. **均线**：dim2 `vs_ma` 与 `vs_indicator` 内的均线段重复 → 主源 `vs_ma`；`vs_indicator` 只留 RSI。
4. **买卖点**：`buy_sell_points`（字符串）与 `buy_sell_points_detail`（结构化）重复 → **主源 `buy_sell_points_detail`**；前者不产话术。

---

## 四、边界确认（不采用 / 仅 JUD / 删除）

### ❌ 删除（不再产）
- **`plain`**（dim2 #17）：§12.1 原料不是 plain；各维不再单独保留 plain，前端叙事唯一直读 dim8。生产点 `dim2_structure_engine.py` 的 `_structure_plain`/plain 键在 dim8 改造时移除。

### ⚠️ 不产话术、仅供内部参考
- **`chanlun_phase`**（#12）：audit「结构健康度」已改读 `structure_health_score`（466 拍板）；若产话术会与"健康度"叙事重复。**保留键、不产话术**；其"因"（11 定理明细）透传给 dim8 作健康度叙事原料（见 §七-③）。
- **`vs_chip`**（#4）：筹码主源 dim4，dim2 不产话术（见 §三-1）。

### 🔒 归 JUD（评分/合成键，2026-09-21 复核修订）
- **`structure_health_score`**（#8，= `chanlun_strength` 同值）：11 定理 overall_score 基底 + 中枢/趋势/背驰/买卖点/换手/大盘信号项**加权合成**（多现状→一结论），且自带 `recommendation`（STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL 判定建议）——与 dim3 `health_score`（7 因子合成归 JUD）同构。**dim8 不产评分句**；评分键保留供 JUD 判定，`audit`「结构健康度」条件仍为主原料（判定链）。

### 🔒 纯契约键，仅供 JUD，不产话术
- **`level_cross_score`**（#11）：数值无档位语义，JUD 消费，dim8 不产句。
- **`ts_strength`**（#13 副键）：映射值语义弱，不产话术。
- **`trend_structure_signal`**（#13 主键）：**条件采用** —— 仅当 signal≠"none" 时产句（"123 买点突破形态"）；茅台=none → 跳过。

---

## 五、audit.conditions → 现状话术（dim8 归集主原料，茅台实例）

dim8 归集时，**优先材料是 dim2 `audit.conditions[]`**（每条=一条分析逻辑实例），直译为现状句：

| audit 条件 | 茅台 satisfied | 现状话术（示例） |
|---|---|---|
| 趋势方向 | ✓ | "缠论方向明确：下降" |
| 价格vs中枢 | ✓ | "价格位于日线中枢内部（1250.10~1292.70）" |
| 结构健康度 | ✗ | 评分已归 JUD；改以**因**呈现："11 定理 5/11 通过（overall 0.61），下降趋势-6、顶背驰-12、多中枢方向矛盾-8"（score details） |
| 背驰检测 | ✗ | "存在顶背驰警示（中枢背驰 0.78，依据：离开中枢后回调跌回中枢内、力度法双确认）" |
| 有确认买点 | ✗ | "当前无确认买点" |

这 5 条 + 结构化键（vs_support_resistance 距离、multi_level 方向等）构成走势结构维完整的"因为→所以→验证"叙事链。

---

## 六、定稿结论与待办

- **现状代码事实**：dim8 `_segment_from_dim` 当前 text=judgment.state（回退 plain）、evidence=plain —— **不符合本定稿**，属 464 待办第 4 项 dim8 改造（"实例→话术"重写 + 各维 plain 移除 + 跨维去重表落地）。
- **dim2 补产出项（待开实施号，2026-09-21 复核后更新）**：
  - ① 中枢**区位比例**（价格位置维补充；vs_zhongshu 只产定性"上方/内部/下方"）；
  - ② 若采 `trend_structure_signal` 话术则确认窗口逻辑（现状已具备）；
  - ③ `buy_sell_points_detail` 话术补 **reason**（判定条件=因），且 reason 内 type 转中文（"zhongshu类型"→"中枢背驰"）；**窗口截取**（当前全历史序列化，如万科含 2026-01~07 四个历史三卖，与 465-1 `_recent_by_type` 对齐取最近）；
  - ④ `divergence` 透传 **details + dual_confirmed**（检测条件=因）：趋势背驰 details 数值已齐全（strength_ratio/macd_area_ratio/macd_confirmed/a+A+b+B+c 各段），**中枢背驰 details 仅中枢 repr、缺"离开上沿/回中枢内"具体数值**需补；
  - ⑤ 透传 **theorem_check.details**（11 定理逐条 passed/score/issues/description）；呈现时**标注"数据不足跳过/占位"**（t4/t7/t8/t9 茅台 PASS 实为跳过、t9 占位实现），与真实 FAIL 区分，避免把"无线段"误读为结构缺陷；
  - ⑥ `structure_health_score` 评分合成迁 **JUD**（与 dim3 health_score 同批，439 号规划）。
- 本定稿供 464 待办第 4 项（dim8 改造）开工时直接引用为标准。

---

## 七、dim3 六步流程复核记录（2026-09-21）

**触发**：dim3 定稿（2026-09-20）确立"逐键是果是因深挖 + 规则标准核查 + 因透传优先 + 评分归 JUD"方法论后，复核 dim2 定稿（早于此流程）三项重点 + 四项次级点。**实证**：只读直连分库取 2026-09-18 真实日线，重跑 `ChanlunAnalyzer({'bi_zs_mode': True})` + `Dim2StructureEngine.evaluate`（茅台 600519 + 万科 000002 对照，与 §一/§五 实例值吻合）。

### ① structure_health_score 归属 → **归 JUD**（复核修订）
- **实证**：茅台 38 = 11定理 0.61×100（基底 61）＋ 有效中枢(+6) ＋ 多中枢方向矛盾(-8) ＋ 下降趋势(-6) ＋ 顶背驰(-12) ＋ 近期卖点(-轻)；另带 `recommendation`（HOLD）。合成性质与 dim3 `health_score`（7 因子）**完全同构**——"多现状→一结论"属 JUD。
- **修订**：§二 撤"结构健康度 38/100（不足）"话术行；评分键保留供 JUD；`audit`「结构健康度」条件仍为主原料（≥60 判定属 JUD 链）。dim8 健康度叙事改呈现"因"= 11 定理明细 + score details（见③）。

### ② 买卖点/背驰判定条件透传 → **买卖点已透传，背驰未透传**
- **买卖点（已透传）**：`buy_sell_points_detail` 已含 `reason`（判定条件=因）——茅台 first_sell 0.78@1323 "上涨趋势背驰，zhongshu类型"、万科 third_sell "反弹不进入中枢,[6.48,7.01],反弹深度大于中枢宽50%"；且含 point_type/confirmed/confidence/price/date/index。**复核修订**：话术补 reason；⚠️ reason 内 type 为英文需转中文；⚠️ 全历史序列化（万科 4 个历史三卖）需窗口截取（补产出项③）。
- **背驰（未透传）**：`Divergence.details` + `dual_confirmed`（面积法+力度法双确认）**已算出未透传**——与 dim3 divergence 细项 5 同构透传缺口。实证：万科趋势背驰 details 数值齐全（strength_ratio 0.46、macd_area_ratio 0.22、macd_confirmed=True、a+A+b+B+c 各段价）；茅台中枢背驰 details 仅 `{"zhongshu": "Zhongshu(up,[1250.10,1292.70]...)"}` 缺"离开+回中枢"数值（补产出项④）。

### ③ 11 定理得分依据 → **details 已算出未透传**
- **实证**：`theorem_check = {summary:{passed 5/11, overall 0.6082}, details:{t1..t11 每条 {passed, score, issues[], description}}}`——茅台 5/11。dim2 只读 `summary.overall_score` 产 `chanlun_phase`（阈值 0.6），**details 未透传**。
- **⚠️ 呈现注意**：t1/t3/t6 茅台得 0 分源于"无线段数据"（日线笔中枢模式无线段属正常，446-D2），t4/t7/t8/t9 为"数据不足跳过"、t9 为"占位实现"——透传时须标注"跳过/占位"，否则会把数据不足误读为结构缺陷（补产出项⑤）。
- `chanlun_phase`（健康/欲病）= 0.6 阈值二态果：保留键不产话术 ✅ 维持；其"因"即本项透传的定理明细。

### 次级复核点（维持原定稿，备注）
| 复核点 | 结论 |
|---|---|
| vs_zhongshu 定性"上方/内部/下方" | ✅ 维持——定性为果；"因"（中枢区间+时效）已在话术中；**区位比例**补产出已列（补产出项①） |
| trend_structure_signal 条件采用 | ✅ 维持——signal≠none 才产句，已对齐"实例"思路 |
| multi_level_direction_text | ⚠️ 方向一致是"果"；"因"= 各级别 direction_map（457 已产）——可选补产出，暂不列入实施 |
| chanlun_phase 与健康度矛盾 | ✅ 已消解（466：audit 改读 structure_health_score ≥60） |

### 复核后 dim2 键最终去向（2026-09-21 更新版）
| 输出键 | 去向 | 说明 |
|---|---|---|
| `structure_health_score` / `chanlun_strength` | **归 JUD** | 合成评分 + recommendation；键保留，dim8 不产句 |
| `buy_sell_points_detail` | dim8 采用（补 reason+窗口） | reason 已透传，补中文类型 + 最近窗口截取 |
| `divergence` 三键 | dim8 采用（补检测条件） | 透传 details + dual_confirmed |
| `theorem_check.details` | dim8 采用（新透传） | 11 定理逐条，标注跳过/占位 |
| `chanlun_phase` | 不产话术 | 二态果，因=定理明细 |
| 其余键 | 维持 §二/§三/§四 原定稿 | 不变 |
