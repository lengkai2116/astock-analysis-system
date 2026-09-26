---
title: SIG 运行问题 P2 处置（结构段内矛盾 + 估值展示语义 + FCF 展示口径）
type: 实施号（SIG 运行实证处置；P2-1 核查后定夺 / P2-2 展示层修正 / P2-3 展示口径对齐）
date: 2026-09-26
version: v1.0
status: 🔄 已开号（根因全部实证定位）
related:
  - 485-SIG全环节运行核查（P2 三项登记来源）
  - 486-SIG运行问题P1修复（本号承接 P2，同一运行批次）
  - 446-dim2趋势判定修正（价格vs中枢主判据——P2-1 涉及主链 vs multi_level 两实例分叉）
  - 457-dim2多周期级联（P2-1 多级别方向 text 来源）
  - 449-dim7估值陷阱（PEG/ROCE 惩罚——P2-2 判定来源）
  - 476-dim7分位接线（SIG 分位 vs RAW composite 双源——P2-2 展示冲突来源）
---

# 487号｜SIG 运行问题 P2 处置

> **定位**：2026-09-26 SIG 8 股运行实证的 P2 三项。根因全部实证定位（勿重做）；本号按「核查 → 实施可做项 → 判定类登记」处置。

## 一、根因实证（2026-09-26）

### P2-1 000001 structure「缠论方向上升」vs「多级别日线下降」段内矛盾
- **实证**：同一 df，主链 `ChanlunAnalyzer({'bi_zs_mode': True})` → `current_trend=up`（价格突破中枢上沿）；`MultiLevelChanlunAnalyzer` 的 daily 分析器 → `current_trend=down`。
- **根因**：两个分析器各自实例化，`_determine_trend` 依赖 `_select_current_zhongshu`（有效中枢选择）——**两实例笔中枢识别/有效中枢选择结果不同**（主链用 `ChanlunAnalyzer({'bi_zs_mode': True})`，multi_level 内 daily 用 `dataclasses.replace(config, multi_level.bi_zs_mode=True)`——配置等价但实例独立，中枢序列可能有差异）。`multi_level_direction_text`（dim8「多级别：…」句）与主链「缠论方向」**同一数据两个口径**。
- **性质**：真矛盾（同段内方向打架）→ 待核查后统一口径（见 §二决策）。

### P2-2 600276 恒瑞「极度高估」vs PE3.8%/PB0.6% 分位极低
- **实证**：composite_rating=-1.0833；四锚明细 asset=**+2.0**（PB 0.6% 分位=低估方向）、earnings=-0.3、cashflow=**-1.0**（FCF 0.11%）、adjusted=0.0；惩罚 ROCE<15% -0.3 + PEG>2 -0.5 + fina_health fail 可能 -0.5。成长类权重 (0.1,0.25,0.2,0.35,0.1)。
- **根因**：**判定逻辑正确执行**（四锚加权 + 449 惩罚链是设计），但 **展示语义冲突**——「极度高估」由现金流锚+PEG/ROCE 惩罚主导，而 PE/PB 历史分位（低估特征）来自 SIG 分位表（476 接线），**判定与分位展示两侧来源不同**，读者看到「PB 0.6% 分位（极度低估特征）+ 极度高估结论」自相矛盾。dim8 展示分位（PE3.8%/PB0.6%）来自 dim7 分位表，composite 来自 RAW。
- **性质**：判定非 bug（445 冻结：改判定=改「果」需 JUD 阶段）；**展示层语义冲突需修正**（§二）。

### P2-3 FCF 收益率「无数据」（601318/600036）
- **实证**：601318（保险）free_cashflow=None、depr=nan；600036（银行）free_cashflow=None、但 cashflow_oper=3046亿、depr=58.7亿 有值；600519 三列齐全。
- **根因**：`compute_tags` 展示段 fcf_yield（valuation_estimator.py:916-922）**只读 `free_cashflow` 列**，未复用 `_anchor_cashflow`（:501）的「cashflow_oper−depr 优先 + 金融排除」口径——银行/保险 free_cashflow 天然缺失（金融类不产标准 FCF）→ 展示「无数据」，而四锚判定用金融=0（不适用）。**展示与判定口径不一致**。
- **性质**：展示层口径缺陷，可实施（§二）。

## 二、处置决策

| 子项 | 内容 | 性质 | 处置 |
|---|---|---|---|
| 487-1 | P2-1 结构段内方向统一 | 主链 vs multi_level daily 分叉 | ✅ **已实施**：根因=multi_level daily 用 ChanlunConfig 对象（min_klines=4）vs 主链字典（min_klines=6 默认）→ 笔/中枢识别分叉（000001 实证 5 vs 10 中枢、方向相反）。修复=multi_level daily 改用与主链同构字典 `{'bi_zs_mode': True}`（chanlun_multi_level.py）。8 股主链 vs multi_level 方向**全部一致** |
| 487-2 | P2-2 估值展示语义 | 判定正确、展示冲突 | **登记关闭**（不改代码）：composite=-1.0833 由四锚（现金流锚-1.0）+ 449 惩罚（ROCE-0.3/PEG-0.5/fina fail-0.5）主导，判定正确执行；dim8 已有陷阱句（「资本回报率低于15%，存在价值陷阱风险；市盈增长比>2，存在成长陷阱风险」）提供归因，读者可理解 PB 低分位 vs 高估结论并存。改判定=改「果」445 冻结 → 如需调整四锚权重/惩罚，登记 JUD 阶段（485-7 dim1-8 接线同批） |
| 487-3 | P2-3 FCF 展示口径 | 展示未对齐四锚 | ✅ **已实施**：VE.compute_tags + dim7 _compute_valuation 双侧 fcf_yield 复用 `_anchor_cashflow` 口径——金融类（601318/600036）→ None（dim8 降级跳过，不再"无数据"）；非金融优先 `cashflow_oper−depr`（449 口径）兜底 free_cashflow（600519 0.11%→4.51% 口径修正，与判定锚一致） |

## 三、实施记录

| 子项 | 状态 | 验证 |
|---|---|---|
| 487-1 多级别 daily 配置对齐 | ✅ 已实施 | 8 股主链 vs multi_level 方向全部一致（000001 up/up）；test_457 适配新实现（daily 字典+weekly ChanlunConfig 双断言） |
| 487-2 估值展示语义 | ✅ 登记关闭 | 判定正确（四锚+449 惩罚），陷阱句已归因；改判定归 JUD（485-7 同批） |
| 487-3 FCF 展示口径 | ✅ 已实施 | VE+dim7 双侧同口径；金融类 None 降级、非金融 oper−depr 真实值；回归 61 passed |
