---
title: 451-dim4 ASR 语义统一 + 集中度惰性分支修复 + framework 双份同步 + 死代码清理
type: 方案（B 类引擎逻辑偏差处置）
date: 2026-09-16
version: v1.0
status: ✅ 已完成
related:
  - 445-dim2-dim7引擎正确性知识库核查——B 类 dim4 偏差项逐项开号源头
  - 298-维度4 ASR 筹码分布规则——原 _dim_asr 4 条规则来源
  - 312-ASR 静态化三处三义——445 评估核心：同 ASR 值在三处相位矛盾甚至相反
  - 443-dim3量价简化与RAW预计算未消费核查——R2 cost_ext 链路（改 framework 前提）
  - 450-dim3量价背离处置——相邻 B 类处置先例（验证走 443 R7 全链路）
---

# 451 — dim4 ASR 语义统一处置

## 起因（445 六维评估 B 类 dim4 偏差项）

445 号评估指出 dim4「**ASR 静态化三处三义**」——同一 ASR 值在三处代码中相位语义矛盾甚至相反：

| 位置 | 原逻辑 | ASR 高时语义 | 与 wiki 对照 |
|---|---|---|---|
| `_dim_asr`（SIG live） | `asr>90→lifting`、`asr>30 高于峰值→distributing` | 高=拉升→随后又判出货（**自相矛盾**） | 🔴 相悖 |
| `_score_building`（SIG live） | `asr>=70→建仓加分` | 高=建仓 | ✅ 部分一致 |
| framework `_score_chip_distribution`（RAW live） | `asr 30-70 适中`、`asr>80 抛压减分`、`asr<20 锁定` | 高=抛压 | 🔴 相悖 |

另核查确认三处**惰性/死代码**：
- `_score_building` 的 `concentration_status` 中文字段**从未被任何代码生产**（仅消费）→ 集中度分支恒丢 2 分，属惰性。
- `identify_phase` / `_phase_to_status` / `MainForceFilter`（dim4 + framework 双份各一套）**零实例化**（294 号已废除选股系统）→ 死代码。

## 处置范围（用户拍板：全选 ①②③④）

1. **① 统一 `_dim_asr` 高 ASR=蓄势**（推荐）——ASR 高→building 筹码集中蓄势，不再直接 lifting；剔除孤立 `asr>30→distributing`。
2. **② 修复 `_score_building` 集中度惰性分支**——接入 chip 真实集中度数值 `concentration`。
3. **③ framework `_score_chip_distribution` ASR 语义同步**——RAW 与 SIG 基准一致，高 ASR 不再判抛压。
4. **④ 清理死代码**——双份 `identify_phase` / `_phase_to_status` / `MainForceFilter`。

## 权威基准（wiki）

- **《ASR指标》**：ASR 高=筹码集中/突破前蓄势，价格脱离高浮筹区（ASR 高位滑落）才是拉升；出货须「高位+放量+浮筹高企」组合，孤立高 ASR 不判出货。
- **《浮筹》**：高位浮筹=股价不稳定；浮筹大量集中在高位=出货完成（须组合位置判据）。
- **《筹码分布分析-主力视角》**：筹码从分散到集中=建仓蓄势（集中度正向驱动建仓分）。

## 实现（已落地）

### ① `_dim_asr`（dim4_chip_fund_engine.py:574）统一语义

```python
def _dim_asr(self, ts_code: str, df: pd.DataFrame) -> dict:
    chip = self._chip_distribution_analysis(ts_code, df)
    asr = chip.get("asr", 0.0)
    peak_price = chip.get("peak_position", 0.0)
    current = df["close"].values[-1]
    rel = current / peak_price if peak_price > 0 else 1.0
    if asr > 90:                              # 高浮筹集中 → 筹码集中/突破前蓄势
        return {"building": 0.6}
    if asr < 15 and abs(rel - 1.0) < 0.10:    # 低浮筹+锁定在密集峰值附近 → 建仓锁仓
        return {"building": 0.6}
    if asr < 15 and rel > 1.2:                # 低浮筹+大幅高于峰值 → 筹码锁定充分、脱密集区 → 拉升
        return {"lifting": 0.5}
    return {}                                  # 剔除孤立 'asr>30 高于峰值→distributing'
```

关键变化：
- `asr>90` 不再 require `rel<0.95` 判 lifting，直接 building（蓄势）。
- **剔除** 原 `asr>30 and rel>1.05 → distributing` 孤立判出（445 三处三义核心矛盾）。
- 保留 `asr<15` 近峰值→building（锁定在建仓范围）。

### ② `_score_building` 集中度惰性分支接通真实数据（dim4_chip_fund_engine.py:1366）

