---
title: 量价形态"体系A"收敛（均线语义移出量价维 + 均线数值改读 indicator_ma 预计算）
type: 架构评估落地方案（A: 均线改读indicator_ma + B: 均线形态移出pattern_signal）
date: 2026-09-20
version: v1.0
status: ✅ 已实施（A 均线改读 indicator_ma + B 均线形态移出 pattern_signal·消费点过滤）
related:
  - 445-dim2-dim7引擎正确性知识库核查 —— 冻结边界（判定逻辑冻结，本号仅改字段口径/形态归类=事实层）
  - 460-dim1取数与各dim原料供应核查报告 —— 统一供给原则（dim2-7数据经dim1注入data_context，各维不独立查库）
  - 412号方案C3 v3.0 —— MA优先从indicator_ma预计算表读取（dim1通过data_context提供）
  - 461-dim11 —— calc_support_resistance 改造先例（indicator_ma_df 预计算优先+raw fallback）
  - 462-444事实层剩余收尾 —— 事实层该改就改、不改引擎判定
  - 316号P5 —— pattern_signal 映射到 VOTE_MAP（本号 B 采用消费点过滤，VOTE_MAP 保留键以满足 316 守卫）
  - 444-SIG现状描述事实层 —— 现状=因；形态归类对 dim8 归集的影响
---

# 467 — 量价形态"体系A"收敛：均线语义移出量价维 + 均线数值改读 indicator_ma

> **定位**：2026-09-20 用户在"两套量价形态体系评估"（A=EnhancedPatternDetector 综合检测器；B=PatternEngine/PatternRegistry wiki权威）后拍板：
> - **A（均线改读indicator_ma）**：让量价引擎的均线判定改读 `indicator_ma` 预计算表（412/460 已确立的统一供给），不再 `np.mean(closes[-N:])` 现算，消除重复计算与口径偏差。
> - **B（均线形态移出 pattern_signal）**：体系A 里 wiki 归入【均线系统/格兰威尔均线八法则】概念的形态，从 `pattern_signal`（量价形态票源）移出，消除与 `ma_alignment` 独立票源的双重计票，还"量价形态"以 wiki 本义。
>
> **冻结边界**（445-freeze-vs-fact-layer）：本号只改**字段口径与形态归类**（事实层/投票映射），**不触碰任何引擎判定逻辑**——量价健康评分（体系B）、格兰威尔八准则 `_classify_granville` 判定均不动。均线形态的"判定函数"（`_is_ma_*`/`_is_granville_*`）**保留不删**（仍可能被其他消费方独立调用），仅从 `detect_all` 的 checks 列表与 `VOTE_MAP['pattern_signal']` 中移除产出。

---

## 一、背景与评估结论（本号依据）

### 1.1 两套体系分工（已核实）
| 体系 | 输出 | 消费方 | wiki 对应 |
|---|---|---|---|
| **A** `EnhancedPatternDetector.detect_all` (volume_price_strategy.py:477-575) | `pattern_signal` 中文形态标签 | cross_validate VOTE_MAP、status_engine(平台突破/量价强势)、strategy_analyze、resonance_service | 技术形态大全（含均线/波段概念，超出量价） |
| **B** `PatternEngine`/`PatternRegistry`（app/engine/patterns/） | `pattern_score` 10分制进 dim3 health_score | dim3 量价健康评分 + audit | wiki《量价形态打分系统》严格对齐 |

**两套是不同抽象层级，不能删 A**（A 的 `pattern_signal` 供 L4 共识投票 + 平台突破/量价强势判定），需要的是**收敛语义、清理混入**。

### 1.2 均线"数据层"现状（已核查，全部就位）
| 层 | 现状 | 证据 |
|---|---|---|
| 数值 MA5/10/20/30/60/120/250 | ✅ 已在 **RAW 预计算表 `indicator_ma`** | enhanced_cache_manager.py:105,572-575（含 ma120/ma250）；get_indicators_wide:1376-1395 |
| dim1 注入 data_context | ✅ 已注入 `indicator_ma_df` | dim1_signal_engine.py:180-183（ma_cols=startswith('ma')/('vol_ma')） |
| 排列 `ma_alignment` | ✅ 独立标签+独立票源 | data_daemon.py:3880-3886；cross_validate VOTE_MAP['ma_alignment'] |

