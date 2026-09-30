"""500号 批次3 探针——DataManager 读口径（#2/#8/#9/#10/#11/#12/#57/#58）

桩验证（不依赖真实库/网络）：
  #2  日期归一（紧凑 YYYYMMDD → YYYY-MM-DD，分库与 ECM 同口径）
  #8  分库分支统一走 self._sharding_manager
  #9  分库读失败 → warning（可见）
  #10 复权零值/负值因子视为缺失；基准非零/非 NaN 守卫
  #11 行业排名按最新交易日聚合
  #12 sync_all_daily_data 按股票数计 max_stocks
  #57 分库读走 _query_shard（带列名，无硬编码列序假设）
  #58 daily_basic 重复路径归一日期 + 白名单列
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402
from app.data import DataManager  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── #2 日期归一（静态方法，免构造） ─────────────────────────────────────
print("=== #2 日期归一 ===")
check(DataManager._normalize_date('20260928') == '2026-09-28', "#2 '20260928'→'2026-09-28'")
check(DataManager._normalize_date('2026-09-28') == '2026-09-28', "#2 已归一格式不变")
check(DataManager._normalize_date(None) is None, "#2 None 透传")


def _mk_dm(cache, shard=None):
    dm = DataManager.__new__(DataManager)
    dm.cache = cache
    dm._sharding_manager = shard
    dm.tushare = None
    dm._source_mgr = None
    return dm


class _StubCache:
    def __init__(self, shard_df=None):
        self.shard_df = shard_df
        self.shard_calls = []

    def _query_shard(self, table, sql, params=None):
        self.shard_calls.append((table, sql, params))
        return self.shard_df

    def get_cached_daily(self, ts_code, start=None, end=None):
        return pd.DataFrame()


class _StubShard:
    def __init__(self, exists=True):
        self._exists = exists
        self.table_exists_calls = []

    def table_exists(self, t):
        self.table_exists_calls.append(t)
        return self._exists


# ── #8/#57：分库分支走 self._sharding_manager + _query_shard ────────────
print("=== #8/#57 分库读路径 ===")
_shard = _StubShard(exists=True)
_df = pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['2026-09-28'],
                    'open': [10.0], 'high': [11.0], 'low': [9.0], 'close': [10.5],
                    'vol': [100.0], 'amount': [1e6], 'pct_chg': [1.0], 'cached_at': ['x']})
_cache = _StubCache(shard_df=_df)
dm = _mk_dm(_cache, _shard)
out = dm.get_cached_daily_data('000001.SZ', start_date='20260901', end_date='20260930')
check(_shard.table_exists_calls == ['daily_cache'], "#8 使用注入的 self._sharding_manager 判表存在")
check(len(_cache.shard_calls) == 1, "#57 走 _query_shard（1 次）")
check(list(out.columns) == list(_df.columns), "#57 结果保留游标列名（无硬编码列序）")
check(_cache.shard_calls[0][2] == ['000001.SZ', '2026-09-01', '2026-09-30'], "#2 日期已归一后绑定")

# ── #9：分库读失败 → warning ────────────────────────────────────────────
print("=== #9 降级告警 ===")


class _BoomShard(_StubShard):
    def table_exists(self, t):
        raise RuntimeError("boom")


_records = []


class _Cap(logging.Handler):
    def emit(self, record):
        _records.append(record)


_lg = logging.getLogger('app.data')
_h = _Cap()
_lg.addHandler(_h)
_lg.setLevel(logging.WARNING)
dm9 = _mk_dm(_StubCache(), _BoomShard())
dm9.get_cached_daily_data('000001.SZ')
_lg.removeHandler(_h)
check(any(r.levelno >= logging.WARNING and 'daily_cache' in r.getMessage() for r in _records),
      "#9 分库读失败发出 warning（不再静默 debug）")

# ── #10 复权守卫 ────────────────────────────────────────────────────────
print("=== #10 复权零因子/基准守卫 ===")


class _AdjCache:
    def __init__(self, adj_df):
        self._adj = adj_df

    def get_cached_adj_factor(self, ts_code):
        return self._adj


dfp = pd.DataFrame({'ts_code': ['000001.SZ'] * 3, 'trade_date': ['2026-09-24', '2026-09-25', '2026-09-28'],
                    'open': [10.0] * 3, 'high': [11.0] * 3, 'low': [9.0] * 3,
                    'close': [10.5, 10.6, 10.7], 'vol': [100.0] * 3})

dm10 = _mk_dm(_AdjCache(pd.DataFrame({'trade_date': dfp['trade_date'], 'adj_factor': [1.0, 0.0, 2.0]})))
r = dm10._apply_adjust_factor(dfp.copy(), 'qfq')
check(not r.empty and r['close'].notna().all(), "#10 含 0 因子不产出 NaN")
check(bool((r[['open', 'high', 'low', 'close', 'vol']].abs() < 1e9).all().all()), "#10 无 inf 溢出")

dm10b = _mk_dm(_AdjCache(pd.DataFrame({'trade_date': dfp['trade_date'], 'adj_factor': [1.0, 1.0, 0.0]})))
rb = dm10b._apply_adjust_factor(dfp.copy(), 'qfq')
check(rb['close'].tolist() == dfp['close'].tolist(), "#10 基准为 0 → 回退未复权（原为 inf/NaN）")

# ── #11 行业排名按最新交易日 ────────────────────────────────────────────
print("=== #11 行业排名最新日 ===")
dm11 = DataManager.__new__(DataManager)
dm11.SUB_INDUSTRY_TO_CODE = {'行业A': '801010.SI', '行业B': '801010.SI', '行业C': '801020.SI'}


def _fake_idx(name):
    if name == '行业A':
        return pd.DataFrame({'trade_date': ['2026-09-28'], 'pct_chg': [5.0]})
    if name == '行业B':
        return pd.DataFrame({'trade_date': ['2026-09-25'], 'pct_chg': [9.0]})
    return pd.DataFrame({'trade_date': ['2026-09-28'], 'pct_chg': [1.0]})


dm11.get_industry_index_data = _fake_idx
rk = dm11.get_all_industry_rankings()
_by_code = {r['code']: r for r in rk}
check('801010.SI' in _by_code and _by_code['801010.SI']['pct'] == 5.0,
      "#11 同指数码取最新交易日者（A=5.0，非最后插入的 B=9.0）")

# ── #12 按股票数计 ──────────────────────────────────────────────────────
print("=== #12/#58 源码断言 ===")
_src12 = inspect.getsource(DataManager.sync_all_daily_data)
check('stock_done' in _src12 and 'stock_done >= max_stocks' in _src12,
      "#12 max_stocks 按股票数（stock_done）判定")
_src_all = inspect.getsource(DataManager)
check('_basic_cols' in _src_all, "#58 daily_basic 白名单列已引入")
check("pd.to_datetime(ds, format='%Y%m%d'" in _src_all, "#58 daily_basic trade_date 归一")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次3 探针全绿（#2/#8/#9/#10/#11/#12/#57/#58）")