```python
conc = indicators.get('concentration')
if conc is not None and float(conc) > 0.3:   # 前 20% 价位筹码占比高=集中 → 建仓加分
    score += 2.0
```

- 原 `concentration_status`（'高度集中'/'较集中'）中文字段**从未被生产**（grep 全仓库仅消费 1 处），分支恒不触发。
- 改接 `concentration` 数值（前 20% 价位筹码占比，`_calculate_concentration` 产出 0-1，高=集中），阈值 0.3 参照 framework 单峰密集语义。
- 语义对齐 wiki「筹码从分散到集中=建仓蓄势」。

### ③ framework `_score_chip_distribution` ASR 同步（chip_strategy.py:959）

```python
asr = indicators.get('asr', indicators.get('ASR', 50))
if asr > 90:
    score += 0.2   # 筹码高度集中，突破前蓄势
elif asr < 20:
    score += 0.1   # 浮筹极低，筹码锁定良好
```

- 原 `asr>80 → 减 0.2（抛压）` 与 wiki 相悖（孤立高 ASR 判抛压减分），改为高 ASR 加分（蓄势）。
- 低 ASR（<20）锁定加分语义保留，与 `_dim_asr` 一致。

### ④ 死代码清理（serena safe_delete_symbol，双份各一套）

删除（均零实例化，安全）：
- `MainForceFilter` 类（dim4_chip_fund_engine.py / chip_strategy.py 各一个）
- `_phase_to_status` 函数（仅被 MainForceFilter.filter 引用）
- `MainForceScorer.identify_phase` 方法（仅被 MainForceFilter.filter 引用）

**保留**（live）：`MainForceScorer` 类本身及其 `get_sub_scores` / `_calc_main_force_cost` / `_calc_margin_cost_price` / `_score_chip_distribution` 等（data_daemon.py 实时消费）。`_chip_indicators` / `_chip_bins` 缓存仍被 `_score_volume_price` 等实时路径消费，未删。

## 验证（443 R7：单测 + SIG 全链路 + 回归）

| 项 | 结果 |
|---|---|
| 新增单测 `tests/test_451_dim4_asr_semantics.py`（15 测试） | ✅ 15 passed |
| 全链路 `scripts/sig_full_test.py`（StatusEngine 真实调用） | ✅ 40 OK / 0 FAIL |
| 回归 chip/dim4 相关（test_443_r2/test_chip_sell_ssrp_phase/test_411_pipeline/test_main_path_unified/test_442_margin + 451） | ✅ 各集合 51 / 29 passed |

单测覆盖：
- TestDimAsrSemantics（7）：高 ASR 各位置→building；低 ASR 近峰→building/远峰→lifting；**孤立中高 ASR 不再判 distributing**；无峰值兜底。
- TestScoreBuildingLive（3）：concentration>0.3 建仓 +2 分（消除惰性）；低/缺失集中度不误加分。
- TestFrameworkAsr（2）：framework 高 ASR 正向（不再减分）。
- TestDeadCodeRemoved（3）：双份 `MainForceFilter`/`_phase_to_status`/`identify_phase` 已删，MainForceScorer live 方法保留。

## 约束 / 后续

- 本号仅统一 ASR/集中度语义 + 清死代码，**不触碰** 445 冻结的 dim4 基准：主力四阶段体系、SSRP/主力集中价成本锚定、资金流连续性(max_streak)、拥挤度三因子、ASR 0-100 量级。
- 剩余 B 类：dim2 D6 待开号（445 剩余项）。全闭环后归入「引擎正确性基准」。
- `_dim_asr` 统一后，`concentration`（集中度）现为建仓正向因子，与 `asr>=70→建仓加分` 分支语义一致，无冲突。

## 工作进度记录（2026-09-16）

- [x] 核查：确认「三处三义」真实 live 点（`_dim_asr`/`_score_building` SIG、framework `_score_chip_distribution` RAW）；识别惰性分支（concentration_status 从未生产）与死代码（identify_phase/`_phase_to_status`/`MainForceFilter` 零实例化）
- [x] 用户拍板范围：全选 ①②③④（统一高ASR=蓄势 为推荐项）
- [x] ① 重写 `_dim_asr` 统一高 ASR=蓄势，剔除孤立 distributing
- [x] ② 修复 `_score_building` concentration_status 惰性分支 → 接真实 concentration 数值
- [x] ③ framework `_score_chip_distribution` ASR 语义同步（高 ASR 不再判抛压减分）
- [x] ④ 清理双份死代码（safe_delete_symbol：MainForceFilter/`_phase_to_status`/`identify_phase`）
- [x] 校验：py_compile 双文件 OK；15 单测 passed；SIG 全链路 40 OK；相关回归通过
- [x] 落稿（本方案）+ 项目记忆
