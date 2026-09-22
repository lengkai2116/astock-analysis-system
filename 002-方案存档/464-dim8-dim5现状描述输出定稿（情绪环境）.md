# 464 号｜dim5 在 dim8 现状描述中的输出定稿（情绪环境）

> **🔖 dim8 细化基准**：本文档为 **dim5 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim5 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、437 总纲第二层（情绪环境维）、`464-dim5情绪环境引擎输出项全量梳理与核查（464方法续）.md` §一/§四（逐键深挖 + 核查发现 A1-D2 全拍板）展开，逐键拍板采用/不采用/去重/边界/补产出。
>
> **范围**：只定"dim5 产出哪些、用什么话术、归哪个维、补哪些透传项"；**不改任何引擎判定逻辑**（445 冻结基准）；补产出项登记待开实施号。
>
> **状态**：✅ **定稿**（2026-09-22 六步流程完成；第三步逐键拍板 + 第五步用户三项确认 + 第六步存档）。
> **前置**：核查发现 A1/B1(470) + B2/B3/C1(471) + B4/C2/D1(472) 已全闭环；本定稿承接 `464-dim5情绪环境引擎输出项全量梳理与核查`。
> **实例贯穿**：茅台 600519.SH（快线中性0.35/慢线看多0.66/四象限MM/audit 4/5）+ 万科 000002.SZ（快线BUY 0.7/慢线中性0.3/四象限MM/audit 4/5），2026-09-18（computed_at 2026-09-21）交易日真实 dim5 evaluate 输出 + 快慢线内部"因"重算实证。

---

## 〇、核心原则（对齐 dim2/dim3/dim4 + 444：现状=因，绝不是果）

- **现状（因）= 被满足的具体条件/实例 + 结构化键值**（audit.conditions + status_description 结构化键）。
- **dim8 归集 = 实例→话术**，不是 plain 拼接；**plain 已删**（§12.1，dim5 现状 7 键无 plain）。
- **评分/合成/灯色键归 JUD**：judgment 全链（market/sector/stock_light + overall_light + overall_direction + continuous_value）——dim2 structure_health_score、dim3 health_score/pattern_score、dim4 crowding_score 同构，均归 JUD。
- **透传优先、不重算**：多数"因"（数值/明细）引擎已算出但未进 status_description——补产出透传，不另起计算。
- **维度归 437 第二层**：dim5 = **情绪环境**（市场/板块/个股三层面情绪 + BOCIASI 快慢线 + 四象限 + 情绪温度）。

---

## 一、dim5 全量最细分析结论输出项（茅台/万科真实实例）+ 逐键深挖

> 实例 = 2026-09-18 交易日真实数据，经 StatusEngine 全链路 evaluate + 快慢线/四象限内部"因"重算实证（探针 2026-09-22 抓取，daemon 停止释放 DB 锁后只读运行，8 股全跑通无 FATAL）。先看两股**完整现状输出原文**，再逐键深挖。

### 1.0 茅台 600519.SH 完整现状输出（真实 evaluate dump）

```
status_description = {
  'market':         '市场处于发酵（市场情绪发酵中，板块轮动活跃）',
  'sector':         '板块排名40以外（冷门板块）',
  'stock':          '个股健康（量价状态强健康，趋势确认强势）',
  'bociasi_quick':  '个股快线=中性（0.35）',
  'bociasi_slow':   '个股慢线ERP=看多（0.66）',
  'quadrant':       '大市四象限(中性·全市场分位)—市场情绪中性，常规配置',
  'temperature':    '57.9/100',
}
judgment = {
  'market_light': 'green', 'sector_light': 'yellow', 'stock_light': 'green',
  'overall_light': 'green', 'overall_direction': 1, 'continuous_value': 0.579,
}
audit = {
  'satisfied_count': 4, 'total_count': 5, 'confidence': 0.8,
  'conditions': [
    {'name':'市场情绪',        'satisfied':True,  'actual':'发酵',   'threshold':'非退潮/冰点'},
    {'name':'板块热度',        'satisfied':False, 'actual':'none',   'threshold':'top_20以内'},
    {'name':'个股情绪',        'satisfied':True,  'actual':'健康',   'threshold':'非极度消极'},
    {'name':'BOCIASI快线非看空','satisfied':True,  'actual':'NEUTRAL','threshold':'非BEARISH'},
    {'name':'四象限非高风险',   'satisfied':True,  'actual':'MM',     'threshold':'非HH'},
  ],
}
```

