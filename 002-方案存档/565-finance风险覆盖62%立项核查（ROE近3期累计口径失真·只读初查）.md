---
title: finance 风险覆盖 62% 立项核查（ROE 近3期累计口径失真·只读初查）
type: 立项核查
date: 2026-11-12
status: v1.1 深查完成并推送（2026-11-12，ddb9309；沙箱配对回放）——ROE 口径失真已确证，且 OCF 腿同样是结构性失真；但「修 ROE 口径」对 avoid 的影响极小（净 −1/260），62% 不是 avoid 73.6% 的主因
---

# 565 - finance 风险覆盖 62% 立项核查

## 一、立项背景

2026-11-11 日终核查（`001-沟通记录/2026-11-12.md` §001）发现：JUD 输出 `dim_states.finance = 风险` 覆盖 **3452/5572（61.95%）**，与 `l0.soft_risks` 中的 `fina_fail` **完全同源同数**；同期 `avoid` 占 73.6%、`final_score` 中位数 0。用户拍板「D 也立项核查」。

本档为**立项 + 只读初查**，不含代码改动；目的是把「62% 是否合理」拆成可验证问题，并给出疑似主因与量化证据。

---

## 二、已完成初查（只读，2026-11-12）

### 2.1 分布与稳定性

| 数据日 | n | finance=风险 | fina_fail | 占比 |
|---|---|---|---|---|
| 2026-11-05 | 5570 | 3450 | 3450 | 61.9% |
| 2026-11-09 | 5572 | 3452 | 3452 | 62.0% |
| 2026-11-10 | 5571 | 3452 | 3452 | 62.0% |
| 2026-11-11 | 5572 | 3452 | 3452 | 62.0% |

- 两者跨日几乎恒定，非单日行情驱动，属**结构性口径**问题。
- `finance = 风险` ⇔ `fina_fail` ∈ `soft_risks`，一一对应（3452/3452）。

### 2.2 判定链路

```
valuation_estimator._fina_health()  →  'pass' | 'suspicious' | 'fail'
        ↓ fina_health='fail'
status_engine._apply_l0()           →  soft_risks += 'fina_fail'，position_coeff × 0.5
dim6_risk_engine                    →  risk_sources += {'name':'财务风险','level':'高'}
dim_adapter                         →  dim_states.finance = '风险'
```

代码位置：

- `backend/app/opportunity_atlas/valuation_estimator.py:669-795` → `_fina_health()`。
- `backend/app/opportunity_atlas/status_engine.py:861-864` → `fina_fail` × 0.5。
- `backend/app/opportunity_atlas/dimensions/dim6_risk_engine.py:203` → `财务风险` 等级 `高 if fh == 'fail'`。
- `backend/app/opportunity_atlas/dim_adapter.py:669-673` → `finance` 状态由 `fina_health` 推导。

### 2.3 `_fina_health` 的实际规则

`fail_count = sum(not v for v in [roe_ok, liab_ok, ocf_ok])`：

- `fail_count >= 2` → `fail`；`>= 1` → `suspicious`。
- `roe_ok`：`df_fina['roe'].dropna()` **前 3 行**均值 > 6.0；数据不足 3 期时 `roe_ok = False`。
- `liab_ok`：最新一期资产负债率 < 70%（金融行业除外）；缺数据默认 `True`。
- `ocf_ok`：近 3 期经营现金流/净利润 > 0.8；缺数据默认 `True`。

读取路径：`enhanced_cache_manager.py:2732-2736` → `ORDER BY end_date DESC`，**排序正确**；因此 `head(3)` 确为「最新 3 个报告期」，不存在取到旧数据的排序缺陷。

### 2.4 疑似主因：最新 3 期是「季度累计值」，不是年度值

`fina_indicator_cache.roe` 为**报告期累计口径**。以 `000001.SZ` 为例（`ORDER BY end_date DESC`）：

| end_date | roe（累计） |
|---|---|
| 2026-09-30 | 7.074 |
| 2026-06-30 | 4.6746 |
| 2026-03-31 | 2.652 |
| 2025-12-31 | 8.1514 |

- 代码取前 3 行均值 = `(7.074+4.6746+2.652)/3 = 4.80` → **roe_ok = False**。
- 若按最近 3 个**年报**（12-31）均值 → `(8.1514+…)/3`，口径才可比。

全市场量化（`fina_indicator_cache`，5594 只有 ≥3 期）：

| 口径 | ROE 均值 > 6% 股票数 | 占比 | 中位数 |
|---|---|---|---|
| 最近 3 期（季度累计，现行代码） | 968 | **17.3%** | **2.20** |
| 最近 3 个年报（12-31） | 2464 | **44.1%** | **4.92** |

即：现行口径把「季度累计 ROE」当年度 ROE 用，系统性压低约一半，**82.7% 的股票 roe_ok 失败**；再用 `liab/ocf` 任一失败凑到 2 条 → 62% 判 `fail`。

