"""500号 批次1 探针——预计算/因子正确性（A#3 + B#36~#49）

隔离/桩验证（不发真实查询、不写库）：
  A#3/#36/#37/#38  compute_win_rates 真多周期 + 批量取价（消除 N+1）+ 双侧守卫 + Sharpe 实算
  #41/#42/#43      _batch_cache_factor_series 日期映射（脏键跳过 / 归一 / 死分支已删）
  #45              precompute_all_factors 冗余 try 已移除
  #46              get_cached_factors 外连接（异构索引不再抛错）
  #47              get_cache_stats 空结果告警（源码断言）
  #48/#49          market_universe 399 注释 + 占位符/参数一致
"""
import os
import sys
import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


from app.data.precompute_indicator_manager import PrecomputeIndicatorManager  # noqa: E402
from app.data.factor_precompute import FactorPrecomputeManager  # noqa: E402

# ── 桩 ECM：为 compute_win_rates 提供确定性数据 ─────────────────────────
_DATES = [f"2026-01-{d:02d}" for d in range(1, 31)]   # 30 个“交易日”
_ENTRY = "2026-01-01"
_C5, _C10, _C20 = "2026-01-06", "2026-01-11", "2026-01-21"
_CODES = [f"T{i:02d}.SZ" for i in range(1, 6)]        # 5 只 → 5 样本


class _StubECM:
    """确定性桩：5 只股票 entry=100；+5d 全盈（离散）/+10d 持平/+20d 全亏（离散）

    +5d: [110,108,112,105,115] → win_rate_5d=1.0, avg=0.10, std>0（Sharpe≠0）
    +10d:[100,100,100,100,100]→ win_rate_10d=0.0（ret=0 不算赢）, avg=0
    +20d:[80,90,85,95,75]     → win_rate_20d=0.0, avg=-0.15, std>0（Sharpe≠0）
    """
    _P5 = [110.0, 108.0, 112.0, 105.0, 115.0]
    _P10 = [100.0, 100.0, 100.0, 100.0, 100.0]
    _P20 = [80.0, 90.0, 85.0, 95.0, 75.0]

    def __init__(self):
        self.calls = 0

    def _query_shard(self, table, sql, params=None):
        self.calls += 1
        if "strategy_signal_detail" in sql:
            import json
            rows = [{'ts_code': c, 'trade_date': _ENTRY,
                     'signal_json': json.dumps({'signals': {'S1': {'signal': 'BUY'}}})}
                    for c in _CODES]
            return pd.DataFrame(rows)
        if "DISTINCT trade_date" in sql:
            return pd.DataFrame({'trade_date': _DATES})
        if "close" in sql:
            rows = []
            for i, c in enumerate(_CODES):
                rows += [
                    {'ts_code': c, 'trade_date': _ENTRY, 'close': 100.0},
                    {'ts_code': c, 'trade_date': _C5, 'close': self._P5[i]},
                    {'ts_code': c, 'trade_date': _C10, 'close': self._P10[i]},
                    {'ts_code': c, 'trade_date': _C20, 'close': self._P20[i]},
                ]
            return pd.DataFrame(rows)
        return pd.DataFrame()


print("=== A#3/#36/#37/#38 compute_win_rates ===")
stub = _StubECM()
mgr = PrecomputeIndicatorManager(stub)
df = mgr.compute_win_rates()
check(not df.empty, "有结果")
if not df.empty:
    r = df.iloc[0]
    # A#3：三窗口独立实算 → 取值不同（旧实现 5d==10d==20d）
    check(r['win_rate_5d'] == 1.0, f"win_rate_5d=1.0（实={r['win_rate_5d']}）")
    check(r['win_rate_10d'] == 0.0, f"win_rate_10d=0.0（实={r['win_rate_10d']}）")
    check(r['win_rate_20d'] == 0.0, f"win_rate_20d=0.0（实={r['win_rate_20d']}）")
    check(r['win_rate_5d'] != r['win_rate_10d'], "5d≠10d（真多周期，非恒等）")
    check(abs(r['avg_return_5d'] - 0.10) < 1e-9, f"avg_return_5d=0.10（实={r['avg_return_5d']}）")
    check(abs(r['avg_return_20d'] - (-0.15)) < 1e-9, f"avg_return_20d=-0.15（实={r['avg_return_20d']}）")
    # #38：Sharpe 不再恒 0（n≥5 且 std>0）
    check(r['sharpe_5d'] != 0.0, f"sharpe_5d 实算非 0（实={r['sharpe_5d']}）")
    check(r['sharpe_20d'] != 0.0, f"sharpe_20d 实算非 0（实={r['sharpe_20d']}）")
    check(r['samples'] == 5, f"samples=5（实={r['samples']}）")
# #36：查询次数应为常数级（signal+dates+close≈3），而非 O(信号数≈10+）
check(stub.calls <= 6, f"#36 查询次数={stub.calls} ≤ 6（消除 N+1）")

# #37：exit_price 为 NaN 时不得抛错
print("=== #37 exit_price NaN 守卫 ===")


class _NaNECM(_StubECM):
    def _query_shard(self, table, sql, params=None):
        d = super()._query_shard(table, sql, params)
        if "close" in sql and not d.empty:
            d.loc[d['trade_date'] == _C5, 'close'] = float('nan')
        return d


try:
    _d = PrecomputeIndicatorManager(_NaNECM()).compute_win_rates()
    check(True, f"NaN 退出价不抛错（结果 {0 if _d.empty else len(_d)} 行）")
