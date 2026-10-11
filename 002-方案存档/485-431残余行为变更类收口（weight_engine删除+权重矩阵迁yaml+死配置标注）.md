---
title: 431 残余行为变更类收口（weight_engine 死模块删除 + 权重矩阵迁 yaml + dim5 死副本清理 + 死配置字段标注）
type: 实施号（431 残余收口；仅行为中性项，判定值调整推迟 JUD）
date: 2026-09-26
version: v1.1
status: ✅ 全面收官（485-1~485-7 全部已实施；485-7 dim1-8 yaml 接线 2026-10-11 完成）
related:
  - 431-430号遗留项核查清单与处置建议（§018 F2+G1 已按「标注+最小真冗余收敛」落地，本号处置其未动的行为变更类）
  - 445-引擎判定逻辑基准（冻结边界：调判定值属「果」，推迟 JUD）
  - 439-A-SIG功能区隔迁移预案（灯色/判定迁移归 JUD 阶段，本号推迟项与其同批）
  - 387号方案5.5（IC动态权重 + 静态矩阵 + 情绪联动，weight_engine 的原始方案来源）
  - 433-IC权重月度滚动重估作业（独立 IC 链，走 potential_engine，不消费 weight_engine）
---

# 485号｜431 残余行为变更类收口

> **定位**：431 号处置进度 19 批全部落地后，**残余仅「行为变更类」**（改了即影响运行时判定）。本号把其中**可实施的行为中性项**（删死模块/迁 yaml/删死副本/标注死配置，均零行为变更）一次性收口；**涉及调判定值的项**（改权重取值、dim1–8 全量接线）登记推迟至 JUD 盘查修正阶段（445 冻结 + 439-A 同批）。

## 一、前提核查（2026-09-26，只读实证，勿重做）

| # | 核查点 | 结论 |
|---|---|---|
| P1 | `weight_engine.py` 消费方 | **全项目零 import**；`dim_adapter.py:371` 仅 docstring 文字提及；`STATIC_WEIGHTS` 与 `status_engine.MARKET_REGIME_WEIGHTS` 逐字节相同（死码孪生）；`EMOTION_MULTIPLIERS` 无对应物 |
| P2 | 433 号 IC 重估是否消费 weight_engine | **否**——走 `potential_engine.recompute_ic_weights` 独立实现（`test_433_ic_recalc.py` 9 用例），与 weight_engine 的 `compute_ic_weights` 无调用关系 |
| P3 | `MARKET_REGIME_WEIGHTS` 迁移兼容 | 唯一 live 权威（`status_engine.py:629`，消费于 `_aggregate` :660 / `_aggregate_v390` :772）；`test_418_jud_v390.py:179/:198/:209` 引用 `StatusEngine.MARKET_REGIME_WEIGHTS` 作覆盖源 ⇒ **类属性必须保留为兜底** |
| P4 | dim5 常量组实态 | **dim5 内 5 组常量（FAST/SLOW_*、PHASE_BASE_TEMP、TEMP_WEIGHTS、BANDWIDTH_*、RANGE_TIGHT、CONSOLIDATION_MIN_DAYS）在 dim5 内零使用点**（仅声明+注释）；live 对应物在 framework 三模块且逐字节相同：`bociasi_quadrant.py:27-30`、`emotion_temperature.py:22/WEIGHTS`、`time_rhythm_engine.py:19-22` ⇒ **dim5 内为死副本**（对 431 §018「无 yaml 对应物，仅标注」的精确化，同 §018 ChanlunLevelValidator 先例） |
| P5 | `signal_registry.yaml` 死字段 | `trigger`/`verify_days`/`verify_rule`/`lifecycle.*.days` 零消费（431 F2 取证）；**唯一 live 字段 = `*.lifecycle.{initial,extended}.dist_pct`**（status_engine:506-507、advice_builder:174、advice_engine:526） |
| P6 | dim5 测试引用面 | `test_479_4_dim5_passthrough.py:24-30` 仅 import 引擎类/话术函数，**不 import 常量** ⇒ 删副本零测试影响 |

## 二、可实施项（本号实施，全部零行为变更）

### 485-1 删除 weight_engine.py 死模块
- `git rm backend/app/opportunity_atlas/weight_engine.py`（整模块零消费方；STATIC_WEIGHTS 权威收敛到 `status_engine.MARKET_REGIME_WEIGHTS`）。
- 验证：grep 无 import 残留；ruff / py_compile。

### 485-2 MARKET_REGIME_WEIGHTS 迁 yaml（值不变）
- `status_engine.yaml` 新增 `market_regime_weights:` 段（4 regime × 7 dim，值=现状逐字节）。
- `status_engine.py.__init__`：`cfg` 含 `market_regime_weights` 且为 dict 时覆盖实例 `self.MARKET_REGIME_WEIGHTS`；**类属性保留为兜底**（yaml 缺失回落，且兼容 test_418 覆盖逻辑）。
- 消费点（`_aggregate`/`_aggregate_v390`）不改行——仍 `self.MARKET_REGIME_WEIGHTS`。

