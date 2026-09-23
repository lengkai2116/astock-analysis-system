# 464 号｜dim7 在 dim8 现状描述中的输出定稿（收益驱动）

> **🔖 dim8 细化基准**：本文档为 **dim7 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim7 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、437-A §2.7（收益驱动，D2=A 并入 summary）展开，逐键深挖 + 逐键拍板（采用/去重/仅 JUD）+ 话术模板。
>
> **范围**：只定"dim7 产出哪些、用什么话术、归哪个维、补哪些透传项"；**不改任何引擎判定逻辑**（445 冻结基准）。
>
> **状态**：✅ **定稿**（2026-09-23 六步流程完成；第三步逐键拍板 **1A/2A/3A/4A** 结构 + 第四步话术模板 + 第五步拍板 **B 方案**：潜力六维全列标注来源）。
> **前置**：476 dim7 SIG 分位表接线 + fcf/EV 单位修正、477 行业分类映射（东财 111 行业→七类）、478 daily_basic 5 年回补（1089 交易日）——均已闭环，本定稿基于修复后可靠数值。
> **实例贯穿**：茅台 600519.SH（`extreme_low`／composite 1.2134／audit 8/8）＋ 万科 000002.SZ（`extreme_high`／composite -0.545／audit 3/8），2026-09-23 daemon 停止态真实 `StatusEngine.evaluate` 全链路，8 股全跑通无 FATAL（探针 `backend/scripts/_dim7_definition_probe.py` / `_dim7_sig_probe.py` / `_dim7_tags_probe.py` / `_dim7_audit_probe.py`）。

---

## 〇、核心原则（对齐 dim2-dim6 + 444：现状=因，绝不是果）

- **现状（因）= 被满足的具体条件/实例 + 结构化键值**（`audit.conditions` + `status_description` 结构化键）。
- **dim8 归集 = 实例→话术**，不是 plain 拼接（dim7 无 `plain` 键）。
- **评分/合成/灯色键归 JUD**：`judgment` 全 7 键 + `potential_score`/`potential_strength`（六维加权评分，dim3 `health_score` 同构先例）。
- **透传优先、不重算**：pe/pb 5 年分位、FCF/股息/营收、潜力六维明细引擎已透传（第③步核查**无缺口**，不登记补产出）。
- **维度归 437 第二层**：dim7 = **收益驱动**（契约键无，437-A **D2=A 并入 summary 尾置**，不产 valuation 段；436 B1 契约维持）。

---

## 一、dim7 全量最细分析结论输出项（茅台/万科真实实例）

> 实例 = 2026-09-23 daemon 停止态真实 `StatusEngine.evaluate(ts_code)` 输出（`dim_engine_results['valuation']`），477/478 修复后数值。

### 1.1 三层全键清单（对照现状代码 `dim7_valuation_engine.py:evaluate`）

**status_description（12 键）**

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `valuation_level` | 五级中文 + composite | `_compute_valuation` 五锚加权 → composite → 截面分位/绝对阈值分档（476 SSOT：tags 优先） |
| 2 | `pe_percentile` | PE近5年X%分位 | df_basic pe_ttm 历史分位（≥20 正样本；478 后 5 年真实） |
| 3 | `pb_percentile` | PB近5年X%分位 | 同 pe |
| 4 | `fcf_yield` | 自由现金流收益率X% | FCF/(total_mv×1e4)×100（476 EV 修正同口径） |
| 5 | `dividend_yield` | 股息率X% | dv_ttm 最新 |
| 6 | `revenue_growth` | 营收同比X% | `_revenue_yoy` 同月跨年同比（320） |
| 7 | `fina_health` | ✅/⚠️/🚫+三态 | 461-2 SSOT=tags（RAW 预计算），三维 fail_count |
| 8 | `value_trap` | 价值陷阱（ROCE<15%，条件输出） | 449（tags 预计算） |
| 9 | `growth_trap` | 成长陷阱（PEG>2，条件输出） | 449（实算 peg_gt2） |
| 10 | `potential_score` | 潜力评分X/100 | `_compute_potential` 六维加权（313/315；476 修 val 表） |
| 11 | `potential_strength` | 潜力评分数字 | 与 potential_score 同值（数字副本，dim_adapter 消费） |
| 12 | `potential_breakdown` | 六维明细 JSON | val/earn/sector/event/fund/trend 各维分位（476 D4 修 val 表） |

**judgment（7 键）**：`valuation_level{value,light}`／`valuation_deviation{value,light}`／`fina_health{value,light}`／`potential_strength{value,light}`／`overall_light`／`overall_direction`／`continuous_value`（(composite+2)/4）。

**audit（8 条件 + 3 汇总）**：①PE数据可用 ②PB数据可用 ③FCF数据可用 ④股息率>0 ⑤财务健康（三维文案，464-4 对齐）⑥营收正增长 ⑦ROCE达标 ⑧无成长陷阱；+ `satisfied_count`／`total_count`／`confidence`。