**结论：均线不需要"新造存放处"——数值在 RAW、排列在标签，全链路已就位。真正的缺陷是体系A 的均线形态判定仍绕开预计算自己 `np.mean` 现算，且以 `pattern_signal` 身份参与 L4 投票与 ma_alignment 双计票。**

### 1.3 体系A 中依赖收盘价 MA 的形态（探针全量梳理，20 条）
> 依赖收盘价均线 `ma5/10/20/30/60/120/250` 的规则 = wiki 归入【均线系统/格兰威尔均线八法则】部分，需移出量价维。**成交量均线 `vol_ma*` 是量能对比，不属格兰威尔，保留。**

| 批次 | 方法 | 中文标签 | 用 MA |
|---|---|---|---|
| 批1 | `_is_fangliang_zhan60` | 放量站上60日线(预涨) | ma60 | ⚠️ 最易遗漏（批1但依赖MA）
| 批2 | `_is_ma5_jinchai_ma10` | MA5金叉MA10(预涨) | ma5,ma10 |
| 批2 | `_is_ma5_sicha_ma10` | MA5死叉MA10(预跌) | ma5,ma10 |
| 批2 | `_is_ma_tuo_pailie` | 均线多头排列(预涨) | ma5,ma10,ma20,ma60 |
| 批2 | `_is_ma_ya_pailie` | 均线空头排列(预跌) | ma5,ma10,ma20,ma60 |
| 批2 | `_is_closes_above_ma60` | 连续站上60日线(预涨) | ma60 |
| 批2 | `_is_ma5_tol_ma20_up` | MA5上穿MA20(预涨) | ma5,ma20 |
| 批2 | `_is_ma60_zhichi` | 回踩MA60获支撑(预涨) | ma60 |
| 批2 | `_is_ma5_jiaotou_ma60` | MA5上穿MA60(预涨) | ma5,ma60 |
| Batch-C | `_is_ma_tuo_pailie_ma30` | 三线开花多头(预涨) | ma5,ma10,ma30,ma60 |
| Batch-C | `_is_ma_ya_pailie_ma30` | 三线开花空头(预跌) | ma5,ma10,ma30,ma60 |
| Batch-C | `_is_ma30_above_ma60` | MA30>MA60(预涨) | ma30,ma60 |
| Batch-C | `_is_price_above_ma120` | 站上MA120(预涨) | ma120 |
| Batch-C | `_is_price_above_ma250` | 站上MA250(预涨) | ma250 |
| P1-#12 | `_is_granville_buy1..4` | 格兰维尔买点1-突破买(预涨)…4-新低买(预涨) | ma10/ma20 |
| P1-#12 | `_is_granville_sell1..4` | 格兰维尔卖点1-跌破卖(预跌)…4-新高卖(预跌) | ma10/ma20 |

**关键澄清（第6节已核实）**：`vol_ma*`（`_get_prev_vol_ma(5/10/20)`）是**成交量**均线，用于量能对比（放量/缩量），wiki 概念上**不归格兰威尔均线八法则**，**不在移出范围**。真正移出的是对 **closes 收盘价**求均的 20 条。

### 1.4 均线"预跌"信号移出后的否决强度影响（B 的关键权衡）
detect_all 里带"预跌"后缀的 label 共21条，其中**均线类预跌4条**：`MA5死叉MA10(预跌)`、`均线空头排列(预跌)`、`三线开花空头(预跌)`、`格兰维尔卖点1-4`。移出后 pattern_signal 的预跌否决强度下降，**但**：这些信号在 `cross_validate VOTE_MAP['ma_alignment']`（bearish=-1）已独立供给——**B 正是消除同只股票 ma_alignment + pattern_signal 均线形态的双计票**，否决语义由 ma_alignment 单源承接，不丢失。