<details><summary>茅台快慢线/四象限内部"因"（已算未透传，evaluate 丢弃）</summary>

```
_bociasi_quickline → signal=NEUTRAL conf=0.35 pass=0
   indicators = {fast_vol:False, fast_price:False, fast_mom:False, fast_breadth:False}
   details    = {vol_ratio:1.26, price_offset_pct:-1.1, mom_5d_pct:-1.99, amplitude_pct:0.73}
_bociasi_slowline  → signal=BULLISH conf=0.66
   details    = {erp:3.5007, erp_signal:BULLISH}   # 1/19.23×100 − 1.7 ≈ 3.50%
BociasiQuadrantAnalyzer → MM
   fast_score=0.7858(高位,≥0.70)  slow_score=0.4845(中间带0.30~0.70)
   _cache = {ma20_ratio:0.5484, turnover_percentile:1, limit_ratio:35.33,
             rsi_percentile:0.5624, erp_percentile:0.6379, margin_trend:0.5434,
             dv_bond_diff:0.4518}
```

</details>

### 1.1 万科 000002.SZ 完整现状输出（真实 evaluate dump）

```
status_description = {
  'market':         '市场处于发酵（市场情绪发酵中，板块轮动活跃）',
  'sector':         '板块排名40以外（冷门板块）',
  'stock':          '个股健康（量价状态强健康，趋势确认强势）',
  'bociasi_quick':  '个股快线=偏多（0.7）',
  'bociasi_slow':   '个股慢线ERP=中性（0.3）',
  'quadrant':       '大市四象限(中性·全市场分位)—市场情绪中性，常规配置',
  'temperature':    '57.9/100',
}
judgment = {
  'market_light': 'green', 'sector_light': 'yellow', 'stock_light': 'green',
  'overall_light': 'green', 'overall_direction': 1, 'continuous_value': 0.579,
}
audit = {
  'satisfied_count': 4, 'total_count': 5, 'confidence': 0.8,
  'conditions': [
    {'name':'市场情绪',        'satisfied':True,  'actual':'发酵',   'threshold':'非退潮/冰点'},
    {'name':'板块热度',        'satisfied':False, 'actual':'none',   'threshold':'top_20以内'},
    {'name':'个股情绪',        'satisfied':True,  'actual':'健康',   'threshold':'非极度消极'},
    {'name':'BOCIASI快线非看空','satisfied':True,  'actual':'BUY',    'threshold':'非BEARISH'},
    {'name':'四象限非高风险',   'satisfied':True,  'actual':'MM',     'threshold':'非HH'},
  ],
}
```

<details><summary>万科快慢线/四象限内部"因"（已算未透传，evaluate 丢弃）</summary>

```
_bociasi_quickline → signal=BUY conf=0.7 pass=4
   indicators = {fast_vol:True, fast_price:True, fast_mom:True, fast_breadth:True}
   details    = {vol_ratio:5.93, price_offset_pct:18.2, mom_5d_pct:19.67, amplitude_pct:10.41}
_bociasi_slowline  → signal=NEUTRAL conf=0.3
   details    = {erp:None, erp_signal:NEUTRAL}   # 该交易日 pe_ttm 无正值 → 无 ERP
BociasiQuadrantAnalyzer → MM
   fast_score=0.7858(高位)  slow_score=0.4845
   _cache = {ma20_ratio:0.5484, turnover_percentile:1, limit_ratio:35.33,
             rsi_percentile:0.5624, erp_percentile:0.6379, margin_trend:0.5434,
             dv_bond_diff:0.4518}
```

