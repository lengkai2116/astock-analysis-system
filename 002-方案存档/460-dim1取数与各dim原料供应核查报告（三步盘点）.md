---
title: dim1 取数分发与各 dim 原料供应核查报告（三步盘点）
type: 核查记录（444 号 ②/③ 前置的取数一致性盘点）
date: 2026-09-17
version: v1.0
status: 📋 盘点完成待拍板阶段（三步核查已完成，实施计划已建，待用户按阶段拍板推进）
related:
  - 444-SIG股票现状描述的事实层构建与显现——本号是其取数一致性前置：444 ②SSOT 表 / ③事实生产核查的"取数分发一致性"专项盘点
  - 444-附件1-SSOT字段素材清单——被本号核查复核，部分结论修正
  - 445-dim2-dim7引擎正确性知识库核查——引擎判定逻辑冻结，本号只查"事实/原料取数"不碰判定
  - 443-dim3量价计算链路简化与RAW预计算未消费核查
  - 458/459 号——「只修读取/对齐、不碰判定阈值」先例
---

# 460 — dim1 取数分发与各 dim 原料供应核查报告

> **定位**：用户推进 444 号前提出的三步核查方法论落地产物。核查范围 = **前端"原料数据"的取数是否统一（经 dim1）、是否正确、是否跨 dim 一致**。**不触碰** 445 冻结的引擎判定逻辑/阈值/输出契约——本号只查"事实/输入"层，与 445 引擎基准解耦。
>
> **核查方式**：3 个只读核查代理并行（①dim 来源是否经 dim1；②跨 dim 同源口径；③前端原料供应其他问题），证据全部为代码实读（文件:行号）。

---

## 〇、关键边界（用户 2026-09-17 明确，勿再误读）

> **445「引擎基准冻结」只冻结"分析输出定结论"的判定逻辑**（前提是分析逻辑无错误，有明确错误可修正）。**444 梳理的是股票的现状=事实（因），不是分析结论（果）**。若分析引擎的**前端数据获取错误、不统一，那就是要改的**——不是"统一分析结论"，而是修复事实。
>
> 修"事实/输入" ≠ 改"判定逻辑"：如 derived.risk_level 恒 LOW 是 main_force_phase 未接线的**假值**，修它不影响"risk 高低该怎么判"的规则。错误输入**该改就改**，不因"引擎冻结"或"有消费方"而搁置。

---

## 一、三步核查框架

用户 2026-09-17 提出，本号按此全面梳理（**统一完成问题梳理后再分阶段开展后续**）：

1. **第一步**：dim2-dim7 是否均通过 **dim1 统一取数和供给**（排除绕过 dim1 直接查库）。
2. **第二步**：是否存在 **dim 原料取数错误**，或 **两个不同 dim 使用同一数据但存在差异**（如均线 dim2 用 A、dim4 用 B 的假设）。
3. **第三步**：前端原料供应是否还存在**其他类型的问题**（缺键/扁平化覆盖/陈旧/单位/静默吞等）。

---

## 二、取数链路全貌（核查基线）

```
dim1 门禁层（dim1_signal_engine.py evaluate）
  ├─ 类别1 ECM 表（实时查）：daily_df / moneyflow_df / daily_basic_df / margin_df /
  │                          fina_df / income_df / balancesheet_df / cashflow_df /
  │                          stk_holder_df / lhb_df
  │                        + 457：weekly_df / hourly_df（多周期）
  ├─ 类别2 indicator 预计算表（宽表拆列）：indicator_ma_df / indicator_macd_df / indicator_other_df
  ├─ 类别3 pre_feat_cache ext 组（9）：chip_fund_ext / cost_ext / volume_ext / risk_ext /
  │                          fund_5d_ext / emotion_ext / structure_ext / market_stats / valuation_ext
  ├─ 类别4 板块热度：sector_heat
  └─ 类别5 相对强弱/RPS：relative_strength（rps_20d/60d）
        ↓ data_context 注入
status_engine Step2（:233-270）→ dim2-dim7 evaluate(ts_code, tags, data_context=...)
```

**扁平化规则**（status_engine.py:135 `_flatten_pre_feat`）：按组插入序平铺、**同名键后者覆盖前者**、None 值丢弃——这是多数"覆盖/丢失"结论的根因。组序：valuation(1)→sentiment(2)→sector(3)→style(4)→timing(5)→…→derived(11)→risk_ext(12)→chip_fund_ext(13)→…→structure_ext(16)→…→market_stats(19)。

---

## 三、第一步核查结果——dim1 统一供给