---

## 二、改动方案

### 2.1 A：`_add_vp_simple_tags` 均线改读 indicator_ma 预计算
**现状**：`data_daemon.py:3880-3886` `_add_vp_simple_tags(df, tags)` 用 `np.mean(closes[-5:])`…现算 ma5/10/20/60 判 `ma_alignment`。
**改为**：扩签名 `_add_vp_simple_tags(df, tags, indicator_ma=None)`，当传入 `indicator_ma`（`_ecm.get_indicators_wide(code)` 的 ma 列）且含所需周期时，从预计算表读取 ma5/10/20/60；缺失/为空回退 `np.mean`（对齐 412/461 的"预计算优先+raw fallback"）。
- **调用方**：`_raw2_one` 量价段（data_daemon.py:3380-3383）在调用 `_add_vp_simple_tags` 前取一次 `_ecm.get_indicators_wide(code)`，传入。
- **复权口径（§三 风险已实证排除）**：indicator_ma 与 RAW-2 前复权 df 口径——探针 `ma_alignment` 验证二者一致（未复权 vs 前复权），A 安全落线。

### 2.2 B：均线形态移出 pattern_signal 产出 ——【消费点过滤】

> **方案定稿（v1.0）**：经 445 冻结边界核查（见 §六），**不采用** §v0.1 拟议的"从 `detect_all` 删 20 条均线规则 + 从 VOTE_MAP 删均线键"，改为**消费点过滤**：

1. **detect_all 规则保持原样**（volume_price_strategy.py:477-575）：20 条均线规则与方法定义全部保留、不删——因 `framework/VolumeStateAnalyzer.analyze`（L2747）也调 detect_all，用返回的"预涨/预跌"形态算 `resonance_score`（L2848-2888，含 ≥2/≥3 共振加分）→ dim3 判定强度（dim_adapter.py:593）+ L3360 BUY/SELL 方向门控。这些均线规则的"预涨/预跌"后缀对共振分是实质贡献，删规则 = 改 framework 判定逻辑，**违反 445 冻结边界**。
2. **VOTE_MAP['pattern_signal'] 保留均线键**（cross_validate.py:239-287）：316 守卫 `test_fix_315_316::test_pattern_signal_mapping_covers_detector` 要求 **detect_all 全部方向性形态 ⊆ VOTE_MAP**，detect_all 仍产出均线形态 → 键必须保留，否则守卫失败。
3. **真正的"移出"落在消费点**：`data_daemon._add_vp_simple_tags` 产出 `pattern_signal` 前，用 `_MA_PATTERN_NAMES` 集合（含 §1.3 全部 20 条均线形态名）**剔除均线类形态**，再按预跌优先取 `pattern_signal`。这样：
   - `pattern_signal` 票源不再含均线形态 → 与 `ma_alignment` 票源不再双计票（达成 B 的语义收敛）；
   - detect_all → framework 共振路径完全不受影响（445 冻结守住）;
   - VOTE_MAP 均线键永不因消费点过滤命中（消费点已剔除），但保留以满足守卫。
4. **`_MA_PATTERN_NAMES` 落点**：定义在 data_daemon.py `_add_vp_simple_tags` 前，`frozenset` 常量。

### 2.3 消费方影响核查（消费点过滤后）
- 均线形态不再以 `pattern_signal` 身份参与 L4 共识投票（cross_validate VOTE_MAP 消费点已剔除）——由 `ma_alignment` 独立票源承接，语义不丢。
- `pattern_signal` → `kline_pattern`（`_detect_kline_patterns` P2 链路）与 framework 共振、`status_engine` 平台突破/量价强势、`strategy_analyze`/`resonance_service` 均不受影响：消费点过滤仅作用于 `_add_vp_simple_tags` 的 `pattern_signal` 输出，framework 的 `VolumeStateAnalyzer.analyze` 仍拿到 detect_all 完整（含均线）形态。

---

