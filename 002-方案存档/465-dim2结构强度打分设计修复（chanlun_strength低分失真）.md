---
title: dim2 数据层与话术修复（464 核查后续：chanlun_strength 打分设计 + 8 项数据层问题）
type: 方案（判定逻辑为主；445 §6.2 冻结合规——确证有错 + 独立号 + 全链路验证；含事实接线/话术层项）
date: 2026-09-19
version: v0.4（465-1 打分设计、465-2 date 回填、465-3 audit 误判已实施；465-4~465-8 待拍板）
status: 🔄 实施中（465-1/465-2/465-3 已完成验证；465-4~465-8 登记待拍板）
related:
  - 464-dim2-dim7分析输出项全量梳理（SIG现状层）——§10.4 为 464-5 取键修复（事实层已落地）；§10.2 话术缺口 2/3 并入本号 465-4/465-5
  - 445-dim2-dim7引擎正确性知识库核查——引擎冻结边界（§6.2）；本号判定逻辑项属确证有错才动
  - 446-dim2-trend-fix——趋势判定修正（465-6 多级别矛盾依赖的 trend 判定背景）
  - 454-dim2-audit-gate——audit 5 条件（465-3 audit 语义失真的改造对象）
---

# 465 — dim2 数据层与话术修复

> **定位**：464 核查（输出项全量梳理 + 真实数据实证）暴露的 **dim2 输出项数据层问题汇集号**。2026-09-19 用户拍板：
> - **C 方案（补传 latest_close/market_context）并入 464-5 收尾（已落地，commit 4850e84）**；
> - **465-1 打分设计（A/B/D）** 与 **465-2~465-8 数据层问题（7 项）** 登记本号，待逐项拍板实施。
>
> **冻结边界**（445-freeze-vs-fact-layer）：**判定逻辑**项（465-1/3/6/7/8）确证有错才动、独立号全链路验证；**事实接线**项（465-2）该改就改不触冻结；**话术层**项（465-4/5）供 dim8 归集素材，改 plain 不触判定。

## 一、问题（真实数据实证，2026-09-19）

dim2 调用方式 `ChanlunScorer.score(chanlun_result)`（464-5 修复前恒 0.5）下，qfq 复权口径抽样 8 只：

| 股票 | 行业 | trend | 买点 | 卖点 | score |
|---|---|---|---|---|---|
| 万科A | 全国地产 | down | 1（一买） | 24（三卖） | **0** |
| 贵州茅台 | 白酒 | up | 0 | 15（三卖） | **0** |
| 宁德时代 | 电气设备 | unknown | 0 | 23（三卖） | **0** |
| 中国平安 | 保险 | unknown | 10（三买b） | 6（三卖） | **0** |
| 平安银行 | 银行 | unknown | 0 | 18（三卖） | **0** |
| 比亚迪 | 汽车整车 | down | 3（三买b） | 8（三卖） | **0** |
| 招商银行 | 银行 | unknown | 12（三买b） | 1（一卖） | 57 |
| 恒瑞医药 | 化学制药 | down | 15（三买b） | 0 | 62 |

**8 只中 6 只 = 0 分**，只有卖点极少（招行 1 个/恒瑞 0 个）才有正分；**茅台 trend=up 却 0 分**——结构强度与趋势方向完全脱节。

## 二、根因（3 层判定逻辑缺陷）

### A. 三买/三卖无数量上限、全历史累计（主因）
- `_find_third_points`（chanlun_strategy.py:2032）遍历**最新中枢之后所有笔对**，每次「上涨-回调/下跌-反弹」产一个三买/三卖，**无窗口/数量限制**；`only_judge_last` 默认 False（全历史模式）。
- 万科 24 个三卖 × (-8) = **-192 分**，一买 +50 完全抵不掉 → clamp 后 0。
- 历史卖点多是**长期走势特征**，非"当前结构强度"。

