"""502号 批次5 探针：Q4 KDJ 平盘统一（#R13）+ 同型 RSV/WILLR

桩验证（全平盘 high==low==close 序列——一字/停牌场景）：
  - a_stock/momentum KDJ 平盘日不再断链（原 replace(0,nan)→ewm 传播 NaN）
  - indicators calculate_all_indicators/calculate_kdj 平盘 K/D/J=50（每日 RAW-1）
  - reversal RSV 平盘→50、WILLR 平盘→-50
  - 正常波动序列两 KDJ 路径一致性
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


def mk_df(closes):
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({'close': c, 'high': c, 'low': c, 'open': c, 'vol': 1e6})


# 全平盘 30 行（一字/停牌场景）；正常波动 120 行
flat = mk_df(np.full(30, 50.0))
rng = np.random.default_rng(5)
vol = 100 + np.cumsum(rng.normal(0, 1, 120))
vol_df = mk_df(vol)

print("== a_stock KDJ 平盘不断链 ==")
from app.factors.builtin.a_stock import KDJ_D as A_KDJ_D  # noqa: E402
from app.factors.builtin.a_stock import KDJ_J as A_KDJ_J  # noqa: E402
from app.factors.builtin.a_stock import KDJ_K as A_KDJ_K  # noqa: E402

for cls, tag in [(A_KDJ_K, 'K'), (A_KDJ_D, 'D'), (A_KDJ_J, 'J')]:
    f = cls()
    r = f.calculate(flat.copy())
    check(bool(r.notna().iloc[-1]), f"ASTOCK_KDJ_{tag} 平盘末值非 NaN（原断链→修复）={r.iloc[-1]:.1f}")
    check(np.isclose(r.iloc[-1], 50.0), f"ASTOCK_KDJ_{tag} 平盘末值=50（中性）")

print("== momentum KDJ 平盘不断链 ==")
from app.factors.builtin.momentum import KDJ_D as M_KDJ_D  # noqa: E402
from app.factors.builtin.momentum import KDJ_J as M_KDJ_J  # noqa: E402
from app.factors.builtin.momentum import KDJ_K as M_KDJ_K  # noqa: E402

for cls, tag in [(M_KDJ_K, 'K'), (M_KDJ_D, 'D'), (M_KDJ_J, 'J')]:
    f = cls()
    r = f.calculate(flat.copy())
    check(bool(r.notna().iloc[-1]), f"KDJ_{tag} 平盘末值非 NaN={r.iloc[-1]:.1f}")
    check(np.isclose(r.iloc[-1], 50.0), f"KDJ_{tag} 平盘末值=50（中性）")

print("== 每日 RAW-1 indicators KDJ ==")
from app.indicators import TechnicalIndicatorEngine  # noqa: E402

eng = TechnicalIndicatorEngine()
r_all = eng.calculate_all_indicators(flat.copy())
for col in ('kdj_k', 'kdj_d', 'kdj_j'):
    check(bool(r_all[col].notna().iloc[-1]), f"calculate_all_indicators {col} 平盘非 NaN={r_all[col].iloc[-1]:.1f}")
    check(np.isclose(r_all[col].iloc[-1], 50.0), f"calculate_all_indicators {col}=50")
r_kdj = eng.calculate_kdj(flat.copy())
check(bool(r_kdj['kdj_k'].notna().iloc[-1]), f"calculate_kdj 平盘非 NaN={r_kdj['kdj_k'].iloc[-1]:.1f}")
check(np.isclose(r_kdj['kdj_k'].iloc[-1], 50.0), "calculate_kdj K=50")

print("== reversal RSV/WILLR 平盘中性 ==")
from app.factors.builtin.reversal import RSV, WILLR  # noqa: E402

fr = RSV()
rr = fr.calculate(flat.copy())
check(np.isclose(rr.iloc[-1], 50.0), f"RSV 平盘→{rr.iloc[-1]:.1f}（应 50）")
fw = WILLR()
rw = fw.calculate(flat.copy())
check(np.isclose(rw.iloc[-1], -50.0), f"WILLR 平盘→{rw.iloc[-1]:.1f}（应 -50）")

print("== 正常波动序列两 KDJ 路径一致 ==")
a = eng.calculate_all_indicators(vol_df.copy())
b = eng.calculate_kdj(vol_df.copy())
for col in ('kdj_k', 'kdj_d', 'kdj_j'):
    check(bool(np.allclose(a[col], b[col], atol=1e-9, equal_nan=True)), f"{col} 两路径逐位一致")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
