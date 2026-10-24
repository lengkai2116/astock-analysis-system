"""548 §六 数据侧三项定向测试：ETF 市场完整性、per_stock 单只、OUT 前指数校验。"""
import types

import pandas as pd

import data_daemon as dd


def test_missing_index_codes(monkeypatch):
    monkeypatch.setattr(dd, '_shard_fetchall', lambda *a, **k: [
        ('000001.SH',), ('000300.SH',), ('399001.SZ',), ('399006.SZ',)])
    assert dd._missing_index_codes('20261023') == ['899050.BJ']


def test_ensure_index_daily_skips_when_complete(monkeypatch):
    calls = []
    monkeypatch.setattr(dd, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(dd, '_batch_index_daily', lambda d: calls.append(d))
    assert dd._ensure_index_daily('20261023') == len(dd.BROAD_INDEX_CODES)
    assert calls == []


def test_ensure_index_daily_backfills_missing(monkeypatch):
    calls = []
    seq = iter([['899050.BJ'], []])
    monkeypatch.setattr(dd, '_missing_index_codes', lambda d: next(seq))
    monkeypatch.setattr(dd, '_batch_index_daily', lambda d: calls.append(d) or 5)
    assert dd._ensure_index_daily('20261023') == len(dd.BROAD_INDEX_CODES)
    assert calls == ['20261023']


def test_batch_daily_single_uses_ts_code(monkeypatch):
    captured = {}

    def fake_ts(fn, *args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '2026-10-23'}])

    class FakeECM:
        def cache_daily_data(self, df):
            captured['rows'] = len(df)
            return len(df)

    import tushare as ts
    monkeypatch.setattr(ts, 'pro_api',
                        lambda: types.SimpleNamespace(daily=lambda **kw: None))
    monkeypatch.setattr(dd, '_ts', fake_ts)
    monkeypatch.setattr(dd, '_ecm', FakeECM())
    n = dd._batch_daily_single('000001.SZ', '20261023')
    assert captured['ts_code'] == '000001.SZ'
    assert captured['trade_date'] == '20261023'
    assert captured['rows'] == 1
    assert n == 1


def test_fund_share_completeness_refetches(monkeypatch):
    calls = []
    monkeypatch.setattr(dd, '_shard_fetchall', lambda *a, **k: [('SH', 0), ('SZ', 792)])
    monkeypatch.setattr(dd, '_batch_fund_share', lambda d: calls.append(d) or 1801)
    monkeypatch.setattr(dd, '_is_trading_day', lambda d: True)
    monkeypatch.setattr(dd, '_is_today_data_ready', lambda: True)
    dd._check_fund_share_completeness(1)
    assert len(calls) == 1
