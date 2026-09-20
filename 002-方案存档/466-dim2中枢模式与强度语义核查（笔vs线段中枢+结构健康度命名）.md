---
title: dim2 中枢模式评估与强度语义核查（笔中枢vs线段中枢 + chanlun_strength 重规划为结构健康度）
type: 核查/评估文档（2026-09-20 真实数据实证后形成；中枢模式①与强度语义③④⑤已全部拍板实施）
date: 2026-09-20
version: v0.3
status: ✅ 中枢模式 ① 已实施（先修延展判定+切日线笔中枢）；强度语义 ③④⑤ 已实施（§四-B）
related:
  - 464-dim2-dim7分析输出项全量梳理（SIG现状层）——输出项契约；§10 话术缺口；465 前身
  - 465-dim2结构强度打分设计修复——465-1A/B 已窗口化+type匹配；本号 ② 为其下一步语义重规划
  - 285-缠论策略量化实现全面审计与对标整改方案——P3a 笔中枢架构裁定（本号 ① 依据）
  - 446-dim2-trend-fix（D1/D2）+ dim2-contract-keys（D10）——线段中枢 + chanlun_phase 契约
  - 463-缠论复权口径与中枢选用级别修复——_select_current_zhongshu 180天时效（"无有效中枢"高发来源）
  - 457-dim2多周期级联接线——多级别统一线段中枢（本号 ① 已改 daily=笔中枢，周/时线保留线段）
  - 444-SIG股票现状描述事实层——现状=因；强度语义对 dim8 归集的影响
  - 445-dim2-dim7引擎正确性知识库核查——冻结边界（判定逻辑确证有错才动，独立号全链路验证）
---

# 466 — dim2 中枢模式评估 + 强度/置信度语义重规划

> **定位**：2026-09-20 用户在 dim2 真实数据核查（茅台/宁德，464/465 上下文）后提出的两个方向性追问，本号**只评估 + 规划，不拍板、不改代码**：
> 1. **中枢构建模式**：日线用"笔中枢"而非"线段中枢"是否更贴合、能否更精准识别中枢（能否缓解"无有效中枢"高发）？
> 2. **置信度语义**：`chanlun_strength`（现被当"置信度"）实际更接近"走势健康度"，需按知识库重新规划命名与计分细节。
>
> **冻结边界**（445-freeze-vs-fact-layer）：两项均涉**判定逻辑**，须用户拍板后独立号（或并入 465 后续）全链路验证；本号不改代码。

---

## 一、背景：本次核查暴露的两个事实

真实数据运行 dim2（`run_dim2_real2.py`，复刻 status_engine 全链路 + 真实扁平化 tags）茅台/宁德：

| 项 | 茅台 600519.SH | 宁德 300750.SZ |
|---|---|---|
| 缠论中枢（日线线段中枢） | `expanded`，[1593,2010.82]，duration 9月 | `normal`，[485.06,570.99]，duration 6月 |
| `vs_zhongshu` | **无有效中枢**（end 距今 >180天 失效） | **无有效中枢**（同） |
| `trend_basis` | 无中枢-最近3段方向 | 价格近3年区间中部震荡（长期横盘） |
| `chanlun_phase` | 健康（11定理≥0.6） | 健康 |
| `chanlun_strength` / continuous_value | **8.0 / 0.08** | **0.0 / 0.0** |
| audit | 3/5（✗ 价格vs中枢、✗ 有确认买点） | 2/5（✗ 趋势方向、✗ 价格vs中枢、✗ 有确认买点） |

**两个事实**：
- **F1（②背景）**：茅台"健康结构 + 上升 + 无背驰"却打出"置信度 8%"——**健康度与"置信度"自相矛盾**，证明 `chanlun_strength` 语义错位。
- **F2（①背景）**：两股都是"**无有效日线中枢**"，audit「价格vs中枢」必 ✗。465-3 已证实全市场 5550 只中 4491 只（81%）为"无有效中枢"——**这是常态，不是 463 的 bug，而是线段中枢与时效过滤叠加的结果**。

