# 464 号｜dim3 在 dim8 现状描述中的输出定稿（量价关系）

> **🔖 dim8 细化基准**：本文档为 **dim3 的 dim8 现状描述输出定稿标准**（SIG 现状层 → dim8 归集，权威基准）。引用入口=《464-dim8现状描述输出定稿基准索引》；引用规范：dim8 改造（464 待办第 4 项）逐维引用，定稿与现状代码冲突时**以本定稿为准**（代码属改造对象）。
>
> **文档定位**：dim3 的 dim8 现状描述输出**定稿标准**。基于 464 号 §12.1（原料=分析逻辑实例）、437 总纲第二层（量价关系维）、464-dim3 梳理（十键实证 + 五存疑点处置）展开，逐键拍板采用/不采用/去重/边界。
>
> **状态**：✅ **定稿**（2026-09-20 八细项全部拍板，见 §三.5）。
> **范围**：只定"dim3 产出哪些、用什么话术、归哪个维"；**不改任何代码**（补产出项已登记待开实施号）。
> **实例贯穿**：万科 000002.SZ（2026-09-18 交易日真实 dim3 evaluate 输出，量价实证最丰富）。
> **前置拍板**（五存疑点 §九）：health_score 归 JUD、pattern/kline_pattern 两链分离、granville 保留双粒度、granville 负面随 hs 归 JUD、plain 已删。

---

## 〇、核心原则（对齐 444：现状=因果链的因，绝不是果）

用户 2026-09-20 逐键点评的核心立场：**dim3 现状输出偏"果"（定性/评分），真正"现状"（因）= 被满足的具体条件/实例**。定稿围绕"把每个键的'因'呈现出来"展开。

---

## 一、dim3 全量最细分析结论输出项（万科真实实例）+ 逐键梳理

> 万科 000002.SZ：vp_state=中性 / hs=9/10强健康 / 量比6.7显著放量 / W底形态 / RPS=61.5 / granville=量价中性 / audit 4/6（confidence 0.67）。
> 对照茅台 600519.SH：vp_state=强健康 / hs=8/10 / 量比1.3温和放量 / 无形态 / RPS=64.5 / granville=回探缩量 / audit 5/6（confidence 0.83）。

| # | 输出键 | 万科实例值 | 是果/是因 | 分析逻辑（规则标准实证） | 用户点评 / 定稿倾向 |
|---|---|---|---|---|---|
| 1 | `vp_state` | 中性 | **果**（3 态概括） | framework `compute_volume_price_signal` 状态机：`state_label`（VP_HEALTHY_BULL/BREAKOUT/DIVERGE_BULL…）→ STATE_SIGNAL_MAP → signal → 映射 3 态（281/333 号） | ❌ 用户：仍是分析结论，非现状。**"因"=状态机命中的具体状态 + rule 文本**（如"放量突破关键位"） |
| 2 | `health_score` | 9/10（强健康） | **果**（7 因子加权合成） | 本地硬编码公式 (raw+4)/12×10，**无方案依据** | ✅ 已拍板**归 JUD，不再输出给 dim8** |
| 3 | `divergence` | 无背离信号 | **果**（结论） | `_detect_divergence_enhanced` 价格+量+MACD 三重确认 → div_type top/bottom/none（450 权威化） | ❌ 用户：分析结论非现状。**"因"=具体检测条件**（如"价格创新高但后量<前量90% + DIF未创新高"→顶背离） |
| 4 | `volume_energy` | 量比6.7，显著放量 | **半果半因** | `ve_l/ve_d` 由 vol_ratio 分档（>2显著/>1.2温和/>0.8正常/else萎缩）；量比 6.7 是事实（461-10） | ⚠️ 用户：相对清晰，但**应补多日连续性**（"已连续放量/缩量"或"当日明显放量"） |
| 5 | `pattern` | 缩量洗盘后放量, W底放量突破, 缩量挖坑后放量 | **因**（具体形态） | PatternEngine 四检测器（Bullish/Bearish/BlackHorse/State）识别前 3 形态 | ❓ 用户：不清楚是什么。答复=具体量价形态识别（相对接近现状），应附形态定义才完整 |
| 6 | `vol_ratio` | 量比6.7 | **果**（数值重复） | 461-10 量比真值 | ❌ 用户：与 volume_energy **重复**（"量比6.7，显著放量"已含）。**去重**，并入 volume_energy |
| 7 | `pattern_score` | 10.0/10 | **果**（评分） | PatternEngine 10 分制聚合（基础5+形态权重） | ❌ 用户：评分是分析结论。形态名已表达现状，score 可选输出或归 JUD |
| 8 | `rps` | 61.5/100 | **果**（评分） | 跨截面 RPS 百分位（446-D12/460 统一供给） | ❌ 用户：评分是分析结论。转表述（前 X% 分位）或归 JUD（相对强弱属判定输入） |
| 9 | `granville` | 量价中性（无明显量价特征） | **半果半因** | `_classify_granville` 8 准则（5 日区间涨幅+量能，450 多日粒度+455 修正）——规则标准见 §三 | ❓ 用户：需说明具体分析逻辑/规则标准以便核实。答复=8 准则分类，命中规则可附上作因 |
| — | `audit.conditions` | 6 条（条件1✗/2✓/3✓/4✓/5✗/6✓） | **每条=一条分析逻辑实例（dim8 主原料）** | 量价关系/健康度/背离/量能/RPS/八准则 | ✅ 主原料（464 §12.1） |

