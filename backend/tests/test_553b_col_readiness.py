"""553-B：COL 就绪判据（本表本日行数 ≥ max(floor, 前日×ratio)）"""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def daemon(monkeypatch):
    d = importlib.import_module('data_daemon')
    monkeypatch.setattr(d, '_COL_RETRY_AT', {})
    return d


def test_col_table_mapping(daemon):
    assert daemon._COL_TABLE == {
        'COL-1': 'daily_cache', 'COL-2': 'daily_basic_cache',
        'COL-3': 'moneyflow_cache', 'COL-4': 'stk_limit_cache', 'COL-5': 'lhb_cache',
    }
    assert daemon._COL_CRITICAL == {'COL-1', 'COL-2', 'COL-3', 'COL-4'}


def test_threshold_uses_floor_when_no_prev(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_col_prev_count', lambda t, d: 0)
    assert daemon._col_ready_threshold('COL-1', '2026-10-29') == 4000
    assert daemon._col_ready_threshold('COL-3', '2026-10-29') == 3000
    assert daemon._col_ready_threshold('COL-5', '2026-10-29') == 1


def test_threshold_uses_prev_ratio(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_col_prev_count', lambda t, d: 5570)
    assert daemon._col_ready_threshold('COL-1', '2026-10-29') == int(5570 * 0.95)
    assert daemon._col_ready_threshold('COL-2', '2026-10-29') == int(5570 * 0.95)
    # COL-5 龙虎榜稀疏，比例 0.5
    assert daemon._col_ready_threshold('COL-5', '2026-10-29') == int(5570 * 0.5)


def test_row_count_and_prev_count(daemon, monkeypatch):
    calls = []

    def fake_query(table, sql, params=None):
        calls.append((table, params))
        return 1234

    monkeypatch.setattr(daemon, '_query_table', fake_query)
    assert daemon._col_row_count('daily_cache', '2026-10-29') == 1234
    assert daemon._col_prev_count('daily_cache', '2026-10-29') == 1234
    assert len(calls) == 2
    assert calls[0][1] == ['2026-10-29']


def test_row_count_failure_returns_zero(daemon, monkeypatch):
    def boom(table, sql, params=None):
        raise RuntimeError('db down')

    monkeypatch.setattr(daemon, '_query_table', boom)
    assert daemon._col_row_count('daily_cache', '2026-10-29') == 0
    assert daemon._col_prev_count('daily_cache', '2026-10-29') == 0


def test_retry_cooldown(daemon, monkeypatch):
    now = {'t': 1000.0}
    monkeypatch.setattr(daemon.time, 'time', lambda: now['t'])
    assert daemon._col_retry_due('20261029', 'COL-2') is True
    assert daemon._col_retry_due('20261029', 'COL-2') is False
    now['t'] += daemon._COL_RETRY_INTERVAL + 1
    assert daemon._col_retry_due('20261029', 'COL-2') is True
    # 不同步骤互不影响
    assert daemon._col_retry_due('20261029', 'COL-3') is True
