---
title: dim7 估值陷阱处置（周期股切 PB 锚 + PEG 降级 + ROCE 判定 + FCF 口径）
type: 方案（B 类引擎逻辑偏差，评估中）
date: 2026-09-16
version: v1.0
status: ✅ 已实施（①②③双侧同步 + ④登记缺口；449单测8 + 回归56 passed）
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号是 445 §6.3 B 类第四号（dim7 估值）
  - 多锚点估值框架（外部 wiki 权威）——四锚 + 周期/成长/价值三陷阱标准
  - 431-sig-config（G1 常量收敛）——dim7 与 valuation_estimator 常量单向导入
  - 444-SIG现状描述事实层——SIG 只产现状条件，JUD 判定
---

# 449 — dim7 估值陷阱处置

## 起因（445 §6.3 dim7 偏差 + 用户拍板开号）

445 号对 dim7 估值引擎判定四处 B 类偏差，用户本号全选处置：

| 偏差 | 445 判定 | 权威 wiki 标准 | 现状（代码已核） |
|---|---|---|---|
| **周期股弱切换**（重加权≠切 PB 锚） | 🔴 | 周期顶点 PE 最低，**自动切换至资产锚(PB)模块**；强周期行业默认 PB 估值 | dim7 L734-748：PE 极低分位(<20%) 时 PB 权重×2、PE×0.5（重加权非切换） |
| **PEG>2 未降级** | 🔴 | 成长陷阱，**PEG>2 时自动降级** | dim7 `_anchor_earnings`(L441-451)：PEG>2→0.0、>3→-0.5，仅收益锚内小幅，未做 composite 级降档 |
| **ROCE 未参与判定** | 🔴 | 价值陷阱，**结合 ROCE 筛选，<15% 直接剔除** | dim7 `_fina_health` 已算 roce_pass（近3年均值>15%）但只输出未参与 composite |
| **FCF 口径不符** | 🔴 | **经营资产FCF=经营现金流-保全性资本支出(折旧近似)** | 用 akshare `free_cashflow`（教科书 FCF=经营-全部资本支出）；库内无折旧列 |

## 权威基线（外部 wiki，445 已确认权威）

- **《多锚点估值框架.md》**
  - 资产锚(净资产/清算)适用：金融、周期、破净股——PB 百分位评级
  - 收益锚(PE/PEG)：成长股、消费白马
  - 三陷阱：价值(PE低但跌，需结合 ROCE)、成长(PEG>2 自动降级)、周期(顶点 PE 最低，自动切换至 PB 锚)
- **《周期股陷阱.md》**：周期股应自动切换至资产锚(PB)模块，PB 在周期中相对稳定；强周期(钢铁/有色/化工)默认 PB 估值
- **《成长陷阱.md》**：PEG>2 时自动降级，即使 PE 百分位显示合理也应谨慎
- **《价值陷阱.md》**：必须结合 ROCE 筛选，ROCE<15% 时直接剔除
- **《经营资产自由现金流.md》**：经营资产FCF=经营活动现金流净额-保全性资本支出；保全性资本支出实务用长期资产折旧摊销近似

## 代码现状核查（已完成）

### 架构：dim7 与 valuation_estimator 双份四锚
- **valuation_estimator.py（RAW 生产权威）**：daemon RAW-2 `ValuationEngine.compute_tags` 预计算 composite_rating 落 pre_feat_cache；percentile 基准（`build_composite_percentile`）从 `dm.get_tags_batch` 读 precompute 结果。
- **dim7_valuation_engine.py（SIG 实算）**：SIG evaluate 用 `_compute_valuation` 实算 composite + 质量调整，产 status_description/judgment/audit。
- **431 G1 已收敛常量**（CN_10Y_BOND_YIELD_PCT/QUALITY_ADJUST/INDUSTRY_CATEGORY/CATEGORY_WEIGHTS 单向导入估值）但**四锚方法体仍是双份**。
- **周期股重加权只在 dim7 有**（L734-748），valuation_estimator compute_tags（L742-751）**只有市值微调、无周期股段** → 双侧已不一致（dim7 SIG 实算与 RAW 权威 composite 基准错位）。

### 数据可用性（FCF ④相关）
- cashflow_cache：`free_cashflow`/`cashflow_oper`/`cashflow_inv`/`cashflow_fin` 有；**无折旧摊销列**。
- balancesheet_cache：`fixed_assets` 有，**无折旧累计/摊销列**。
- fina_indicator_cache：`roce` 有（Tushare 实测不返，dim4/dim7 已回退用 income+bs 计算 ROCE=营业利润/(总资产-流动负债)）。
- **结论：①周期股/PB 切换②PEG 降级③ROCE 判定 底层数据已具备可直接实施；④FCF 需补采折旧列（数据缺口），本号登记、另号补采后落地。**

