---
title: dim2-dim7 分析输出项全量梳理（SIG 现状层，逐项结论+分析逻辑）
type: 核查文档（2026-09-19 会话内逐项核对代码后形成；§八 存疑点逐项沟通处置中）
date: 2026-09-19
version: v0.3（八-1~八-4 + 464-5 chanlun_strength 取键修复已处置）
status: 🔄 逐项确认中（八-1~八-4 + 464-5 已完成）
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号为 445 §6 评估范围「输出项」的完整落地清单
  - 460-dim1取数与各dim原料供应核查报告——取数链路背景
  - 461-dim1取数一致性合并实施号——461-1~13 已全部落地，本号引用其修复结果
  - 444-SIG股票现状描述的事实层仲裁与叙事框架方案——SIG 现状=因，本号梳理的是因的产出项
  - 437-A-dim8归集映射设计——dim8 归集对象即本号输出项
  - 464-dim8现状描述输出定稿基准索引——**各维定稿基准的权威引用入口**（本号为定稿原料，勿当作定稿基准）
  - 464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）——**dim4 完整版独立文档**（本号 §三 为其简要版 + 核查发现另载）
---

# 464 — dim2-dim7 分析输出项全量梳理

> **定位**：把 SIG 侧 dim2-dim7 六引擎 `evaluate()` 产出的**每个分析输出项**逐一列出「输出结论 + 对应分析逻辑（规则/阈值/窗口/枚举/数据源）」，作为 445 §6 输出项评估的完整落地清单、dim8 归集与 JUD 消费的字段级依据。
>
> **⚠️ 与定稿基准区分**：本号为**输出项梳理清单（原料）**，**不是** dim8 输出定稿基准。各维已定稿标准见《464-dim8现状描述输出定稿基准索引》（dim2/dim3 ✅，dim4~dim7 ⏳）。
>
> **方法**：逐文件读 `evaluate()` + 全部 `_assess_*`/子引擎函数，与 461 号各子项落地状态交叉核对；本轮发现的疑点记入 §八（不改代码、不拍板）。
>
> **边界**：本号只梳理**现状（因）输出**；灯色/判定归 JUD（SIG/JUD 边界共识），此处列出的 light/overall_light 均为 SIG 建议值。

---

## 〇、统一输出契约

六引擎 `evaluate(dims, tags, signals, lifecycle, data_context)` → 统一返回：

```
{
  status_description: { 现状描述（因）——各输出键见各维清单 },
  judgment: { 分析结论（果）——state/light/score/overall_light/overall_direction/continuous_value },
  audit: { conditions: [{name, satisfied, actual, threshold}], satisfied_count, total_count, confidence },
}
```

- **status_description**：dim8 归集对象（437-A），前端现状描述主体。
- **judgment**：供 JUD 判定；`light/overall_light` 是 SIG 建议灯色，非最终判定。
- **audit**：条件稽核 `conditions[].{name,satisfied,actual,threshold}`，`confidence = satisfied/total`。445 后各维已从「全为数据门槛恒真」改为**判读结论条件**（454/455/459 号）。

---

## 一、dim2 结构位置引擎（Dim2StructureEngine）

**数据源**：daily_df（前复权，data_context 优先）→ `ChanlunAnalyzer({'bi_zs_mode': False})`（446 号日线=线段中枢）；457 号多级别联立（weekly_df/hourly_df）；shared `calc_support_resistance`；tags 各预计算键。

### 1.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `vs_zhongshu` | 价格相对**当前有效中枢**的位置：上方/下方/内部/无有效中枢 | `_assess_vs_zhongshu`：`_select_current_zhongshu`（463 号）从 zs 列表尾部向前选中枢，`end_date` 距今 >180 天判失效跳过；最新收盘 vs 中枢上下沿比较；全失效→"无有效中枢"；缠论不可用→tags `position_vs_zs` 兜底 |
| 2 | `vs_ma` | 均线排列 | tags `ma_alignment` → `ma_alignment_cn`；缺失→"均线数据不足" |
| 3 | `vs_support_resistance` | 距支撑/压力位 % | shared `calc_support_resistance`：支撑=MA20 与近 20 日低点取大（须低于现价、距现价≤15% 封顶）；压力=高于现价的最近位（60 日高/MA60） |
| 4 | `vs_chip` | 筹码集中度 + 获利盘 | tags `chip_concentration`（concentrating/dispersing/stable，445-A3 英文枚举）+ `profit_ratio` |
| 5 | `vs_indicator` | 均线形态 + RSI 强弱 | tags `indicator_status` 的 `ma=` 段（bullish/bearish/mixed）；`rsi`（461-1 SSOT=chip_fund_ext.rsi，≥70 偏强 / ≤30 偏弱 / 中性）——**已删除市场级 rsi_percentile 概念错位** |
| 6 | `chanlun_direction` | 缠论趋势 up/down/unknown | framework `_determine_trend`（446/463）：主判据=价格 vs 当前有效中枢（>上沿 up / <下沿 down）；中枢内部→与前一中枢比较（上移/下移/中心）；无有效中枢→长期横盘判据（近 3 年区间中部 30%~70% 且近 1 年未显著突破→盘整）→ 最近 3 段方向多数派兜底 |
| 7 | `trend_basis` | 趋势判定依据文案 | `_determine_trend_basis` 与 6 逐一对齐（"价格突破中枢上沿"/"中枢内部-中枢上移"/"长期横盘"等），444 因果链的因 |
| 8 | `chanlun_strength` | 结构强度 0-100 | `ChanlunScorer.score`：买点 +30（一买+20/二买+15/三买+10）、卖点 -20（一卖-15/二卖-10/三卖-8）；价格匹配度（买点跌破>5% 惩罚、远离>30% 追高惩罚、卖点反弹加分）；底背驰+15/顶背驰-10；趋势 up+10/down-5；中枢+5；多中枢方向矛盾-10、笔段矛盾-8、中枢扩张-5；市场上下文（换手>10%+5/>5%+3、大单±3、大盘±5）；最后 +50 归一到 0-100 |
| 9 | `buy_sell_points` | 前 3 买卖点字符串 | buy_points+sell_points 前 3 条 |
| 10 | `multi_level` / `multi_level_direction_text` | 周/日/60min 区间套结论 | 457 号 `MultiLevelChanlunAnalyzer`（MultiLevelConfig.enabled 开关；键契约 enabled/levels/direction_map/direction_text/near_levels）；数据不足不产键 |
| 11 | `level_cross_score` | 级别交叉校验分 | 445 D10：`ChanlunLevelValidator.validate(df).cross_score`（日/周/月三级分析+级别定理验证；默认 0.5） |
| 12 | `chanlun_phase` | 结构健康度：健康/欲病 | 11 定理 `theorem_check.summary.overall_score ≥0.6` → 健康（445 契约键补产出） |
| 13 | `trend_structure_signal` / `ts_strength` | 趋势结构信号 + 强度 | `TrendStructureDetector.detect(df)`：三假设（突破下降趋势线/回调不创新低≥1%/突破反弹高点≥1%）→ signal（123_buy_breakout/higher_low/none）；strength 字符串映射 strong→0.3/basic→0.1（供 dim_adapter 读 float） |
| 14 | `buy_sell_points_detail` | 买卖点结构化明细 | type(buy/sell)/point_type/confirmed(conf≥0.6)/confidence/price/date/index/reason |
| 15 | `stage_name` | 结构态：上升/下降/盘整 | 缠论 trend 映射（440 号引擎自产） |
| 16 | `divergence` / `divergence_type` / `divergence_strength` | 背驰方向/类型/强度 | divergence.direction up→底背驰/down→顶背驰；type→趋势/盘整/中枢背驰；strength=confidence（445 契约键，供 conflict_matrix C6/C10） |
| 17 | `plain` | 白话总结 | `_structure_plain` 拼接中枢位置+均线+支撑阻力+筹码 |

