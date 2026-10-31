"""2026-10-31：跨表一致性检查剔除指数（修 10-30 遗留⑤）

`daily_cache` 同时存个股与指数（5 只宽基 + 31 只申万行业指数 801*.SI），
`daily_basic_cache` 是个股口径。原检查直接做集合差，恒报
`[数据一致性] daily_basic缺失: 36 只股票`。

本测试锁定：
1. 只有指数差异时不告警；
2. 真实个股缺失仍告警且计数正确。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def daemon():
    import importlib
    return importlib.import_module('data_daemon')


def _fake_fetch(daily, basic):
    def fetch(table, sql, params=None):
        if 'DISTINCT ts_code FROM daily_cache' in sql:
            return [(c,) for c in daily]
        if 'DISTINCT ts_code FROM daily_basic_cache' in sql:
            return [(c,) for c in basic]
        return [(0,)]
    return fetch


def test_consistency_ignores_index_only_difference(daemon, monkeypatch, caplog):
    daily = ['600000.SH', '301718.SZ', '000001.SH', '000300.SH',
             '399001.SZ', '399006.SZ', '899050.BJ', '801010.SI', '801020.SI']
    basic = ['600000.SH', '301718.SZ']
    monkeypatch.setattr(daemon, '_shard_fetchall', _fake_fetch(daily, basic))

    with caplog.at_level('WARNING'):
        daemon._check_data_consistency()

    assert not any('daily_basic缺失' in r.message for r in caplog.records), \
        '指数差异不应再报个股缺失'


def test_consistency_still_reports_real_stock_gap(daemon, monkeypatch, caplog):
    daily = ['600000.SH', '301718.SZ', '000001.SH']
    basic = ['600000.SH']
    monkeypatch.setattr(daemon, '_shard_fetchall', _fake_fetch(daily, basic))

    with caplog.at_level('WARNING'):
        daemon._check_data_consistency()

    assert any('daily_basic缺失: 1 只股票' in r.message for r in caplog.records)
