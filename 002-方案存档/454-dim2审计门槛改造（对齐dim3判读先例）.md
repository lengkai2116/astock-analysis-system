---
title: 454号 dim2 audit 门槛改造（消除「全为有数据级门槛」恒真，对齐 dim3 判读先例）
type: 方案（B类引擎逻辑修正，445 §6.1 dim2「audit 4项全为有数据级门槛」处置）
date: 2026-09-17
version: v1.0
status: ✅ 已完成
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号是 445 §6.1 dim2「audit 4项全为有数据级门槛（有数据即恒True），判读结论不参与稽核」处置
  - 446-dim2-7契约键补产出（D10）——本号新增判读条件依赖 D10 已产出的 chanlun_phase/divergence/buy_sell_points_detail 三个契约键
  - 436-seven-dim-shell——dim8 归集器消费 audit.confidence（SIG 条件稽核算力下限的体现链）
---

# 454 号 — dim2 audit 门槛改造（对齐 dim3 判读先例）

## 一、问题确认（445 §6.1 dim2，代码级已核）

**445 §6.1 dim2 登记**：「audit 4 项全为有数据级门槛——趋势方向/价格vs中枢/均线排列/支撑阻力都只查『有无数据』，有数据恒 True，判读结论不参与稽核」。

**现状核查**（`dim2_structure_engine.py` step 8 audit）：
- 原 4 条 `conditions` 全部为「数据完整」门槛：
  - 价格vs中枢 / 均线排列 / 支撑阻力 → `bool(有数据)`
  - 缠论分析 → `trend != 未知`
- 含义缺失：**只要字段非空即满足**。audit 无法反映缠论结构质量（是否健康、是否背驰、有无确认买点），`audit.confidence` 对真实盘面几乎恒为 1.0，下游 dim8 `audit.confidence<0.7→data_warning（数据完整度偏低）` 形同虚设。

**对照 dim3 先例**（`dim3_vp_engine.py`）：audit 混合两条**判读结论条件**（量价关系/背离检测判「健康/无背离」而非「有数据」）+ 数据完整门槛（相对强弱 RPS「数据不足时中性放行」）。dim2 应同构。

## 二、修复方案（用户拍板：判读条件对齐 dim3）

`dim2_structure_engine.py` step 8 audit 由 4 条数据完整门槛重写为 **5 条 = 2 数据完整 + 3 判读结论**：

### 2.1 保留 2 条数据完整门槛
| 条件 | 判定 | 数据源 |
|------|------|--------|
| 趋势方向 | `trend not in (未知/无/无数据/unknown)` | `chanlun_result['trend']` |
| 价格vs中枢 | `bool(vs_zhongshu['position'])`（上方/下方/内部） | `_assess_vs_zhongshu` / tags.position_vs_zs |

### 2.2 新增 3 条判读结论条件（D10 契约键）
| 条件 | 判定 | 数据源（446 §6.1 D10 补产出） |
|------|------|------|
| 结构健康度 | `chanlun_phase == '健康'` | 11定理 overall_score≥0.6（D10③） |
| 背驰检测 | `not divergence`（无背驰才满足） | `divergence` 中文串（D10①） |
| 有确认买点 | `buy_sell_points_detail` 含 `type='buy'` 且 `confirmed` | `buy_sell_points_detail`（D10②） |

- `audit` 仍为 `{conditions, satisfied_count, total_count, confidence}` 结构（436 契约键形状不变）。
- 移除了原「均线排列」「支撑阻力」两条数据完整门槛（仍经 `vs_ma`/`geo` 用于 `status_description` 与 `_structure_plain` 文本，不删产出）。

### 2.3 影响（confidence 语义变化已知）
- dim8 `_extract_dim_audit_confidence` 读 dim2 audit.confidence 均值 <0.7 → `data_warning「数据完整度偏低」`（`dim8_summary_engine.py:584`，420号增强6）。454 后 dim2 confidence 将随判读条件浮动，可能触发「数据完整度偏低」文案——
  - 此属 **dim3 已有同构语义**（dim3 judge 条件也会拉低 confidence），非新增缺陷，**不在本号修复**（与 450/443 既有口径一致）。
- 真实盘面 dim2 confidence 从「近乎恒 1.0」变为「随结构健康度/背驰/确认买点浮动」，下游稽核恢复效力。

## 三、验证（全部通过）

### 3.1 单元测试 `tests/test_454_dim2_audit.py`（17 测试）✅
- **结构与契约（3）**：5 条件名/顺序正确；合成基准路径 `satisfied_count<total_count`（消除恒真）；confidence=比例。
- **数据完整门槛（5）**：趋势方向 up→True / unknown→False / 无数据→False；价格vs中枢 tags.position_vs_zs 有→True / 无→False。
- **判读结论条件（8）**：结构健康度 overall_score 0.7=健康→True / 0.5=欲病→False；背驰检测 无背驰→True / 顶背驰→False / 底背驰→False；有确认买点 conf≥0.6 且 type=buy→True / conf<0.6→False / 仅卖点→False。
- **全真场景（1）**：上升+健康+无背驰+确认买点+有位置 → satisfied_count=5、confidence=1.0。
- 用 `mock.patch(ChanlunAnalyzer.analyze)` 精确控制 chanlun 输出逐条验证判读语义；`data_context` 注入 **不触发真实 DB**。

### 3.2 相关回归 ✅（177 passed）
- dim8/dim7 契约与增强：`test_436_seven_dim_contract` + `test_420_dim8_enhancement` 71（含 454）
- dim2 全部：`test_396_dim2_engine` + `test_446_dim2_{contract_keys,divergence_exit,first_0axis,start_containment,trend}` + `test_454_dim2_audit` 106（含 454）
- dim6 本批前置：`test_452`/`test_453` 一并回归通过
- 确认无任何测试断言旧 dim2 audit 条件名（均线排列/支撑阻力/缠论分析），移除安全。

### 3.3 环境说明
- 454 测试本身 `data_context` 注入无需 DB（daemon 运行态也可跑）；但回归批含 DB 触碰用例，按 daemon-stop-policy 先停 daemon+看守，跑完经 `start_daemon.sh` 恢复。

## 四、约束 / 后续

- 本号只改 **dim2 audit 门槛结构与语义**；dim8 `data_warning` 文案随 confidence 浮动属 dim3 同构已知先例，留待 dim8 语义统一阶段（437-A D1-D7 / 444 事实层统一）统筹，不在本号。
- 455+ 待办（450 未覆盖 dim3 放量滞涨/八准则装饰性、dim4 融资成本进阶段投票、dim2 多周期级联立、JUD 侧等）仍按批次优先级排队。

## 工作进度记录（2026-09-17）

- [x] 445 §6.1 dim2「audit 4项全为有数据级门槛」核查（源码确认 4 条件皆 bool(有数据)，confidence 恒近 1.0，dim8 data_warning 失效）
- [x] 用户拍板设计：**判读条件对齐 dim3**（保留 2 数据完整 + 新增 3 判读结论）
- [x] 实现：dim2 audit 重写为 5 条件（趋势方向/价格vs中枢 + 结构健康度/背驰检测/有确认买点），依赖 D10 契约键，移除均线排列/支撑阻力两条
- [x] 校验：py_compile OK + 原型 evaluate（合成数据）确认 5 条件命名/confidence 非恒真
- [x] 新单测 17 passed（逐条 patch 验证判读语义）+ 相关回归 177 passed
- [x] 重启 daemon（start_daemon.sh + data_daemon）恢复运行态
- [x] 落稿（本方案）+ 项目记忆