### 1.2 judgment
`structure`（上升/下降/盘整）、`position`（price_position 标签）、`light`（上升 green/下降 red/盘整 yellow）、`overall_light`、`overall_direction`（+1/-1/0）、`continuous_value`（strength 归一）。

### 1.3 audit 条件（454 号：2 数据门槛 + 3 判读）
1. 趋势方向：trend 非 未知/无/无数据
2. 价格vs中枢：position 非空
3. 结构健康度：chanlun_phase=健康（11 定理 ≥0.6）
4. 背驰检测：无背驰
5. 有确认买点：buy_sell_points_detail 存在 type=buy 且 confirmed

---

## 二、dim3 量价健康引擎（Dim3VPEngine）

**数据源**：daily_df、tags（volume_price_fit/volume_ratio/ma_alignment/chip_concentration/rsi/RPS）、PatternEngine、data_context（relative_strength）。

### 2.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `vp_state` | 量价状态：强健康/背离/中性 | tags `volume_price_fit`（framework compute_volume_price_signal 产）映射 healthy→强健康/diverging→背离/其余中性（440 号自产） |
| 2 | `health_score` | 健康度 x/10 + 档位 | 10 分制：`raw = vp_score(healthy 2/diverging -1/其他1) + ve 量能(量比>2→2/>1.2→1.5/>0.8→1/else 0) + ms 均线(多头1/空头0/混合0.5) + cs 筹码(concentrating 1/else 0.5) + is_RSI(60<rsi≤70→1、30≤rsi<40→0.8、rsi>70或<30→0.2、else 0.5；461-1 SSOT=rsi) + rps_factor(RPS>85→+1，445 补产出) + dp 背离(-1.5) + 形态偏差((pattern_score-5)/5×1.5)`；`hs=(raw+4)/12×10` clamp 0-10；分档 ≥8 强健康/≥6 健康/≥4 中性/≥2 弱/else 严重背离 |
| 3 | `divergence` | 量价背离信号 | 450 号：删本地 MACD 兜底段，完全以 framework 权威标签 `volume_price_fit=='diverging'` 为准 |
| 4 | `volume_energy` | 量能强度 | 量比>2 显著放量/>1.2 温和放量/>0.8 正常/else 量能萎缩 |
| 5 | `pattern` | 形态识别 | PatternEngine 10 分制评分，前 3 形态名（pattern_code_cn） |
| 6 | `vol_ratio` | 量比 | 当日量/5 日均量（tags 预计算，缺省 1.0） |
| 7 | `pattern_score` | 形态评分 x.x/10 | PatternEngine 输出 |
| 8 | `rps` | RPS 相对强弱 | 445/461-1：data_context relative_strength rps_20d 优先、rps_60d 兜底，再回退独立查询；RPS>85 记 +1 分 |
| 9 | `granville` | 格兰威尔八准则分类 | `_classify_granville`（450 号多日粒度：5 日区间涨幅 + 5/20 日均量比率；455 号放量滞涨修正=近 3 日每根量>前20日均量×1.5 且 3 日涨幅和<1%）：涨>2%放量→量价齐升(量增>40%→井喷)/涨>1.5%缩量→价升量减/连续放量滞涨→放量滞涨/跌>2%放量→放量下跌/跌>1%缩量→回探缩量/跌>4%放量破MA20→放量破均线/标签 diverging→量价背离/else 量价中性 |
| 10 | `plain` | 白话总结 | 按 vp_state 拼装+量能+形态+RPS+健康度档位 |

### 2.2 judgment
`state`、`light`（强健康/健康 green、中性 yellow、背离/严重背离 red）、`score`（hs）、`overall_light`、`overall_direction`、`continuous_value`（hs/10）。

### 2.3 audit 条件（6 条）
1. 量价关系：强健康/健康
2. 健康度评分：hs≥5
3. 背离检测：无背离
4. 量能强度：温和/显著放量
5. 相对强弱RPS：RPS>85（**数据不足中性放行**）
6. 量价八准则：granville.rule 非负面（heavy_pressure/weakening/selling_pressure/breakdown/diverging，455 号升为 audit 证据项）

---

## 三、dim4 资金筹码引擎（Dim4ChipFundEngine）

> **📌 完整版独立文档**：本节约为 dim4 输出项简要梳理；**逐键实证 + 2026-09-21 全面核查发现（十项，实施号 464-6~464-15）见《464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）.md》**。

**数据源**：tags + data_context（chip_fund_ext/moneyflow_df/indicator_ma_df/indicator_other_df/cost_ext/margin_df）+ `PhaseDetectionEngine.compute_tags`（df≥30 根时真实阶段分析，覆盖基础标签）。

### 3.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `phase` | 主力阶段：建仓/洗盘/拉升/出货/护盘（未知） | `_assess_phase` 读 tags `main_force_phase`（461-6 后由 PhaseDetectionEngine 生产）映射；**df 可用时被 compute_tags 覆盖**。⚠️ 见 §八-1 枚举口径疑点 |
| 2 | `fund_flow` | 资金流向：强流入/强流出/中性 | `_assess_fund_flow`：tags `fund_flow` 5d_inflow→强流入/5d_outflow→强流出；被 PhaseDetector fund_flow 覆盖（inflow/outflow/mixed） |
| 3 | `cost_structure` | 筹码结构：集中度+ASR+CYQKL+获利盘+质量 | `_assess_cost_structure`：chip_concentration + ASR（活跃筹码比率）+ CYQKL（筹码穿透力）+ profit_ratio；quality 按 ASR 分档（>80 活跃/<30 沉寂）。~~⚠️ 461-9 后 chip 白名单已删 asr/cyqkl → 该两段数据源恒缺（死路径，quality 恒"中性"）~~ **已澄清（八-2）：asr/cyqkl 真生产者在 chip_fund_ext 组（443 R1），链路完整非死路径**；⚠️ quality 死输出见独立文档 §四-6 |
| 4 | `signal` | 筹码买卖点信号 | tags `buy_sell_point`（461-9 后 chanlun 白名单唯一保留键）→ 一买/二买/三买/一卖/二卖。⚠️ **映射缺 third_sell（三卖被吞）**，见独立文档 §四-11（464-16） |
| 5 | `retail_institution` | 散户与机构博弈 | building+5d_inflow→机构买入；distributing→主力出货；否则中性 |
| 6 | `margin` | 融资余额 5 日变化 | tags `margin_change_5d`，缺失时 margin_df 的 rzye 算 5 日变化（442 缺陷②修复）；>10% 杠杆上升 / <-10% 去杠杆 / 否则正常 |
| 7 | `crowding` | 拥挤度等级+建议+分数 | `CrowdingFactor.evaluate`：三信号（融资余额占比>流通市值 5% 高/<1% 低；换手率 vs 20 日均值 >1.5× 高/<0.5× 低；布林带宽度 p20 分位以下=高拥挤/p80 以上=低拥挤）→ ≥2 高信号→HIGH（score 0.7-1.0）/≥2 低信号→LOW（0.1-0.3）/否则 MODERATE（0.5）。~~⚠️ 换手分项实际恒 NORMAL~~ **已修复（464-3）：从 daily_basic_df.turnover_rate 提取传 turnover_data**；⚠️ **融资分项恒死（calc_margin_ratio 列名错位）→ 三态退化恒 MODERATE(0.5)、continuous_value 恒 0.5**，见独立文档 §四-1（464-6） |
| 8 | `fund_price_divergence` / `_status` / `_risk` | 资金×价格背离（445 补产出） | 资金方向 × 价格方向（PhaseDetector trend_alignment 归一，无引擎时 df 5 日斜率>1% 兜底）：同向→"一致性确认"（无风险）；流出+涨→"拉抬出货，散户接盘危险信号"（danger/bearish）；流入+跌→"底部吸筹/逆势建仓"（提示/bullish）；数据不足→none |
| 9 | `plain` | 白话总结 | `_fund_chip_plain` 拼接阶段/资金流/筹码结构/融资 + 背离后缀（risk≠无时） |

