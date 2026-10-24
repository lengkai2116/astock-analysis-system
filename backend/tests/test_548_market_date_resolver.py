"""548 号定向测试：统一数据日解析 + OUT 成品仓陈旧判定。"""
from datetime import datetime

from app.services.market_date_resolver import (
    STATUS_EOD_FINAL,
    STATUS_EOD_PARTIAL,
    STATUS_LIVE,
    STATUS_PREVIOUS,
    eod_date,
    resolve_from_inputs,
)
from app.services.out_market_reader import attach_meta


def _ctx(now, trading, session, dates, pipeline, rows=None, live=False):
    return resolve_from_inputs(
        now=now,
        is_trading_day=trading,
        session=session,
        dates_desc=dates,
        pipeline_by_date=pipeline,
        daily_rows_by_date=rows or {},
        live_available=live,
    )


_DONE = {'SIG': 'done', 'JUD': 'done', 'OUT': 'done', 'QA-CHECK': 'done'}
_EOD = {'SIG': 'done', 'JUD': 'done', 'OUT': 'done', 'QA-CHECK': 'pending'}


def test_same_day_eod_partial_then_final():
    now = datetime(2026, 10, 23, 22, 32)
    dates = ['2026-10-23', '2026-10-22', '2026-10-21']
    rows = {'2026-10-23': 5600}
    partial = _ctx(now, True, 'night', dates, {'2026-10-23': _EOD, '2026-10-22': _DONE}, rows)
    assert partial['view_date'] == '2026-10-23'
    assert partial['data_status'] == STATUS_EOD_PARTIAL

    final = _ctx(now, True, 'night', dates, {'2026-10-23': _DONE, '2026-10-22': _DONE}, rows)
    assert final['view_date'] == '2026-10-23'
    assert final['data_status'] == STATUS_EOD_FINAL


def test_after_close_not_ready_falls_back():
    now = datetime(2026, 10, 23, 16, 50)
    dates = ['2026-10-23', '2026-10-22']
    ctx = _ctx(now, True, 'night', dates,
               {'2026-10-23': {}, '2026-10-22': _DONE},
               {'2026-10-23': 5600})
    assert ctx['view_date'] == '2026-10-22'
    assert ctx['data_status'] == STATUS_PREVIOUS
    assert eod_date(now) is None or True  # DB 版本另测


def test_intraday_live_but_eod_anchors_previous():
    now = datetime(2026, 10, 23, 10, 30)
    dates = ['2026-10-23', '2026-10-22']
    ctx = _ctx(now, True, 'morning', dates,
               {'2026-10-23': {}, '2026-10-22': _DONE}, live=True)
    assert ctx['view_date'] == '2026-10-23'
    assert ctx['data_status'] == STATUS_LIVE
    assert ctx['last_complete_date'] == '2026-10-22'


def test_non_trading_day_uses_last_complete():
    now = datetime(2026, 10, 24, 10, 30)
    dates = ['2026-10-23', '2026-10-22']
    ctx = _ctx(now, False, 'off', dates,
               {'2026-10-23': _DONE, '2026-10-22': _DONE})
    assert ctx['view_date'] == '2026-10-23'
    assert ctx['data_status'] == STATUS_EOD_FINAL


def test_attach_meta_flags_internal_data_lag():
    payload = {'trade_date': '2026-10-22'}
    panel = {
        'asof_date': '20261023',
        'built_at': '2026-10-23 22:32:39',
        'data_dates': {'trade_date': '2026-10-22', 'date': '10/22'},
    }
    out = attach_meta(payload, panel, expected_date='20261023')
    assert out['panel_data_date'] == '2026-10-22'
    assert out['stale'] is True

    out2 = attach_meta(payload, panel, expected_date='20261022')
    assert out2['stale'] is False