</details>

### 1.2 逐键深挖

| # | 输出键 | 是果/是因 | 分析逻辑（规则标准实证） | 深挖要点（2026-09-22） |
|---|---|---|---|---|
| 1 | `market` | **果** + 因 | `_assess_market_emotion`：tags `sentiment_phase` → `PHASE_MAP`（六段论 ice/sprout/ferment/climax/ebb/regression + neutral，472 C2）→ 中文名+灯色；BOCIASI 四象限修正（HH→高位风险/LL→情绪底部/HL→高位震荡/LH→底部反弹） | 果=阶段名（发酵）；**因=sentiment_phase 原始阶段**（daemon 六段论，471 C1 降级标注）——PHASE_MAP 是映射话术；四象限修正时 market 被覆盖为修正语态 |
| 2 | `sector` | **果** + 因 | `_assess_sector_emotion`：tags `sector_heat` 枚举（top_10/top_20/normal/none）+ data_context `sector_heat` 按行业补排名（442） | 果=等级（none 冷门）；**因=heat 等级 + 行业排名**（sector_heat[industry].rank，茅台=黄金 none rank101 / 万科=bank none） |
| 3 | `stock` | **果** + 因 | `_assess_stock_emotion`：tags `volume_price_fit`（healthy/diverging/neutral）+ dim3 `judgment.state=='严重背离'`→极度消极（447 T4a） | 果=情绪档（健康）；**因=volume_price_fit + dim3 严重背离状态**（个股量价状态主源实为 dim3，见去重边界） |
| 4 | `bociasi_quick` | **半果半因** | `_bociasi_quickline`（dim5 内嵌，470 A1）：4 指标（当日量>5日均量×1.5=fast_vol / 收盘>5日均价=fast_price / 5日动量>3%=fast_mom / 当日振幅>3%=fast_breadth）；pass≥3→BUY 0.65 / ≥2→WATCH 0.50 / 非price∧动量<-3→BEARISH 0.35 / else NEUTRAL 0.35；vol+mom±0.05、breadth∧非price-0.05，clamp 0.1-0.9 | 果=信号（茅台中性/万科BUY）；**因=indicators 4 布尔 + details 数值**（vol_ratio/price_offset/mom/amplitude，`_bociasi_quickline` **已算进 details 但 evaluate 丢弃**→补透传） |
| 5 | `bociasi_slow` | **半果半因** | `_bociasi_slowline`（dim5 内嵌）：ERP=1/PE_ttm×100−国债（**CN_10Y_BOND_YIELD_PCT 统一 1.7**，470 B1）；绝对阈值 >5 强多0.75/>3 弱多0.60/<0.5 强空0.75/<1.5 弱空0.60（471 B2 删 sb 死分支=纯 ERP）；len<60→'数据不足（个股 pe_ttm 序列<60日）'（472 B4） | 果=信号（茅台 BULLISH 0.66/万科 NEUTRAL 0.3）；**因=ERP 数值 + erp_signal**（details 已算，evaluate 只取 signal/confidence→补透传）；万科 erp=None（pe_ttm 该日无正值） |
| 6 | `quadrant` | **果** + 因 | `BociasiQuadrantAnalyzer.analyze`（framework 活跃）：快线 4 键（ma20_ratio/turnover_percentile/limit_ratio/rsi_percentile）+ 慢线 3 键（erp_percentile/margin_trend/dv_bond_diff，447 T3a/458 分库）→ `_classify`（fast/slow 各≥0.70 高 / ≤0.30 低 / 中间→**MM**） | 果=象限（两股均 MM）；**因=fast_score/slow_score + `_cache` 7 指标明细**（analyze **已算 details 但 evaluate 只取 quadrant/desc/mult**→补透传）；8 股同 MM=全市场共享指标，非回退（真实中性，见 §五） |
| 7 | `temperature` | **果**（0-100） | SSOT `calc_emotion_temperature`（447 T5）：7 权重 market_phase 0.25/limit_up 0.15/blast_rate 0.10/sector_heat 0.15/volume_price 0.15/margin 0.10/breadth 0.10；BOCIASI 修正 temp=原×0.4+(0.6×fast+0.4×slow)×100×0.6 | 果=温度分数（茅台/万科均 57.9）；**因=7 入参明细**（sentiment_phase/limit_up_count/sealing_rate/sector_rank/volume_price_fit/margin_change_pct/breadth）；breadth 用 ma20_ratio 近似（472 D1 已订正 docstring） |
| — | `plain` | — | 已删（2026-09-15 dim8 改造 §12.1） | ❌ 无 plain，现状 7 键 |
| — | `judgment` | **果/评分/灯色** | market/sector/stock_light + overall_light + overall_direction + continuous_value(temperature/100) | **全归 JUD**（439 灯色迁移） |
| — | `audit.conditions` 5 条 | **每条=一条分析逻辑实例（dim8 主原料）** | 市场情绪/板块热度/个股情绪/BOCIASI快线非看空/四象限非高风险 | 5 条照录 evidence |