所有 dim2-dim7 均从 `data_context` 取主数据，dim1 统一装配，注入键均实际消费（无只传不用）。系统主体已走 dim1。

**但有 3 处硬偏差**（即便 data_context 齐全也绕过 dim1，属架构偏差）：

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 偏差1 | dim7 `_fina_health`（:560） | **恒直查五表**（fina_indicator/finance_report/income/balancesheet/cashflow），完全不走 data_context | 绕过 dim1 字段一致性/日期归一保障 |
| 偏差2 | dim4 `CrowdingFactor.get_margin`（:5313） | **恒直查 margin_cache**，不读 data_context | 同上；margin 滞后 ≤7 天风险未归一 |
| 偏差3 | dim5 `BociasiQuadrantAnalyzer`（bociasi_quadrant.py:242-409） | market_stats 缺键时**裸 SQL 回退**，直连 sharding_manager | 绕过 dim1，存在分库写路由/缓存不一致风险 |

**约 8 处"缺键兜底直查"**（低偏差，411 号 Phase6 设计为"优先 data_context、回退独立查询"）：
- dim2:76 `get_cached_daily`（daily_df 缺失兜底）
- dim3:148 `get_relative_strength`（RPS 兜底）
- dim4:530/843/984/1109 `get_cached_moneyflow`（4 处阶段判定兜底）
- dim5:410/418/431 快慢线/融资兜底；:468 `get_stock_industry`
- dim6:405 `_assess_piers_leverage` `get_cached_fina_indicator`
- dim7:717-745 四表兜底；:170 `_adjust_composite` 兜底

> **结论**：统一供给主体达成；**3 处硬偏差需接回 dim1**，兜底直查保持兼容。

---

## 四、第二步核查结果——跨 dim 同源口径差异

逐概念比对。**重点打架项 3 个** + 轻微口径差异 3 个 + 一致项 7 个。

### ❌ 重点打架项

| 概念 | 各 dim 取数 | 判定/根因 |
|---|---|---|
| **RSI** | dim2=`rsi_percentile`（**市场级** `market_stats`，:2884，当个股级展示）；dim3=`rsi14`（**恒 50 断链**——pre_feat 无此键，:126）；dim4=`indicator_other.rsi14`（dim1 宽表，**真值**） | ❌ **三套键**，dim3 断链恒 50、dim2 概念错位 |
| **fina_health 财务健康** | dim6=`tags.fina_health`（valuation 组 `ve.compute_tags` 产）；dim7=`_fina_health`（fina_indicator_cache **独立实时重算**，未消费 tags） | ❌ **生产点不同**，可能打架 |
| **volatility_level 波动率** | derived(量比代理 :3337) → risk_ext 后写覆盖(`_calc_volatility(df,{})` 传空 tags → **恒 medium**) → dim6 恒 medium | ❌ **量比代理成死代码**，dim6 波动率判定失真 |

### ⚠️ 轻微口径差异

| 概念 | 差异 | 判定 |
|---|---|---|
| **MA 均线** | dim2/dim3=`tags.ma_alignment`（pre_feat raw 均值 ma5>10>20>60）；dim4=`indicator_ma_df`（dim1 宽表）。判据一致但**生产点不同** | ⚠️ users 举例"dim2 A / dim4 B"属实 |
| **chip_concentration** | dim2/dim3=枚举（chip 组 concentrating/dispersing/stable）；dim4=`chip_fund_ext.concentration`（数值分，445 注明 concentration_status「从未生产」） | ⚠️ 口径不同 |
| **情绪温度** | dim5 实时重算 `calc_emotion_temperature`（:513）vs pre_feat 预写 `emotion_ext.emotion_temperature`，**双副本**（代码源同一，输入一致则值一致） | ⚠️ 双副本，应 SSOT |

### ✅ 一致项

profit_ratio（chip_fund_ext 覆盖 derived，三处同源）/ 支撑阻力（`shared_support_resistance` 唯一源，dim6 消费 structure_ext 后写/dim2 直调同函数）/ sentiment_phase（六段枚举同源）/ sector_heat（442 后 rank/strength 统一）/ RPS（仅 dim3 用）/ volume_ratio（459 真值单一）/ 流通市值·成交额（dim6 万元 circ_mv、dim7 万元 total_mv 单位统一，口径不同但单位一致）。

---

## 五、第三步核查结果——前端原料供应其他问题

