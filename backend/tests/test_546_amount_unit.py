"""546号 P1：市场地图实时 overlay 成交额统一为千元口径。

as_market_snapshot.amount 为元，treemap_snapshot.amount 为千元；
_merge_snapshot_with_realtime 必须换算后再写入，否则前端 ÷1e5 会放大 1000 倍。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
    os.environ.pop(_k, None)

import pytest
from app.routes.opportunity_atlas import _merge_snapshot_with_realtime


def test_amount_yuan_converted_to_thousand_yuan():
    items = [{
        'ts_code': '000001.SZ', 'price': 11.30, 'pct_change': -0.96,
        'amount': 1468424.72209, 'snapshot': False,
    }]
    rt = [{
        'ts_code': '000001.SZ', 'price': 11.20, 'change_pct': -0.88,
        'amount': 1161789918.21, 'cached_at': '2026-10-23 13:43:20',
    }]

    merged = _merge_snapshot_with_realtime(items, rt)

    assert merged[0]['amount'] == pytest.approx(1161789.91821)
    assert merged[0]['price'] == 11.20
    assert merged[0]['pct_change'] == -0.88
    assert merged[0]['snapshot'] is True


def test_ohlc_not_divided():
    items = [{'ts_code': '600519.SH', 'price': 0, 'amount': 0, 'snapshot': False}]
    rt = [{
        'ts_code': '600519.SH', 'price': 1326.86, 'change_pct': 0.63,
        'open': 1311.84, 'high': 1343.88, 'low': 1310.0,
        'amount': 5756239526.0, 'cached_at': '2026-10-23 13:43:20',
    }]

    merged = _merge_snapshot_with_realtime(items, rt)[0]

    assert merged['open'] == 1311.84
    assert merged['high'] == 1343.88
    assert merged['low'] == 1310.0
    assert merged['amount'] == pytest.approx(5756239.526)


def test_non_realtime_item_keeps_daily_amount():
    items = [{'ts_code': '920036.BJ', 'price': 29.7, 'amount': 37429.4265,
              'snapshot': False}]
    merged = _merge_snapshot_with_realtime(items, [])
    assert merged[0]['amount'] == 37429.4265
    assert merged[0]['snapshot'] is False


def test_overlay_prev_close_and_amplitude():
    """546号 P2：实时 prev_close 覆盖，并按实时高低/昨收重算振幅。"""
    items = [{
        'ts_code': '000001.SZ', 'price': 11.30, 'pct_change': -0.96,
        'amount': 1468424.72209, 'amplitude': 1.42, 'snapshot': False,
    }]
    rt = [{
        'ts_code': '000001.SZ', 'price': 11.20, 'change_pct': -0.88,
        'prev_close': 11.30, 'open': 11.27, 'high': 11.35, 'low': 11.17,
        'amount': 1161789918.21, 'cached_at': '2026-10-23 13:43:20',
    }]

    merged = _merge_snapshot_with_realtime(items, rt)[0]

    assert merged['prev_close'] == 11.30
    assert merged['amplitude'] == pytest.approx(1.59, abs=0.01)


def test_overlay_without_prev_close_keeps_snapshot_amplitude():
    items = [{'ts_code': '000001.SZ', 'price': 11.30, 'amplitude': 1.42,
              'snapshot': False}]
    rt = [{'ts_code': '000001.SZ', 'price': 11.20, 'change_pct': -0.88,
           'cached_at': '2026-10-23 13:43:20'}]
    merged = _merge_snapshot_with_realtime(items, rt)[0]
    assert merged['amplitude'] == 1.42


def test_overlay_marks_partial_when_realtime_ohlc_zero():
    """546号 P3：实时 OHLC=0 时保留日终 OHLC，并标记 quote_partial。"""
    items = [{'ts_code': '601059.SH', 'price': 15.0, 'open': 15.0,
              'high': 15.6, 'low': 14.9, 'snapshot': False}]
    rt = [{'ts_code': '601059.SH', 'price': 15.56, 'change_pct': 0.0,
           'prev_close': 15.56, 'open': 0.0, 'high': 0.0, 'low': 0.0,
           'cached_at': '2026-10-23 13:43:20'}]
    merged = _merge_snapshot_with_realtime(items, rt)[0]
    assert merged['quote_partial'] is True
    assert merged['high'] == 15.6
    assert merged['low'] == 14.9


def test_overlay_handles_none_ohlc_without_overwrite():
    """OCR P3：字段为 None 时不崩溃、不覆盖日终 OHLC，仅标记 partial。"""
    items = [{'ts_code': '000001.SZ', 'open': 11.27, 'high': 11.35,
              'low': 11.17, 'amplitude': 1.59, 'snapshot': False}]
    rt = [{'ts_code': '000001.SZ', 'price': 11.2, 'change_pct': -0.88,
           'prev_close': None, 'open': None, 'high': None, 'low': None,
           'amount': None, 'cached_at': '2026-10-23 13:43:20'}]
    merged = _merge_snapshot_with_realtime(items, rt)[0]
    assert merged['quote_partial'] is True
    assert merged['high'] == 11.35
    assert merged['amplitude'] == 1.59