---

## 二、granville 八准则规则标准（实证，供用户核实）

`_classify_granville(df, vol_ratio, tags)`——5 日窗口（price_chg = 收盘[-1]/收盘[-6]-1；vr = 5日/20日均量比率×100；vol_ratio 仅兜底）：

| 准则 | rule | 规则（5 日区间涨幅 + 量能） |
|---|---|---|
| 量价井喷 | explosive | price_chg>2 且 vr>40 |
| 量价齐升 | healthy | price_chg>2 且 vr>10 |
| 价升量减 | weakening | price_chg>1.5 且 vr<-10 |
| 放量滞涨 | heavy_pressure | 近3日每根量>前20日均量×1.5 且 3日涨幅和<1%（455 修正，对齐 framework） |
| 放量下跌 | selling_pressure | price_chg<-2 且 vr>10 |
| 回探缩量 | pullback_shrinking | price_chg<-1 且 vr<-10 |
| 放量破均线 | breakdown | price_chg<-4 且 vr>10 且 跌破 MA20 |
| 量价背离 | diverging | volume_price_fit==diverging |

**数据源**：df（daily_df，前复权）的 close/volume 列；df<20 日回退 vol_ratio 兜底。
**定位**：8 准则分类是"多日窗口观测的现状归类"——准则名是果，但可附命中规则作因（如"5日回调-3%+量缩15%"）。

---

## 三、待与用户深入沟通的细项（逐项深挖后定稿）

| # | 细项 | 当前方案倾向 | 需确认点 |
|---|---|---|---|
| 1 | **vp_state 的"因"怎么呈现** | 输出状态机具体状态（state_label + rule），替代 3 态概括 | dim8 是否需要 vp_state 键位保留（JUD 消费）？状态机 state_label 是否透传进 dim3 status_description？ |
| 2 | **volume_energy 连续性** | 补"连续 N 日放量/缩量"事实 | 连续性数据源（需多日 volume 序列）？"当日明显放量"与"连续放量"如何区分表述？ |
| 3 | **vol_ratio 去重** | 并入 volume_energy，不单独输出 | vol_ratio 是否有其他消费方需保留键位？ |
| 4 | **pattern 形态定义** | 形态名附定义（如"W底放量突破=两次探底+放量突破颈线"） | 形态定义从哪来（detector _NAMES/registry）？前 3 形态截断是否合适？ |
| 5 | **divergence 的"因"** | 有背离时输出检测条件 | 无背离时是否不占位？检测条件字段（divergence_type/strength）如何呈现？ |
| 6 | **rps 表述** | 转"前 X% 分位"或归 JUD | RPS 属现状（排名事实）还是判定输入（强弱）？ |
| 7 | **pattern_score** | 可选输出或归 JUD | 形态评分对 dim8 叙事是否必要？ |
| 8 | **granville 命中规则附因** | 准则名 + 命中规则（5日回调-X%+量缩Y%） | 命中规则的计算值从哪取？granville 返回值是否需扩展？ |

---

## 三.5 细项拍板记录（逐项深入沟通后更新）