---

## 二、① 中枢模式评估：笔中枢 vs 线段中枢（是否更贴合、更精准）

### 2.1 知识库指引（权威，无矛盾）
《缠论走势结构量化系统配置指南》：
- §二-L72：**"对于 T+1/T+2 短线，建议使用笔中枢"**（短线允许笔中枢）。
- §二-L136：**"中枢定义：短线允许笔中枢，中长线强制线段中枢"**。

即知识库承认**两套中枢**，按操作级别区分：短线(笔) / 中长线(线段)。

### 2.2 现有实现的裁决历史（矛盾点）
| 方案 | 裁定 | 结果 |
|---|---|---|
| **285 号 P3a** | 架构转型：日线默认 `bi_zs_mode=True`（**笔中枢**）；依据=czsc/chan.py 社区真实数据特征序列分型几乎不触发线段终结，两库默认跳过线段层直接笔中枢；46 笔自然形成 5~8 个笔中枢 | 新增 `BiZhongshuFinder` + `bi_zs_mode=false` 回退单行 |
| **446-D2** | dim2 日线定 `bi_zs_mode=False`（**线段中枢**）；依据=知识库"中长线强制线段中枢" | 日线=线段中枢，段不足回退笔中枢 |
| **457 号** | 多级别(周/日/60min)统一线段中枢 | 各级别对齐线段中枢 |

**矛盾**：285 曾裁定日线默认笔中枢（对齐 czsc 实战），446-D2 又按知识库字面改为线段中枢（日线=中长线）。**当前生效口径=线段中枢**，与本系统 285 时期的设计意图相反。

### 2.3 线段中枢为何导致"无有效中枢"高发（机理）
- 线段中枢由**线段**构建，而线段终结依赖**特征序列分型**，285 实证该分型在真实数据几乎不断线 → 线段少且长 → 中枢由连续多段延伸/扩张形成**巨长中枢**：
  - 茅台日线 expanded 9月、宁德 6 月、周线 42~60 月。
- 463 号 `_select_current_zhongshu` 对 **end_date 距今 >180 天**判"失效跳过" → 巨长中枢的 end 往往 >180 天 → **被判定无有效中枢**。
- **结论**：线段中枢的"大跨度"与 180 天时效的叠加，是"无有效中枢"81% 高发的**结构性根因**，不是单点参数问题。趋势延续股（茅台/宁德）长期无新线段中枢，必然退化到"最近3段方向/长期横盘"兜底。

### 2.4 笔中枢为何更贴合、更精准
- 笔中枢由**笔**直接构建，笔在真实数据稳定（分型成笔确定性高），不像线段那样受"特征序列几乎不断线"约束。
- 285 P3a 实测：46 笔自然形成约 **5~8 个笔中枢**（3 年周期）——**中枢更小、更密、更新**，最近中枢更可能落在 180 天时效窗内。
- **直接收益**（对齐本次两大痛点）：
  1. "无有效中枢"高发显著缓解 → audit「价格vs中枢」可达成，audit confidence 抬升；
  2. `trend_basis` 从"最近3段方向/长期横盘"退化为**"价格突破中枢上沿/跌破中枢下沿"**（真实中枢依据）——**正是 444"现状=因"要的因果链核心素材**；
  3. 与 czsc/chan.py 行业标准对齐，多级别联立口径一致。
- **代价/风险**：笔中枢对噪音更敏感（笔粒度细，中枢更小更短），可能引入更多假中枢/假位置；285 已留 `bi_zs_mode=False` 单行回退。

