"""553-B 增补：非关键源 COL-5 在 18:30/20:00 重试（只改 detail，不阻塞 RAW）"""
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
    monkeypatch.setattr(d, '_NONCRITICAL_RETRY_STATE', {})
    return d


class _FrozenDT(real_datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


def _freeze(daemon, monkeypatch, hh, mm):
    cls = type('FrozenDT', (_FrozenDT,), {'_now': real_datetime(2026, 10, 29, hh, mm, 0)})
    monkeypatch.setattr(daemon, 'datetime', cls)


class _FakeECM:
    def __init__(self):
        self.executed = []
        self.committed = 0

    def load_pipeline_status(self, d):
        return {'COL-5': {'status': 'done'}}

    @property
    def conn(self):
        return self

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def commit(self):
        self.committed += 1


def _setup(daemon, monkeypatch, rows, calls):
    fake = _FakeECM()
    monkeypatch.setattr(daemon, '_ecm', fake)
    monkeypatch.setattr(daemon, '_col_ready_threshold', lambda s, d: 33)
    monkeypatch.setattr(daemon, '_col_row_count', lambda t, d: rows['n'])

    def fake_lhb(date):
        calls.append(date)
        rows['n'] = 75
        return 75

    monkeypatch.setattr(daemon, '_batch_lhb', fake_lhb)
    return fake


def test_no_retry_before_1830(daemon, monkeypatch):
    rows, calls = {'n': 0}, []
    fake = _setup(daemon, monkeypatch, rows, calls)
    _freeze(daemon, monkeypatch, 18, 10)
    daemon._maybe_retry_noncritical_cols()
    assert calls == []
    assert fake.executed == []


def test_retry_at_1830_backfills(daemon, monkeypatch):
    rows, calls = {'n': 0}, []
    fake = _setup(daemon, monkeypatch, rows, calls)
    _freeze(daemon, monkeypatch, 18, 31)
    daemon._maybe_retry_noncritical_cols()
    assert calls == ['2026-10-29']
    assert len(fake.executed) == 1
    assert '18:30 重试后 75/33' in fake.executed[0][1][0]


def test_retry_skipped_when_ready(daemon, monkeypatch):
    rows, calls = {'n': 75}, []
    fake = _setup(daemon, monkeypatch, rows, calls)
    _freeze(daemon, monkeypatch, 20, 1)
    daemon._maybe_retry_noncritical_cols()
    assert calls == []
    assert fake.executed == []


def test_retry_slot_deduped(daemon, monkeypatch):
    rows, calls = {'n': 0}, []
    _setup(daemon, monkeypatch, rows, calls)
    _freeze(daemon, monkeypatch, 18, 31)
    daemon._maybe_retry_noncritical_cols()
    daemon._maybe_retry_noncritical_cols()
    assert calls == ['2026-10-29']


def test_retry_2030_slot_after_2000(daemon, monkeypatch):
    rows, calls = {'n': 0}, []
    _setup(daemon, monkeypatch, rows, calls)
    _freeze(daemon, monkeypatch, 18, 31)
    daemon._maybe_retry_noncritical_cols()
    rows['n'] = 0  # 模拟 18:30 重试仍未发布
    _freeze(daemon, monkeypatch, 20, 1)
    daemon._maybe_retry_noncritical_cols()
    assert len(calls) == 2


def test_detail_reconciled_when_already_ready(daemon, monkeypatch):
    """数据已由完整性检查补齐时，校正残留的「采集后 0/N」明细。"""
    rows, calls = {'n': 69}, []
    fake = _FakeECM()

    class _ECM2(_FakeECM):
        def load_pipeline_status(self, d):
            return {'COL-5': {'status': 'done',
                              'detail': '非关键源，采集后 0/33 行，不阻塞 RAW'}}

    fake = _ECM2()
    monkeypatch.setattr(daemon, '_ecm', fake)
    monkeypatch.setattr(daemon, '_col_ready_threshold', lambda s, d: 33)
    monkeypatch.setattr(daemon, '_col_row_count', lambda t, d: rows['n'])
    monkeypatch.setattr(daemon, '_batch_lhb', lambda d: calls.append(d) or 0)
    _freeze(daemon, monkeypatch, 20, 1)
    daemon._maybe_retry_noncritical_cols()
    assert calls == []
    assert len(fake.executed) == 1
    assert '复核后 69/33' in fake.executed[0][1][0]
