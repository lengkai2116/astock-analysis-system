"""501号 批次3 探针——calculator/缓存契约（#R29/#R31/#R32/#R33/#R34/#R35/#R36/#R37）

隔离/桩验证（不发真实查询、不写库）：
  #R29  FactorCalculator 惰性取注册表（__init__ 不急切；_get_registry 首次现取）
  #R31  _batch_cache_factor_series 非数值值跳过（不毁整批）
  #R33  clear_cache 结果日志
  #R34  位置索引映射防御（序列长度≠data 行数告警）
  #R35  calculate_multiple_factors 重复因子名 warning
  #R36  因子返回序列异索引 → reindex 对齐 + warning
  #R37  calculate_single_factor 入口统一 copy（调用方 data 不被 mutate）
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture(logger_name):
    lg = logging.getLogger(logger_name)
    cap = _Cap()
    lg.addHandler(cap)
    lg.setLevel(logging.WARNING)
    return lg, cap


from app.data.factor_precompute import FactorPrecomputeManager  # noqa: E402
from app.factors import FactorCalculator  # noqa: E402
from app.factors.base import BaseFactor, FactorParam  # noqa: E402


# ══════════════ 桩因子 ══════════════
class _MA(BaseFactor):
    name = "PROBE_MA"
    name_cn = "探针MA"
    category = "probe"
    required_columns = ["close"]
    params = [FactorParam("period", 5, "int", 1, 60, "周期")]

    def calculate(self, data):
        return data['close'].rolling(self.get_param('period')).mean()


class _MUT(BaseFactor):
    """就地 mutate data 的坏因子（验证 #R37 copy 保护）"""
    name = "PROBE_MUT"
    name_cn = "探针MUT"
    category = "probe"
    required_columns = ["close"]

    def calculate(self, data):
        data['close'] = data['close'] * 1000  # 就地改调用方
        return data['close']


# ══════════════ #R35/#R36/#R37：FactorCalculator ══════════════
_calc = FactorCalculator()
# 注入桩因子
_calc._get_registry().register(_MA)
_calc._get_registry().register(_MUT)

_df = pd.DataFrame({
    'close': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    'vol': [100] * 8,
})
_df_orig = _df.copy()

# #R37：入口统一 copy——坏因子 mutate 调用方 data 后原 df 不受影响
_out_mut = _calc.calculate_single_factor(_df, "PROBE_MUT")
check(_df['close'].iloc[0] == 1.0,
      f"#R37 calculate_single_factor 统一 copy：调用方 data 未被 mutate（实际 {_df['close'].iloc[0]}）")
check(_out_mut.iloc[0] == 1000.0,
      f"#R37 返回值含 mutate 结果（实际 {_out_mut.iloc[0]}）")

# #R35：重复因子名 warning
_lg35, _cap35 = _capture('app.factors.calculator')
_cfg35 = [
    {"name": "PROBE_MA", "params": {"period": 5}},
    {"name": "PROBE_MA", "params": {"period": 3}},   # 重复名
]
_out35 = _calc.calculate_multiple_factors(_df, _cfg35)
check("PROBE_MA" in _out35.columns,
      f"#R35 结果含 PROBE_MA（实际 {list(_out35.columns)}）")
check(any('因子名重复' in r.getMessage() for r in _cap35.records),
      "#R35 重复因子名已记 warning")
_lg35.removeHandler(_cap35)

# #R36：异索引 reindex 对齐 + warning
_lg36, _cap36 = _capture('app.factors.calculator')


class _IdxShift(BaseFactor):
    """返回重排/偏移索引的因子"""
    name = "PROBE_IDXSHIFT"
    name_cn = "探针IDX"
    category = "probe"
    required_columns = ["close"]

    def calculate(self, data):
        s = data['close'].copy()
        s.index = range(100, 100 + len(s))  # 与 data.index 不同
        return s


_calc._get_registry().register(_IdxShift)
_out36 = _calc.calculate_multiple_factors(
    _df, [{"name": "PROBE_IDXSHIFT", "params": {}}])