### 485-3 dim5 内死副本常量清理（5 组）
- 删除 `dim5_emotion_engine.py` 中 `FAST_HIGH_THRESHOLD`/`FAST_LOW_THRESHOLD`/`SLOW_HIGH_THRESHOLD`/`SLOW_LOW_THRESHOLD`/`PHASE_BASE_TEMP`/`TEMP_WEIGHTS`/`BANDWIDTH_TIGHT`/`BANDWIDTH_NARROW`/`RANGE_TIGHT`/`CONSOLIDATION_MIN_DAYS`（零使用点）。
- 431 标注注释更新为「已删副本（485号）：live 在 framework bociasi_quadrant/emotion_temperature/time_rhythm_engine」。
- framework 三模块 live 常量**保持代码常量**（引擎内部算法常量，431 定性成立，不迁 yaml）。

### 485-4 signal_registry.yaml 死字段标注
- 仅加注释标注 `trigger`/`verify_days`/`verify_rule`/`lifecycle.*.days` 为**废弃字段（431 F2 取证零消费）**；`dist_pct` 标注为唯一 live 字段。**不改任何值**。

## 三、推迟项（登记，JUD 盘查修正阶段；445 冻结 + 439-A 同批）

| 项 | 内容 | 推迟理由 |
|---|---|---|
| 485-5 | 调 `MARKET_REGIME_WEIGHTS` **取值**（如 trending_down 下 risk 权重） | 属 L2 聚合判定逻辑（果侧），445 冻结（**2026-10-11 仍冻结**：调值走 status_engine.yaml `market_regime_weights` 段） |
| 485-6 | 调 dim5/framework 阈值**取值** | 情绪温度/节奏判定（果侧），445 冻结 ✅ **2026-09-27 已实施一部分（情绪方向口径统一，见下）** |
| 485-7 | dim1–8 全量接线 yaml（F2 真实边界：哪些注册表字段真接线、哪些明确废弃） | **✅ 2026-10-11 已实施**（见 §五；dim2/3/4/5/6 + shared_vol_ratio 收敛 `dim_engine.yaml`，零行为变更；剩余外部 SSOT 阈值族明确不迁、中优先级标注下沉） |

## 三-b、485-6 情绪方向口径统一（2026-09-27 实施，来源 491 §七 批次2）

**背景**：491 号批次2 决策材料（`491-490号登记项（R1-R9）处置方案与批次实施计划.md` §七）发现系统并存**两套相反**的情绪方向表：生效表 `dim_adapter._EMOTION_DIRECTION`（**逆势**：冰点+1/积极-1）与休眠表 `dim_adapter.DIM_DIRECTION['emotion']` + `status_engine._DIM_DIRECTION['emotion']`（**顺势**：冰点-1/积极+1）；且 `conflict_matrix` C3 文案「情绪冰点」却用顺势判据 `emotion_direction == -1` → 在 v390 下**不可达**。

**KB 依据**：逆势派＝`共振冰点策略`（情绪+指数共振触底＝最佳抄底信号）、`逆向投资布局-情绪周期`（极度恐慌＝左侧买点）；顺势派＝`情绪周期四阶段模型`/`情绪周期-仓位联动`（冰点防守、高潮减仓、退潮空仓）；**合流点：高潮＝看空两派一致；冰点＝唯一实质分歧**。

**用户拍板（2026-09-27）**：Q1＝**A 统一逆势**；Q2（R9 情绪极端档是否切 `extreme_panic` 全市场权重）＝**①保留现状**；Q3＝本批**并入 485-6**。

**实施**：
1. 两处**休眠**表 emotion 行统一为逆势口径（与生效表逐键一致）：冰点/萌芽/发酵/复苏→+1；高潮/积极→-1；退潮/退潮·高潮/消极/正常/中性/回归→0。
2. `conflict_matrix` C3 判据改为按阶段：`dim5 sd.market_phase ∈ ('ice','ebb')`（文案同步为「情绪冷区(冰点/退潮)」），不再依赖方向符号。
3. R9 **不改代码**（退潮/高潮 → extreme_panic：risk 0.40/valuation 0.25 保持；数值调整走 485-5 yaml）。

**影响**：v390 判定零变更（两处休眠表 + C3 判据）；C3 由不可达→可达。**新增测试** `tests/test_491_emotion_direction_unified.py`（6 用例）。
**遗留观察**：`_EMOTION_DIRECTION['消极'] = 0`（统一时原样镜像未改语义）——若认为应为 -1 需另提（属语义调整）。

## 四、实施记录

| 子项 | 状态 | 验证 |
|---|---|---|
| 485-1 删 weight_engine.py | ✅ 已实施 | `git rm`；grep 无 import 残留（仅 dim_adapter docstring 已同步修正）；探针确认 |
| 485-2 权重矩阵迁 yaml | ✅ 已实施 | yaml 4/4 regime 与类属性逐字节一致；实例覆盖+缺失兜底双路径探针 OK；test_418（15）+ test_431（19）通过 |
| 485-3 dim5 死副本清理 | ✅ 已实施 | 5 组常量删除；dim5 模块导入正常、无旧常量；dim5 六套件 73 passed |
| 485-4 signal_registry 死字段标注 | ✅ 已实施 | 仅注释标注（trigger/verify_days/verify_rule/days 废弃，dist_pct live）；yaml 解析 OK、值不变 |