### B. type 变体不匹配 → 评分不对称（次因）
- `BuySellPointDetector` 产出变体类型：`third_buy_a`/`third_buy_b`/`first_buy_p`（盘整背驰一买）/`first_sell_p`/`third_sell_a`；
- `ChanlunScorer.score` 只匹配 `first_buy`/`second_buy`/`third_buy` → **买点变体每点加分被跳过**（只拿 `if buy_points:` 的 +30 基础）；卖点 `third_sell`（无前一卖时）能匹配 **-8×N** → 卖点照扣、买点不加，方向不对称。

### C. （已随 464-5C 落地，本号不重复）dim2 补传 latest_close/market_context

### D. clamp 大负分归 0
- `score = max(0, min(100, score + 50))`——大额扣分直接压 0，无法体现"有确认一买 + 结构健康"。

## 三、处置方案（465-1 已实施 A+B；D 由 A 吸收）

| 方案 | 内容 | 位置 | 状态 |
|---|---|---|---|
| **A 窗口限制** | 计分限每 type 最近 K 个买卖点（`_recent_by_type`，按 position.idx 取 idx 最大前 K 个；idx 缺失视为最新保留）；产出 analysis_result 不变、`buy_sell_points_detail` 仍全量展示 | `ChanlunScorer.score` 计分前过滤 + 模块级 `_recent_by_type`（K=`_RECENT_POINT_WINDOW`=3） | ✅ 已实施 |
| **B type 变体匹配** | scorer 补全 `first_buy_p`/`second_buy_b`/`third_buy_a`/`third_buy_b`/`first_sell_p`/`third_sell_a` 匹配（对齐基础三型 +20/+15/+10、-15/-10/-8） | `ChanlunScorer.score` 买卖点循环 | ✅ 已实施 |
| **D 三卖扣分封顶/降权** | 单类型扣分封顶 | — | 🔀 已由 A 吸收（每 type 最近 K 个即封顶语义），不再单列 |

**实施说明（2026-09-19）**：A+B 已在 `framework/chanlun_strategy.py` `ChanlunScorer.score` 落地。真实数据实证（8 只 qfq 抽样）：修复前 6/8 score=0（万科0/茅台0/宁德0/平安0/平安银行0/比亚迪0）→ 修复后 **0/8=0**（万科36/茅台11/宁德1/平安53/平安银行26/比亚迪56/招行87/恒瑞92）——与"当前结构强度"语义吻合（招行恒瑞三买多卖点少高分、茅台有三卖压力低分、宁德无买点 23 卖最低）。

## 四、445 冻结合规与验证计划

- **判定逻辑确证有错**（实证 6/8 score=0 + 茅台 up 打 0 + 买点不加分）→ 满足 445 §6.2 "有明确错误可修正"。
- **独立号全链路验证**（本号实施时）：
  1. 单测：`tests/test_465_chanlun_strength_design.py`——窗口/类型匹配/封顶各规则 + 边界（无买卖点/仅买/仅卖/大量卖点）+ 回归 test_464/396/446/457/463/454。
  2. 真实数据：全市场/抽样 score 分布（修复前 6/8 为 0 → 修复后差异化分布），对比茅台 up 不再 0 分。
  3. 下游回归：dim_adapter（0.4×chanlun_strength）、dim8 置信权重、status_engine confidence、前端七维段"置信xx%"。
- **不触碰**：trend/中枢/背驰判定（446/463 已定）、`_find_third_points` 的产出（buy_sell_points_detail 仍全量展示）、464-5 已落地的取键/归一/接线。

## 五、验收口径

- 修复后：有确认一买 + 结构健康的股票 score 为正（不再被历史三卖淹没）；茅台 up 不再 0 分；买点变体计入加分。
- 分布：全市场 score 不再"恒 0.5"或"大面积 0"，呈差异化分布。
- 下游：continuous_value 反映差异化置信，dim8 权重/前端置信随结构强度浮动。

---

## 六、其余 dim2 数据层问题登记（465-2~465-8，2026-09-19 用户拍板并入）

> 来源：464 §十 逐项评估 + 2026-09-18 真实数据核查（万科A/茅台/宁德/平安等，strategy_signal_detail 2026-09-18 交易日 5550 只）。每项标注**性质**（判定逻辑=445 冻结合规 / 事实接线=该改就改 / 话术层=dim8 归集素材）。