### 1.2 完整实例（两股对照，477/478 后数值）

**600519.SH 贵州茅台**（`valuation_level=extreme_low`）
- `pe_percentile="PE近5年3.1%分位"`／`pb_percentile="PB近5年5.1%分位"`（478 后 5 年极低位）
- `fcf_yield=1.8786%`／`dividend_yield=4.15%`／`revenue_growth=+1.47%`
- `fina_health=pass`；`value_trap=null`／`growth_trap=null`
- `potential_score="潜力评分89/100"`；`potential_breakdown={"val":1.0,"earn":0.986,"sector":0.5,"event":0.6,"fund":0.3,"trend":0.5}`
- judgment `{extreme_low,green, dev:24.3,green, pass,green, 89,green, overall:green, dir:+1, cv:0.8034}`；audit **8/8（1.0）**

**000002.SZ 万科A**（`valuation_level=extreme_high`）
- `pe_percentile="PE近5年52.9%分位"`／`pb_percentile="PB近5年46.1%分位"`（478 后方向修正：原 9 个月窗口 99.4%→5 年 46.1%）
- `fcf_yield=-2.5093%`／`dividend_yield=10.53%`（478 回补后有值，低股价推高）／`revenue_growth=-33.38%`
- `fina_health=fail`；`value_trap="ROCE低于15%，存在价值陷阱风险"`／`growth_trap=null`
- `potential_score="潜力评分0/100"`；`potential_breakdown={"val":0.016,"earn":0.04,"sector":0.5,"event":0.7,"fund":0.5,"trend":0.8}`
- judgment `{extreme_high,red, dev:-10.9,red, fail,red, 0,red, overall:red, dir:-1, cv:0.3638}`；audit **3/8（0.375）**（财务/营收/ROCE 不满足）

**8 股分布**：`valuation_level` = 2 extreme_low（茅台/宁德）+ 2 fair（平安/招行系外）+ 3 extreme_high（万科/比亚迪/平安银行/招行系）+ 1 high（中芯）；audit 8/8 仅茅台 1 只（其余 5-7/8）。

---

## 二、逐键深挖（果/因 + 规则来源）

| # | 键 | 定性 | 规则标准来源 |
|---|---|---|---|
| 1 | `valuation_level` | **果**（五锚加权→五级分档定性） | 445（五级 5/20/80/95）/449（陷阱修正）/476-478（口径修复） |
| 2-3 | `pe/pb_percentile` | **因**（数据事实：5 年历史位置） | 478（5 年分位修复） |
| 4 | `fcf_yield` | **因**（FCF/市值） | 476（EV 修正）/449（FCF 口径） |
| 5 | `dividend_yield` | **因**（dv_ttm 最新） | 315 |
| 6 | `revenue_growth` | **因**（同月跨年同比） | 320 |
| 7 | `fina_health` | **果**（三维 fail_count 定性） | 461-2（SSOT）/464-4（文案） |
| 8-9 | `value_trap`/`growth_trap` | **果**（陷阱判定，449） | 449 |
| 10-11 | `potential_score`/`potential_strength` | **果**（六维加权评分） | 313/315 |
| 12 | `potential_breakdown` | **因**（六维分位明细） | 313/315/476（val 表 dev 分布） |
| 13-19 | judgment 全 7 键 | **果**（灯色/方向/合成） | 445 §6.1 契约键 |
| 20-27 | audit 8 条件 | **因**（分析逻辑实例化） | 464 §12.1 主材料 |

---

## 三、逐键拍板（1A/2A/3A/4A 结构，对齐 dim6 先例）

| # | 键 | 拍板 | 理由 / 去向 |
|---|---|---|---|
| 1 | `valuation_level` | **采用**（现状主结论） | 客观陈述估值分级（无操作建议），对齐 dim6 1A risk_level 先例；随收益驱动并入 summary |
| 2-6 | `pe/pb_percentile`、`fcf_yield`、`dividend_yield`、`revenue_growth` | **采用**（因透传） | 收益驱动段细则 |
| 7 | `fina_health` | **去重** | 与 dim6 **同源**（tags.fina_health）；437-A §三-2 财务健康风险归 risk 段（dim6 表述），dim7 不重复 |
| 8-9 | `value_trap`/`growth_trap` | **采用**（现状句） | 客观陈述陷阱判定（449，dim7 专属），随收益驱动入 summary |
| 10-11 | `potential_score`/`potential_strength` | **仅 JUD** | 六维加权评分 → JUD 判定输入（dim3 health_score 先例）；dim8 不产评分句 |
| 12 | `potential_breakdown` | **采用**（因透传） | 六维分位明细（val/earn/sector/event/fund/trend） |
| 13-19 | judgment 全 7 键 | **仅 JUD** | 灯色/方向/continuous_value 归 JUD |
| 20-27 | audit 8 条件 | **采用** | dim8 主材料（动态读 satisfied/total） |

---

## 四、437 维度映射（收益驱动）+ 话术模板