---

## 二、规则来源已封存（dim5 特有）

- `market` 阶段：447 T2a（去 recovery，六段论）+ 471 C1（daemon 降级为四档 climax/ebb/ice/ferment + sprout/regression 兜底→ferment，接受降级标注）+ 472 C2（PHASE_MAP 补 neutral 键对齐温度 SSOT）+ BOCIASI 四象限修正（LL/LH/HL/HH 覆盖）。
- `bociasi_quick`：470 A1（framework 双类死代码清理，dim5 内嵌）+ 原本地 4 指标算法（358 号）。
- `bociasi_slow`：470 B1（国债 2.85→CN_10Y_BOND_YIELD_PCT 统一）+ 471 B2（删 sb 死分支，纯 ERP）+ 472 B4（len<60 数据不足标注）。
- `quadrant`：447 T3a（慢线 3 键历史绝对分位 + 去股债位置差）+ 458 R1（分库路由修复静默回退）+ 471 C1（用户拍板接受主源降级）+ B3（双语义分层：个股慢线ERP vs 大市四象限·全市场分位）。
- `temperature`：447 T5（唯一代码源 emotion_temperature.py）+ 472 D1（breadth=ma20_ratio 近似标注）。

---

## 三、逐键拍板结果（第三步，2026-09-22）

| # | 输出键 | 去向 | dim8 话术模板（茅台/万科示例） | 补产出 |
|---|---|---|---|---|
| 1 | `market` | **dim8 采用（改因）** | "市场**发酵**（市场情绪发酵中，板块轮动活跃；全市场 sentiment_phase=ferment，PHASE_MAP 映射）" | 无（sentiment_phase 因透传） |
| 2 | `sector` | **dim8 采用（补排名因）** | "板块**排名40以外**（黄金行业 rank101，冷门板块；heat=none）" | 无（sector_heat 已有 rank） |
| 3 | `stock` | **dim8 采用（改因，主源 dim3）** | "个股**健康**（量价状态强健康，趋势确认强势；volume_price_fit=healthy，dim3 强健康同源）" | 无（volume_price_fit 因，dim3 主源） |
| 4 | `bociasi_quick` | **dim8 采用（补数值因）** | "个股快线**偏多**（置信0.7：4指标全中——放量5.9×/价偏移+18.2%/5日动量+19.7%/振幅10.4%）" | **①透传 bociasi_quick.details+indicators** |
| 5 | `bociasi_slow` | **dim8 采用（补数值因）** | "个股慢线ERP**看多**（置信0.66：ERP=3.50% > 3%弱多阈）"；或"**数据不足**（个股 pe_ttm 序列<60日）" | **②透传 bociasi_slow.details（erp 数值）** |
| 6 | `quadrant` | **dim8 采用（补分位因）** | "大市四象限**中性·全市场分位**（快线0.79高位/慢线0.48低位→中间带 MM；快MA20占比54.8%换手/慢ERP分位63.8%融资54.3%股债45.2%）" | **③透传 quadrant 内部 fast/slow_score + _cache 7 指标** |
| 7 | `temperature` | **dim8 采用（转五档话术）** | "情绪**偏热 57.9**（market_phase 发酵基温60+板块/量价权重，BOCIASI 修正后，五档映射见 §六-④）" | **④温度转五档话术**（continuous_value 归 JUD） |
| — | `plain` | ❌ 删除 | — | 已删（dim8 改造） |
| — | `judgment` 全链 | 🔒 全归 JUD | — | 灯色/方向/continuous 迁 JUD（439 同批） |