### 465-2｜`buy_sell_points_detail.date` 空（事实接线）✅ 已实施

- **现象（实证）**：万科A 一买 `{"type":"buy","point_type":"first_buy","confirmed":true,"confidence":1.0,"price":2.98,"date":"","index":1261}`——**date 为空**；601318 等二三买有 date。话术"确认一买信号于 **X 日** Y 元"的时间要素缺失。
- **根因**：一买 position = `divergence.position`（`BuySellPointDetector.find` 一买分支只带 `divergence.position`，含 idx 无 date）；二三买 position 由 `_find_second/_find_third_points` 显式带 `date`。dim2 序列化 `'date': str(_pos.get('date', '') or '')` 如实透传空。
- **处置（已实施，2026-09-19）**：dim2 新增 `_resolve_bsp_date(position, df)`——position.date 非空原样返回；空则从 `position.idx` 反查 `daily_df['trade_date']`（`str(...)[:10]`，越界/无 trade_date 列/异常 → ''）。仅 dim2 序列化层回填，framework 判定零改动。
- **验证**：`tests/test_465_dim2_strength_design.py` `TestBspDateBackfill`（5 用例：idx 回填/原样保留/越界/无 df/无 trade_date 列）+ `TestDim2BspDateIntegration`（2 用例：evaluate 输出一买 date 回填、二买 date 保留）。

### 465-3｜audit「价格vs中枢」把「无有效中枢」当满足（判定逻辑）✅ 已实施

- **现象（实证）**：万科/茅台 audit `cond[价格vs中枢] satisfied=True actual=无有效中枢`——"无明确位置"被判满足，两股 audit confidence 因此抬到 0.8。**全市场：5550 只中 4491 只（81%）为「无有效中枢」（463 时效过滤后为常态），旧逻辑 `bool(position)` 全部误判满足。**
- **根因**：454 号 audit 条件 `'satisfied': bool(vs_zhongshu['position'])`，`_assess_vs_zhongshu` 无有效中枢时返回 `{'position': '无有效中枢', ...}`——非空字符串 → satisfied=True。
- **处置（已实施，2026-09-19）**：条件判定改为 `vs_zhongshu['position'] not in ('', '无有效中枢')`（有效值域=上方/下方/内部；无有效中枢视为该条件未达成），threshold 改「有明确位置（有效中枢上/下/内）」。audit confidence 回归真实达成度。
- **影响评估（真实库 5550 只，2026-09-18）**：
  - audit confidence 分布：旧 0.8/1.0 占 57%（3173 只）→ 新 0.6/0.4 占 77%（4272 只），不再虚高。
  - dim8 `data_warning`（7 维 audit 均值 <0.7）：旧 90.1%（4998 只）→ 新 95.0%（5275 只），仅新增 277 只（+4.9pp）；**90.1% 本就是既有状态**（454 判读条件后各维 confidence 普遍偏低所致，非 465-3 引入）。
- **验证**：`tests/test_465_dim2_strength_design.py` `TestAuditZhongshuPosition`（4 用例：无有效中枢不满足/有效中枢上方满足/tags 兜底满足/万科场景 3/5=0.6）；`tests/test_454_dim2_audit.py` 适配 463+465-3 现状（`_mk_zs` 有效中枢构造替代 tags 兜底，3 个既有失败全部修复）；framework+dim2 回归 130 passed + dim8/dim_adapter 链 83 passed。
- **注**：`data_warning` 本身 90% 大面积触发是既有状态（420 增强6 语义 vs 各维 confidence 普遍偏低的现状），不在本子项范围，可另议。

### 465-4｜`plain` 缺趋势方向结论句（话术层；464 §10.2-1 最严重缺口）