### 3.2 阶段引擎核心（PhaseDetectionEngine.compute_tags，312/412 号）

输出 `main_force_phase / phase_confidence / price_position / trend_alignment / fund_flow / phase_conflict / phase_vote_ratio`。

- **7 维阶段向量**（控盘度维度批次 3 未接）：chip 筹码形态、fund 资金流向、stage 量价四阶段、asr ASR、trend 趋势斜率、ssrp 主力成本锚（443 补传 cost_ext）、chan 缠论买点。
- **加权共识 `_consensus`**：维度权重 `_DIM_WEIGHTS = {chip:3.0, fund:3.0, stage:2.5, asr:2.0, trend:1.5, ssrp:2.5, chan:2.0}`；阶段总分=Σ 维度强度×权重×环境因子（情绪 climax 买入证据×0.7、热点板块 washing×0.7）；冲突阈值 gap<0.08（325 档案校准）→ 置信度×0.6；**确认门槛：top 阶段支持者（该阶段强度>0.25 的维度数）≥2**，不足则降级次高，仍不足→unknown_no_evidence；置信度=top 总分/总分和；capital_nature 机构+0.05/游资×0.8。
- **涨停交叉校验 `_limit_up_cross_check`**（298 号）：pct_chg>9.5% 时——building+低位+非巨量→确认 building；building+高位→distributing；lifting+高位+巨量+次日低开→distributing；distributing+低位+缩量→building。

### 3.3 judgment
`phase`、`direction`（fund_flow）、`light`（=phase light）、`overall_light`、`overall_direction`（building/**lifting**→+1、distributing→-1，~~raising~~ 464-1 已统一为 lifting）、`continuous_value`（1-crowding_score，⚠️ 融资维死后恒 0.5，见独立文档 §四-1）。

### 3.4 audit 条件（5 条）
1. 主力阶段：building/**lifting**/distributing（~~raising~~ 464-1 已统一）⚠️ 不看置信度，见独立文档 §四-8
2. 资金流向：有明确流向（very_strong~weak）⚠️ 判定集漏 strong_out + 死枚举，见独立文档 §四-9
3. 筹码集中：有集中度数据 ⚠️ 'stable' 也满足（独立文档观察项）
4. 拥挤度合理：非 HIGH_CROWDING/unknown ⚠️ 融资维死后恒满足，见独立文档 §四-1
5. 资金×价格无危险背离：risk≠危险 ⚠️ 数据不足时恒"无"（独立文档 §四-2）

---

## 四、dim5 情绪环境引擎（Dim5EmotionEngine）

**数据源**：tags（sentiment_phase/sector_heat/volume_price_fit）+ data_context（daily_df/daily_basic_df/market_stats/sector_heat/emotion_ext/margin_df）+ `BociasiQuadrantAnalyzer`。

### 4.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `market` | 市场情绪阶段（六段论）+ 灯色 | tags `sentiment_phase` → PHASE_MAP：ice 冰点(red)/sprout 萌芽(yellow)/ferment 发酵(green)/climax 高潮(red)/ebb 退潮(yellow)/regression 回归(yellow)（447 去 recovery 兜底词）；BOCIASI 四象限修正：HH 且原 green→"高位风险"red、LL 且原 red→"情绪底部"green、HL 且原 green→"高位震荡"yellow、LH 且原 red→"底部反弹"yellow |
| 2 | `sector` | 板块热度等级+排名 | tags `sector_heat` 枚举 top_10/top_20/normal/none（none=真实冷门，442 缺陷④）；data_context sector_heat 补行业排名 detail |
| 3 | `stock` | 个股情绪：健康/关注/中性/极度消极 | tags `volume_price_fit` 映射（healthy 健康 green/diverging 关注 yellow/中性 yellow）；447 T4a：dim3 judgment.state=='严重背离'→极度消极 red |
| 4 | `bociasi_quick` | 快线信号 BUY/WATCH/BEARISH/NEUTRAL + 置信度 | `_bociasi_quickline` 4 指标：当日量>5日均量×1.5 / 收盘>5日均价 / 5 日动量>3% / 当日振幅>3%；pass≥3→BUY(0.65)/≥2→WATCH(0.50)/非 price 且动量<-3→BEARISH(0.35)/else NEUTRAL(0.35)；修正：vol+mom +0.05、breadth 且非 price -0.05，clamp 0.1-0.9 |
| 5 | `bociasi_slow` | 慢线 ERP 信号 BULLISH/BEARISH/NEUTRAL | `_bociasi_slowline`：ERP=1/PE_ttm×100−国债收益率（默认 2.85）；ERP>5 强多(0.75)/>3 弱多(0.60)/<0.5 强空(0.75)/<1.5 弱空(0.60)；相对强弱（20 日个股−指数收益差 ±5%→多/空，置信度 0.5+|差| 封顶 0.7）；两信号投票合并 |
| 6 | `quadrant` | 四象限 LL/LH/HL/HH + 权重乘数 | `BociasiQuadrantAnalyzer`（461-5 核实活路径）：快线 7 键（ma20_ratio/turnover_percentile/limit_ratio/rsi_percentile）+ 慢线 3 键（erp_percentile/margin_trend/dv_bond_diff），缺键走全市场 SQL 回退（458 号已接分库路由）；LL 底部(×1.15)/LH 底部反弹(×1.05)/HL 高位震荡(×0.90)/HH 上涨尾声(×0.75) |
| 7 | `temperature` | 情绪温度 0-100 | `calc_emotion_temperature`（447 T5 SSOT）：7 分项权重 market_phase 0.25/limit_up 0.15/blast_rate 0.10/sector_heat 0.15/volume_price 0.15/margin 0.10/breadth 0.10；分项得分（涨停家数直映/封板率直映/板块排名 100-2×rank/量价 healthy80 diverging20/融资 +5%→80 分/广度直映）；BOCIASI 修正：temperature = 原×0.4 + (0.6×fast_score+0.4×slow_score)×100×0.6 |
| 8 | `plain` | 白话总结 | `_emotion_plain` 拼接市场阶段/四象限/温度/板块/个股情绪 |