### 2.5 评估结论（建议，待拍板）
- **建议①**：**日线主判据切笔中枢**（`bi_zs_mode=True`），线段中枢保留为可选项/确认层，保留 285 回退开关。
- **建议（备选）**：若想保留线段中枢"中长线严谨性"，可**放宽线段中枢时效**（180 天→跨年/升级周线口径，463 原意）而非切笔；但工程上笔中枢更直接解决"无有效中枢高发 + czsc 对齐"两目标。
- **判定影响面**：`_determine_trend`/`_determine_trend_basis`/`_assess_vs_zhongshu`/audit「价格vs中枢」`buy_sell_points_detail`（三买三卖依赖最新中枢）都会随中枢模式变化 → 属 445 冻结边界"判定逻辑确证改善"，须独立号全链路验证（含全市场中枢分布、audit confidence 分布、dim8 归集回归）。

---

## 三、② `chanlun_strength`（置信度）→ 走势健康度 重规划

### 3.1 现状问题（语义错位）
- **字段**：`chanlun_strength`=0-100（`ChanlunScorer.score`）；`continuous_value = strength/100`，被当"置信度"。
- **本质**：`ChanlunScorer.score` 是**纯买卖点加减打分**（465-1A/B 已窗口化每 type 最近 3 点 + type 变体匹配；另有价格匹配/背驰/趋势/中枢/市场上下文加权）+50 归一到 0-100。
- **矛盾实证**：茅台 健康+上升+无背驰 → 8%(仅因有三卖)；宁德 健康 → 0%。**"置信度"度量的是"近期有无买卖点信号"，不是健康度，更不是可信度** → 前端展示"置信xx%"失真。

### 3.2 知识库健康度依据（权威）
- **缠中说禅笔定理**：走势状态四态（1,1）、(-1,1)、(1,0)、(-1,0)，用于判断**未病/欲病/已病**（`concepts/缠中说禅笔定理.md`、`concepts/缠论.md`、`concepts/中阴阶段.md`）。
- **11 定理**：本系统 `ChanlunTheoremValidator.validate` 已输出 `overall_score`（11 定理均分 0-1），dim2 已用 `≥0.6→健康` 产出 `chanlun_phase`（446 D10）。**11 定理才是"走势健康度"的权威量化来源。**

### 3.3 重规划建议（三块）
**① 命名（语义明确为健康度）**：
- 输出键建议 `chanlun_strength` → **`structure_health_score`**（0-100）；`channel_phase`（健康/欲病）保留为档位标签。
- `judgment.continuous_value` 语义从"置信度"改为"**结构健康度归一**"，供 JUD/dim8 作健康置信，不再冒充信号置信。
- 前端七维段"置信xx%"展示文案改为"**结构健康xx/100**"（待前端/ dim8 渲染侧同步）。

**② 计分重构（多源加权，买卖点降为信号项）**：
- 新计分 `structure_health_score` 以 **11 定理 `overall_score` 为基底**（健康度权威），叠加：
  - 中枢质量（有效中枢形成/稳定性）
  - 趋势延续（趋势方向一致性/多级别共振）
  - 买卖点信号（一/二/三买加分、三卖减分，仍 465-1A/B 窗口化）
  - 背驰（无背驰健康 / 顶背驰警示）
- 消解"健康结构却 8%"：**有 11 定理健康 + 无背驰 + 无确认买点**时应回落到中性偏高（而非被三卖压到 8%）。
- 注意与 465-1（chanlun_strength 打分设计）衔接：465-1 已修"恒0.5/大面积0"，本号是**进一步把计分主源从买卖点换到 11 定理**，属同一字段的语义升级，建议**并入 465 号后续子项（465-9）**或独立号。

**③ 消费方迁移（改名影响面，已逐一核出）**：
- `dim2_structure_engine.py:260`（产 `chanlun_strength` 键）、`:289`（`continuous_value = strength/100`）
- `dim_adapter.py:526-533`（`_str_sd.get('chanlun_strength')`，0.4×加权，/100归一）
- `reliability_assessor.py:83-84`（读 `chanlun_strength_components`）
- 测试契约：`test_464_chanlun_strength.py`、`test_418_jud_v390.py`、`test_390_integration.py`、`test_446_dim2_contract_keys.py`
- 前端七维段/ dim8 归集（`_extract_dim_plain`/evidence 的置信文案）
- **兼容建议**：新增 `structure_health_score` 键，`chanlun_strength` 保留为别名/迁移期兼容（consumer 双读），避免一次性 break 契约。