### ✅ 细项 1（2026-09-20）：vp_state 的"因"= 透传状态机 state_label + rule
**拍板**：RAW 预计算阶段把状态机 `state_label` + `rule` 存进 pre_feat（volume_price 组新增 `vp_state_label`/`vp_rule`），dim3 透传到 status_description，dim8 输出"放量突破（VP_BREAKOUT：放量突破关键位）"——完整因果链（因→果）。

**核查现状（实施前置）**：
- pre_feat 的 `volume_price` 组当前来自 **`_simple`（简化版 `_add_vp_simple_tags`，data_daemon:3890）**——用"价格趋势 vs 量能趋势"粗逻辑（L3931-3945）产 volume_price_fit，**不是状态机**。
- 完整状态机 `compute_volume_price_signal` 在 **L3580 `_vp_f`**（derived/emotion 组运行时算），**不存 pre_feat**。
- **实施缺口**：把完整 `compute_volume_price_signal` 的 `state_label`+`rule` 透传到 pre_feat volume_price 组（新增字段），dim3 读取透传。**登记为待开实施号（补产出项）。**

**下游影响**：dim8 输出变"放量突破（VP_BREAKOUT：放量突破关键位）→ 量价强健康"（先因后果）；JUD 侧 vp_state 键位保留（dim3 judgment.state 仍产 3 态供投票，dim8 叙事用 state_label+rule）。

### ✅ 细项 2（2026-09-20）：volume_energy 补多日连续性
**拍板**：dim3 从 `data_context.daily_df` 算连续性（连续 N 日量>前20日均量×1.5=连续放量；<0.8=连续缩量；当日单独明显放量=当日放量），volume_energy 输出如"量比6.7，连续3日放量"——因（连续天数）→果（显著放量）。
**数据源**：daily_df 的 vol 列（dim3 已有，PatternEngine 用）已就绪。
**实施缺口**：dim3 新增连续性计算（多日 volume 序列），登记待开实施号。

### ✅ 细项 3（2026-09-20）：vol_ratio 在 dim8 叙事层去重
**拍板**：dim8 的 T 表只保留 volume_energy（含连续性+量比），移除 vol_ratio 键位；**引擎仍产 vol_ratio**（dim3 内部 ve/hs/granville + JUD signal_registry trigger 用），仅 dim8 叙事不重复输出。

### ✅ 细项 4（2026-09-20）：pattern 透传 conditions（形态因）
**拍板**：dim3 的 pattern_details 补透传 `conditions`（每条判定条件）→ dim8 输出如"W底放量突破（预涨）：条件[两次探底+放量突破颈线]"——**直接用引擎算出的"因"**，不需另建定义表。
**关键发现**：`PatternResult` 已有 `conditions`/`interpretation`/`strength`/`completion`/`levels` 字段（engine/patterns/__init__.py:60-77），但 dim3 的 `pattern_details['patterns']` 只取 `{'name','direction','strength'}`（engine.py:112）——**conditions 没透传**。
**实施缺口**：dim3 pattern_details 补透传 conditions（每条判定条件）。

### ✅ 细项 5（2026-09-20）：divergence 透传检测条件
**拍板**：RAW 预计算把 `VolumePriceSignal` 的 `divergence_type`/`divergence_confidence`/`divergence_macd_confirmed` 透传到 pre_feat，dim3 输出如"顶背离（置信0.6，MACD确认）"——有背离时呈现检测条件；无背离不占位。
**核查现状**：framework `VolumePriceSignal` dataclass 已有这三个字段（L154-168），但 data_daemon `_vp_f`（L3580）只取 volume_price_fit/kline_pattern，**未透传**。
**实施缺口**：data_daemon 透传 + dim3 读取，登记待开实施号。

### ✅ 细项 6（2026-09-20）：rps 转表述留 dim8
**拍板**：dim8 转表述"RPS=61.5（近20日涨幅全市场前 38% 分位）"——排名事实作现状；RPS>85 强势判定归 JUD。

### ✅ 细项 7（2026-09-20）：pattern_score 归 JUD
**拍板**：形态因（conditions）已透传，pattern_score 评分属结论归 JUD（dim8 不产）；引擎键保留供 JUD 判定。

### ✅ 细项 8（2026-09-20）：granville 附命中规则值
**拍板**：granville 返回值补 `price_chg`/`vr` 原始值（如"回探缩量：5日回调-3.2%，量缩15%"）——命中的具体规则作"因"，dim8 呈现。
**实施缺口**：`_classify_granville` 返回值扩展（rule/name/description + price_chg/vr），登记待开实施号。