### 4.2 judgment
`market_light`/`sector_light`/`stock_light`/`overall_light`（任一 red→red；≥2 green→green；否则 yellow）/`overall_direction`/`continuous_value`（temperature/100）。

### 4.3 audit 条件（5 条）
1. 市场情绪：非退潮/冰点
2. 板块热度：top_10 或 top_20
3. 个股情绪：非极度消极
4. BOCIASI快线非看空：非 BEARISH
5. 四象限非高风险：非 HH

---

## 五、dim6 风险引擎（Dim6RiskEngine）

**数据源**：daily_df、daily_basic_df、tags（risk_ext/atr/event_details 等预计算）、fina_indicator。

### 5.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `risk_level` / `risk_detail` / `risk_light` | 风险等级：低/中/高/极高 | `_assess_risk_level`：4 基础源计数（缠论 risk_level=HIGH、财务 fina_health=fail、事件 catalyst_event∈EVENT_RISK_SET、主力 distributing）+ 流动性触发（452 双门槛）；≥2 高/1 中/0 低；**事件升格（459 号同 audit 口径）**：高/极高事件→升"高"；PIERS 硬否决（448：造假/退市/ST退市）→"极高"；453 号 ST 分档：direction≤-2（*ST/退市整理）→极高、普通 ST→高 |
| 2 | `risk_factors` | 风险因素明细 | `_list_risk_factors`（与风险源对齐 T45）+ event_risks + PIERS 杠杆：缠论高/财务 fail 高·suspicious 中/事件高/主力出货中/流动性不足高/估值过高中/获利盘≥80%中；无显著风险补"无显著风险" |
| 3 | `piers_leverage` | PIERS-E 高杠杆指标（SIG 现状条件，非否决） | `_assess_piers_leverage`（448）：debt_to_assets>70%→高杠杆（中）、ROCE<15%→资本回报率偏低（中）；tags 预计算优先，回退 fina_indicator |
| 4 | `support_price`/`resistance_price`/`dist_to_*`/`risk_reward`/`signal_days`/`dist_to_prev_high_pct` | 几何化交易参数 | `calc_geometric`（461-11 收敛到 shared SSOT）；risk_reward=｜距压力% / 距支撑%｜；signal_days=收盘连续站上前 60 日高点天数 |
| 5 | `rr_value` / `rr_level` / `rr_assessment` | 盈亏比分级 | `_assess_rr`：<1R 不值得交易(red)/1-2R 可考虑(yellow)/2-3R 较好(green)/>3R 优质(green) |
| 6 | `volatility_level` / `atr_14d` / `atr_pct` / `volatility_percentile` | 波动率（仅参考，非风险源） | `_calc_volatility`（461-4 对齐 framework）：TR→ATR14；档位=**未年化** 20 日 std×100（high>4/medium>2/low）；历史分位用年化 20 日波动排名；452 号波动从风险源摘除 |
| 7 | `liquidity_risk` / `liquidity_detail` / `avg_amount_wan` / `circ_mv_wan` | 流动性触发+明细 | `_assess_liquidity`（452 双门槛）：日均成交额<5000 万 或 流通市值<30 亿 → 触发；数据不足默认不触发（443 保守） |
| 8 | `invalidation` | 失效/止损条件 | `_build_invalidation`：跌破防守位（priority1）/情绪 ebb/climax（2）/右侧否决（3，404 已知死代码） |
| 9 | `event_count`/`event_details`/`event_summary` | 事件风险详情（前 5） | tags `event_details`（RAW-2 预计算）→ 类型/描述/方向/置信度/日期 |
| 10 | `risk_evidence` | 证据摘要串 | 风险等级+防守位+压力位+盈亏比+波动率+高风险因素+事件描述 |
| 11 | `plain` | 白话总结 | `_risk_plain`：风险等级→防守位→压力位→盈亏比→波动→需关注→止损条件 |
| 12 | `support_resistance` | 防守/压力文案 | 防守位 X 元（距现价 Y%），压力位 Z 元（距现价 W%） |

> 注：dim6 文件内另有 `EagleSwordResonance`（framework 鹰剑共振，模块级便捷函数入口），**非 Dim6RiskEngine.evaluate 输出路径**（evaluate 不调用），不计入输出项。

### 5.2 judgment
`level`/`risk_level`、`light`（高/极高 red、中 yellow、低 green）、`overall_light`、`overall_direction`（高/极高→-1、低→+1）、`continuous_value`（min(rr/3,1)，无数据 0.5）。

### 5.3 audit 条件（5 条）
1. 风险等级：低或中
2. 盈亏比：≥2R
3. 流动性：日均成交额>5000万 且 流通市值>30亿
4. 无高风险事件：无 severity=极高
5. 防守位有效：support_price 非空

---

## 六、dim7 估值引擎（Dim7ValuationEngine）

**数据源**：daily_basic/income/balancesheet/cashflow（data_context 优先）+ tags（461-2 SSOT=fina_health/roce_pass/value_trap）+ 行业分类 + 分位表（daemon precompute 前 `ve.build_composite_percentile`/`build_fcf_percentile`，data_daemon:3168/3173）。

### 6.1 status_description 输出项

| # | 输出键 | 输出结论 | 分析逻辑 |
|---|---|---|---|
| 1 | `valuation_level` | 估值分级（极低估/低估/合理/高估/极高估）+ composite | `_compute_valuation` 五锚加权（见下）+惩罚/调整 → composite∈[-2,2] → level：comp_percentile 分位（>0.95 极低/0.80 低/0.20 合理/0.05 高/else 极高），无分位表回退绝对阈值（c>1.0 极低/≥0.3 低/≥-0.3 合理/≥-1.0 高/else 极高）；deviation=composite×20 |
| 2 | `pe_percentile` / `pb_percentile` | PE/PB 近 5 年百分位 | 历史序列（≥20 正值样本）当前值分位 |
| 3 | `fcf_yield` | 自由现金流收益率 | FCF /（总市值×1e4）×100（445-A2 万元单位修复） |
| 4 | `dividend_yield` | 股息率 | dv_ttm 最新值 |
| 5 | `revenue_growth` | 营收同比 | `_revenue_yoy(income)` 最新两期营收同比×100 |
| 6 | `fina_health` | 财务健康：pass/suspicious/fail | **461-2 SSOT=RAW 侧 tags**（ve.compute_tags 生产）；tags 缺失才运行时 `_fina_health` 五表重算兜底。四维判定：ROE 近 3 年均值>6% / ROCE>15%（roce_pass 独立）/ 负债率<70%（金融除外）/ 经营现金流覆盖净利>0.8；fail_count≥2→fail、≥1→suspicious |
| 7 | `value_trap` / `growth_trap` | 估值陷阱标注（449） | 价值陷阱=ROCE<15%（有数据时触发，无数据默认通过）；成长陷阱=PEG>2 |
| 8 | `potential_score` / `potential_strength` / `potential_breakdown` | 潜力评分 0-100 + 分项明细 | `_compute_potential`（见下） |
| 9 | `plain` | 白话总结 | 估值分级+PE 分位+FCF 收益率+股息率+潜力评分 |