### 4.1 映射
- dim7 → **收益驱动**（437-A §2.7，契约键无 → **D2=A 并入 summary 尾置，不产 valuation 段**）。
- 跨维去重：fina_health → dim6（risk 段）；fund/trend/sector 维度 → dim4/dim2-3/第一层（潜力六维标注来源，B 方案）。
- 主源：pe/pb 分位、FCF/股息/营收、陷阱、潜力 val/earn → dim7 独占。

### 4.2 话术模板（因果链「因为→所以→验证」）

```
【所以】估值{水平}：{五锚加权 composite=X}
【因为】PE近5年X%分位、PB近5年X%分位（历史低位/高位）；
      自由现金流收益率X%、股息率X%、营收同比X%。
【附加现状句】存在价值陷阱（ROCE<15%）／存在成长陷阱（PEG>2）——条件输出
【潜力因明细】潜力六维：估值分位X / ROE分位X / 板块X / 事件X / 资金X / 趋势X
            （资金/趋势/板块维度见对应段——B 方案标注来源）
【验证】估值条件 N/8 满足（dim8 动态读 audit.satisfied/total）
```

### 4.3 两股示例（收益驱动段，477/478 后真实数值）

**600519.SH**：估值水平：极度低估（五锚加权 composite=1.21）。PE 近5年 **3.1%** 分位、PB 近5年 **5.1%** 分位——处于历史低位；自由现金流收益率 1.88%，股息率 4.15%，营收同比 +1.47%。潜力六维：估值分位 1.0、ROE 分位 0.99、板块 0.5、事件 0.6、资金 0.3、趋势 0.5。**估值条件 8/8 满足。**

**000002.SZ**：估值水平：极度高估（五锚加权 composite=-0.55）。PE 近5年 52.9% 分位、PB 近5年 46.1% 分位；自由现金流收益率 **-2.51%**，股息率 10.53%（低股价推高），营收同比 **-33.38%**。**存在价值陷阱（ROCE<15%）**。潜力六维：估值分位 0.02、ROE 分位 0.04、板块 0.5、事件 0.7、资金 0.5、趋势 0.8。**估值条件 3/8 满足**（财务健康/营收正增长/ROCE 达标不满足）。

---

## 五、用户拍板记录（2026-09-23）

| # | 决策点 | 拍板 |
|---|---|---|
| 1 | fina_health 去重（dim6 表述风险） | ✅ 确认 |
| 2 | value_trap/growth_trap 采用为现状句（非灯色） | ✅ 确认 |
| 3 | potential_score/strength 仅 JUD（breakdown 六维透传） | ✅ 确认 |
| 4 | 全部采用键去向=收益驱动并入 summary（D2=A） | ✅ 确认 |
| 5 | 潜力六维呈现：**B 方案**（六维全列标注来源：资金→dim4、趋势→dim2/3、板块→第一层） | ✅ B |
| 6 | 与 dim6 交叉引用（估值 vs 风险并列） | ✅ 确认 |
| 7 | 措辞边界（客观陈述，无操作建议） | ✅ 确认 |
| 8 | composite 分位/行业均值不透传（pe/pb 分位已支撑"历史低位"话术） | ✅ 确认 |
| 9 | audit confidence→data_warning 与 dim3 同构已知，不属本号 | ✅ 确认 |

---

## 六、补产出项（dim7 无引擎侧缺口；登记跨维待办）

- **引擎侧：无**（第③步核查 12+7+8 键全部已透传，无"已算未透传"）。
- **跨维/归集层待办**（沿用 dim6 定稿 §六 登记）：
  1. **评分迁 JUD（439 同批）**：dim7 `potential_score`/`potential_strength` 与 dim2/3/4/5/6 评分键全链统一迁 JUD。
  2. **dim8 层共性 P9-P15**（dim6 定稿提出，dim7 同适用）：audit `actual/threshold` 透传 · `evidence[:5]` 截断 · 中文化接入（dim7 未接入 dim8-cn-gateway）· 收益驱动段 T/E 表编制。
  3. **中文化网关接入 dim7**（dim8-cn-gateway 记忆：dim2/3/4 已接入，dim5-7 未接入）——`valuation_level` 中文已自产（LEVEL_CN），pe/pb "PE近5年X%分位" 已中文；fina_health emoji 已中文；`potential_breakdown` JSON 需展示层解析。

---

## 七、最终去向表

| 去向 | 键 |
|---|---|
| **收益驱动段（summary 尾置）** | `valuation_level`（主结论）＋ `pe/pb_percentile`/`fcf_yield`/`dividend_yield`/`revenue_growth`（因）＋ `value_trap`/`growth_trap`（现状句）＋ `potential_breakdown`（六维明细，标注来源） |
| **risk 段（dim6 表述）** | `fina_health`（去重，dim7 不产） |
| **仅 JUD** | judgment 全 7 键 ＋ `potential_score`/`potential_strength` |
| **audit（dim8 验证层）** | 8 条件（动态读 satisfied/total/confidence） |
