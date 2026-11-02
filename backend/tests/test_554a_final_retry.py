"""554-A：OUT 终版重建有界重试（失败→退避，超限→done+告警）

背景：`OUT-MARKET-FINAL` 入 `PIPELINE_STEPS` 后，`_drive_pipeline` 在 QA done 后
每 tick 直调 `_finalize_out_market_panel`；原实现只有 `prev == 'done'` 一条护栏，
`errors` 非空只写 failed、异常被吞成 warning ⇒ 任一模块持续报错即每 30s 重建
17 个模块，且 `_is_pipeline_complete` 永不成立。

本测试锁定：成功写 done+completed_at；失败写 failed+retry_count 并退避；
退避期内不再重建；超限转 done + 告警（沿用 543 号 QA-CHECK 先例）。
"""
import contextlib
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402

_DATE = '20261030'


@pytest.fixture()
def daemon():
    import importlib
    return importlib.import_module('data_daemon')


@pytest.fixture()
def fake_ecm(daemon, monkeypatch):
    from app.data import sharding_manager as sm_mod
    conn = sqlite3.connect(':memory:')
    conn.execute(
        "CREATE TABLE pipeline_status ("
        " pipeline_date TEXT, step_id TEXT, step_name TEXT,"
        " status TEXT DEFAULT 'pending', started_at TEXT, completed_at TEXT,"
        " detail TEXT, retry_count INTEGER DEFAULT 0,"
        " PRIMARY KEY (pipeline_date, step_id))")

    class _E:
        pass

    ecm = _E()
    ecm.conn = conn
    monkeypatch.setattr(daemon, '_ecm', ecm)
    monkeypatch.setattr(daemon, '_ensure_index_daily', lambda d: 5)
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_FINAL_RETRY_STATE', {'date': '', 'next_at': 0.0})
    monkeypatch.setattr(sm_mod.sharding_manager, 'get_write_lock',
                        lambda db: contextlib.nullcontext())
    return ecm


def _row(ecm):
    return ecm.conn.execute(
        "SELECT status, detail, retry_count, completed_at FROM pipeline_status "
        "WHERE pipeline_date=? AND step_id='OUT-MARKET-FINAL'", [_DATE]).fetchone()


def _seed(ecm, status, retry_count=0, detail=None):
    ecm.conn.execute(
        "INSERT OR REPLACE INTO pipeline_status "
        "(pipeline_date, step_id, step_name, status, detail, retry_count) "
        "VALUES (?, 'OUT-MARKET-FINAL', 'OUT成品仓终版', ?, ?, ?)",
        [_DATE, status, detail, retry_count])
    ecm.conn.commit()


def test_success_marks_done_with_completed_at(daemon, fake_ecm, monkeypatch):
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: {'written': 17, 'errors': {}})

    assert daemon._finalize_out_market_panel(_DATE) == 'done'
    status, detail, rc, completed = _row(fake_ecm)
    assert status == 'done'
    assert detail == 'written=17 errors=[]'
    assert rc == 0
    assert completed, 'done 必须写 completed_at（原实现为 NULL）'


def test_failure_marks_failed_and_backs_off(daemon, fake_ecm, monkeypatch):
    calls = []
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: calls.append(d) or {'written': 3, 'errors': {'market_alerts': 'x'}})

    assert daemon._finalize_out_market_panel(_DATE) == 'failed'
    status, detail, rc, _ = _row(fake_ecm)
    assert (status, rc) == ('failed', 1)
    assert '第1/3次失败' in detail and 'market_alerts' in detail
    assert daemon._FINAL_RETRY_STATE['next_at'] > time.time()
    assert len(calls) == 1

    # 退避期内：直接 skipped，不再重建
    assert daemon._finalize_out_market_panel(_DATE) == 'skipped'
    assert len(calls) == 1


def test_exhausted_becomes_done_and_alerts(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'failed', retry_count=2)
    alerts = []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, atype, src, meta: alerts.append((title, msg, atype)))
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: {'written': 0, 'errors': {'market_index_daily': 'empty'}})

    assert daemon._finalize_out_market_panel(_DATE) == 'done'
    status, detail, rc, _ = _row(fake_ecm)
    assert status == 'done', '超限转 done，避免管道永不完成（543 先例）'
    assert rc == 3
    assert '重试超限' in detail
    assert alerts and alerts[0][2] == 'OUT_FINAL_FAILED'


def test_exception_counts_as_failure(daemon, fake_ecm, monkeypatch):
    def boom(_d):
        raise RuntimeError('panel build down')

    monkeypatch.setattr(daemon, '_build_out_market_panel', boom)

    assert daemon._finalize_out_market_panel(_DATE) == 'failed'
    status, detail, rc, _ = _row(fake_ecm)
    assert status == 'failed' and rc == 1
    assert '异常: panel build down' in detail


def test_done_is_idempotent(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'done', detail='written=17 errors=[]')
    calls = []
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: calls.append(d) or {'written': 17, 'errors': {}})

    assert daemon._finalize_out_market_panel(_DATE) == 'done'
    assert calls == []