### 6.2 五锚加权细节（composite=Σwᵢaᵢ）
- **a1 资产锚（PB）**：PB 历史分位 → `_pct_rating_wide`（<5%→+2/<20%→+1/<80%→0/<95%→-1/else -2）
- **a2 收益锚（PE+PEG+股息）**：PE 分位（`_pct_rating_narrow`：+1/+0.5/0/-0.5/-1）+ PEG（<0.5→+1/<1→+0.5/<2→0/<3→-0.5/else -1，PEG>2 置 peg_gt2）+ 股息率（>4%→+1/>2%→+0.5/>1%→0/else -0.5），`_sum3_to_2` 压缩到 [-2,2]
- **a3 现金流锚**（金融跳过）：FCF/EV（总市值+总负债-现金）收益率 − 10 年国债（默认 1.7%，env 可配）利差分档（>3→+2/>1→+1/>-1→0/>-3→-1/else -2）；有分位表用 分位×4-2
- **a4 调整PE锚**（仅科技/成长）：研发费用率>5% 时净利加回研发×(1-0.25)×0.20 重算 PE，降幅比>20%→+2/>10%→+1/>5%→+0.5
- **a5 股债锚**：股息率 vs 国债（>2×→+2/>1.2×→+1/>0.6×→0/>0.3×→-1/else -2）
- **权重** `CATEGORY_WEIGHTS`（七大行业）：蓝筹(0.15,0.30,0.30,0.15,0.10)/成长(0.10,0.25,0.20,0.35,0.10)/周期(0.40,0.15,0.25,0.15,0.05)/科技(0.10,0.15,0.20,0.50,0.05)/金融(0.45,0.20,0.10,0.20,0.05)/稳定收息(0.15,0.25,0.35,0.15,0.10)/微小亏损(0.40,0.05,0.30,0.20,0.05)
- **特殊修正**：周期股 PE 分位<20%（疑似周期顶点）→ 纯 PB 锚（449）；总市值<50 亿 → 资产锚权重减半归一（445-A2）；价值陷阱 -0.3、成长陷阱 PEG>2 -0.5（449）；`_adjust_composite`：fina fail -0.5、pass 且 ROE>12% → +0.25×min(1,ROE/20)、科技/成长营收 YoY>20% → +0.2

### 6.3 潜力评分 `_compute_potential`（6 维加权）
- 维度分：val（估值偏差→分位表）、earn（ROE→分位表）、sector（板块 top_10=0.9/top_20=0.75/其余0.5）、event（EVENT_SCORE：业绩0.9/突破0.8/题材0.6/造假0.1…）、fund（资金 5d_inflow=0.7/5d_outflow=0.3）、trend（TREND_SCORE：up_aligned=0.8/down_aligned=0.2）
- 权重：val 0.20/earn 0.15/sector 0.15/event 0.10/fund 0.20/trend 0.20；sector≥0.75 且 fund≥0.6 → 双×1.1
- 修正：环境权重（ice/climax×0.8、ebb×0.3）、质量系数（suspicious 0.88/fail 0.2）、dev>30 → ×0.3、≥2 维≥0.7 → ×(1+0.08×(n-1))
- `_map_score`：≤0.14→0；0.14-0.58 线性映射 0-85；>0.58 指数映射 85-100

### 6.4 judgment
`valuation_level{value,light}`（LEVEL_LIGHT：极低/低 green、合理 yellow、高/极高 red）、`valuation_deviation{value,light}`（>10 green/<-10 red/else yellow）、`fina_health{value,light}`、`potential_strength{value,light}`（≥60 green/<30 red）、`overall_light`、`overall_direction`、`continuous_value`（(composite+2)/4）。

### 6.5 audit 条件（8 条）
1. PE数据可用 / 2. PB数据可用 / 3. FCF数据可用 / 4. 股息率>0
5. 财务健康（⚠️ threshold 文案"ROE>6%近3年平均"与实际四维判定不完全一致，见 §八-4）
6. 营收正增长 / 7. ROCE达标（近 3 年均值>15%）/ 8. 无成长陷阱（PEG≤2）

---

## 七、横览小结

1. **status_description** = 现状（因）主要载体：每维并列输出**事实条件**（位置/量比/分位/计数/触发与否）与**结论标签**（阶段/等级/情绪），供 dim8 归集、前端展示。
2. **judgment** = 分析结论（果）：统一含 light/overall_light/overall_direction/continuous_value，供 JUD 综合判定。
3. **audit** = 验证：每条 {name, satisfied, actual, threshold}，confidence=satisfied/total。454/455/459 后各维已从"数据门槛恒真"改为**判读结论条件**。
4. 445 §6.1 七契约键（dim2 divergence/chanlun_phase/level_cross_score/trend_structure_signal/ts_strength/buy_sell_points_detail/stage_name、dim4 资金×价格背离、dim3 RPS）均已真实接线；461-1~13 取数一致性全部落地。
5. 数据依赖：各维均以 data_context 优先（dim1 统一供给），tags 兜底；461-5 已消除 dim7/dim4 绕过 dim1 的硬偏差，dim5 降级层为设计内健康回退。

---

## 八、核查发现与存疑点（待逐项沟通确认，未改代码）

> 以下为 2026-09-19 逐项核对时发现的问题，均不擅自修改（445 冻结判定逻辑 + 待用户拍板）。

### 八-1（✅ 已处置：464-1，2026-09-19）dim4 阶段枚举口径不一致：`lifting` vs `raising`
- 现状：`PHASE_LIFTING="lifting"`；`_consensus` 阶段向量 phases = `["building","washing","lifting","distributing"]` → **PhaseDetectionEngine 产出 `lifting`**（461-6 实证其枚举 = {building,washing,lifting,distributing,unknown}）。
- 但 dim4 evaluate 中：
  - light 判断：`('building', 'raising')` → **`lifting` 落 yellow（应 green）**
  - overall_direction：`('building', 'raising')` → `lifting` 得 0（应 +1）
  - audit 条件 1：`('building', 'raising', 'distributing')` → `lifting` 不满足（应满足）
- 同时 `_assess_phase`（tags 路径）的 pm 映射**无 `lifting` 键**（只有 raising）→ tags.main_force_phase='lifting' 时判 unknown。
- `PHASE_MAP` 同时含 `raising` 与 `lifting` 两键（都映射"拉升期"）——历史双枚举并存痕迹。
- **影响**：PhaseDetectionEngine 判"拉升期"时，dim4 灯色/audit 可能错位（yellow 而非 green、audit 主力阶段不满足、plain 缺"主力正在拉升"）。
- **处置（464-1，用户拍板"可修改策略引擎，以生产稳定可用为原则"）**：
  - 前置核查：pre_feat_cache 存量 `raising`=0 行、`lifting`=4498 行 → **无存量 raising，无需别名兼容**；测试侧全部断言 lifting（456/418/451/390）。
  - 改动（dim4_chip_fund_engine.py 6 处）：PHASE_MAP 删 `raising` 键（统一枚举）；`_assess_phase` pm 映射 + light 判断改 `lifting`；`_fund_chip_plain` `pn=='raising'`→`'lifting'`；evaluate 的 light/overall_direction/audit 条件改 `lifting`。
  - 保留：大写 `RAISING`（TradingPhaseDetector 内部枚举，经 mapping 归一为 lifting）与 dim_adapter:73 `'raising'` 显示键（JUD 显示层死键，保留防御）。
  - 验证：新增 `tests/test_464_dim4_phase_enum.py`（9 例：_assess_phase lifting 识别 / evaluate 引擎路径 light=green、overall_direction=1、audit 满足、plain 含"主力正在拉升" / distributing 仍 red / PHASE_MAP 无 raising 键）**9 passed**；回归 test_456 **16 passed**；AST+import OK。
  - 注：test_451 TestFrameworkAsr 挂起为既有环境问题（`MainForceScorer._score_chip_distribution`→`_calc_margin_cost_price` 触发 DataManager 在开发基准库 `_init_tables` 卡 DB 初始化，与本次改动无关，diff 已证）。

