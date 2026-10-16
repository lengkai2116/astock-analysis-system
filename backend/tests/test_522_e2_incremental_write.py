"""522号 E2：`_batch_cache_factor_series` 增量写（只写最新交易日）验证。

背景：原实现每日把每只股票每个因子的**整条历史序列**逐行重写（RAW-3 每日写
`factor_cache` ≈6670 万行）。E2 只写「该股 data 最新交易日」的行；全史仍保留。

覆盖：① 3 日序列 → 只产出最后一日记录；② 紧凑日期（YYYYMMDD）末行亦能取对 cutoff；
③ 最新日为 NaN → 不写；④ 单日 data → 正常写入。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from app.data.factor_precompute import FactorPrecomputeManager  # noqa: E402


class _CaptureCM:
    def __init__(self):
        self.records = []

    def cache_factor_data(self, records):
        self.records.extend(records)


def _fpm():
    fpm = FactorPrecomputeManager.__new__(FactorPrecomputeManager)
    fpm.cache_manager = _CaptureCM()
    return fpm


def test_only_latest_trade_date_written():
    fpm = _fpm()
    df = pd.DataFrame({'trade_date': ['2026-10-13', '2026-10-14', '2026-10-15']})
    series = pd.Series([1.0, 2.0, 3.0])          # 位置索引 0/1/2
    fpm._batch_cache_factor_series(series, 'X', 'F', df)
    assert [r['trade_date'] for r in fpm.cache_manager.records] == ['2026-10-15']
    assert fpm.cache_manager.records[0]['value'] == 3.0


def test_cutoff_from_compact_last_row():
    fpm = _fpm()
    df = pd.DataFrame({'trade_date': ['20261013', '20261015']})
    series = pd.Series([1.0, 2.0])
    fpm._batch_cache_factor_series(series, 'X', 'F', df)
    assert [r['trade_date'] for r in fpm.cache_manager.records] == ['2026-10-15']


def test_nan_latest_writes_nothing():
    fpm = _fpm()
    df = pd.DataFrame({'trade_date': ['2026-10-14', '2026-10-15']})
    series = pd.Series([1.0, float('nan')])
    fpm._batch_cache_factor_series(series, 'X', 'F', df)
    assert fpm.cache_manager.records == []


def test_single_day_written():
    fpm = _fpm()
    df = pd.DataFrame({'trade_date': ['2026-10-15']})
    series = pd.Series([9.0])
    fpm._batch_cache_factor_series(series, 'X', 'F', df)
    assert [r['trade_date'] for r in fpm.cache_manager.records] == ['2026-10-15']