按影响排序：

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| P1 | **depth 组 8 键整组死键** | `_raw2_one`:3309-3319 白名单 8 键全 None，扁平化整组丢弃；main_force_phase/fund_flow/capital_nature/hold_float_ratio/turnover_rate/main_force_presence 无生产者 | dim4/dim6/status_engine 多处读空走兜底且值域二次错位 |
| P2 | **volatility_level/trend 系恒兜底** | risk_ext 恒 medium；state_label 恒 unknown；trend_alignment 恒 misaligned | dim6 波动率判定失真（与 §四打架项同根） |
| P3 | **pe_percentile/rsi_percentile 市场级顶掉个股级** | market_stats:2936/:2884 后写覆盖，dim2:256 当个股级展示 | 个股估值分位/RSI 分位事实被市场级污染 |
| P4 | **size_factor 万元未×1e4 致阈值差 10 倍** | `_raw2_one`:3230-3236 `circ>5e10`(万=5000亿) vs `_compute_style_exposure`:4391 `_mv*1e4>5e10`(500亿) | 同股 size_factor 与 style_exposure 口径矛盾 |
| P5 | **volume_ratio 跨表日期可能错位 + 对齐检查漏 margin** | 459 读 daily_basic.latest；dim1 `_validate`(:309-313) 只查 daily_basic/moneyflow 未查 margin；margin ≤7 天滞后(:1968-1990) | 量比与当日量可能错日；融资成分日期陈旧 |
| P6 | **内层 except:pass 静默吞** | style(:3240)/risk_ext(:3375)/chip_fund(:3414,3423)/fund_5d(:3456)/valuation(:3478,3484)/cost(:3499) | 字段落 None/默认，无日志暴露 |
| P7 | **支撑阻力两套实现** | risk_ext calc_geometric vs structure_ext calc_support_resistance，structure 后写覆盖；dim6 消费被覆盖版 | 多口径，与 §四 ✅ 项冲突的潜在变体 |
| P8 | **大量算而不出字段** | volume_ext.vol_ma5/roc_20、style、bociasi_signal、volume_price.gap_type/breakout_attempts、net_lg_5d_consecutive、sector_momentum/is_sector_leader、catalyst_impact 等无消费 | 无用预计算、daemon CPU 浪费 |

**预计算持久化缺键**（白名单空、算而未落库，仍存在，444 附件1 已记录）：valuation `pe/pb/ps_percentile`&`roe`（-5y 键不产/roce_pass）、timing `cycle_position/turnover_signal`、chanlun `trend_direction/zhongshu_count/bi_count/duan_count`、chip `asr/cyqkl`、depth 整组——**5 处白名单空键**。

---

## 六、分阶段实施计划

> 阶段划分遵循用户方法论：**先统一（确立 SSOT → 迁移消费方 → 再废弃），删除是统一完成后的收尾动作**；事实/取数错误**该改就改**，不触引擎判定；每阶段改动走 StatusEngine 真实全链路验证（sig_full_test.py）+ 相关测试回归。

### 阶段 0：取数硬错位统一（P0，直接消除矛盾/失真；独立号逐个）

| 子项 | 内容 | 处置号建议 |
|---|---|---|
| 0-1 | **RSI 三键统一**：确立 chip_fund_ext.rsi14 为 SSOT（或统一键名），dim2 停止用市场级 `rsi_percentile`、dim3 改读真值、dim4 indicator_other 收敛 | 461 |
| 0-2 | **fina_health 双生产统一**：dim7 `_fina_health` 接 tags.fina_health（ve 产）为 SSOT，消除与 dim6 打架 | 附 461 |
| 0-3 | **volatility_level 三口径统一**：确立单一 ATR 档位 SSOT，消除 risk_ext 恒 medium/dim6 波动率失真 | 462 |
| 0-4 | **3 处绕过 dim1 硬偏差接回**：dim7 _fina_health、dim4 CrowdingFactor.get_margin、dim5 Bociasi 裸 SQL | 462 |
| 0-5 | **size_factor 万元单位**：×1e4 对齐 _compute_style_exposure | 461 |

### 阶段 1：伪字段/死键处置（P1，修复事实来源）

| 子项 | 内容 | 处置号建议 |
|---|---|---|
| 1-1 | **depth 组 8 死键**：分类处置（有真生产者→接线或归 JUD；控盘度/换手率→补生产） | 463 |
| 1-2 | **derived 伪字段统一**：price_position/state_label/trend_alignment/risk_level/support_resistance('{}')/profit_ratio 代理，接真实 SSOT（dim4 120日分位 / chanlun trend / dim6 判定） | 464 |
| 1-3 | **pe_percentile/rsi_percentile 市场级与个股级分离**（键名改名，个股分位勿被市场级覆盖） | 463 |
| 1-4 | **白名单 5 处空键清理**：valuation/timing/chanlun/chip/depth | 464 |
| 1-5 | **volume_ratio 跨表日期对齐 + dim1 校验补 margin** | 465 |

