# 504号｜既有失败挂账处置（dim7 测试错位修复 + 快照日终 gap 登记）

> **版本**：v1.0（2026-10-01 开号，核查 + 拍板 + dim7 测试修复；快照验证待 09-30 日终完成）
> **前置**：resume-20261001 优先序第 1 项——全量回归 4 个基线既有失败（502/503 期间 stash 验证与改动无关）

---

## 一、核查结论（4 失败 × 根因）

| 测试 | 失败 | 根因 |
|------|------|------|
| `test_484::test_dim7_oper_minus_depr` | `Dim7ValuationEngine` 无 `_anchor_cashflow` | **测试代码 bug**：484 号实施时测试引用 `Dim7ValuationEngine._anchor_cashflow`；476 号双份方法体收敛后 dim7 现金流锚**委托 `ValuationEngine`**（dim7_valuation_engine.py:398 `_ve=ValuationEngine(); a3=_ve._anchor_cashflow(...)`），dim7 副本移除、测试未跟随。同文件 `test_valuation_estimator_oper_minus_depr`（用 ValuationEngine）通过佐证 |
| `test_484::test_dim7_fallback_free_cashflow` | 同上 | 同上 |
| `test_t14::test_snapshot_pe_matches_source` | 快照 pe 5.1436 vs 源 5.2665 | **真实日终未完成（数据未就绪）**：treemap_snapshot 停 2026-09-28（snapshot_date=09-29），源已到 09-30 |
| `test_t25::test_snapshot_ohl_values` | 快照 open 11.28 vs 源 11.36 | 同上 |

**快照 gap 根因链**：pipeline_status 显示 **09-29/09-30 日终在 RAW-2 起全 pending**（COL 全 done、RAW-1 done，RAW-2/2B/2C/3/SIG/JUD/OUT/QA-CHECK pending）——RAW-2（`_precompute_raw_features` 全市场特征提取）超 1800s 触发 428 P1-2 超时续算；12:25 daemon 12:57 超时后台续算 → 13:13 被停（502 全量回归）→ 13:19 重启后**正在续算 09-30 RAW-2**。快照（OUT 环节生成）停在 09-28 是果。

## 二、拍板记录（2026-10-01）

| 项 | 决策 |
|----|------|
| dim7 2 失败 | **改测试**用 `ValuationEngine`（对齐 476 收敛后的实际委托路径，不重建双份） |
| 快照 2 失败 | **不改测试**（断言正确：快照应与源一致）；**等 13:19 daemon 完成 09-30 日终** → 快照更新到 09-30 → 重跑验证；**登记 09-29 日终历史 gap** |

## 三、实施（dim7 测试修复 ✅）

`tests/test_484_data_backfill.py` `TestAnchorCashflowFCF`：两个失败测试 `Dim7ValuationEngine` → `ValuationEngine`（类注释更新 476 收敛说明）。**4/4 passed**。

## 四、登记（数据 gap）

| 登记 | 内容 | 处置 |
|------|------|------|
| 登记-1 | **09-29/09-30 日终 RAW-2 起未完成**（RAW-2/2B/2C/3/SIG/JUD/OUT/QA-CHECK pending） | 09-30 为最新 data_date，数据驱动续算中（13:19 daemon RAW-2 续算）→ 完成后快照更新；**09-29 非最新日不会被数据驱动补算** → SIG/JUD/OUT/快照历史 09-29 缺（历史 gap，待后续专项或可接受） |
| 登记-2 | 快照验证依赖 09-30 日终完成（预计 30-60min） | 完成后重跑 test_t14/test_t25 确认 |

## 五、验证口径

- dim7：`pytest tests/test_484_data_backfill.py::TestAnchorCashflowFCF` → 4 passed ✅
- 快照：等 daemon 09-30 日终 OUT done（treemap_snapshot MAX(trade_date)=2026-09-30）→ `pytest tests/test_t14_pe_pb.py tests/test_t25_f4_ohl.py` → 应 5 passed（原 4 中 2 快照失败转绿）
- 全量回归：待快照验证后跑（停 daemon 前置）

## 六、沟通记录

- **2026-10-01 开号**：核查 4 失败 → 两类根因（dim7 测试错位 / 快照=日终未完成）→ 拍板（改测试 + 等日终 + 登记 gap）→ dim7 测试修复完成。
