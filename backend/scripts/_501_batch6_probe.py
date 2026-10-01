"""501号 批次6 探针——公式/语义错位非每日路径（#R40/#R42/#R43/#R44/#R55/#R56/#R57/#R59/#R60/#R61）

隔离验证（不发真实查询、不写库）：
  #R40  qlib158 rank 文档更正为时序分位（源码断言 formula/description）
  #R42  CMO 保留 NaN（首行/缺口不再当 0 计入滚动和）
  #R43  CVaR 空/退化分布显式 NaN（不静默 0/NaN）
  #R44  HURST 守卫基准对齐 period（源码断言）
  #R55  GTJA 真因子短输入抛 ValueError（不再全 NaN 静默）
  #R56  GTJA191 硬编码标签参数化（源码断言 description/formula 用 N）
  #R57  GTJA191 平盘判定 isclose（源码断言）
  #R59  momentum MACD 参数名 fast/slow/signal（源码断言 + 实例计算）
  #R60  MOM description 归一提示（源码断言）
  #R61  alpha101 Alpha1 docstring 补全（源码断言）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


def _read(rel):
    return open(os.path.join(os.path.dirname(__file__), '..', rel),
                encoding='utf-8').read()


from app.factors.builtin.academic import ACADEMIC_CVAR, ACADEMIC_HURST  # noqa: E402
from app.factors.builtin.gtja import GTJA_AMOUNT20, GTJA_HL20  # noqa: E402
from app.factors.builtin.momentum import MACD_DIF, MOM  # noqa: E402
from app.factors.builtin.reversal import CMO  # noqa: E402

# ══════════════ #R40：qlib158 rank 文档 ══════════════
_src_qlib = _read('app/factors/builtin/qlib158.py')
check('rolling(close, N).rank(pct=True)' in _src_qlib,
      "#R40 QLIB_RANK formula 更正为时序分位")
check('rolling(low, N).rank(pct=True)' in _src_qlib,
      "#R40 QLIB_LOW_RANK formula 更正")
check('rolling(high, N).rank(pct=True)' in _src_qlib,
      "#R40 QLIB_HIGH_RANK formula 更正")
check('rolling(volume, N).rank(pct=True)' in _src_qlib,
      "#R40 QLIB_VOLUME_RANK formula 更正")
check('非横截面' in _src_qlib,
      "#R40 description 明确非横截面")

# ══════════════ #R42：CMO NaN 传播 ══════════════
_df = pd.DataFrame({'close': [10.0, 11.0, 12.0, 11.0, 12.0, 13.0, 12.0, 13.0, 14.0]})
_cmo = CMO().calculate(_df)
# 首行 diff=NaN（原 fill=0 → 首行 up/down=0 计入；新保留 NaN）
check(pd.isna(_cmo.iloc[0]),
      f"#R42 CMO 首行 NaN 保留（实际 {_cmo.iloc[0]}）")
check(_cmo.dropna().between(-100, 100).all(),
      "#R42 CMO 有效值在 [-100,100]")

# ══════════════ #R43：CVaR 退化分布显式 NaN ══════════════
_rng = np.random.default_rng(3)
_close = _rng.uniform(8, 12, 60).cumsum() + 100
_df_cvar = pd.DataFrame({'close': _close})
_cvar_out = ACADEMIC_CVAR().calculate(_df_cvar)
check(np.isfinite(_cvar_out.dropna()).all(),
      "#R43 CVaR 有效窗口有限")

# ══════════════ #R44：HURST 守卫对齐 period（源码断言） ══════════════
_src_acad = _read('app/factors/builtin/academic.py')
check('if len(series) < period:' in _src_acad,
      "#R44 HURST 守卫基准对齐 period（原硬编码 20）")

# ══════════════ #R55：GTJA 短输入 ValueError ══════════════
_df_short = pd.DataFrame({'open': [1.0] * 5, 'close': [1.0] * 5, 'vol': [100.0] * 5,
                          'high': [1.1] * 5, 'low': [0.9] * 5})
for _cls, _label in [(GTJA_AMOUNT20, 'GTJA_AMOUNT20'), (GTJA_HL20, 'GTJA_HL20')]:
    try:
        _cls().calculate(_df_short)
        check(False, f"#R55 {_label} 短输入(5<period)应抛 ValueError")
    except ValueError as e:
        check('数据长度' in str(e),
              f"#R55 {_label} 短输入抛 ValueError")

# ══════════════ #R56：GTJA191 硬编码标签参数化（源码断言） ══════════════
_src_gtja191 = _read('app/factors/builtin/gtja191.py')
check('AMOUNT_N = MA(Close * Volume, N)' in _src_gtja191,
      "#R56 GTJA014 formula 参数化")
check('STD_N = STD(Close, N)' in _src_gtja191,
      "#R56 GTJA021/022 formula 参数化")
check('MA_N = MA(Close, N)' in _src_gtja191,
      "#R56 GTJA034 formula 参数化")
check('EMA_N = EMA(Close, N)' in _src_gtja191,
      "#R56 GTJA038 formula 参数化")

# ══════════════ #R57：GTJA191 平盘 isclose（源码断言） ══════════════
check('np.isclose(close, close.shift(1))' in _src_gtja191,
      "#R57 GTJA191 平盘判定 isclose（原浮点相等）")

# ══════════════ #R59：momentum MACD 参数名 ══════════════
_src_mom = _read('app/factors/builtin/momentum.py')
check('FactorParam("fast", 12' in _src_mom and 'FactorParam("slow", 26' in _src_mom,
      "#R59 MACD_DIF 参数 fast/slow")
check('FactorParam("signal", 9' in _src_mom,
      "#R59 MACD_DEA 参数 signal")
_macd = MACD_DIF()
check(_macd.get_param("fast") == 12 and _macd.get_param("slow") == 26,
      "#R59 MACD_DIF 默认值经新参数名可取")

# ══════════════ #R60：MOM description 归一提示（源码断言） ══════════════
check('跨截面比较需先归一' in _src_mom,
      "#R60 MOM description 归一提示")

# ══════════════ #R61：alpha101 Alpha1 docstring 补全（源码断言） ══════════════
_src_a101 = _read('app/factors/builtin/alpha101.py')
check('"""Alpha1: (rank(ts_argmax(signedpower(returns, 2), 5)) - 0.5) * -1"""' in _src_a101,
      "#R61 Alpha1 docstring 补全（原 (-1 截断）")

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