### 阶段 2：质量与清理（P2，收尾）

| 子项 | 内容 | 处置号建议 |
|---|---|---|
| 2-1 | **支撑阻力单实现**：calc_geometric vs calc_support_resistance 择一 | 466 |
| 2-2 | **内层 except:pass 消除**：对齐 441/442 教训，补日志防静默吞 | 466 |
| 2-3 | **算而不出字段清理**：删除无消费者预计算组/字段（vol_ma/roc_20/style/bociasi_signal/gap_type 等）省 daemon CPU | 467 |

### 阶段 3：交付 444

- 取数一致性修复完成后，回到 444 号第②步 SSOT 逐项拍板 + ③事实生产核查落地，最终回 437-A。

> **各阶段独立开号**（461-467 建议，遵循 443-459 先例：一号一文档一验证），每号实施前由用户确认范围，完成后 sig_full_test OK/FAIL + 相关测试回归 + 更新本文档实施记录。

---

## 六·补、实施落地状态（2026-09-18）

> 用户 2026-09-17 拍板：**461 号合并实施**（一号多子项、统一记录跟进、子项独立实施验证记录于同一文档）。阶段0-2 全部 13 子项已由 **461 号**实施完成，2026-09-18 批量 `sig_full_test.py` 全链路 **OK 40 / WARN 0 / FAIL 0**。处置号对应：0-1→461-1、0-2→461-2、0-5→461-3、0-3→461-4、0-4→461-5、1-1→461-6、1-2→461-7、1-3→461-8、1-4→461-9、1-5→461-10、2-1→461-11、2-2→461-12、2-3→461-13。阶段3 交付 444 已于同日启动（见 444 文档工作进度记录）。
> 实施要点与逐项验证见 `461-dim1取数一致性合并实施号（多子项统一）.md`。461 交付后剩余 3 项挂账（active_signal/right_side_confirm/相对强弱接线）已由 **462 号**于同日落地（见 `462-444事实层剩余收尾（active_signal与right_side_confirm统一+相对强弱接线）.md`，sig_full_test OK 40/0/0）。遗留挂账（归 445/444，非本号）：FCF 折旧列补采（449/445 登记）；另 RAW-2 估值组恒空（子线程 app_context 缺失，既有生产状态，见 462 附）可另开号。

---

## 七、待拍板决策项（供用户按阶段推进）

1. **阶段 0 是否先行**（RSI/fina_health/volatility/size_factor/绕过 dim1——直接消除矛盾的 5 项）？
2. **独立号编号**：按 461-467 逐个开，还是一号合并多子项？
3. **处置顺序**：是否严格按 阶段0→1→2→3，还是可并行/调整？
4. 其余详见 444 号既有决策项（§六 D1-D7 与 437-A D1-D7）。

## 工作进度记录（2026-09-17）

- [x] 用户明确三步核查方法论（统一梳理→分阶段，不逐项零改）
- [x] 第一步：3 只读代理并行核查，产出「dim 来源是否经 dim1」（3 硬偏差 + ~8 兜底直查）
- [x] 第二步：跨 dim 同源口径差异（3 打架 + 3 轻微 + 7 一致）
- [x] 第三步：前端原料供应其他问题（P1-P8 + 白名单空键 5 处）
- [x] 整合三步结论 + 建立分阶段实施计划（0-3 阶段 + 461-467 号建议）
- [x] 本盘点文档落稿（v1.0，待拍板）
- [x] **用户按阶段拍板 → 开处置号**（2026-09-17 拍板：461 号合并实施，一号多子项统一记录、子项独立实施验证记录同文档）
- [x] **阶段0-2 全部 13 子项实施完成**（461-1~13，2026-09-17~18，见 461 文档逐项记录）——批量 `sig_full_test.py` 全链路 **OK 40 / WARN 0 / FAIL 0**（2026-09-18）
- [x] **阶段3 交付 444**（2026-09-18）——444 文档工作进度记录已补记 461 交付覆盖项与剩余挂账
- [ ] 441/442/443 关联项并入相应阶段：stk_holder 补采（441 ✅）、RPS 弱信号（446 D12 ✅）、**FCF 折旧列补采（449/445 登记，未落地）**——仍挂账，待另号补采后落地
