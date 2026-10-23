"""544-A：FCF 截面基准批量实现单元测试（假 cache，不触库）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd  # noqa: E402

from app.opportunity_atlas.fcf_percentile import build_fcf_percentile  # noqa: E402


class FakeCache:
    def __init__(self, mv_df, fcf_df, latest='2026-10-22'):
        self.mv_df = mv_df
        self.fcf_df = fcf_df
        self.latest = latest

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_basic_cache':
            if 'MAX(trade_date) AS d' in sql:
                return pd.DataFrame({'d': [self.latest]})
            return self.mv_df
        if table == 'daily_cache':
            return self.mv_df[['ts_code']].drop_duplicates()
        return self.fcf_df


def _cache(mv, fcf):
    return FakeCache(
        pd.DataFrame({'ts_code': list(mv), 'total_mv': list(mv.values())}),
        pd.DataFrame({'ts_code': list(fcf), 'free_cashflow': list(fcf.values())}),
    )


def test_batch_percentile_basic():
    cache = _cache({'A': 100.0, 'B': 200.0}, {'A': 10.0, 'B': 20.0})
    pct = build_fcf_percentile(cache, min_samples=2)
    assert pct is not None
    # A: 10/(100*1e4)*100 = 0.001; B: 20/(200*1e4)*100 = 0.001
    assert pct(0.001) == 0.0
    assert pct(0.002) == 1.0


def test_batch_percentile_distinct_values():
    cache = _cache({'A': 100.0, 'B': 200.0}, {'A': 10.0, 'B': 30.0})
    pct = build_fcf_percentile(cache, min_samples=2)
    # A=0.001, B=0.0015 → 中位数落在两者之间
    assert pct(0.00125) == 0.5


def test_codes_filter():
    cache = _cache({'A': 100.0, 'B': 200.0}, {'A': 10.0, 'B': 20.0})
    pct = build_fcf_percentile(cache, codes=['A'], min_samples=1)
    assert pct is not None
    assert pct(0.0) == 0.0 and pct(1.0) == 1.0


def test_empty_codes_returns_none():
    cache = _cache({'A': 100.0}, {'A': 10.0})
    assert build_fcf_percentile(cache, codes=[], min_samples=1) is None


def test_min_samples_and_invalid_values():
    cache = _cache(
        {'A': 0.0, 'B': 100.0, 'C': float('nan')},
        {'A': 10.0, 'B': 20.0, 'C': 30.0},
    )
    # 仅 B 有效
    pct = build_fcf_percentile(cache, min_samples=2)
    assert pct is None
    pct = build_fcf_percentile(cache, min_samples=1)
    assert pct is not None


def test_missing_fcf_excluded():
    cache = _cache({'A': 100.0, 'B': 200.0}, {'A': 10.0})
    pct = build_fcf_percentile(cache, min_samples=1)
    assert pct is not None
    assert pct(0.001) == 0.0