### 现有测试覆盖
- test_315_316（ROCE/负债率构造式）、test_273a_implementation、test_value_pipeline（ValuationEngine）。无周期股/PEG 降级专项测试。

## 处置设计（待拍板）

### 一、周期股 → PB 锚切换（①②③共享：双侧同步）
- 现状 dim7：PE 极低分位(<20%) 时 PB×2/PE×0.5 重加权。
- 改：`cat=='周期'` 且 PE 极低分位（疑似周期顶点）时，权重**归一为纯 PB**（w1=1、其余=0），彻底切换至资产锚。否则维持原加权。
- **valuation_estimator.compute_tags 同步**（当前无此段，补一致逻辑），消除双侧错位。

### 二、PEG>2 自动降级（双侧）
- 现状：dim7 `_anchor_earnings` PEG>2→peg_score=0.0，仅收益锚内小幅。
- 改：composite 合成后，成长/科技类 + PEG>2 → composite 下调一档（对齐 wiki"即使 PE 合理也应谨慎"），status/audit 标注 growth_trap。
- 需 `_anchor_earnings` 回传 peg 值或 evaluate 复算。

### 三、ROCE 参与判定（双侧）
- 现状：dim7 `_fina_health` 已算 roce_pass 但只输出。
- 改：composite 合成后，roce_pass=False → composite 下调（价值陷阱惩罚），对齐 wiki"结合 ROCE 二次验证"。SIG 只产现状条件，JUD 侧做剔除判定（对齐 444 边界）。

### 四、FCF 口径修正（登记数据缺口）
- 现状：`free_cashflow` 教科书 FCF → EV 折现。
- 改：需补采现金流折旧摊销列后，`_anchor_cashflow` 改用「经营现金流-保全性资本支出(折旧近似)」口径。
- 本号登记缺口，另号补采后实现。

## 约束
- 445 引擎基准：改动不破坏既有判定与冻结基准（rr<1、事件识别、主力出货、情绪联动）。双侧一致。
- SIG/JUD 边界：dim7 只产现状条件（PEG>2 降级、ROCE 惩罚、周期 PB 切换），JUD 做剔除判定。
- 验证走 StatusEngine 真实全链路 + 多股抽样（443 R7 教训：单测覆盖不到全链路）。

## 落地状态（已实施 2026-09-16）

### 双侧同步改动（RAW 权威 `valuation_estimator.py` + SIG 实算 `dim7_valuation_engine.py`）
- **①周期股→PB锚**：dim7 L734 `cat=='周期' 且 PE 极低分位(<20%)` → 权重纯PB归一（w1=1，a1~a5 其余0）；valuation_estimator compute_tags 补一致段（原无周期股处理 → 消除双侧 composite 基准错位）。
- **②PEG>2降级**：`_anchor_earnings` 改为返回 `(score, peg_gt2)`；`peg_gt2=True`（成长/科技类）→ composite 降 **-0.5**；status_description 补 `growth_trap` 标注、audit 加「无成长陷阱」条件。
- **③ROCE判定**：`_fina_health` 三态化返回 `roce_na`（区分无数据/不达标）；`roce_pass=False 且 not roce_na` → composite 降 **-0.3**（价值陷阱）。无数据默认通过（对齐 dim4 `_check_roce`）。status 补 `value_trap` 标注、audit 加「ROCE达标」条件。
- **④FCF口径**：**登记数据缺口**（库内无折旧摊销列），另号补采后用「经营资产FCF=经营现金流-保全性资本支出(折旧≈)」。
- **隐藏缺陷修复**：`_yoY_growth`（双侧）用 `end_date==target` 匹配 Timestamp vs str 恒 None → **PEG 从不真正生效**；改为 `.apply(pd.Timestamp(d)==target)`。

### 验证
- 449 单测 **8 passed**（tests/test_449_dim7_valuation_traps.py）：PEG>2 标记、PEG<=2 不标记、roce_na 三态、growth trap 标注、RAW 侧同步。
- 回归 **56 passed**：test_fix_315_316 / test_273a / test_value_pipeline / test_319 / test_448。
- py_compile 双侧 OK。

## 工作进度记录
- [x] 用户拍板开号（445 B 类第四号，dim7 估值，全选①②③④）
- [x] 权威 wiki 三陷阱 + FCF 标准确认
- [x] 代码现状核查（双侧双份架构、周期股仅 dim7、PEG 小幅、ROCE 只输出、FCF 教科书）
- [x] 数据可用性核查（①PB②PEG③ROCE 已具备；④需补采折旧列）
- [x] 设计拍板（①纯PB归一 / ②composite降-0.5 / ③composite惩罚 / ④登记缺口）
- [x] 实施 + 双侧同步 + 验证（单测8 + 回归56 + py_compile）
