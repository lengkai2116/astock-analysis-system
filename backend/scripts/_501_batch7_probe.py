"""501号 批次7 探针——死代码/文档清理（#R53/#R54/#R62/#R63）

隔离验证（不发真实查询、不写库）：
  #R53  calculate_factor_combination 权重分母仅统计实际参与因子（含失败因子 → 权重归一正确）
  #R54  opportunity DIVIDEND_YIELD/EMOTION_EXTREME 设计态登记（源码断言）
  #R62  data_daemon _erp_percentile len<2 返回 None（源码断言）；CN_10Y_BOND_YIELD_PCT 单位=百分数（1.7）
  #R63  calculator 惰性日志参数化（源码断言）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


def _read(rel):
    return open(os.path.join(os.path.dirname(__file__), '..', rel),
                encoding='utf-8').read()


from app.factors import FactorCalculator  # noqa: E402
from app.factors.base import BaseFactor, FactorParam  # noqa: E402
from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT  # noqa: E402


# ══════════════ #R53：权重分母仅统计实际参与因子 ══════════════
class _MA(BaseFactor):
    name = "PROBE_MA"
    name_cn = "探针MA"
    category = "probe"
    required_columns = ["close"]
    params = [FactorParam("period", 5, "int", 1, 60, "周期")]

    def calculate(self, data):
        return data['close'].rolling(self.get_param('period')).mean()


_calc = FactorCalculator()
_calc._get_registry().register(_MA)

_df = pd.DataFrame({'close': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
                    'vol': [100] * 8})
# 两个因子：PROBE_MA（参与）+ PROBE_NONEXIST（失败，不在 columns）
_cfg53 = [
    {"name": "PROBE_MA", "params": {}, "weight": 0.5},
    {"name": "PROBE_NONEXIST", "params": {}, "weight": 0.5},
]
_out53 = _calc.calculate_factor_combination(_df, _cfg53)
# 全失败因子 weight=0.5 不计入分母 → 仅 PROBE_MA weight=0.5/0.5=1.0 倍自身
_exp = _MA().calculate(_df.copy())
_diff = (_out53.dropna() - _exp.reindex(_out53.index).dropna()).abs().max()
check(_diff < 1e-9,
      f"#R53 权重分母仅统计参与因子（失败因子不稀释；max_diff={_diff:.2e}）")

# 全失败 → 返回长度匹配的全 NaN 序列（原 pd.Series([], index) 在新版 pandas 抛
# Length mismatch；现在返回 NaN 序列避免误导性全 0）
_out53b = _calc.calculate_factor_combination(_df, [{"name": "PROBE_NONEXIST", "params": {}, "weight": 1.0}])
check(len(_out53b) == len(_df) and _out53b.isna().all(),
      f"#R53 全失败因子 → 长度匹配的全 NaN 序列（实际 len={len(_out53b)}）")

# ══════════════ #R54：设计态登记（源码断言） ══════════════
_src_opp = _read('app/factors/builtin/opportunity.py')
check('501 #R54 登记：设计态因子' in _src_opp,
      "#R54 DIVIDEND_YIELD 设计态登记")
check('TODO: 待改造后BOCIASI就绪' in _src_opp,
      "#R54 EMOTION_EXTREME TODO 标注")

# ══════════════ #R62：erp len<2 守卫 + 单位确认 ══════════════
_src_daemon = _read('data_daemon.py')
check('if len(erp_series) < 2:' in _src_daemon,
      "#R62 _erp_percentile len<2 返回 None 守卫")
check(CN_10Y_BOND_YIELD_PCT == float('1.7'),
      f"#R62 CN_10Y_BOND_YIELD_PCT 单位=百分数（1.7%，实际 {CN_10Y_BOND_YIELD_PCT}）")

# ══════════════ #R63：惰性日志参数化（源码断言） ══════════════
_src_calc = _read('app/factors/calculator.py')
check('logger.debug("factor_cache 命中: %s", factor_name)' in _src_calc,
      "#R63 calculator 惰性日志参数化（命中）")
check('logger.debug("factor_cache 读取失败(%s): %s", factor_name, e)' in _src_calc,
      "#R63 calculator 惰性日志参数化（读取失败）")

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