### 3.4 判定影响面
- 属 445 冻结边界"判定逻辑"→ 独立号全链路验证（单测 + 全市场 score 分布 + dim8/dim_adapter/reliability 回归）。

---

## 四、待拍板清单（本号不改代码）

> **更新（v0.3）**：中枢模式 ① 已实施（§四-A）；**强度语义 ③④⑤ 已全部实施**（§四-B）——`structure_health_score` 以 11 定理为基底计分，`chanlun_strength` 保留别名，dim8 structure 维文案改"结构健康xx/100"。

| # | 项 | 类型 | 建议 |
|---|---|---|---|
| ① | 日线中枢模式：线段→笔中枢 | 判定逻辑 | ✅ **已拍板实施**（见 §四-A） |
| ② | 线段中枢时效放宽备选 | 判定逻辑 | 🔄 备选方案，随 ① 实施已不再需要 |
| ③ | `chanlun_strength` 更名 `structure_health_score`，continuous_value 语义改"健康度归一" | 命名+语义 | ✅ **已实施**（新增键+保留别名迁移，consumer 双读；见 §四-B） |
| ④ | 计分重构：11 定理为基底，买卖点降为信号项 | 判定逻辑 | ✅ **已实施**（新增 `ChanlunScorer.structure_health_score`；见 §四-B） |
| ⑤ | 前端/dim8 置信文案改"结构健康xx/100" | 话术层 | ✅ **已实施**（dim8 structure 维；见 §四-B） |

**冻结边界**：② ④ 属判定逻辑（已独立实现+全链路验证）；③ ⑤ 命名/话术层随 ④ 同号迁移完成。

## 四-A、① 实施记录：日线切笔中枢（2026-09-20 拍板）

### A.1 背景：用户要求
> "做日线的笔中枢，另外需要你严格检查笔中枢的代码配置，是否符合中枢鉴别、中枢延展、新中枢产生等具体的中枢规则，避免因代码问题导致的问题，同时借鉴一下同类项目关于中枢的设置"

即：① 日线切笔中枢 + ② 严格核查 `BiZhongshuFinder` 是否符合中枢三规则 + 借鉴 czsc 同类项目。

### A.2 全市场样本实证（对比脚本 `tmp/compare_zs_mode.py`，30 只 seed=42）
| 指标 | 线段中枢 | 笔中枢 |
|---|---|---|
| 有效中枢占比 | 13% | **87%** |
| 无有效中枢占比 | 87% | 13% |
| 真实中枢依据(trend_basis)占比 | 13% | **87%** |
| 与均线排列参照一致率（junxian-xitong 多头/空头） | 30% | **80%** |

- 均线排列（`junxian-xitong.md`：MA5/10/20/60 多头=up/空头=down）为**独立于缠论**的第三方参照，验证笔中枢趋势方向与客观走势识别高度一致。
- 笔中枢大幅缓解"无有效中枢"（87%→13%），是 466 号 F2/465-3 所述 81% 高发的根治。

### A.3 代码核查：`BiZhongshuFinder` 与 czsc 权威实现对照
**czsc 权威参照**（`.venv/.../czsc/py/objects.py`）：
- `ZS` 中枢：`zd = max(bis[:3].low)`（下沿=max前3笔下沿）、`zg = min(bis[:3].high)`（上沿=min前3笔上沿）——**中枢区间=前三笔重叠**。
- `ZS.is_valid`：**每笔 `bis` 的区间与中枢 [zd,zg] 有交集即算中枢有效/延伸**（`zg>=bi.high>=zd or zg>=bi.low>=zd or bi.high>=zg>zd>=bi.low`）。
- `get_zs`：连续 3 笔重叠 → 中枢。