### 2.5 阈值校准也被同一失真口径带偏

`valuation_estimator.py:703-705` 注释：

> 「校准 2026-08-02：原 10% 阈值过高——A股 ROE 中位仅 ~2.25，ROE>10% 仅 10.8% 达标，致 83% 股票被判 suspicious」

本次实测「季度累计口径」全市场中位 **2.20**，与该注释的 `~2.25` 高度吻合 → 说明 6% 门槛是**按失真口径的分布**下调的，所以即使降到 6%，仍有 82.7% 不过。

### 2.6 补充事实

- `roe_yearly` 字段虽存在，但覆盖极低：2026-09-30 仅 4 行、全表仅 147 只 → **当前不可直接替代**。
- `fina_indicator_cache` 覆盖 5597 只、≥3 期 5594 只 → 覆盖面不是问题，问题在口径。
- 11-11 `risk = 高` 2738 只（49.1%），其中「财务风险（高）」是主要贡献源之一；`avoid` 73.6% 与 `fina_fail 62%` 同向，但本档**不预设因果强度**，需第 4 节敏感性核查。

---

## 三、待核查问题（Q1~Q6）

| 编号 | 问题 | 判定口径 |
|---|---|---|
| Q1 | Tushare `fina_indicator.roe` 是否确为报告期累计（非 TTM）？ | 抽样 30 只，对比年报/季报与 `roe_waa/roe_dt/roe_yearly` |
| Q2 | `roe_ok` 应改「最近 3 个年报」还是「TTM / 最新年报」？ | 需先定业务口径；影响 44.1% vs 17.3% |
| Q3 | `liab_ok` / `ocf_ok` 两腿的独立失败率与与 ROE 的交叉率是多少？ | 全市场分组统计，定位 62% 中 ROE 腿贡献占比 |
| Q4 | 6% 门槛在「年报口径」下应取多少（6% / 分位阈值 / 行业中位数）？ | 属「果」层阈值，须知识库依据 + 独立拍板 |
| Q5 | 若仅修口径、不动阈值，`avoid` 占比会降多少？ | 沙箱重放 11-11：改 `_fina_health` 口径 → JUD-only 重算 → 对比状态分布 |
| Q6 | 与 445/439「果层冻结」的边界如何界定？ | 口径修复（数据正确性）≠ 阈值调优；但 Q4 必须单独论证 |

---

## 四、深查方法（只读 + 沙箱）

1. **只读取数清单**（全部 `mode=ro`）：
   - `fina_indicator_cache`：`roe/roe_waa/roe_dt/roe_yearly/end_date` 分布；
   - `income_cache` / `balancesheet_cache` / `cashflow_cache`：`end_date` 对齐与缺失率；
   - `status_snapshot_history`：`finance/fina_fail/avoid` 交叉表（按 ROE 腿/负债腿/现金流腿分组）。
2. **抽样复核**：30 只（各行业 + 大中小市值 + 亏损/微利/高 ROE），人工核对 `_fina_health` 三腿结论与报表。
3. **敏感性重算**（沙箱）：
   - `cp -c` 克隆 `data/duckdb`；
   - `DATA_DIR` + `init_sharding(tmp)` 双切（红线：只切 DATA_DIR 会写回基准库）；
   - 仅改 `_fina_health` 的 ROE 口径（不改阈值），对 11-11 跑 JUD-only；
   - 输出：`avoid` 变化、`final_score` 分布、`max_position_ratio` 分布、逐股 state 翻转清单。
4. **不写基准库**：任何试算均在克隆库完成；基准库只读核查。

---

## 五、产出物与验收标准

| 产出 | 内容 |
|---|---|
| 核查档（565 更新为 v1.1） | Q1~Q6 逐项结论 + 全市场分组表 + 30 只抽样表 |
| 敏感性报告 | 口径修正前后 `avoid/enter/wait` 与分数分布对比；逐股翻转 Top 50 |
| 建议 | 是否修口径、门槛是否重定标、是否需要新号实施 |
| 验收 | 结论可复跑（SQL/脚本落档）；沙箱重放不污染基准库；口径修正后 `finance=风险` 占比与年报 ROE 分布自洽 |

---

## 六、声明

- 本档为**立项核查**，不预设「62% 一定错误」；仅确认「现行 ROE 口径混用季度累计值」这一事实，及其对达标率的量化影响。
- 不修改任何代码、配置或数据；后续实施须另开号并经拍板。

---

## 七、深查结果（v1.1，2026-11-12）

### 7.1 全市场三腿分解（5597 只有 ROE 数据；按 `_fina_health` 原逻辑复算）