### 八-2（✅ 已澄清：非死路径，无需处置，2026-09-19）dim4 cost_structure 的 ASR/CYQKL 段
- **原疑点**：461-9 清理 chip 白名单移除 `asr`/`cyqkl`，疑 `_assess_cost_structure` 读 `tags.get('asr')`/`tags.get('cyqkl')` 恒 None → ASR/CYQKL 文案与 quality 分档不产出。
- **实证推翻（生产库 2026-09-18 快照，模拟 `_flatten_pre_feat` 后实测）**：
  - flat tags **有真实值**：000001 `asr=54.66, cyqkl=7.41`、000002 `asr=13.46, cyqkl=23.78`、000006 `asr=17.93, cyqkl=5.11`、600519 `asr=28.76, cyqkl=0.96`。
  - `_assess_cost_structure` 正常产出：`'筹码集中，ASR=55，CYQKL=7.4，获利盘78%'`；quality 分档真实触发（000006 asr=18→沉寂、600519 asr=29→沉寂）。
- **根因澄清**：461-9 移除的是 **chip 组**白名单的 asr/cyqkl（生产者 `ChipDistributionEstimator.get_tags` 从不产该组，移除正确）；但 asr/cyqkl 的**真正生产者在 chip_fund_ext 组**（`ChipIndicators.calculate_all_indicators`，443 R1 已真实化），data_daemon:3664/3667 直接赋值、无白名单截断、扁平化正常摊平。461-9 文档"dim4 读恒 None（死路径）"表述在 443 R1 后不再成立。
- **结论**：链路完整（chip_fund_ext 组生产 → 扁平化 → tags → _assess_cost_structure 输出），**无需处置**；quality 语义（高 ASR=活跃/>80、低 ASR=沉寂/<30）与 451 号统一口径一致。

### 八-3（✅ 已处置：464-3，2026-09-19）dim4 crowding 换手分项恒 NORMAL
- **原疑点**：`calc_turnover_crowding` 需 df 含 turnover_rate/turn 列或传入 turnover_data；daily_df 为前复权 OHLCV（无 turnover 列），evaluate 的 market_context 仅传 `{'margin_df': ...}` → 换手分项恒 NORMAL_TURNOVER，拥挤度实际由融资+波动两维决定。
- **前置核查**：daily_basic_cache.turnover_rate 为真实生产列（461-6 确认；2026-09-18 全市场 5553 行均值 3.27）；dim1 data_context 加载 daily_basic_df（dim1_signal_engine.py:112-114，含 turnover_rate）；depth 组亦产 turnover_rate（461-6，快照实测 000001='0.44' 字符串）。
- **处置（464-3）**：dim4 evaluate 构造 market_context 时，从 `data_context.daily_basic_df['turnover_rate']` 提取 dropna 序列传 `turnover_data`（CrowdingFactor.evaluate :5344 读取、calc_turnover_crowding :5197 优先消费）→ 换手分项真实参与 2/3 拥挤判定。无 daily_basic_df 时保持原兜底（NORMAL_TURNOVER）。
- **验证**：新增 4 例测试（test_464 `TestCrowdingTurnoverWiring`）：HIGH_TURNOVER（当前>20日均值1.5×）/ LOW_TURNOVER（<0.5×）/ 无数据兜底 NORMAL / evaluate 确实把 daily_basic_df.turnover_rate 传入 market_context.turnover_data 且判定为 HIGH。test_464 现 16 例全过。

### 八-4（✅ 已处置：464-4，2026-09-19）dim7 audit「财务健康」threshold 文案与实现不一致
- **原疑点**：audit 文案"ROE>6%近3年平均"过简（仅 ROE 一维）；实际 `_fina_health`（SSOT=RAW 侧 ve.compute_tags，461-2；dim7 兜底逐行一致）判定为**三维 fail_count**：ROE 近3年均值>6% + 负债率<70%（金融除外）+ 经营现金流/净利>0.8 连续3年；≥2 fail / ≥1 suspicious / 0 pass。ROCE>15% 是独立 roce_pass（audit 另有「ROCE达标」条件，不在 fina_health 内）。
- **处置（464-4，纯文案对齐，不触判定）**：audit「财务健康」threshold 改为 `'ROE近3年均值>6%且负债率<70%(金融除外)且现金流覆盖净利>0.8'`。
- **验证**：新增 1 例测试（test_464 `TestDim7FinaHealthAuditText`，mock _compute_valuation/_compute_potential/_get_dm 后断言 threshold 含三维关键词且不再仅 ROE）。test_464 现 17 例全过。

### 八-5（观察）dim6 EagleSwordResonance 非 evaluate 输出
- dim6 文件内 `EagleSwordResonance` + 模块级便捷函数 `evaluate(...)`（chanlun_result/volume_price_signal/bociasi_quick/bociasi_slow/crowding/market_state 入参）供外部信号共振调用，**不在 Dim6RiskEngine.evaluate 输出中**——本号不列入输出项，仅备注防混淆。

> **📌 dim4 核查发现（2026-09-21）已独立成档**：见《464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）.md》——§四 十项发现（实施号 464-6~464-15 已登记，判定类待拍板）。本号不再重复载入，避免与 dim2-dim7 汇总混淆。

---

## 九、待确认清单（逐项沟通用）

| # | 项 | 类型 | 建议 |
|---|---|---|---|
| 1 | ~~八-1 lifting/raising 枚举统一~~ | ✅ 已处置（464-1） | 统一枚举 + 同步 _assess_phase/evaluate 判断（已完成并验证） |
| 2 | ~~八-2 ASR/CYQKL 死路径~~ | ✅ 已澄清（非死路径） | 实证 chip_fund_ext 组生产 → 扁平化正常输出，无需处置 |
| 3 | ~~八-3 crowding 换手分项~~ | ✅ 已处置（464-3） | 从 daily_basic_df.turnover_rate 提取序列传 turnover_data（已完成并验证） |
| 4 | ~~八-4 audit 文案对齐~~ | ✅ 已处置（464-4） | threshold 对齐三维判定文案（ROE+负债率+现金流覆盖）（已完成并验证） |
| 5 | 各维 status_description 键是否全部进入 dim8 归集范围 | 437-A 字段级映射 | 逐键核对 437-A T/E/S/D 去向 |
| 6 | **dim4 核查发现（十项，464-6~464-15）** | 见独立文档 | 《464-dim4资金筹码引擎输出项全量梳理与核查（464方法续）.md》§四/§五 |

