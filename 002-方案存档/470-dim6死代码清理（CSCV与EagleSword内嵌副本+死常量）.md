# 470号｜dim6 风险引擎死代码清理（CSCV/EagleSword 内嵌副本 + 死常量）

**定位**：dim6 只读代码审查（2026-09-22）后续清理号。纯删冗余，不涉及任何"果"逻辑或数据面修改（445 冻结边界内安全）。

## 起因
dim6 dim6_risk_engine.py（1283 行）静态 + 探针审查（600519/000002/000078）发现大量死代码：内嵌两个从未被生产的类副本（~635 行）+ 一组只被死代码引用的常量，且存在与权威模块的重复维护负担。

## 核查结论（删除前已验证）
- **全项目外部引用**仅导入 `Dim6RiskEngine`/`calc_geometric`/`_assess_risk_level`/`_assess_piers_leverage`/`_calc_volatility` 等**存活**符号；无人导入 `CSCVValidator`/`EagleSwordResonance`/`compute_cscv_pbo`/模块级 `evaluate`。
- **权威源存在**：
  - `app/engine/framework/cscv_validator.py` — CSCVValidator + compute_cscv_pbo（同型权威）
  - `app/engine/framework/eagle_sword_resonance.py` — EagleSwordResonance + 模块级 evaluate（同型权威）
- **存活路径**（`Dim6RiskEngine.evaluate` 生产链）从不调用这些副本：`evaluate`（类方法 L1056）只用 `calc_geometric`/`_assess_liquidity`/`_assess_risk_level`/`_list_risk_factors`/`_assess_piers_leverage`/`_calc_volatility`/`_build_invalidation` 等。
- 与 470 号前删 `Bociasi` 双类（BociasiQuickLine/BociasiSlowLine）同型处置。

## 删除清单（dim6_risk_engine.py）

### A. 死代码类/函数（L413-1047，~635 行）
- `calculate_sharpe`（L414，仅 CSCV 用）
- `class CSCVValidator`（L447）+ `compute_cscv_pbo`（L666）
- `class EagleSwordResonance`（L700）
- 模块级 `evaluate(...)`（L1018，仅转调 EagleSwordResonance）
- 段首注释 `# === cscv_validator.py ===` / `# === eagle_sword_resonance.py ===`

### B. 死代码常量（L48-120）
- `_EVENT_DIM_MAP`（L49）/ `_event_dim_prefix`（L65）/ `_direction_to_sign`（L70）
- `CATALYST_EVENT_MAP`（L80）
- `_RESONANCE_TABLE`（L93）/ `_FALLBACK_ACTION`（L120）
- 上述均为事件/鹰剑共振专用，存活路径零引用；权威版本在 `event_monitor.py`（L37/61/70）。

### C. import 清理
- `import itertools`（L17）—— 仅 `CSCVValidator.compute_pbo` 内 `itertools.combinations` 用，删。
- `from typing import Any, Callable, Dict, List`（L20）—— 大写 `Dict/Any/List/Callable` 注解全部在死代码；存活函数均用 `dict/list` 小写，整行删。

## 保留确认（不删）
- `RISK_LEVEL_LIGHT` / `EVENT_RISK_SET` / `ST_WARNING_EVENT` / `ST_WARNING_EXTREME_DIR` / `PIERS_HARD_EVENTS` —— 存活路径使用。
- `calc_geometric`/`_calc_volatility`/`_assess_liquidity`/`_assess_risk_level`/`_list_risk_factors`/`_assess_piers_leverage`/`_assess_rr`/`_build_invalidation`/`class Dim6RiskEngine` —— 存活。
- 文件头注释"整合源 list"更新，移除 cscv_validator/eagle_sword_resonance 两行（其已迁移至 framework 独立模块）。

## 预期
- 文件 1283 → 570 行（减 ~713 行死代码副本 + 死常量 + 死 import）。
- 无功能变化；dim6 生产链、单测、sig 链路不受影响（外部引用均指向存活符号）。

## 验证
- py_compile OK；存活符号 import OK。
- **单测 55 passed**（test_459_dim6_riskaudit / test_448_piers_hard_veto / test_452_dim6_liquidity_volatility / test_453_dim6_st_warning / test_461_dim6_depth_dead_keys / test_461_dim11_support_resistance_unify；338s）。测试前 daemon 停（释放 DB 锁）避免 pytest 卡锁，测后恢复。

## 待办追踪
- 本号仅清理 dim6 内嵌死代码。事件映射权威版（event_monitor.py）无需改动。
- dim6 仍挂账：audit「无高风险事件」只查 severity=='极高' 口径（445 冻结，需拍板）、PIERS-E roce=0.0 误触发（数据`因`层，另号核查数据源）。