**当前 `BiZhongshuFinder` 与 czsc 的三规则对照**：
| 规则 | czsc 标准 | 现状代码 | 结论 |
|---|---|---|---|
| 中枢鉴别（形成） | 连续 3 笔重叠 | `find()` 起头 3 笔求重叠区间 `[max(三笔下沿), min(三笔上沿)]` | ✅ 一致 |
| 中枢区间 | `zd=max(前3笔low), zg=min(前3笔high)` | `overlap_low=max(lows), overlap_high=min(highs)` | ✅ 一致（数学等价） |
| 中枢延展 | 每笔区间与 [zd,zg] **有交集**即延伸 | **旧：`if end_p>high or end_p<low: break`（只用笔终点单点）** | ❌ **偏差** |
| 新中枢产生 | 整笔离开后闭合、从离开笔继续 | 闭合后 `i=j` 从离开笔继续 | ✅ 一致（但受延展误判影响） |

**核心偏差（已修复）**：旧延展判定用**笔终点 `end_price` 单点**判断是否离开。czsc 用**整笔区间是否与中枢重叠**。
- 后果：一笔冲高中枢上沿后回落（终点回到中枢内、但整笔已破上沿）、或假突破下沿后拉回，旧实现会单点误判 → 中枢**提前闭合**或**过度延伸**。
- **修复**（`chanlun_strategy.py` `BiZhongshuFinder.find`）：改用整笔区间
  ```python
  s_lo = min(seg.start_price, seg.end_price); s_hi = max(...)
  if s_hi < low or s_lo > high:  # 整笔完全离开 → 闭合
      break
  ```
  对齐 czsc `ZS.is_valid`：整笔与中枢区间有交集即延伸，完全不相交才闭合。

### A.4 切换与接线（已实施）
| 文件 | 改动 |
|---|---|
| `dim2_structure_engine.py:103` | 日线 `ChanlunAnalyzer({'bi_zs_mode': True})`（原 `False`）——**主链切笔中枢** |
| `chanlun_multi_level.py` | `analyze` 内 daily 级别 `dataclasses.replace(config.multi_level, bi_zs_mode=True)` 覆盖为笔中枢；weekly/hourly 保持线段中枢（知识库：中长线线段、短线笔） |
| `chanlun_strategy.py` | `BiZhongshuFinder.find` 延展判定修整笔区间交集（§A.3）；`_determine_trend/_determine_trend_basis` 兜底已用 `strokes` 末 3 笔，笔中枢模式天然可用 |

**兼容**：`MultiLevelConfig.bi_zs_mode` 默认值保持 `False`（周/时线线段），仅 daily 在联立内覆盖为笔中枢——语义为"日线笔中枢、周线线段中枢"分级，符合知识库。

### A.5 验证
- **新增单测** `tests/test_466_dim2_bi_zhongshu.py`（5 项）：三笔重叠成中枢 / 笔终点离开但整笔重叠→仍延伸（修复核心）/ 整笔完全离开→闭合 / 闭合后新中枢产生 / 笔数不足。
- **联立断言** `test_457_multi_level.py::TestBiZsModeAlignment::test_daily_level_uses_bi_zs_mode_true`：daily 走笔中枢。
- **回归**：dim2/缠论/联立相关 135 项全过（test_396/446_*/454/457/463/464/465/466/chanlun_verification）；全量套件 1256 passed，11 failed 均为既有 DB 环境类（无 daily_cache/daily_basic_cache 表，snapshot/gateway 类，非本改动引入）。
- **真实数据**（`tmp/verify_bi_fix.py`）：茅台/宁德/002690/600066/920069 均产笔中枢且有有效中枢；中枢时间跨度合理（不再巨型）；`vs_zhongshu` / 趋势 / `multi_level` direction_text 正常。延展修复后笔中枢桩数较修复前收敛（茅台 22→13、宁德 17→13、002690 14→11、600066 16→9）——不再把假突破笔误延伸进中枢。
- **修复后 30 只全市场重跑**：有效中枢 87%、均线一致率笔 80%、真实中枢依据 87% 全部保持；平均桩数 11.5→8.1（延展收敛的自然结果）。