---

## 四、audit.conditions → 现状话术（dim8 归集主原料，茅台/万科实例）

dim8 归集时**优先材料 = `audit.conditions[]`**（每条=一条分析逻辑实例 `{name,satisfied,actual,threshold}`），直译现状句；5 条作 evidence：

| audit 条件 | satisfied 判定（茅台/万科） | 现状话术（示例） |
|---|---|---|
| 市场情绪 | 非退潮/冰点（两股 PASS，actual=发酵） | "市场情绪发酵（非退潮/冰点）" |
| 板块热度 | top_10 或 top_20（两股 FAIL，actual=none） | "板块热度冷门（rank40 以外）未达 top_20" |
| 个股情绪 | 非极度消极（两股 PASS，actual=健康） | "个股情绪健康（非极度消极）" |
| BOCIASI快线非看空 | 非 BEARISH（茅台 NEUTRAL PASS / 万科 BUY PASS） | "快线中性/偏多（非看空）" |
| 四象限非高风险 | 非 HH（两股 MM PASS） | "四象限中性·全市场分位（非高风险）" |

---

## 五、跨维去重/协作边界

1. **板块热度**：主源 **dim5**（437 归属）——`sector_heat` 行业排名 + `sector['heat']` 等级，dim8 段为主。
2. **个股情绪档**：主源 **dim3**（量价状态）——dim5 `stock` 读 `volume_price_fit` + dim3 `judgment.state`（严重背离→极度消极，447 T4a）；dim8 中个股情绪呈现以 dim3 量价为因、dim5 只作情绪档概括，不重复产量价细节。
3. **市场情绪阶段（六段论）**：主源 **dim5**——daemon RAW `sentiment_phase`（471 C1 降级为四档+兜底）经 `_assess_market_emotion` 呈现；同源 `emotion_ext.market_emotion`（447 T2a 后一致 ferment）。
4. **BOCIASI 快慢线/四象限**：个股快线慢线 = dim5（dim5 `bociasi_quick/bociasi_slow`）；大市四象限 = dim5（framework quadrant）——**B3 双语义分层**：个股慢线 ERP（绝对阈值）vs 大市四象限·全市场分位（历史分位），dim8 话术前缀必须区分。
5. **情绪温度**：主源 **dim5/SSOT**——`temperature`（emotion_temperature.py 唯一代码源），供 JUD 评分。

---

## 六、补产出项汇总（待开实施号）

> 快慢线/四象限的"因"（数值/明细）**引擎已算出但 status_description 未透传**——与 dim2/dim3/dim4 相同透传缺口。dim5 现有 status_description 只输出 signal+confidence（茅台/万科实测），details/indicators/cache 被 evaluate 丢弃。补产出①-③属透传；④温度转五档话术属表述层。