## 三、风险与对冲
| 风险 | 对冲 |
|---|---|
| **复权口径**：indicator_ma 与 RAW-2 前复权 df 口径不一致风险 | **已实证排除**：探针 `ma_alignment` 一致性验证——indicator_ma（未复权）与 qfq（前复权）计算的 ma_alignment 一致，A 安全落线 |
| **B 移除导致 pattern_signal 信息量下降** | 均线"预跌"否决由 `ma_alignment`（bearish=-1）票源承接（单源化消除双计票）；纯量价/K线形态不受影响 |
| **445 冻结边界（删 detect_all 规则会改 framework 共振判定）** | **方案改为消费点过滤**（§2.2）：detect_all 规则/VOTE_MAP 键保留，仅在 `_add_vp_simple_tags` 消费点剔除均线形态 |
| **test_fix_315_316 覆盖断言** | VOTE_MAP 保留均线键 → 守卫天然通过（detect_all 仍产出均线形态 ⊇ 映射），不更新该测试 |
| **其他消费方依赖 detect_all 返回均线标签** | grep 排查确认 VolumeStateAnalyzer 复用 detect_all → 即 445 冻结根因，消费点过滤已规避 |

---

## 四、实施清单
- [x] A：`_add_vp_simple_tags` 扩 signature `indicator_ma=None` + `_read_ma(period)` 预计算优先/raw fallback
- [x] A：`_raw2_one` 量价段调用 `_ecm.get_indicators_wide(code)` 传 `indicator_ma=_ind_ma`
- [x] B：data_daemon 新增 `_MA_PATTERN_NAMES` 常量，`_add_vp_simple_tags` 消费点过滤均线形态再取 pattern_signal
- [x] B（冻结保障）：detect_all 规则保留（恢复 v0.1 越界改动）；VOTE_MAP 保留均线键
- [x] 测试：新增 `tests/test_467_mover_line_out_of_pattern.py`（B1 消费点过滤生效/仅均线→none、B2 detect_all+VOTE_MAP 保留+316守卫延续、A1 indicator_ma 优先+缺列/空表 fallback+上下行判定）；`test_kline_pattern_wiring::test_simple_pattern_signal_still_computed` 断言更新为 `indicator_ma=`；删除冗余 test 方法
- [x] grep 排查 `detect_all` 其他调用方（确认 VolumeStateAnalyzer 复用 → 445 冻结结论 → 消费点过滤方案）
- [x] 跑相关测试基线：145（量价/dim3/共振/cross_validate）+ 66（indicator/dim2/446）+ 23（t61/461-deadkey/t10/t66）= **234 passed 全绿**

---

## 五、验证计划
- 单测（已跑通 234 passed）：A——indicator_ma 传入优先 / 缺列回退 / 空表回退 / 上下行判定；B——消费点过滤生效 / 仅均线→none / detect_all+VOTE_MAP 保留 / 316守卫延续
- 回归（已跑通）：test_467、test_kline_pattern_wiring、test_fix_315_316、test_dim3_patterns、test_450/455_dim3_granville、test_446_dim3/dim2、test_462、test_418、test_390、test_411、test_t61/66、test_t10、test_461_dim13/dim8、test_442_vs_indicator、test_466
- 全链路：`sig_full_test` 待有 SIG 真实全量环境时执行（涉及 pattern_signal 实际产出与 dim3 判定接线）
- ✅ **真实数据实测 + 全量重算（2026-09-20）**：见 §六下「kline_pattern 恒 none 根因诊断闭环」

> **§二 变更记录**：v0.1 曾拟议 delete-detect_all 方案（§2.2/§2.3 原表述），实施核查确认其违反 445 后由用户拍板改为**消费点过滤**（v1.0）。

---

## 六、kline_pattern 恒 none 根因诊断闭环（2026-09-20 实测）

**结论：恒 none 是"存量 pre_feat 未按修复代码重算"的假象，非真实 bug；688981 类纯均线股 `none` 是 467 消费点过滤的预期语义。**

