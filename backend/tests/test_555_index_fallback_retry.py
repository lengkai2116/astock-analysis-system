"""2026-10-31：指数日线兜底重试 + 晚到重建终版（修 10-30 遗留①）

背景：Tushare 指数日线可能晚于 OUT 才发布（10-30 直到 18:40 才可采，历史 19:01）。
原 `_ensure_index_daily` 只补采一次且忽略结果，缺则带缺口建面板；面板构建后指数再到
也不会重建，只能等次日 08:30 的终版兜底。

本测试锁定：
1. `_ensure_index_daily` 缺数据时有界重试（3 次、间隔 10s），补齐即返回；
2. 重试仍缺时告警放行（不阻塞管道）；
3. 整点巡检补到指数后，把最新数据日已 done 的 `OUT-MARKET-FINAL` 重置为 pending。
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


@pytest.fixture()
def ecm(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_ensure_index_retries_until_complete(daemon, monkeypatch):
    missing = ['000300.SH', '399001.SZ']
    seq = [missing, missing, missing, []]
    calls = []

    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: seq.pop(0))
    monkeypatch.setattr(daemon, '_batch_index_daily',
                        lambda d: calls.append(d) or 5)
    sleeps = []
    monkeypatch.setattr(daemon.time, 'sleep', lambda s: sleeps.append(s))

    assert daemon._ensure_index_daily('2026-10-30') == 5
    assert calls == ['20261030', '20261030'], '应重试到补齐（2 次补采）'
    assert sleeps == [daemon._INDEX_ENSURE_INTERVAL]


def test_ensure_index_gives_up_with_warning(daemon, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(daemon, '_missing_index_codes',
                        lambda d: ['000001.SH', '399006.SZ'])
    monkeypatch.setattr(daemon, '_batch_index_daily',
                        lambda d: calls.append(d) or 0)
    sleeps = []
    monkeypatch.setattr(daemon.time, 'sleep', lambda s: sleeps.append(s))

    with caplog.at_level('WARNING'):
        assert daemon._ensure_index_daily('2026-10-30') == 3

    assert len(calls) == daemon._INDEX_ENSURE_ATTEMPTS
    assert len(sleeps) == daemon._INDEX_ENSURE_ATTEMPTS - 1
    assert any('重试后仍缺' in r.message for r in caplog.records)


def _seed_final(ecm, date='20261030', status='done'):
    ecm.conn.execute(
        "INSERT OR REPLACE INTO pipeline_status "
        "(pipeline_date, step_id, step_name, status) "
        "VALUES (?, 'OUT-MARKET-FINAL', 'OUT成品仓终版', ?)", [date, status])
    ecm.conn.commit()


def test_refresh_final_resets_when_index_late(daemon, ecm, monkeypatch):
    _seed_final(ecm)
    monkeypatch.setattr(daemon, '_ecm', ecm)
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-30')

    assert daemon._refresh_out_final_if_index_late(
        '2026-10-30', ['000300.SH']) is True

    row = ecm.conn.execute(
        "SELECT status, detail FROM pipeline_status "
        "WHERE pipeline_date='20261030' AND step_id='OUT-MARKET-FINAL'").fetchone()
    assert row[0] == 'pending'
    assert '指数日线补采完成' in row[1]


def test_refresh_final_skips_without_missing_before(daemon, ecm, monkeypatch):
    _seed_final(ecm)
    monkeypatch.setattr(daemon, '_ecm', ecm)
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-30')

    assert daemon._refresh_out_final_if_index_late('2026-10-30', []) is False
    row = ecm.conn.execute(
        "SELECT status FROM pipeline_status "
        "WHERE pipeline_date='20261030' AND step_id='OUT-MARKET-FINAL'").fetchone()
    assert row[0] == 'done'


def test_refresh_final_skips_when_still_missing(daemon, ecm, monkeypatch):
    _seed_final(ecm)
    monkeypatch.setattr(daemon, '_ecm', ecm)
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: ['000001.SH'])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-30')

    assert daemon._refresh_out_final_if_index_late(
        '2026-10-30', ['000001.SH']) is False


def test_refresh_final_skips_historical_date(daemon, ecm, monkeypatch):
    _seed_final(ecm, '20261029')
    monkeypatch.setattr(daemon, '_ecm', ecm)
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-30')

    assert daemon._refresh_out_final_if_index_late(
        '2026-10-29', ['000300.SH']) is False