except Exception as e:
    check(False, f"NaN 退出价抛错: {e}")

# ── #41/#42/#43 _batch_cache_factor_series ──────────────────────────────
print("=== #41/#42/#43 因子日期映射 ===")


class _Cap:
    def __init__(self):
        self.records = []

    def cache_factor_data(self, records):
        self.records.extend(records)


fp = FactorPrecomputeManager.__new__(FactorPrecomputeManager)
cap = _Cap()
fp.cache_manager = cap
data = pd.DataFrame({'trade_date': ['2026-09-28', '2026-09-29']})

# 位置索引 0/1 → 取 data 日期
s = pd.Series([1.0, 2.0], index=[0, 1])
fp._batch_cache_factor_series(s, 'T1', 'MA_5', data)
check([r['trade_date'] for r in cap.records] == ['2026-09-28', '2026-09-29'], "#41 位置索引映射到 data 日期")

# 位置索引越界（无 data）→ 跳过（不得写 "0"）
cap.records = []
s2 = pd.Series([1.0, 2.0], index=[0, 1])
fp._batch_cache_factor_series(s2, 'T1', 'MA_5', None)
check(cap.records == [], "#41 越界整数索引被跳过（不写 \"0\"/\"1\" 脏键，不写 1970-01-01）")

# 紧凑日期串 → 归一
cap.records = []
s3 = pd.Series([1.0], index=['20260929'])
fp._batch_cache_factor_series(s3, 'T1', 'MA_5', None)
check([r['trade_date'] for r in cap.records] == ['2026-09-29'], "#43 '20260929' → '2026-09-29'")

# Timestamp 索引 → 归一
cap.records = []
s4 = pd.Series([1.0], index=[pd.Timestamp('2026-09-29')])
fp._batch_cache_factor_series(s4, 'T1', 'MA_5', None)
check([r['trade_date'] for r in cap.records] == ['2026-09-29'], "#43 Timestamp 归一")

# 非法串 → 跳过
cap.records = []
s5 = pd.Series([1.0], index=['not_a_date'])
fp._batch_cache_factor_series(s5, 'T1', 'MA_5', None)
check(cap.records == [], "#43 非法日期被跳过")

# #42：源码不含重复的 pd.Timestamp 死分支
_src = inspect.getsource(FactorPrecomputeManager._batch_cache_factor_series)
check(_src.count("isinstance(idx, pd.Timestamp)") == 0 and "elif isinstance(idx, (datetime, pd.Timestamp, str))" in _src,
      "#42 死分支已删/归一")

# ── #45 precompute_all_factors 无冗余 try ───────────────────────────────
print("=== #45/#47 源码断言 ===")
_src45 = inspect.getsource(FactorPrecomputeManager.precompute_all_factors)
check('except Exception' not in _src45, "#45 precompute_all_factors 无冗余 try/except")
_src47 = inspect.getsource(FactorPrecomputeManager.get_cache_stats)
check('logger.warning' in _src47, "#47 get_cache_stats 空结果记 warning")

# ── #46 get_cached_factors 外连接 ───────────────────────────────────────
print("=== #46 get_cached_factors 外连接 ===")


class _Hetero:
    def get_cached_factor(self, ts_code, name):
        if name == 'A':
            return pd.Series([1.0, 2.0], index=['2026-09-28', '2026-09-29'])
        if name == 'B':
            return pd.Series([3.0], index=['2026-09-30'])   # 不同索引
        return None


fp2 = FactorPrecomputeManager.__new__(FactorPrecomputeManager)
fp2.cache_manager = _Hetero()
try:
    merged = fp2.get_cached_factors('T1', ['A', 'B'])
    check(list(merged.index) == ['2026-09-28', '2026-09-29', '2026-09-30'], f"#46 异构索引外连接（index={list(merged.index)}）")
    check(list(merged.columns) == ['A', 'B'], "#46 列为因子名")
except Exception as e:
    check(False, f"#46 抛错: {e}")

# ── #48/#49 market_universe ─────────────────────────────────────────────
print("=== #48/#49 market_universe ===")
from app.data.market_universe import stock_only_sql, is_index_code  # noqa: E402
sql, params = stock_only_sql('d')
check(sql.count('?') == len(params), f"#49 占位符数({sql.count('?')}) == 参数数({len(params)})")
check(is_index_code('399001.SZ'), "#48 399001.SZ 判为指数")
check(not is_index_code('000001.SZ'), "#48 平安银行 000001.SZ 判为非指数（后缀不可忽略）")
check(is_index_code('801010.SI'), "#48 申万 801010.SI 判为指数")
_srcmu = inspect.getsource(is_index_code)
check('500号#48' in _srcmu, "#48 399 规则注释已加")

# ── A#3 旧缺陷结构性确认：源码不再用单一 lookahead ──────────────────────
_srcwr = inspect.getsource(PrecomputeIndicatorManager.compute_win_rates)
check('_WIN_HORIZONS' in _srcwr and 'for h in self._WIN_HORIZONS' in _srcwr,
      "A#3 多窗口循环（非单一 lookahead）")
# 精确断言：签名不再有 lookahead 形参（docstring 中的说明性文字不计）
check('def compute_win_rates(self) ->' in _srcwr,
      "A#3 签名已移除旧 lookahead 形参")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次1 探针全绿（A#3 + #36~#49）")