---

## 四、定稿原则（沿用 dim2 定稿文档总则 + dim3 特有）

1. **原料 = audit.conditions 实例 + 结构化键值**（非 plain；plain 已删）。
2. **dim8 归集 = 实例→话术**，不是 plain 拼接。
3. **去重**：vol_ratio 并入 volume_energy；dim5 个股情绪主源 dim3（已定）；pattern 主源 PatternEngine（kline_pattern 归 JUD 右侧确认链）。
4. **纯契约/评分键**（health_score/rps/pattern_score）：优先归 JUD 或转表述，不裸放评分进叙事。
5. **因果链**：先因（依据/实例）后果（定性），如"放量突破（VP_BREAKOUT：放量突破关键位）→ 量价强健康"。

---

## 五、dim3 定稿结论（十键最终去向总表）

| 输出键 | 去向 | 定稿呈现（万科示例） | 补产出项（待开号） |
|---|---|---|---|
| `vp_state` | dim8 采用（改因） | "放量突破（VP_BREAKOUT：放量突破关键位）→ 量价强健康" | 透传状态机 state_label+rule 到 pre_feat（细项1） |
| `health_score` | **归 JUD**（不产 dim8） | — | hs 合成迁 JUD（439 同批） |
| `divergence` | dim8 采用（改因） | "顶背离（置信0.6，MACD确认）"；无背离不占位 | 透传 divergence_type/confidence/macd_confirmed（细项5） |
| `volume_energy` | dim8 采用（补连续性） | "量比6.7，连续3日放量" | 连续性计算（细项2） |
| `pattern` | dim8 采用（透传因） | "W底放量突破（预涨）：条件[两次探底+放量突破颈线]" | 透传 conditions（细项4） |
| `vol_ratio` | **dim8 去重**（引擎保留） | 并入 volume_energy，不单独输出 | dim8 T 表移除（细项3） |
| `pattern_score` | **归 JUD**（不产 dim8） | — | 引擎键保留供 JUD（细项7） |
| `rps` | dim8 采用（转表述） | "RPS=61.5（近20日涨幅全市场前 38% 分位）" | 转表述（细项6） |
| `granville` | dim8 采用（附命中值） | "回探缩量：5日回调-3.2%，量缩15%" | 返回值补 price_chg/vr（细项8） |
| `audit.conditions` | **dim8 主原料** | 6 条件逐条（量价关系/健康度/背离/量能/RPS/八准则） | 已就绪 |

**去重边界**：dim8 量价关系段 = vp_state(因) + volume_energy(含量比+连续性) + pattern(形态+条件) + rps(排名) + granville(命中值) + divergence(有背离时) + audit satisfied 项；health_score/pattern_score/vol_ratio 不进 dim8 叙事。
**因果链话术标准**：先因（state_label/conditions/命中值）后果（3 态/形态），如"放量突破（VP_BREAKOUT）→ 量价强健康"。

---

## 六、补产出项汇总（待开实施号）

| # | 补产出项 | 涉及文件 | 关联细项 |
|---|---|---|---|
| 1 | 透传状态机 state_label+rule 到 pre_feat volume_price 组（vp_state_label/vp_rule） | data_daemon _raw2_one + dim3 | 细项1 |
| 2 | volume_energy 多日连续性计算（连续 N 日放量/缩量） | dim3 | 细项2 |
| 3 | dim8 T 表移除 vol_ratio（并入 volume_energy） | dim8_summary_engine | 细项3 |
| 4 | pattern_details 透传 conditions（形态判定条件） | dim3 | 细项4 |
| 5 | 透传 divergence_type/confidence/macd_confirmed 到 pre_feat | data_daemon + dim3 | 细项5 |
| 6 | rps 转表述（全市场前 X% 分位） | dim3/dim8 | 细项6 |
| 7 | _classify_granville 返回值补 price_chg/vr | dim3 | 细项8 |
| — | health_score/pattern_score 归 JUD 合成迁移 | dim3 + JUD（439 同批） | 细项1-前置拍板 |

> **本文档为 dim3 定稿存档**（代码不改，仅定稿）；§六 补产出项登记为待开实施号，实施时新增锁定测试 + 全量回归（含 StatusEngine 真实全链路，443 R7 教训）。