- **现象（实证）**：万科 plain="均线交织，距支撑位3.13元(-5.7%)，距压力位3.40元(+2.4%)，筹码集中，获利盘28%"——**无"下降"结论句、无 trend_basis 依据**；前端叙事链断裂（dim8 段落 text/evidence 主源是 plain）。
- **根因**：`_structure_plain(vs_z, vs_ma, vs_sr, vs_chip, vs_ind)` 只拼中枢位置+均线+支撑阻力+筹码，不读 `chanlun_direction`/`trend_basis`/`stage_name`（注意：pos=='上方' 时输出"价格突破中枢上沿，离开成本区"近似 trend_basis 文案，但无趋势方向结论）。
- **处置方向**：plain 前缀补趋势句（如"当前处于下降趋势（依据：无中枢-最近3段方向）"），对齐 444「现状=因果链的因」——trend_basis 即因。

### 465-5｜`vs_ind` 计算未入 plain（话术层；464 §10.2-2）

- **现象（实证）**：万科 vs_indicator="均线纠缠，RSI 59 中性"已产出，但 plain 无 RSI/均线形态段。
- **根因**：`_structure_plain` 签名含 `vs_ind` 参数，**函数体从未使用**（只用了 vs_z/vs_ma/vs_sr/vs_chip）。
- **处置方向**：函数体补 `vs_ind` 拼接（RSI 强弱 + 均线形态，注意与 vs_ma 均线段去重）。

### 465-6｜多级别方向 vs 单级别趋势矛盾（判定逻辑）

- **现象（实证）**：茅台 judgment=**上升**（green），但 `multi_level_direction_text`=**"周线下降趋势中的日线反弹"**——周线下降、日线上升；万科 judgment=下降 但 multi_level 同为"周线下降趋势中的日线反弹"。10.1 #10 的"周/日/60min 方向一致（上升），多周期共振"话术在两股均不成立。
- **根因**：单级别 `_determine_trend`（无有效中枢 → 最近 3 段多数派兜底）与 457 号 `MultiLevelChanlunAnalyzer`（周/日/60min 区间套，周线定大方向）**两套方向判定、无仲裁**。
- **处置方向**：需定义多级别与单级别方向冲突时的口径（以周线为纲降级日线？还是 SIG 如实并列输出"周线降+日线反弹"现状、判定归 JUD）；属 445 引擎判定逻辑，独立号验证。

### 465-7｜顶背驰与确认一买并存（判定逻辑/叙事层）

- **现象（实证）**：万科 audit「背驰检测=False（**顶背驰**，趋势背驰，强度1.0）」与「有确认买点=True（**确认一买**，置信1.0）」同时成立；一买 reason="下跌趋势背驰，trend类型"——顶背驰（方向 down）与一买（下跌背驰买入）方向语义冲突。
- **根因**：`divergence`（最新背驰）与 `buy_points`（全历史买卖点，最新中枢后累积）来自不同时间点/不同背驰，audit 两条件分别读各自来源 → 可同真且方向矛盾。
- **处置方向**：明确"顶背驰 + 确认一买"并存时 SIG 现状如何表述（如实并列"出现顶背驰警示 + 存在确认一买"、由 JUD 仲裁）；或 audit「背驰检测」限定与最新买点同源。属判定逻辑，独立验证。

### 465-8｜RSI 31-69 全归中性（判定逻辑）

- **现象（实证）**：茅台 RSI **34**（偏弱侧）被判"中性"；vs_indicator="均线纠缠，RSI 34 中性"。10.1 #5"RSI 72 偏强"成立但弱侧信息在 31-69 区间被吞。
- **根因**：`_assess_vs_indicator` 分档 `rsi >= 70 偏强 / <= 30 偏弱 / else 中性`（461-1 SSOT 后）。
- **处置方向**：分档加中位参考（如 40-60 中性、30-40 偏弱、60-70 偏强），或保持三档但对齐知识库档位；属判定逻辑（阈值），独立验证。

### 附注

- **464 §10.2-3 跨键重复**（均线 #2/#5 两源、买卖点 #9/#14 两处）——dim8 归集需定主源（建议 #14、#2），属 437-A 归集设计范畴，未列本号子项；如需并入请拍板。
- 登记即事实（2026-09-19 实证），未改代码；每项实施前按 445 冻结边界分类走验证流程。