**汇总验证**：探针 ALL_PROBE_OK；测试 57（418/431/433/479-4）+ 73（dim5 系）+ 27（462）+ 77（StatusEngine 消费回归，1 DB 用例环境排除）= **234 passed**；ruff 干净（dim5 I001 为改动前已存在、非本次引入）。

## 五、485-7 dim1–8 全量接线 yaml（431 F2 真实边界，2026-10-11 实施）

**缘起**：431 §018 F2 取证「维度引擎零配置引用」→ JUD 阶段（509）已全面收官、JUD 定型 → 开工。**拍板**（2026-10-11）：**全量收敛 + 新建 `backend/config/dim_engine.yaml`**（`config.get_dim_engine_config()` 加载入口 + status_config 再导出）。

**口径（零行为变更）**：
- 收敛值**逐字节不变**（445 冻结果层）；yaml 缺失/键缺失**回退代码默认值**（431 F1「配置可选+兜底」）。
- **外部已 SSOT 的阈值族明确不迁**（维度引擎只消费其产物）：light_derive 灯色 / emotion_temperature 温度 7 入参 / potential_engine 潜力权重 / valuation_estimator 估值锚 / phase_detector 主力阶段 / framework 缠论。
- 中优先级（展示派生/兜底）**标注下沉不迁**：dim8 `DIM_WEIGHTS` 加「展示派生 + 与 potential_engine.DIM_WEIGHTS 同名异义」警示。

**批次实施（4 commits，全部已推送）**：

| 批次 | commit | 收敛内容 |
|---|---|---|
| 1 | `be8553f` | dim6：event_risk_set / ST 分档 / 流动性双门槛（5000万·30亿）/ PIERS-E（70·15）/ 盈亏比（1R·2R·3R）/ 波动率档位（4·2）/ 风险分级计数；**删 `RISK_LEVEL_LIGHT` 死常量**；**`PIERS_HARD_EVENTS` 上移模块头改读 status_engine.yaml `l0.event_hard_risks` 同源统一**（SIG/JUD 防双份漂移） |
| 2 | `ce80ee0` | shared_vol_ratio 量比 5 档（3.0/2.0/1.2/0.8/0.5）+ dim2（confirmed 0.6 / chanlun_phase 0.6 / 健康度 60） |
| 3 | `dc7fed2` | dim5：快线判据（1.5x/3.0/3.0/-3.0）+ pass 档位（3/2）+ 置信（0.65/0.50/0.35/±0.05）、慢线 ERP 四档（5/3/0.5/1.5）+ 置信（0.75/0.60/0.8 上限/1.1 放大）、四象限（QCONF 0.5 + LL 1.15/LH 1.05/HL 0.90/HH 0.75/MM 1.00）、温度合成（0.6/0.4/0.4/0.6） |
| 4-6 | `32074d2` | dim3：HS 7 因子权重（vp 2/-1/1、ve 2/1.5/1/0、ms 1/0/0.5、cs 1/0.5、RSI 四档 1/0.8/0.2/0.5、RPS 85、dp -1.5、pattern_dev 5/1.5）+ 合成参数（4/12/10）+ 档位（8/6/4/2）+ audit 5、Granville 八准则×13；dim4：CrowdingFactor（融资 0.05/0.01、换手 1.5/0.5、布林 P20/P80、2/3 票数、score 0.7+0.1×n）+ audit 阶段置信 0.3；**删 dim3 内联 calc_vol_ratio/classify_vol_ratio 死副本**（与 shared_vol_ratio 逐字重复、零消费）；test_464_17 源码断言同步 |

**验证**：全量回归 **2239 passed / 2 skipped / 9 xfailed 零失败**（35.94s，daemon 停后跑）；分系列 dim2 131 / dim3 56 / dim4 110 / dim5 48 / dim6 67 / test_464_17 26 全绿；py_compile 通过。daemon 重启加载全部新代码。

**F2 边界结论（定稿）**：**真接线**＝dim2/3/4/5/6 + shared_vol_ratio 判定阈值（已收敛 `dim_engine.yaml`）；**明确不迁**＝外部 SSOT 阈值族（light_derive/emotion_temperature/potential_engine/valuation_estimator/phase_detector/framework 缠论）+ 全部中文映射/展示编排表（实现细节）+ 枚举常量；**废弃**＝`RISK_LEVEL_LIGHT`（dim6 死常量）、dim3 内联 vol_ratio 副本、signal_registry 死字段（485-4 已标注）。**仍冻结**＝485-5/485-6 取值调整（果侧，改 yaml 即可，须独立号 + 知识库依据 + 全链路验证）。