### 证据链
1. **接线修复 commit `38db949`（"kline_pattern 接线缺陷——接 _add_vp_simple_tags 真值"）落地于 2026-09-20 11:00**；而 pre_feat_cache 存量行生成于 **2026-09-18 21:43**（`trade_date=2026-09-18`）。**修复代码在存量数据之后才进仓库** → 08-31~09-18 全部 pre_feat 的 `kline_pattern` 走的是修复前路径（`_simple` 为空 → 恒 `'none'`）。
2. **链路核查**（data_daemon）：`features['volume_price']['kline_pattern']` = `_simple.get('pattern_signal','none')`（L3404，`_add_vp_simple_tags` 填真值）→ `_vp_f=features.get('volume_price')`（L3556）→ `_derived['pattern_signal']`（L3589）与 `_rsc_tags['pattern_signal']`（L3581，供 right_side_confirm）同源。
3. **定向重跑 RAW-2**（`_precompute_raw_features` 8 只）后，7/8 产出真实形态，与探针 `detect_all` 预期逐只吻合：

| 代码 | kline_pattern（重跑后） | derived.pattern_signal | 说明 |
|---|---|---|---|
| 600519.SH | M顶 | M顶 | 存量 `none` → 真值 |
| 000001.SZ | 看涨吞没 | 看涨吞没 | ✅ |
| 300750.SZ | 看跌捉腰带 | 看跌捉腰带 | ✅ |
| 000002.SZ | 地量后倍量启动 | 地量后倍量启动 | ✅ |
| 601318.SH | 镊子底 | 镊子底 | ✅ |
| 600036.SH | 上升楔形 | 上升楔形 | ✅ |
| 002594.SZ | 头肩顶 | 头肩顶 | ✅ |
| 688981.SH | none | none | **467 消费点过滤预期**（其 detect_all 全形态均均线类被剔） |

4. **688981 语义归因**（非缺陷）：`detect_all` 返回全为均线形态（如 MA30>MA60、格兰维尔买点4）→ 被 `_MA_PATTERN_NAMES` 剔除 → `pattern_signal='none'`。这正是 467"均线形态移出 pattern_signal、改读 dim1 indicator_ma 链路"的设计意图；真实非均线形态（看涨吞没/镊子底/头肩顶等）均正常保留。

### 全量重算
- 定向 8 只已重写；**全量 pre_feat 已于 2026-09-20 14:47 调用 `_precompute_raw_features(全量 codes)` 重算完成：5550/5552 只成功、失败 0、耗时 820s、trade_date=2026-09-18**（股票池口径 `_get_active_codes()` 统一入口，剔指数），消除 09-18 存量"接线修复前"数据。
- 重算后抽样 8 只：7 只非 none（M顶/看涨吞没/看跌捉腰带/地量后倍量启动/镊子底/上升楔形/头肩顶）+ 688981 语义性 none（467 均线过滤预期），与定向验证逐只一致。
- 本次为纯数据回填 + 验证，无代码改动、无 commit。

---

## 七、445 冻结边界核查结论（本次实施的关键决策点）
`EnhancedPatternDetector.detect_all` **不只有 data_daemon 这一个消费方**：
- `framework/VolumeStateAnalyzer.analyze`（L2747）调用 detect_all，用返回的"预涨/预跌"形态算 `_calc_resonance_score`（L2848-2888，每形态 ±2 + ≥2/≥3 追加共振分）
- → `resonance_score` 进入 dim3 判定强度（dim_adapter.py:593 `0.7*sm_conf+0.3*resonance_norm`）+ L3360 `resonance_score>=3 and direction=="BUY"` 方向门控 + L3512 结论文案

**判定**：被移出的 20 条均线规则**全部带"预涨/预跌"后缀**，从 detect_all 删除会实质降低 resonance_score → 改变 framework"结论(果)的判定逻辑"，**正属 445 冻结范围，不能动**。因此 B 只能落到 `_add_vp_simple_tags` 消费点（§2.2）。`volume_price_fit` 走独立的 `compute_volume_price_signal`（volume_price_strategy.py:4126-4153，不经过 detect_all），已确认不受删/滤影响。
