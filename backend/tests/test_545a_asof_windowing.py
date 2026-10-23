"""545号 A1~A3：as_of 历史重算的日期视窗不变量

1. 日期归一：YYYYMMDD / YYYY-MM-DD 都归一到 YYYY-MM-DD；
2. 行情/资金/指标切片不得包含 as_of 之后的行；
3. SIG 结果 trade_date 必须等于 as_of（而不是 MAX(daily_cache)）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd  # noqa: E402


def test_norm_asof_compat_formats():
    from app.services.signal_computation_service import SignalComputationService as S
    assert S._norm_asof('20261021') == '2026-10-21'
    assert S._norm_asof('2026-10-21') == '2026-10-21'
    assert S._norm_asof(None) is None
    assert S._norm_asof('') is None


def test_slice_as_of_excludes_future_rows():
    from app.services.signal_computation_service import SignalComputationService as S
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'] * 3,
        'trade_date': ['2026-10-20', '2026-10-21', '2026-10-22'],
        'close': [10.0, 11.0, 12.0],
    })
    out = S._slice_as_of(df, '2026-10-21')
    assert list(out['trade_date']) == ['2026-10-20', '2026-10-21']
    assert out['close'].iloc[-1] == 11.0


def test_dim1_helpers_slice_and_norm():
    from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine as D
    assert D._norm_asof('20261020') == '2026-10-20'
    df = pd.DataFrame({
        'trade_date': ['2026-10-19', '2026-10-20', '2026-10-21'],
        'close': [1.0, 2.0, 3.0],
    })
    assert list(D._slice_df(df, '2026-10-20')['close']) == [1.0, 2.0]
    # 无日期列 → 原样返回（indicator 子帧等）
    assert D._slice_df(pd.DataFrame({'ma5': [1.0]}), '2026-10-20') is not None


def test_sig_trade_date_uses_as_of():
    from app.engine.unified_core import UnifiedStrategyCore
    core = UnifiedStrategyCore()
    res = core._to_standardized('000001.SZ', [], 'long', None, as_of='20261021')
    assert res.trade_date == '2026-10-21'


def test_pre_feat_map_accepts_trade_date():
    import inspect
    import data_daemon as dd
    params = inspect.signature(dd._load_pre_feat_treemap_map).parameters
    assert 'trade_date' in params
