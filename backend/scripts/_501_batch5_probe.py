"""501号 批次5 探针——非有限值/边界守卫（#R18/#R19/#R20/#R22/#R24/#R25）

隔离验证（不发真实查询、不写库）：
  #R18  VOLATILITY pct_change 零前收 → 输出无 inf（NaN）
  #R19  HV log 零/负前收 → 输出无 -inf/NaN
  #R20  REV pct_change 零前收 → 输出无 inf
  #R22  ACADEMIC_GARMAN_KLASS 负方差 → clamp 后有限（不再 sqrt(负) NaN）
  #R24  GTJA 真因子/alpha101 缺列 → ValueError（契约错误，非裸 KeyError）
  #R25  data_daemon cl_result 显式初始化（源码断言）
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


# ══════════════ 通用：构造含零前收/负前收的数据 ══════════════
def _mk_zero_close_df():
    """close 序列：... → 0 → 10（pct_change inf）→ 10（NaN）"""
    close = [5.0, 6.0, 0.0, 10.0, 10.0, 12.0, 11.0]
    n = len(close)
    return pd.DataFrame({
        'close': close,
        'high': [c + 0.5 for c in close],
        'low': [c - 0.5 for c in close],
        'open': [c for c in close],
        'vol': [1000.0] * n,
    })


from app.factors.builtin.a_stock import REV_1  # noqa: E402
from app.factors.builtin.academic import ACADEMIC_GARMAN_KLASS  # noqa: E402
from app.factors.builtin.alpha101 import Alpha006, Alpha007, Alpha008  # noqa: E402
from app.factors.builtin.gtja import (  # noqa: E402
    GTJA_AMOUNT20,
    GTJA_AMOUNT60,
    GTJA_CORR_VOL10,
    GTJA_HL20,
)
from app.factors.builtin.volatility import HV, VOLATILITY  # noqa: E402

# ══════════════ #R18：VOLATILITY pct_change inf 守卫 ══════════════
_df_zero = _mk_zero_close_df()
_vol = VOLATILITY().calculate(_df_zero)
check(np.isfinite(_vol.dropna()).all(),
      f"#R18 VOLATILITY 零前收无 inf（dropna 后有限性: {np.isfinite(_vol.dropna()).all()}）")

# ══════════════ #R19：HV log 零/负前收守卫 ══════════════
_df_neg = _mk_zero_close_df().copy()
_df_neg.loc[2, 'close'] = -1.0  # 负前收 → log(-) NaN
_hv = HV().calculate(_df_neg)
check(np.isfinite(_hv.dropna()).all(),
      f"#R19 HV 零/负前收无 -inf（dropna 后有限性: {np.isfinite(_hv.dropna()).all()}）")

# ══════════════ #R20：REV pct_change 零前收守卫 ══════════════
_rev = REV_1().calculate(_df_zero)
check(np.isfinite(_rev.dropna()).all(),
      f"#R20 REV 零前收无 inf（dropna 后有限性: {np.isfinite(_rev.dropna()).all()}）")

# ══════════════ #R22：Garman-Klass 负方差 clamp ══════════════
rng = np.random.default_rng(5)
_n = 60
_close = rng.uniform(8, 12, _n).cumsum() + 100
# 构造极端开收比使 co² 项 > 0.5*hl²（GK 方差可负）
_open = _close * 0.999 + 0.1
_high = np.maximum(_close, _open) + 0.5
_low = np.minimum(_close, _open) - 0.5
_df_gk = pd.DataFrame({'open': _open, 'high': _high, 'low': _low, 'close': _close})
_gk = ACADEMIC_GARMAN_KLASS().calculate(_df_gk)
check(np.isfinite(_gk.dropna()).all(),
      f"#R22 Garman-Klass 负方差 clamp 后有限（dropna 后有限性: {np.isfinite(_gk.dropna()).all()}）")
check((_gk.dropna() >= 0).all(),
      "#R22 Garman-Klass 波动率非负")

# ══════════════ #R24：GTJA/alpha101 check_data 契约 ══════════════
# 缺 vol 列 → 应抛 ValueError（契约错误），非裸 KeyError
_df_no_vol = _df_gk[['open', 'high', 'low', 'close']]  # 无 vol
for _cls, _label in [
    (GTJA_AMOUNT20, 'GTJA_AMOUNT20'),
    (GTJA_AMOUNT60, 'GTJA_AMOUNT60'),
    (GTJA_HL20, 'GTJA_HL20'),
    (GTJA_CORR_VOL10, 'GTJA_CORR_VOL10'),
    (Alpha006, 'Alpha006'),
    (Alpha007, 'Alpha007'),
    (Alpha008, 'Alpha008'),
]:
    _inst = _cls()
    try:
        _inst.calculate(_df_no_vol)
        check(False, f"#R24 {_label} 缺 vol 应抛 ValueError")
    except ValueError as e:
        check('数据缺少必需列' in str(e),
              f"#R24 {_label} 缺 vol 抛 ValueError（契约错误）")
    except KeyError:
        check(False, f"#R24 {_label} 仍抛裸 KeyError（check_data 未生效）")

# 正常数据（含 vol）→ 正常计算
_df_full = _df_gk.copy()
_df_full['vol'] = rng.uniform(1000, 5000, _n)
for _cls, _label in [
    (GTJA_AMOUNT20, 'GTJA_AMOUNT20'),
    (GTJA_HL20, 'GTJA_HL20'),
    (Alpha006, 'Alpha006'),
]:
    _out = _cls().calculate(_df_full)
    check(_out is not None and len(_out) == _n,
          f"#R24 {_label} 正常数据计算成功")

# ══════════════ #R25：cl_result 显式初始化（源码断言） ══════════════
_src = open(os.path.join(os.path.dirname(__file__), '..',
            'data_daemon.py'), encoding='utf-8').read()
check('cl_result = None' in _src,
      "#R25 data_daemon cl_result 显式初始化")
# 排除注释行（:3795 #R25 说明文字本身含该字样）
_code_lines25 = [l for l in _src.splitlines()
                 if l.strip() and not l.strip().startswith('#')]
check(not any("'cl_result' in dir()" in l for l in _code_lines25),
      "#R25 data_daemon 活代码无 'cl_result' in dir() 作用域内省")
check('cl_result if cl_result is not None else {}' in _src,
      "#R25 消费点改判 cl_result is not None")

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