### A.6 后续
- 强度语义 ③④⑤（`structure_health_score` 命名 + 11 定理基底计分 + 前端文案）已并入本号于 §四-B 实施。
- 444/dim8 归集依赖中枢位置素材，笔中枢已提供"价格突破/跌破中枢上沿/下沿"真实依据，与 444"现状=因"因果链目标一致。

---

## 四-B、③④⑤ 实施记录：chanlun_strength → 结构健康度（2026-09-20 拍板）

> 用户延续 466 号方向性追问的落地指令："继续做③④⑤强度语义改造"。以 464/465 真实核查暴露的"健康+上升+无背驰却置信8%/0%（茅台/宁德）"为根因，把 `chanlun_strength` 语义从"信号强度/置信度"重规划为"结构健康度"。

### B.1 计分重构 ④：`ChanlunScorer.structure_health_score(analysis_result, market_context)`（新增）
以 11 定理 `overall_score` 为**基底**（权威健康来源，与 `chanlun_phase` 同源，`ChanlunAnalyzer` step 9 已产 `theorem_check`）：
- `base = theorem if theorem>0 else 0.6`（无定理数据按"欲病"中性不塌底）→ `score = 100*base`
- 轻信号项加权：有效中枢 +6 / 多中枢方向矛盾 -8 / 上升 +10、下降 -6 / 底背驰 +6、顶背驰 -12 / 近期买卖点 ±轻（买 +2/点 上限+6，卖 -3/点 上限-8）/ 换手活跃 +2~3 / 大盘偏弱 -4、偏强 +2
- `score = clamp[0,100]`；返回 `{'score','details','recommendation'}`（与 `score()` 同构，consumer 复用）
- **消解"健康却8%"**：健康(0.7)+上升+无背驰 → 80 分（旧 `score()` 因 15 三卖 -192 压到 6）；健康+大量三卖也只轻扣，不被历史卖点压底。
- **`score()` 保留**：纯买卖点信号强度，供 `ChanlunAlphaModel.generate_insights` / `ChanlunLevelValidator._analyze_level` 使用——职责分离（信号强度 vs 结构健康度）。

### B.2 产出接线 ③：`dim2_structure_engine.py`
- `evaluate` step 4：调用 `scorer.structure_health_score(chanlun_result, market_context=...)`（不传 `latest_close`——价格匹配惩罚是 `score()` 信号语义，与健康度无关）。
- 契约键：`status_description.chanlun_strength`（**保留别名**，0-100，现语义=结构健康度）+ **新增 `structure_health_score`**（同值）；`judgment.continuous_value = 健康度/100`（"健康度归一"而非"置信度"）。
- 消费方迁移：`dim_adapter.py` 优先读 `structure_health_score`、回退 `chanlun_strength`（0-100 归一 0-1，参与 0.4/0.4/0.2 加权）；`reliability_assessor` 走 `chanlun_strength_components` 不受影响。

### B.3 话术 ⑤：`dim8_summary_engine._brief_text`
- `key_in == 'structure'` → `"状态（结构健康{conf*100:.0f}/100）"`；其余维保持 `"置信{conf:.0%}"`。dim8 对结构维不再冒充信号"置信%"，改显式结构健康度。

