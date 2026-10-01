"""502号 批次4 探针：Q3 RSI 零除数三套统一（#R10/#R11/#R12）

桩验证三态语义（单调上涨→100、单调下跌→0、全平盘→50）逐实现：
  a_stock RSI_6/14/24（rolling mean）、qlib158 QLIB_RSI_14（Wilder EMA）、
  gtja191 GTJA042（rolling mean）、momentum RSI（Wilder EMA）、
  indicators calculate_all_indicators + calculate_rsi（每日 RAW-1）
关键守卫：窗口不足保持 NaN（不被平盘 50 误填）
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


# 三态桩：单调上涨 / 单调下跌 / 全平盘（各 30 行）
up = mk_df(np.arange(30, 60, 1.0))
down = mk_df(np.arange(60, 30, -1.0))
flat = mk_df(np.full(30, 50.0))

print("== 三态语义（最后有效值）==")
from app.factors.builtin.a_stock import RSI_14 as A_RSI14  # noqa: E402
from app.factors.builtin.gtja191 import GTJA042  # noqa: E402
from app.factors.builtin.momentum import RSI as M_RSI  # noqa: E402
from app.factors.builtin.qlib158 import QLIB_RSI_14  # noqa: E402

cases = [('a_stock RSI_14', A_RSI14(), True), ('qlib158 QLIB_RSI_14', QLIB_RSI_14(), False),
         ('gtja191 GTJA042', GTJA042(), True), ('momentum RSI', M_RSI(), False)]
for label, f, is_rolling in cases:
    if label.startswith('a_stock'):
        f.set_param('period', 14)
    elif label.startswith('gtja'):
        f.set_param('period', 6)
    ru = f.calculate(up.copy())
    rd = f.calculate(down.copy())
    rf = f.calculate(flat.copy())
    check(np.isclose(ru.iloc[-1], 100.0), f"{label} 单调上涨→{ru.iloc[-1]:.1f}（应 100）")
    check(np.isclose(rd.iloc[-1], 0.0), f"{label} 单调下跌→{rd.iloc[-1]:.1f}（应 0）")
    check(np.isclose(rf.iloc[-1], 50.0), f"{label} 全平盘→{rf.iloc[-1]:.1f}（应 50）")
    # 窗口不足守卫仅适用于 rolling 实现（ewm 无起始窗口概念，首行即有效）
    if is_rolling:
        check(rf.iloc[:1].isna().all(), f"{label} 起始窗口保持 NaN（未误填 50）")

print("== 每日 RAW-1 indicators 双实现 ==")
from app.indicators import TechnicalIndicatorEngine  # noqa: E402

eng = TechnicalIndicatorEngine()
r_all = eng.calculate_all_indicators(up.copy())
check(np.isclose(r_all['rsi14'].iloc[-1], 100.0), f"calculate_all_indicators 单调上涨→{r_all['rsi14'].iloc[-1]:.1f}")
r_all_f = eng.calculate_all_indicators(flat.copy())
check(np.isclose(r_all_f['rsi14'].iloc[-1], 50.0), f"calculate_all_indicators 全平盘→{r_all_f['rsi14'].iloc[-1]:.1f}")
r_rsi = eng.calculate_rsi(up.copy(), period=14)
check(np.isclose(r_rsi['rsi14'].iloc[-1], 100.0), f"calculate_rsi 单调上涨→{r_rsi['rsi14'].iloc[-1]:.1f}")
r_rsi_f = eng.calculate_rsi(flat.copy(), period=14)
check(np.isclose(r_rsi_f['rsi14'].iloc[-1], 50.0), f"calculate_rsi 全平盘→{r_rsi_f['rsi14'].iloc[-1]:.1f}")

print("== 双实现一致性（正常波动序列）==")
rng = np.random.default_rng(3)
vol = 100 + np.cumsum(rng.normal(0, 1, 120))
dfv = mk_df(vol)
a = eng.calculate_all_indicators(dfv.copy())
b = eng.calculate_rsi(dfv.copy(), period=14)
check(bool(np.allclose(a['rsi14'], b['rsi14'], atol=1e-9)), "两实现 rsi14 逐位一致")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
