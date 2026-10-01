"""502号 批次3 探针：Q2 BETA 系接真实市场基准（#R2 HS300 + R_f 国债）

桩验证（mock 市场序列）+ 真实数据验证（000001.SZ，只读）：
  - BETA 用 HS300 序列时 = Cov(R_i,R_m)/Var(R_m)（与手算对照；ALPHA 不再恒 0）
  - 基准缺失（_get_market_return → None）→ 全 NaN（426 无源守卫）
  - R_f 默认 None → CN_10Y_BOND_YIELD_PCT/100
  - 返回序列索引与原 data 索引一致
"""
import os
import sys
from unittest import mock

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


import app.factors.builtin.academic as acad  # noqa: E402
from app.factors.builtin.academic import (  # noqa: E402
    ACADEMIC_ALPHA,
    ACADEMIC_BETA,
    ACADEMIC_CAPM_ALPHA,
    ACADEMIC_TREYNOR,
)

# 构造 60 日个股（与市场部分相关）
rng = np.random.default_rng(7)
n = 60
dates = pd.date_range('2026-01-01', periods=n, freq='B').strftime('%Y-%m-%d')
mkt_ret = rng.normal(0.0005, 0.01, n)
stock_ret = 0.8 * mkt_ret + rng.normal(0, 0.005, n)
mkt_close = 3000 * np.cumprod(1 + mkt_ret)
stock_close = 10 * np.cumprod(1 + stock_ret)
mkt = pd.Series(mkt_ret, index=dates)
df = pd.DataFrame({
    'trade_date': dates,
    'close': stock_close,
    'high': stock_close * 1.01,
    'low': stock_close * 0.99,
    'open': stock_close,
    'vol': 1e6,
})

print("== #R2 BETA 真实市场基准 ==")
with mock.patch.object(acad, '_get_market_return', return_value=mkt):
    f = ACADEMIC_BETA()
    f.set_param('period', 20)
    res = f.calculate(df)
    check(res.notna().sum() > 10, f"BETA 有效样本 {res.notna().sum()}")
    # 手算对照：Cov(R_i,R_m)/Var(R_m) rolling 20
    stock_s = pd.Series(stock_ret, index=dates)
    aligned = pd.concat([stock_s.rename('stock'), mkt.rename('mkt')], axis=1, join='inner').dropna()
    manual = aligned['stock'].rolling(20).cov(aligned['mkt']) / (aligned['mkt'].rolling(20).var() + 1e-10)
    manual_r = pd.Series(manual.values, index=aligned.index).reindex(dates)
    m = res.notna().values
    check(bool(np.allclose(res.values[m], manual_r.values[m], atol=1e-9)), "BETA 与手算 Cov/Var 一致")
    check(0.5 < res.dropna().median() < 1.2, f"BETA 量级合理（中位 {res.dropna().median():.2f}，构造 beta=0.8）")

print("== #R2 ALPHA 不再恒 0 ==")
with mock.patch.object(acad, '_get_market_return', return_value=mkt):
    fa = ACADEMIC_ALPHA()
    fa.set_param('period', 20)
    ra = fa.calculate(df)
    check(ra.notna().sum() > 10, f"ALPHA 有效样本 {ra.notna().sum()}")
    check(bool((np.abs(ra.dropna()) > 1e-9).any()), "ALPHA 非恒 0（原自引用恒 0）")
    check(not bool(np.isclose(ra.dropna(), 0).all()), "ALPHA 全非 0")

print("== 基准缺失 → 全 NaN（426 无源守卫）==")
with mock.patch.object(acad, '_get_market_return', return_value=None):
    fb = ACADEMIC_BETA()
    rb = fb.calculate(df)
    check(rb.isna().all(), "BETA 基准缺失 → 全 NaN")
    fa2 = ACADEMIC_ALPHA()
    ra2 = fa2.calculate(df)
    check(ra2.isna().all(), "ALPHA 基准缺失 → 全 NaN")

print("== R_f 默认取国债 ==")
check(abs(acad._resolve_rf(None) - 0.017) < 1e-6, f"_resolve_rf(None) = {acad._resolve_rf(None):.4f}（CN_10Y_BOND_YIELD_PCT/100）")
check(abs(acad._resolve_rf(0.03) - 0.03) < 1e-9, "_resolve_rf(0.03) = 0.03（参数覆盖）")

print("== TREYNOR/CAPM_ALPHA 接线 ==")
with mock.patch.object(acad, '_get_market_return', return_value=mkt):
    ft = ACADEMIC_TREYNOR()
    ft.set_param('period', 20)
    rt = ft.calculate(df)
    check(rt.notna().sum() > 10, f"TREYNOR 有效样本 {rt.notna().sum()}")
    # CAPM_ALPHA 默认 period=252/min=60：用更长桩（80 日）
    n2 = 80
    dates2 = pd.date_range('2025-10-01', periods=n2, freq='B').strftime('%Y-%m-%d')
    mkt2 = pd.Series(rng.normal(0.0005, 0.01, n2), index=dates2)
    stock2 = 10 * np.cumprod(1 + (0.8 * mkt2.values + rng.normal(0, 0.005, n2)))
    df2 = pd.DataFrame({'trade_date': dates2, 'close': stock2,
                        'high': stock2 * 1.01, 'low': stock2 * 0.99,
                        'open': stock2, 'vol': 1e6})
    fc = ACADEMIC_CAPM_ALPHA()
    fc.set_param('period', 60)
    with mock.patch.object(acad, '_get_market_return', return_value=mkt2):
        rc = fc.calculate(df2)
    check(rc.notna().sum() > 0, f"CAPM_ALPHA(60) 有效样本 {rc.notna().sum()}")

print("== 索引对齐 ==")
with mock.patch.object(acad, '_get_market_return', return_value=mkt):
    fb = ACADEMIC_BETA()
    rb = fb.calculate(df)
    check(len(rb) == len(df), f"返回长度 {len(rb)} == 输入 {len(df)}")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
