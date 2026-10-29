"""553-C：同花顺 time/realhead 兜底解析测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest  # noqa: E402

from app.data import ths_provider as ths  # noqa: E402

_TIME_SAMPLE = (
    'quotebridge_v6_time_hs_000001_last({"hs_000001":{"name":"平安银行",'
    '"pre":"11.31","date":"20261029",'
    '"data":"0930,11.30,10292040,11.300,910800;0931,11.33,29726486,11.316,2625650"}});'
)
_SNAP_SAMPLE = (
    'quotebridge_v6_realhead_hs_000001_defer_last({"items":{"10":"11.54","8":"11.55"}});'
)


def test_parse_intraday_minutes(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_SAMPLE)
    df = ths.fetch_intraday_minutes('000001.SZ', '2026-10-29')
    assert len(df) == 2
    assert list(df.columns) == ['trade_date', 'trade_time', 'open', 'high',
                                'low', 'close', 'volume', 'amount']
    assert df.iloc[0]['trade_time'] == '2026-10-29 09:30:00'
    assert df.iloc[0]['close'] == 11.30
    assert df.iloc[0]['volume'] == 910800.0
    assert df.iloc[0]['amount'] == 10292040.0


def test_intraday_date_mismatch_returns_empty(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_SAMPLE)
    assert ths.fetch_intraday_minutes('000001.SZ', '2026-10-28').empty


def test_intraday_http_failure_returns_empty(monkeypatch):
    def boom(url, timeout=8):
        raise OSError('network down')

    monkeypatch.setattr(ths, '_get', boom)
    assert ths.fetch_intraday_minutes('000001.SZ', '2026-10-29').empty


def test_parse_snapshot_raw(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _SNAP_SAMPLE)
    items = ths.fetch_snapshot_raw('000001.SZ')
    assert items.get('10') == '11.54'