| # | 补产出项 | 数据位置（已算未透传） | 涉及改动 | 关联拍板 |
|---|---|---|---|---|
| ① | 透传 `bociasi_quick.details`（vol_ratio/price_offset_pct/mom_5d_pct/amplitude_pct）+ `indicators`（fast_vol/price/mom/breadth 4 布尔）到 status_description | `_bociasi_quickline` 返回值 `details` 已算（L139-141），evaluate L374 只取 signal/confidence/pass_count | dim5 evaluate 快线封装 | 第三步-透传缺口 |
| ② | 透传 `bociasi_slow.details`（erp 数值 + erp_signal）到 status_description | `_bociasi_slowline` 返回值 `details` 已算（L217-219），evaluate L383 只取 signal/confidence | dim5 evaluate 慢线封装 | 同上 |
| ③ | 透传 `quadrant` 内部 `fast_score`/`slow_score` + `_cache` 7 指标明细（ma20_ratio/turnover/limit/rsi/erp/margin/dv_bond）到 status_description | `BociasiQuadrantAnalyzer.analyze` 返回值 `fast_score/slow_score/details` 已算（bociasi_quadrant.py），evaluate L393-403 只取 quadrant/desc/mult | dim5 evaluate 四象限封装 | 同上 |
| ④ | 温度转五档话术（如 冰冷<20/偏冷20-40/中性40-60/偏热60-80/过热≥80） | `temperature` 数值已有，dim5 status_description 现裸打 "57.9/100" | dim5 status_description 话术封装（纯表述，不改连续值） | 用户拍板-五档话术 |
| — | `judgment` 全链（灯色/方向/continuous_value）迁 JUD | — | dim8 叙事不产 + JUD（439 同批） | 第二步 |
| — | plain 删除 | dim5 已删 | dim8 改造（§12.1） | 第二步 |

> **实施规范**（沿用 461/464-17 先例）：①-④ 属透传/表述（445 冻结边界内可改，前端数据获取/口径）；实施时新增锁定测试 + 全链路回归（含 StatusEngine 真实链路）。dim5→dim8 归集属 464 待办第 4 项（dim8 改造），与其余各维一并落地。

---

## 七、定稿结论与待办

- **dim5 定稿六步完成**：第一步（全量输出项清单，茅台/万科对照）→ 第二步（逐键深挖，3 透传缺口 + judgment 归 JUD + 观察项）→ 第三步（逐键拍板，7 键采用 + 3 补产出）→ 第四步（映射 437 第二层，情绪环境）→ 第五步（用户拍板）→ 第六步（本文档存档 + 索引登记 + 记忆）。
- **待 open 实施号**：§六 ①-④（透传快慢线/四象限内部因 + 温度转五档话术）+ 灯色迁 JUD（439 同批）。
- **dim5 观察项（定稿标注，后续斟酌）**：①`stock` 个股情绪随 dim3 量价状态，dim5 层档位概括与 dim3 细节须在 dim8 组合时防重复；②BOCIASI 四象限全市场 8 股同值（market_stats 全市场共享），个股差异只体现在快慢线/stock/temperature 的部分入参——dim8 呈现时"大市四象限"应标注全市场口径；③`temperature` 因 BOCIASI 修正占 60% 权重 + market_phase 基温共享，茅台/万科同为 57.9——已拍板转五档话术（§六-④），并以 7 入参明细作因透传。

---

## 八、dim8 中文标注网关（dim5 现状 + 留待）

dim4 定稿 §八 已将 `_to_display_text` 中文网关扩展到所有维段 + summary，但 **dim5-7 段未接入**（核查 D2）。dim5 段接入后需映射：
- BOCIASI 信号 `BUY/WATCH/BEARISH/NEUTRAL/BULLISH` → 偏多/观望/看空/中性/看多（`bociasi_signal_cn` 已存在于 enum_cn_map）。
- 四象限 `LL/LH/HL/HH/MM` → 情绪底部/底部反弹/高位回调/行情尾声/中性（`quadrant_cn` 已存在）。
- `top_10/top_20/normal/none` → 前10/11-20/21-40/40以外（sector_heat 中文）。
- `ice/sprout/ferment/climax/ebb/regression/neutral` → 冰点/萌芽/发酵/高潮/退潮/回归/正常（PHASE_MAP 中文已就绪）。
- **留待 464 待办 dim8 改造**（用户"后续也许"），非引擎缺陷。

---
*本文档为 dim5 定稿存档（代码不改，仅定稿）；§六 补产出项登记待开实施号。本定稿供 464 待办第 4 项（dim8 改造）与各维引擎补产出开工时直接引用为标准。*
