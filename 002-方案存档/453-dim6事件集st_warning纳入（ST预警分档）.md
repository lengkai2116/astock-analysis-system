---
title: 453号 dim6 事件集 st_warning 纳入（ST预警分档）
type: 方案（B类引擎逻辑修正，445 §6.3 dim6「事件集不完整」处置）
date: 2026-09-17
version: v1.0
status: ✅ 已完成
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号是 445 §6.3 dim6「事件集不完整：st_warning/pledge_risk/holder_reduce 已注册未纳入」处置中的 st_warning 子项
  - 448-dim6风险引擎PIERS硬否决扩展——dim6 前一号（造假/退市升 L0a 硬否决 + E 高杠杆 + audit 假检查修复；当时 st_warning 未纳入，留待本号）
  - 452-dim6流动性口径与波动率处置——dim6 系列本批另一号（流动性双门槛 + 波动率摘除）
  - 439-SIG功能区隔迁移预案——SIG/JUD 边界（SIG 产条件，JUD 否决/灯色归 JUD）
---

# 453 号 — dim6 事件集 st_warning 纳入（ST预警分档）

## 一、问题确认（445 §6.3 dim6，代码级已核）

**445 §6.3 dim6 登记**：「事件集不完整（st_warning/pledge_risk/holder_reduce 已注册未纳入）」——ST/监管标记检测器早已存在并产出事件，但消费链未纳入。

**现状核查**（`event_monitor.py` C3 `_detect_st_warning`，L409）：
- 检测器已产出 `st_warning` 事件进 `tags['event_details']`，三档：
  - `*ST` → direction=**-2**（confidence 1.0）
  - 退市整理（名含「退」）→ direction=**-2**（confidence 0.95，335号并入）
  - 普通 `ST` → direction=**-1**（confidence 0.8）
- **但消费链两处未纳入**：
  1. **SIG 侧 dim6**：`EVENT_RISK_SET = {'fraud_sign','regulatory','delist_risk','goodwill_risk'}` **不含 st_warning** → ST 预警不做事件风险源/因子/audit 呈现，ST 股在 dim6 看不到任何 ST 风险信号。
  2. **JUD 侧 `_apply_l0`**：yaml `event_hard_risks: [fraud_sign, delist_risk]` + 代码 `_hard_labels` **不含 st_warning** → 不直接硬否决。仅靠 `CATALYST_EVENT_MAP['st_warning']='regulatory'` 兜底，但 `catalyst_event` 取 |direction| 最大事件，普通 ST（-1）可能被其它事件覆盖，监管立案硬否决路径不可靠。

> pledge_risk/holder_reduce 属 **R 维数据缺口**（448 已登记，无 pledge_stat/stk_holdertrade 表），不在本号。

## 二、修复方案（用户拍板：SIG + JUD 分档）

ST 预警按 direction 分档（`*ST`/退市整理 direction≤-2 是重大退市预警、同 delist_risk；普通 ST direction=-1 是关注级）：

### 2.1 SIG 侧 dim6（`dim6_risk_engine.py`，产条件不产否决）

- **`EVENT_RISK_SET` 纳入 `st_warning`**（事件风险源），并增模块常量 `ST_WARNING_EVENT='st_warning'` / `ST_WARNING_EXTREME_DIR=-2`。
- **`_list_risk_factors`** 事件名中文映射补 `st_warning→ST预警`（原 fallback 显示原始英文键）。
- **`evaluate` 事件循环**新增 st_warning 直读 `event_details` 分档（同 448 直读模式，不依赖 catalyst_event 单值）：
  - direction≤-2（*ST/退）→ severity=**「极高」**（进 audit「无高风险事件」不满足 + 供 JUD 硬否决）；
  - direction=-1（普通 ST）→ severity=**「高」**（事件风险源，audit 记「无极高」仍为满足）。
  - 多条只增不降（若有 -2 则升极高）。

### 2.2 JUD 侧 `_apply_l0`（StatusEngine，灯色/否决归 JUD）