---

## 十、dim2 输出项话术能力评估（2026-09-19 逐项核对，仅存档未改码）

> 评估口径：①分析逻辑合理性（对照 445 知识库 + 446/454/457/463 已落地处置）；②能否整理出对股票现状的描述话术（444「现状=因果链的因」；dim8 归集素材能力）。

### 10.1 逐项评估表

| # | 输出键 | 分析逻辑合理性 | 现状话术整理能力 |
|---|---|---|---|
| 1 | `vs_zhongshu` | ✅ 合理（463 时效过滤+前复权+有效中枢） | ✅ 强：直接成话术"价格位于中枢上方（区间 X~Y，日期）" |
| 2 | `vs_ma` | ✅ 合理（ma_alignment 枚举映射） | ✅ 中：成话术"均线多头排列"；⚠ 与 #5 重复（同概念两源） |
| 3 | `vs_support_resistance` | ✅ 合理（461-11 shared SSOT，支撑≤15% 封顶） | ✅ 强："距支撑位 X 元(-2.3%)，距压力位 Y 元(+5.1%)" |
| 4 | `vs_chip` | ✅ 合理（445-A3 英文枚举+获利盘） | ✅ 中：直述"筹码集中，获利盘 78%"，需语境加工（高获利盘+高位=出货风险） |
| 5 | `vs_indicator` | ⚠ 基本合理但均线段与 #2 重复；RSI（461-1 SSOT）分档合理 | ✅ 中：RSI 可成话术"RSI 72 偏强"；⚠ 均线重复且**整键未入 plain** |
| 6 | `chanlun_direction` | ✅ 合理（446/463 价格 vs 有效中枢主判据） | ✅ 强：结论句"上升/下降/盘整"（果，依据在 #7） |
| 7 | `trend_basis` | ✅ 合理（与 trend 判定逐一对齐，444 因果链的因） | ✅ **最强**："价格突破中枢上沿"——dim8 叙事核心素材 |
| 8 | `chanlun_strength` | ✅ 合理（ChanlunScorer 0-100） | ✅ 中：总分话术"结构强度 72/100"；成分黑盒（details 未输出）。**⚠ 2026-09-19 实测恒 0.5（取键 bug），已处置为 464-5**（见 10.4） |
| 9 | `buy_sell_points` | ✅ 合理（前 3 买卖点） | ✅ 中：⚠ 与 #14 重复，话术应优先 #14 结构化明细 |
| 10 | `multi_level` / `multi_level_direction_text` | ✅ 合理（457 周/日/60min 区间套） | ✅ 强："周/日/60min 方向一致（上升），多周期共振" |
| 11 | `level_cross_score` | ✅ 合理（日/周/月三级交叉校验） | ⚠ 契约键话术弱：数值无档位语义（默认 0.5），需先定义档位 |
| 12 | `chanlun_phase` | ✅ 合理（11 定理 ≥0.6 健康） | ✅ 中："缠论结构健康（11 定理 0.75）" |
| 13 | `trend_structure_signal` / `ts_strength` | ✅ 合理（三假设→123_buy_breakout/higher_low） | ✅ 中：signal 可成话术"123 买点突破形态"；ts_strength 映射值语义弱 |
| 14 | `buy_sell_points_detail` | ✅ 合理（结构化明细） | ✅ 强："确认一买信号于 X 日 Y 元（置信度 0.82）" |
| 15 | `stage_name` | ✅ 合理（trend→上升/下降/盘整） | ✅ 强：结构态结论标签，可直接作段落标题 |
| 16 | `divergence` / `_type` / `_strength` | ✅ 合理（方向+类型+强度） | ✅ 中-强："出现顶背驰（趋势背驰，强度 0.8）" |
| 17 | `plain` | ⚠ 有缺陷：只拼中枢位置+均线+支撑阻力+筹码，**缺趋势依据/RSI/多级别/背驰/买卖点/结构强度** | ✅ 弱-中：缺"趋势方向+依据"核心叙事句 |

### 10.2 话术缺口（3 项，待拍板是否纳入 464 修）

1. **plain 未含趋势依据（最严重）**：`trend_basis` 是核心"因"，却不在 plain。dim8 若只读 plain 得"价格位于中枢上方、均线多头、距支撑 X、筹码集中"——**缺"当前处于上升趋势（依据：价格突破中枢上沿）"结论句**，叙事链断裂。
2. **vs_indicator 被计算未输出**：`_structure_plain` 签名含 `vs_ind` 参数但函数体**未使用**——RSI 强弱/均线形态算出来但 plain 没有。
3. **跨键重复**：均线（#2/#5 两源）、买卖点（#9/#14 两处）——dim8 归集需定主源（建议 #14、#2）。

### 10.3 话术能力分级（供 437-A 归集参考）

- **可直接成话术（强）**：vs_zhongshu、trend_basis、multi_level、buy_sell_points_detail、stage_name、vs_support_resistance
- **需加工成话术（中）**：vs_ma、vs_chip、vs_indicator、chanlun_strength、chanlun_phase、divergence、buy_sell_points
- **纯契约键（话术弱，供 JUD）**：level_cross_score、ts_strength、divergence_strength

### 10.4（✅ 已处置：464-5，2026-09-19）chanlun_strength 恒 0.5 取键修复

**现象（真实数据实证，2026-09-19）**：万科A/茅台/宁德/平安 等策略信号（2026-09-18 交易日，5550 只）`chanlun_strength` **全部 = 0.5**，`continuous_value` 恒 0.5 → 前端七维段"下降/上升（置信50%）"恒值。

**根因**：`dim2_structure_engine.py` 第 4 步 `score_result.get('strength', 0.5)` —— `ChanlunScorer.score` 返回键为 `'score'`（0-100，内部 +50 归一 clamp）**无 `'strength'` 键** → 恒回退 0.5，真实结构强度从未接入。连带 `judgment.continuous_value` 恒 0.5，喂给 dim_adapter（0.4×chanlun_strength 加权）、status_engine confidence、dim8 置信权重全部恒定。

**处置（4 处联动）**：
1. dim2 取键修复：`strength = float(score_result.get('score', 50))`；无缠论/异常时中性分 50（0-100 域）。
2. `continuous_value = strength / 100`（0-1 统一置信语义，修复后不再恒 0.5）。
3. `dim_adapter.convert_to_factors`：`chanlun_strength` 0-100 域归一为 0-1（`>1` 判 0-100 域除 100，兼容旧恒 0.5 数据与测试模拟 0.7）后再参与 `0.4/0.4/0.2` 加权（原混单位加权在恒 0.5 时被掩盖，真实 0-100 会爆表）。
4. **464-5C（用户拍板：C 并入本号收尾）**：dim2 调 `scorer.score` 补传 `latest_close` + `market_context`——原只传 analysis_result，价格匹配度（买点跌破>5% 惩罚/远离>30% 追高惩罚/卖点反弹加分）与换手/大单市场调整全部被跳过。新增模块级 `_build_market_context(data_context)`：`turnover_rate`←`daily_basic_df` 最新、`net_lg_amount`←`moneyflow_df` 最新（NaN 剔除，缺键不产）；`index_condition` 无独立数据源（data_context 无指数环境键）→ 不传，scorer .get 缺省不调整。

