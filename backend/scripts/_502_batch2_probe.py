"""502号 批次2 探针：Q2 纯公式修复（SORTINO/PARKINSON）+ 文档标注（ROC_R/MOM_R/PE/PB/PS）

隔离/桩验证（不发真实查询、不写库）：
  #R3   SORTINO 下行偏差 RMS（与手算 clip(r-target,0)² 公式一致；新旧差异）
  #R45  PARKINSON 括号位（(hl²).rolling vs rolling(mean)²；新值>旧值）
  #R8   ROC_R/MOM_R 时序 rank（rolling rank ∈ [0,1]；formula 标 RollingRank）
  #R7   PE/PB/PS_PERCENTILE_5Y description 标注「非严格 5Y」
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {msg}")
    else:
        FAIL += 1
        print(f"  ❌ {msg}")


# ── #R3 SORTINO 下行偏差 RMS ───────────────────────────────────
print("== #R3 SORTINO 下行偏差修复 ==")
from app.factors.builtin.academic import ACADEMIC_SORTINO  # noqa: E402

n = 60
close = 100 + np.cumsum(np.random.default_rng(42).normal(0, 1, n))
df = pd.DataFrame({'close': close, 'high': close + 1, 'low': close - 1})
f = ACADEMIC_SORTINO()
f.set_param('period', 20)
new_s = f.calculate(df)
# 旧实现（复现 501 前行为）：where(<target,0).std()
returns = df['close'].pct_change()
old_s = (returns.rolling(20).mean() - 0.0) / (returns.where(returns < 0, 0).rolling(20).std() + 1e-10)
valid = new_s.notna() & old_s.notna()
check(valid.sum() > 10, f"有效样本 {valid.sum()}")
# 新旧实现存在差异（修复生效；0 值处理方式不同）
check(not bool(np.allclose(new_s[valid], old_s[valid], atol=1e-9)), "新值 ≠ 旧值（0 值处理方式不同，修复生效）")
# 手算对照（滚动 20 下行 RMS）
down = (returns - 0.0).clip(upper=0)
manual = (returns.rolling(20).mean() - 0.0) / (np.sqrt((down ** 2).rolling(20).mean()) + 1e-10)
check(bool(np.allclose(new_s[valid], manual[valid], atol=1e-9)), "与手算 RMS 公式一致")

# ── #R45 PARKINSON 括号位 ─────────────────────────────────────
print("== #R45 PARKINSON 括号位 ==")
from app.factors.builtin.academic import ACADEMIC_PARKINSON  # noqa: E402

hl = np.log(df['high'] / df['low'])
old_p = np.sqrt((hl.rolling(20).mean() ** 2) / (4 * np.log(2))) * np.sqrt(252)
fp = ACADEMIC_PARKINSON()
fp.set_param('period', 20)
new_p = fp.calculate(df)
v = new_p.notna()
check(bool((new_p[v] > old_p[v] - 1e-9).all()), "新值 > 旧值（Jensen 不等式：rolling(mean²) ≥ mean²）")
manual_p = np.sqrt(((hl ** 2).rolling(20).mean()) / (4 * np.log(2))) * np.sqrt(252)
check(bool(np.allclose(new_p[v], manual_p[v], atol=1e-9)), "与 (hl²).rolling 公式一致")

# ── #R8 ROC_R/MOM_R 时序 rank ─────────────────────────────────
print("== #R8 ROC_R/MOM_R 时序 rank ==")
from app.factors.builtin.reversal import MOM_R, ROC_R  # noqa: E402

fr = ROC_R()
fr.set_param('period', 5)
r = fr.calculate(df)
check(bool((r.dropna() >= 0).all() and (r.dropna() <= 1).all()), "ROC_R rolling rank ∈ [0,1]")
check(not bool(np.allclose(r.dropna(), 0)), "非全 0（与原始 ROC 不同）")
fm = MOM_R()
fm.set_param('period', 20)
m = fm.calculate(df)
check(bool((m.dropna() >= 0).all() and (m.dropna() <= 1).all()), "MOM_R rolling rank ∈ [0,1]")
check("RollingRank" in ROC_R.formula and "RollingRank" in MOM_R.formula, "formula 已标 RollingRank")

# ── #R7 PE/PB/PS 文档标注 ─────────────────────────────────────
print("== #R7 PE/PB/PS_PERCENTILE_5Y 文档标注 ==")
from app.factors.builtin.opportunity import (  # noqa: E402
    PB_PERCENTILE_5Y,
    PE_PERCENTILE_5Y,
    PS_PERCENTILE_5Y,
)

check("非严格 5Y" in PE_PERCENTILE_5Y.description, "PE_PERCENTILE_5Y description 标注")
check("非严格 5Y" in PB_PERCENTILE_5Y.description, "PB_PERCENTILE_5Y description 标注")
check("非严格 5Y" in PS_PERCENTILE_5Y.description, "PS_PERCENTILE_5Y description 标注")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
