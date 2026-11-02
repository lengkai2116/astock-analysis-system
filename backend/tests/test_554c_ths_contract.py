"""554-C：同花顺 time 分时解析契约（ts_code/freq + HHMM 校验 + 日期归一）

背景：553-C 把 THS 兜底挂在 414 号 R20 已停用的 v1 分钟回填上（死路径），
且返回帧缺 `ts_code`：一旦接线，`cache_minute_kline` 会以 `ts_code=NULL`
落 `minute_kline_cache`（PK 含 ts_code、读取恒 `WHERE ts_code=?`）⇒ 写入即不可读。

本测试锁定 provider 侧契约：①必带 ts_code/freq；②非法 HHMM 跳过；
③date/datetime 入参可归一；④截断 JSONP 不抛异常（与"无数据"同义）。
"""
import datetime
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
# 含 3 位 HHMM（930）与非法时分（2570），均应跳过
_TIME_BAD_HHMM = (
    'quotebridge_v6_time_hs_000001_last({"hs_000001":{"date":"20261029",'
    '"data":"930,11.30,1,11.3,100;0931,11.33,2,11.3,200;2570,1,1,1,1"}});'
)


def test_frame_carries_ts_code_and_freq(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_SAMPLE)
    df = ths.fetch_intraday_minutes('000001.SZ', '2026-10-29')

    assert list(df.columns) == ['ts_code', 'trade_date', 'trade_time', 'freq',
                                'open', 'high', 'low', 'close', 'volume', 'amount']
    assert set(df['ts_code']) == {'000001.SZ'}
    assert set(df['freq']) == {'1min'}
    assert df.iloc[0]['trade_time'] == '2026-10-29 09:30:00'
    assert df.iloc[0]['close'] == 11.30


def test_invalid_hhmm_rows_are_skipped(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_BAD_HHMM)
    df = ths.fetch_intraday_minutes('000001.SZ', '2026-10-29')

    assert len(df) == 1, '仅 0931 合法；930 与 2570 必须丢弃'
    assert df.iloc[0]['trade_time'] == '2026-10-29 09:31:00'


def test_date_objects_are_normalized(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_SAMPLE)

    for value in (datetime.date(2026, 10, 29), datetime.datetime(2026, 10, 29, 15, 0)):
        assert len(ths.fetch_intraday_minutes('000001.SZ', value)) == 2


def test_truncated_jsonp_returns_empty(monkeypatch):
    monkeypatch.setattr(ths, '_get',
                        lambda url, timeout=8: 'quotebridge_v6_time({"hs_000001":{"date":"20261029","data":"0930')
    df = ths.fetch_intraday_minutes('000001.SZ', '2026-10-29')
    assert df.empty


def test_mismatched_date_returns_empty(monkeypatch):
    monkeypatch.setattr(ths, '_get', lambda url, timeout=8: _TIME_SAMPLE)
    assert ths.fetch_intraday_minutes('000001.SZ', '2026-10-28').empty
