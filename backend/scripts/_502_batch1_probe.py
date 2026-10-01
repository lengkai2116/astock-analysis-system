"""502号 批次1 探针：Q1 文档对齐（WILLR 文档修正 + MACD_HIST 2× 惯例确认）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

PASS = FAIL = 0
def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {msg}")
    else:
        FAIL += 1
        print(f"  ❌ {msg}")

from app.factors.builtin.a_stock import MACD_HIST
from app.factors.builtin.qlib158 import QLIB_MACD_HIST
from app.factors.builtin.reversal import WILLR

print("== #R41 WILLR 文档 ==")
check("WILLR" in WILLR.__name__, "WILLR 类存在")
check("-100" in WILLR.description and "0-100" not in WILLR.description,
      f"description 已改 -100..0: {WILLR.description!r}")
check("(-100)" in WILLR.formula, f"formula 与实现自洽: {WILLR.formula!r}")

print("== #R17 MACD_HIST 2× 惯例确认（零改动）==")
check("2 * (DIF - DEA)" in MACD_HIST.formula, f"a_stock MACD_HIST formula 保持 2×: {MACD_HIST.formula!r}")
check("2×(DIF - DEA)" in QLIB_MACD_HIST.description or "2 * (DIF - DEA)" in QLIB_MACD_HIST.formula,
      f"qlib158 QLIB_MACD_HIST 文档保持 2×: {QLIB_MACD_HIST.description!r}")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