**验证**：`tests/test_464_chanlun_strength.py` 14 passed（score 真实接入 72/100/0/37 → continuous_value 0.72/1.0/0.0/0.37；无缠论/异常 → 50/0.5；dim_adapter 归一 0.632/旧数据 0.5 兼容；464-5C 接线 3 用例——latest_close/market_context 捕获断言 + 缺源/脏值容错）；dim2 系列回归 77 passed（396/446_contract/446_trend/457/463；test_454 2 个 463 既有失败与本次无关）+ test_418(12) + test_462(27) + test_420(18) + test_436(26)。真实数据实证（万科A qfq 口径）：旧取键恒 0.5 → 新取键 score=0（24 个历史三卖累计 -192 分压到底）。

**⚠ 连带发现（已开 465 号登记，判定逻辑，本次未动）**：`ChanlunScorer.score` 对**全历史**买卖点累计扣分（24 个历史三卖 -192 → 当前强度压到 0），一买 +50 远不够抵；且 type 变体（third_buy_a/b、first_buy_p 等）不匹配 scorer 只认的 first_buy/second_buy/third_buy → 买点每点加分被跳过、卖点 third_sell 照扣，评分不对称；也无"最近 N 根 K 线窗口"限制。8 只抽样 6 只 score=0（含茅台 up）。属 445 引擎判定逻辑范畴（冻结边界：确证有错才动 + 独立号 + 全链路验证），登记 465 号（方案 A/B/D）。

---

## 十一、plain 的功用（各 dim 统一契约，2026-09-19 核查）

### 11.1 plain 是什么

六引擎 `status_description['plain']` 是**每维输出的一段中文自然语言摘要**（非结构化键值），由各维 `_*_plain()` 拼接关键现状字段而成：
- dim2 `_structure_plain`、dim3 内联拼装（vp_state 分支）、dim4 `_fund_chip_plain`、dim5 `_emotion_plain`、dim6 `_risk_plain`、dim7 内联 plain_parts。

### 11.2 消费方与功用（实测代码链路）

| 消费方 | 位置 | 功用 |
|---|---|---|
| **dim8 归集器**（`build_seven_dim_from_dim_results`） | `dim8_summary_engine.py:388` `_extract_dim_plain` | 提取每维 plain 作为**段落 text 兜底**（`:498` `_brief_text` 先取 judgment.state，无则回退 plain） |
| **dim8 evidence** | `dim8_summary_engine.py:474` `_yield_evidence` | plain 进 `evidence` 列表（前端"依据"展示） |
| **dim8 summary 段** | `dim8_summary_engine.py:708` | summary 段 `text` 直接取 dim8 自身 assemble 的 plain |
| **status_engine L1 维度判定** | `status_engine.py:350` | 结构维 `evidence: [plain]`（维度判定的依据文本） |
| **dim_adapter（JUD 消费）** | `dim_adapter.py:121` | `evidence: [sd.get('plain')]`（JUD 判定证据链） |
| **前端接口** | `strategy_analyze.py:152` | `text = sd.get('plain') or sd.get('attribute')` → 每维中文摘要行 |

### 11.3 plain 功用结论

1. **统一叙事载体**：SIG 各维把"现状"压缩成一句人话，供前端直接展示（`_build_dim_summary` 等逐行 `- {维}: {light} {plain}`）。
2. **dim8 段落 text/evidence 的主来源**：当 judgment.state 缺失或过简时，plain 是唯一有语义的段落文本（437-A 归集主体）。
3. **JUD 证据链一环**：status_engine/dim_adapter 把 plain 挂到 `evidence`，作为判定"依据"透传。
4. **⚠ 因 plain 是唯一"人话"层，其内容质量直接决定前端叙事**——dim2 plain 缺趋势依据（§10.2-1）即前端看不到"为什么上升"，属事实呈现缺口。

---

## 十二、dim8 架构正确定义（用户 2026-09-19 拍板，存档）

> §十一 对 plain 的定位是**现状代码事实**（dim8 当前确以 plain 为 text/evidence 主来源），但**不符合架构意图**。用户拍板以下标准，作为 dim8 后续改造基准。

### 12.1 dim8 的原料 = 各 dim 输出键对应的「分析逻辑实例」

- **原料不是 plain**：plain 是各 dim 对自己输出的**初加工/成稿文字**，dim8 不应"提取某个初加工整理好的内容来拼凑"。
- **原料是分析逻辑实例**：`audit.conditions[]` 每条 `{name, satisfied, actual, threshold}` = 一条分析逻辑在个股上的**实例化**（规则名 / 是否达成 / 实际值 / 阈值）；外加 `status_description` 的结构化键值（如 `vs_zhongshu.position/detail`、`risk.support_price`、`emotion.temperature` 等）。
- 依据：444「现状=因果链的因，因=audit.conditions 中 satisfied=true 的项」；dim8 归集对象即这些**结构化因实例**。

### 12.2 dim8 的处理逻辑

通过**维度归集、整理、去重、统一**等逻辑，组合成**细分维度**的现状描述：
- 归集：按前端契约维度（structure/volume_price/fund_chip/emotion/risk/…）组织各 dim 的分析逻辑实例；
- 整理：把 satisfied 的 condition + 结构化键 → 可读现状句（"趋势方向=上升（实际：上升，阈值：有明确缠论方向）"）；
- 去重：跨维同质内容取主源（440 号已拍板 4 对：dim3 个股情绪 / dim6 风险+dim7 估值 / dim4 资金流 / dim2↔dim6 支撑阻力）；
- 统一：中英枚举映射、X（X）去重（440 号）、口径统一。

### 12.3 与现状代码的差距（§十一 实况 vs 本架构）

| 维度 | 架构要求 | 现状代码（dim8_summary_engine.py） | 差距 |
|---|---|---|---|
| 原料 | audit.conditions + status_description 结构化键 | `_segment_from_dim` text=`_brief_text`（先取 judgment.state，无则回退 **plain**）；evidence=`_yield_evidence`（取 **plain**/text/conclusion） | ❌ text/evidence 仍以 judgment 结论 + plain 初稿为主，audit.conditions 只透传 name/satisfied 未用于话术 |
| 跨维组合 | 归集+去重+统一 | `_generate_text` 仅 `'；'.join` 逐维 plain 串联 + 关键位锚点 | ❌ 无任何跨维去重/统一逻辑（440 号 4 对主源未在 dim8 落地） |
| 细分维度 | 组合成细分现状描述 | 每维一段（title/text/evidence/audit 透传） | ⚠️ 段结构在，但内容来源错误 |

### 12.4 影响与后续

- **plain 的角色降级**：plain 可作为 dim8 加工时的参考/兜底，但**不是原料**；dim8 话术应从 audit.conditions + 结构化键重新组装。
- **dim2-dim7 侧**：各维 audit.conditions 的 `actual/threshold` 质量成为关键（§十 已逐键核对各维 audit 已从"数据门槛恒真"改为判读条件，455/454/459 号——素材已具备）；status_description 结构化键需保证非装饰性。
- **改造范围**：dim8 `build_seven_dim_report`/`_segment_from_dim`/`_generate_text` 的 text/evidence 生成逻辑重写为"实例→话术"；跨维去重表落地。此为**后续独立实施项**（436 B1 后 dim8 改造），待用户下达开工指令。