| 腿 | 失败数 | 失败率 | 说明 |
|---|---:|---:|---|
| `roe_ok`（现行：最近 3 期累计均值 >6%） | 4629 | **82.7%** | 年度口径（最近 3 个 12-31）失败降为 3133（56.0%） |
| `liab_ok`（资产负债率 <70%，金融豁免） | 623 | 11.1% | 缺数据默认 True |
| `ocf_ok`（近 3 期 OCF/净利润 全部 >0.8） | 3940 | **70.4%** | 见 7.2 |
| **合计 `fina_health=fail`（≥2 腿失败）** | **3468** | 62.0% | 复算 3468 vs 库内 3452（差 16，0.5%，来自行业分类/数据对齐） |
| 年度 ROE 口径下 fail | 2469 | 44.1% | 仅换 ROE 腿，降 999 只 |

迁移矩阵（现行 → 年度 ROE 口径）：`fail→fail 2349`、`fail→suspicious 1119`、`suspicious→fail 120`、`suspicious→pass 507`、`pass→suspicious 25`、`pass→pass 254`、`suspicious→suspicious 1223`。

### 7.2 OCF 腿是第二处结构性失真

- 期次对齐问题很小：5587 只中期次错配仅 **4 次**（income/cashflow 均按 end_date DESC 排序后配对）。
- 但规则是 **3 期逐期 `>0.8` 全部满足**：`3 期全坏 1753 只（31%）`、`坏 1 期 1146`、`坏 2 期 1041`、`全部达标 1647`。
  ⇒ **1146 只是因为「单期不达标」被判失败**。
- 比率中位数 **0.773**（恰在 0.8 门槛下）；**负值占比 33.9%**——亏损公司「OCF/净利润」符号无经济含义（正现金流/负利润 = 负比率），必然失败。
- 极端样本：`600170.SH` 三期比率 `-17.69 / -38.16 / -15943.48`。

### 7.3 抽样回放（沙箱 + 配对差分）

- 方法：`cp -c` 克隆 `data/duckdb` → `DATA_DIR=/tmp/564d` + `init_sharding('/tmp/564d')` 双切；把 `fina_indicator.roe` 前 3 行替换为「最近 3 个年报 ROE」，重算 `ValuationEngine.compute_tags` → `StatusEngine.evaluate(dim_results=None, asof_date='2026-11-11')`。
- 样本：260 只（150 只现行 fail + 100 只非 fail + 10 只固定大盘/银行/亏损样本），同口径跑 **对照组（不换 ROE）** 与 **修正组**，采信配对差分（消除 RSC 覆盖等回放偏差）。
- 结果（对照 → 修正）：

| 指标 | 结果 |
|---|---|
| `fina_fail` | fail→非 fail **45/154（29.2%）**；非 fail→fail **9** |
| `finance` 状态 | 风险→关注 45；关注→pass 17；关注→风险 9 |
| `opportunity_state` | 仅 `avoid→reduce 3`、`avoid→wait 1`、`reduce→wait 1` 转出；`wait→avoid 1`、`reduce→avoid 2` 转入；其余 252 不变 |
| `final_score` | 上升 22 只 / 不变 226 / 下降 12；45 只翻出 fail 中仅 11 只分数上升（均值 +12.2） |
| 净 avoid 变化 | **−1 / 260（≈ −0.4%）** |

### 7.4 结论（修正立项初判）

1. **62% 确实含口径失真**：ROE 用季度累计值、OCF 用「3 期逐期严格 + 亏损公司比率无意义」，两者都把 `fina_health` 系统性推向 `fail`。
2. **但 62% 不是 avoid 73.6% 的主因**：仅修 ROE 口径，`finance=风险` 约降 29%（全市场估计 3452→~2469），而 avoid 净变化仅 −1/260；45 只翻出 fail 的股票里 33 只仍为 avoid。
3. **主因另在别处**：11-11 `structure=下降 4176（75%）`、`risk=高 2738（49%）`、`vp=背离/中性 4463（80%）`，评分制 v390 下这些维度主导 `final_score`。下一号应做「avoid 主因分解」，而不是继续在 finance 单点深挖。

### 7.5 局限

- 抽样 260 只（非全市场）；回放未重算 RAW-2 的全市场横截面百分位（`composite_rating` 相对分位），故为**下界估计**。
- 对照组回放与库内基线存在 RSC 差异（`wait→avoid 23` 等），因此只采信「对照 vs 修正」的配对差分，不用「回放 vs 库内」的绝对差。

---

## 八、下一步建议

| 项 | 建议 | 性质 |
|---|---|---|
| 565-1 | 修 `_fina_health` 的 ROE 口径：改为「最近 3 个年报」或 TTM；`roe_yearly` 需先补采（当前仅 147 只） | 数据正确性，建议做 |
| 565-2 | 修 OCF 腿：亏损公司单列（不用比率）、单期失配改「3 期中 ≥2 期达标」或看中位数 | 数据正确性，影响面大于 ROE |
| 565-3 | 6% / 0.8 门槛重定标 | 「果」层，须独立拍板 + 知识库依据 |
| 565-4 | 新开号做「avoid 73.6% 主因分解」（structure/risk/vp/consensus 敏感度） | 诊断，建议优先于 finance 深挖 |