check(any('索引与 data 不一致' in r.getMessage() for r in _cap36.records),
      "#R36 异索引已记 warning")
check(_out36['PROBE_IDXSHIFT'].isna().all(),
      "#R36 异索引 reindex 后全 NaN（对齐失败可见而非静默）")
_lg36.removeHandler(_cap36)

# ══════════════ #R29：惰性注册 ══════════════
check(not hasattr(_calc, '_get_registry') or callable(_calc._get_registry),
      "#R29 _get_registry 存在")
_reg1 = _calc._get_registry()
_reg2 = _calc._get_registry()
check(_reg1 is _reg2, "#R29 _get_registry 两次取同一注册表（缓存于实例）")

# ══════════════ #R31/#R33/#R34：FactorPrecomputeManager ══════════════
class _StubECM:
    """记录 _exec_shard/_query_shard 调用的桩"""
    def __init__(self):
        self.exec_calls = []
        self.factor_rows = []

    def _exec_shard(self, table, sql, params=None):
        self.exec_calls.append((table, sql, params))

    def cache_factor_data(self, records):
        self.factor_rows.extend(records)


_ecm = _StubECM()
_pm = FactorPrecomputeManager(_ecm)


class _StrVal(BaseFactor):
    """返回含字符串哨兵值的因子"""
    name = "PROBE_STRVAL"
    name_cn = "探针STR"
    category = "probe"
    required_columns = ["close"]

    def calculate(self, data):
        s = data['close'].astype(object).copy()  # object dtype 允许字符串哨兵
        s.iloc[2] = "OOV"  # 非数值
        return s


# #R31：非数值跳过不毁整批
_pm.registry.register(_StrVal)
_lg31, _cap31 = _capture('app.data.factor_precompute')
_data31 = pd.DataFrame({'close': [1.0, 2.0, 3.0, 4.0],
                        'trade_date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04']})
_ok31 = _pm.precompute_factor('T01.SZ', _data31, 'PROBE_STRVAL')
check(_ok31, "#R31 非数值行不毁整批（precompute 返回 True）")
check(len(_ecm.factor_rows) == 3,
      f"#R31 有效 3 行入库（实际 {len(_ecm.factor_rows)}）")
check(any('非数值' in r.getMessage() for r in _cap31.records),
      "#R31 非数值行已记 warning")
_lg31.removeHandler(_cap31)

# #R34：长度不一致告警
_lg34, _cap34 = _capture('app.data.factor_precompute')
_data34 = pd.DataFrame({'close': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                        'trade_date': ['2026-01-01', '2026-01-02', '2026-01-03',
                                       '2026-01-04', '2026-01-05', '2026-01-06']})


class _Short(BaseFactor):
    name = "PROBE_SHORT"
    name_cn = "探针S"
    category = "probe"
    required_columns = ["close"]

    def calculate(self, data):
        return data['close'].head(3)  # 截断 → 长度 ≠ data


_pm.registry.register(_Short)
_pm.precompute_factor('T01.SZ', _data34, 'PROBE_SHORT')
check(any('长度' in r.getMessage() and '≠' in r.getMessage() for r in _cap34.records),
      "#R34 长度不一致已记 warning")
_lg34.removeHandler(_cap34)

# #R33：clear_cache 结果日志（用 INFO——clear_cache 记 logger.info）
_lg33, _cap33 = _capture('app.data.factor_precompute')
_lg33.setLevel(logging.INFO)
_cap33.setLevel(logging.INFO)
_pm.clear_cache('T01.SZ', 'PROBE_MA')
check(len(_ecm.exec_calls) == 1 and 'DELETE' in _ecm.exec_calls[0][1],
      f"#R33 clear_cache 走 _exec_shard DELETE（实际 {_ecm.exec_calls}）")
check(any('清除 factor_cache' in r.getMessage() for r in _cap33.records),
      "#R33 clear_cache 已记结果日志")
_lg33.removeHandler(_cap33)

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
