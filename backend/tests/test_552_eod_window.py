"""552：日终跨夜治理（门槛数据驱动 / COL-7 前移 / RAW-2 多进程 / 截止告警）"""
import importlib
import os
import sys
from datetime import datetime as real_datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def daemon(monkeypatch):
    d = importlib.import_module('data_daemon')
    monkeypatch.setattr(d, '_EOD_WARN_STATE', {'date': '', 'warned': set()})
    monkeypatch.setattr(d, '_FIN_SYNC_STATE', {'date': '', 'started': False})
    monkeypatch.setattr(d, '_READY_PROBE_STATE',
                        {'date': '', 'ready': False, 'probed_at': 0.0, 'rows': 0})
    return d


class _FrozenDT(real_datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


def _freeze(daemon, monkeypatch, hh, mm):
    cls = type('FrozenDT', (_FrozenDT,), {'_now': real_datetime(2026, 10, 28, hh, mm, 0)})
    monkeypatch.setattr(daemon, 'datetime', cls)


def test_raw2_process_count_env(daemon, monkeypatch):
    monkeypatch.delenv('RAW2_PROCESSES', raising=False)
    assert daemon._raw2_process_count() == 6
    monkeypatch.setenv('RAW2_PROCESSES', '0')
    assert daemon._raw2_process_count() == 1
    monkeypatch.setenv('RAW2_PROCESSES', '99')
    assert daemon._raw2_process_count() == 12


def test_estimate_remaining_seconds(daemon):
    status = {s: {'status': 'done'} for s in daemon._EOD_STEP_BASELINE}
    assert daemon._estimate_remaining_seconds(status) == (0, [])
    status['SIG'] = {'status': 'pending'}
    status['JUD'] = {'status': 'running'}
    sec, remaining = daemon._estimate_remaining_seconds(status)
    assert sec == 4512 + 2216
    assert set(remaining) == {'SIG', 'JUD'}


def test_ready_gate_before_probe_window(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    called = []
    monkeypatch.setattr(daemon, '_probe_today_daily_published',
                        lambda: called.append(1) or True)
    _freeze(daemon, monkeypatch, 15, 4)
    assert daemon._is_today_data_ready() is False
    assert called == []


def test_ready_gate_starts_probe_at_1505(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    called = []
    monkeypatch.setattr(daemon, '_probe_today_daily_published',
                        lambda: called.append(1) or True)
    _freeze(daemon, monkeypatch, 15, 5)
    assert daemon._is_today_data_ready() is True
    assert called == [1]


def test_ready_gate_uses_probe_in_window(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    _freeze(daemon, monkeypatch, 17, 5)
    monkeypatch.setattr(daemon, '_probe_today_daily_published', lambda: True)
    assert daemon._is_today_data_ready() is True
    monkeypatch.setattr(daemon, '_probe_today_daily_published', lambda: False)
    assert daemon._is_today_data_ready() is False


def test_ready_gate_hard_backstop_at_18(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    _freeze(daemon, monkeypatch, 18, 0)
    monkeypatch.setattr(daemon, '_probe_today_daily_published',
                        lambda: (_ for _ in ()).throw(AssertionError('不应探测')))
    assert daemon._is_today_data_ready() is True


def test_ready_gate_non_trading_day(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: False)
    _freeze(daemon, monkeypatch, 19, 0)
    assert daemon._is_today_data_ready() is False


def test_financial_sync_triggers_once_at_1535(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    started = []

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None, name=None):
            self._target, self._args = target, args

        def start(self):
            started.append((self._target, self._args))

    monkeypatch.setattr(daemon.threading, 'Thread', _FakeThread)
    _freeze(daemon, monkeypatch, 15, 34)
    daemon._maybe_run_financial_sync()
    assert started == []
    _freeze(daemon, monkeypatch, 15, 40)
    daemon._maybe_run_financial_sync()
    daemon._maybe_run_financial_sync()
    assert len(started) == 1
    assert started[0][1] == ('2026-10-28',)


def test_deadline_warning_once_per_slot(daemon, monkeypatch):
    sent = []

    class _FakeECM:
        def load_pipeline_status(self, date):
            return {s: {'status': 'done'} for s in daemon._EOD_STEP_BASELINE} | {
                'SIG': {'status': 'pending'}, 'JUD': {'status': 'pending'}}

    class _FakeNotifier:
        def send(self, *a, **k):
            sent.append((a, k))

    monkeypatch.setattr(daemon, '_ecm', _FakeECM())
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    monkeypatch.setattr(daemon, '_is_pipeline_complete', lambda d: False)
    monkeypatch.setattr('app.services.alert_notifier.AlertNotifier', _FakeNotifier)
    _freeze(daemon, monkeypatch, 20, 31)
    daemon._check_eod_deadline_warning()
    daemon._check_eod_deadline_warning()
    assert len(sent) == 1
    _freeze(daemon, monkeypatch, 21, 1)
    daemon._check_eod_deadline_warning()
    assert len(sent) == 2
    assert sent[1][1].get('severity') == 'CRITICAL'