- **L0a 硬否决**：`_hard_labels` 增 `st_warning→'ST/退市整理（L0a 硬否决）'`；直读 `event_details`，**仅 direction≤-2（*ST/退）硬否决**，普通 ST（=-1）跳过不进硬否决。
- **L0b 软风险**：普通 ST（direction=-1）且未硬否决者 → `soft_risks` 增 `'st_warning'`，`position_coeff ×0.8`；`config/status_engine.yaml` `soft_risk_coeff` 增 `st_warning: 0.8`。

### 2.3 边界合规

- SIG 只产 severity（极高/高）+ 条件；**否决/灯色在 JUD 侧 `_apply_l0`**，符合 444/439 SIG/JUD 边界。
- 既有 fraud_sign/delist_risk 硬否决路径**零改动**（回归验证）。

## 三、影响评估

- ***ST**/退市整理（direction=-2）：现被**一票硬否决**（L0a）+ dim6 升「极高」——这些是最极端退市风险，补上了原缺口。
- **普通 ST**（direction=-1）：dim6 呈现「高」事件风险、JUD 仓位×0.8（不硬否决）——不误杀，仅收敛仓位。
- **无 ST 事件**股票：完全不受影响；fraud/delist 既有路径不变（回归通过）。
- `catalyst_event='regulatory'` 兜底路径保留（*ST 时 catalyst 仍可能映射 regulatory），与新增直读并存不冲突。

## 四、验证（全部通过）

### 4.1 单元测试 `tests/test_453_dim6_st_warning.py`（12 测试）✅
- **SIG 侧（5）**：EVENT_RISK_SET 含 st_warning；*ST(-2)→risk_level 极高 + ST预警因子含「极高」；普通 ST(-1)→高；*ST audit「无高风险事件」不满足；无 ST 事件基线不变。
- **JUD 侧（5）**：*ST(-2)→L0a 硬否决（文案含 ST/退市）；普通 ST(-1)→不硬否决、soft_risks 含 st_warning 且仓位 0.8；无 ST 不触发；st_warning 与 fraud_sign 并存时 fraud 硬否决优先；st_warning(-1)+catalyst=regulatory 走原监管硬否决。
- **源码接线（2）**：status_engine._apply_l0 含 st_warning 分档；dim6.evaluate 含 ST_WARNING_EVENT。
- 全程注入 data_context（dim6）或 mock dm（JUD），**不触发真实 DB 回退**。**12 passed。**

### 4.2 相关回归 ✅（33 passed）
- `test_448_piers_hard_veto.py` 9 + `test_452_dim6_liquidity_volatility.py` 17 + `test_321_s4_snapshot.py` 7 ＝ **33 passed**——确认 st_warning 改动不破坏 fraud/delist 硬否决、dim6 流动性、JUD L0b。

### 4.3 环境说明
- 测试须在 daemon **停止**状态下跑（开发态基准库有 SQLite 写锁；452 同限制）；验证后已重启 daemon（`start_daemon.sh` 看守 + `data_daemon`）恢复运行态。

## 五、约束 / 后续

- 本号只处置 **st_warning**；dim6 事件集剩余项：
  - **pledge_risk / holder_reduce** → 属 **R 维数据缺口**（448 登记，需补采 pledge_stat/stk_holdertrade 表），不在本号。
- JUD L0 体系其它项（452 的 low_liquidity 换手率软风险、439-A SIG 灯色迁移）仍留待 JUD 盘查阶段统一规划。

## 工作进度记录（2026-09-17）

- [x] 445 §6.3 dim6「事件集不完整」核查（C3 检测器已产 st_warning 三档，SIG EVENT_RISK_SET / JUD event_hard_risks 双缺）
- [x] 用户拍板范围：**SIG + JUD 分档**（direction≤-2 硬否决/极高，-1 软风险/高）
- [x] SIG：EVENT_RISK_SET 纳入 st_warning + 常量 + _list_risk_factors 中文 + evaluate 分档
- [x] JUD：_apply_l0 增 st_warning 硬否决（仅≤-2）+ L0b 软风险（×0.8）+ yaml soft_risk_coeff
- [x] 校验：py_compile OK + yaml 校验 OK；新单测 12 passed + 回归 33 passed
- [x] 重启 daemon（start_daemon.sh + data_daemon）恢复运行态
- [x] 落稿（本方案）+ 项目记忆