### B.4 验证
- **新增单测** `tests/test_466_dim2_strength_semantics.py`（10 项）：健康结构不塌底（茅台场景 80）/ 大量三卖不压底 >60 / 欲病下降顶背驰 <60 / 11 定理基底拉开 / 中枢 +6 / 契约键 present + 同值 + continuous=健康/100 / dim8 structure 维文案 + 其他维置信保持 + 缩放。
- **回归**：test_464（mock 改 `structure_health_score`，原最新价/市场键断言随新签名更新）/ 465 / 446 / 420 / 454 / 418 / 390 / 396 / 457 / 463 — **192 项全过**；全量套件 collection 报错（`test_api_health`/`test_api_routes` `create_app` import、`$TMPDIR/test_sandbox`）均为既有环境类，非本改动引入。
- 真实语义样例：茅台（健康+上升+无背驰+15 三卖）健康度由旧 `score()` 的 8 分升至 >60 健康区间——消解 F1 矛盾。
- **全市场分布验证（真实数据，seed=42，n=50，2026-09-20）**：`structure_health_score` 均值 53.6 / 中位 54 / p25 45 / p75 60 / min 35 / max 79；分档 0-20(0) 20-40(5) 40-60(32) 60-80(13) 80-100(0)；按结构态下降 50.6 < 盘整 56 < 上升 62.3（方向区分正确）。`chanlun_strength` 别名 = `structure_health_score` 100%（0 失配）；`continuous_value = 健康度/100` 100%（0 失配）。
- **拍板口径（audit 同源）**：验证暴露"front 健康度<60 但旧 phase=健康（纯 11 定理）"分叉。用户拍板 audit「结构健康度」改用 `structure_health_score>=60`（不再读 `chanlun_phase`），与前端文案同源。改造后 audit 该条件 ⟺ 前端分数>=60 失配 **0/50**，消除"audit=健康但前端结构健康54/100"打架；`chanlun_phase` 键保留（仍由 11 定理产出），仅不作 audit 判读。

### B.5 后续
- `chanlun_strength` 别名保留一段迁移期；如后续消费方全部切 `structure_health_score` 可再删别名（一次性 break 风险已在 §3.3 评估，当前选择双读兼容）。

---

## 五、验证计划（已执行）

> ① 中枢模式与 ③④⑤ 强度语义均已实施并验证（见 §四-A / §四-B）。

- **①中枢模式**：全市场新旧中枢分布对比（线段 vs 笔）——**已执行**（§A.2：有效中枢 13%→87%、均线一致率 30%→80%、真实依据 13%→87%）+ 茅台/宁德/万科 回归（trend_basis 从兜底→真实中枢依据）。
- **③④强度语义**：单测（`structure_health_score` 命名/11定理基底/买卖点降权/边界）——**已执行**（§B.4：test_466_dim2_strength_semantics 10 项）；dim8/dim_adapter 回归——已执行；**全市场 score 分布**——**已执行**（§B.4，n=50：均值 53.6、别名/continuous 100% 同步、audit 与前端口径同源失配 0/50）；前端置信文案回归——后端 dim8 侧已落地，渲染侧原型非生产（待前端正式页同步）。
- **全链路**：sig_full_test 全量 dim 回归（确认不强依赖中枢模式的 dim3-dim7 不受影响）——待有 SIG 真实全量运行环境时执行。

---

## 六、附注（供参考）

- **`bi_zs_mode` 现状（更新 v0.3）**：dim2 日线=**笔中枢**（`ChanlunAnalyzer({'bi_zs_mode': True})`，466 ① 已改）；multi_level **daily=笔中枢**、weekly/hourly=线段中枢（`MultiLevelConfig.bi_zs_mode` 默认 False，daily 在联立内覆盖为 True，466 ① 已改）；`BiZhongshuFinder` 延展判定已对齐 czsc `ZS.is_valid` 整笔区间交集语义（§四-A）。
- **强度语义现状（v0.3 新增）**：`channel_strength`（0-100）现语义=**结构健康度**（466 ③④），新增 `structure_health_score` 键同值；`judgment.continuous_value`=健康度/100 供 JUD/dim8 作健康置信；dim8 structure 维文案"结构健康xx/100"（§四-B）。旧 `chanlun_strength` 键名保留为迁移别名。
- **"无有效中枢"与 465-3**：465-3 已把 audit「价格vs中枢」改为"无有效中枢≠满足"（全市场 confidence 从 57% 虚高降到 77% 在 0.6/0.4）；本号 ① 若切笔中枢，将**从源头降低该条件的 ✗ 率**，与 465-3 目标一致、非冲突。
