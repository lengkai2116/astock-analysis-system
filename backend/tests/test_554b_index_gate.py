"""554-B：终版构建的指数硬门禁 + 晚到补偿重建

背景：10-30 面板 18:40 建、指数 19:01 发布；`_refresh_out_final_if_index_late`
只在 `idx_checks`（当场发现缺口）里被调用 ⇒ 19:00 仍缺、20:00 已齐，一次都不触发。
且缺指数时 `get_market_volume` 用历史序列静默拼接、errors=[] ⇒ FINAL 记 done，
次日 `_check_eod_completion` 见 done 直接返回，当日指数永久缺失。

本测试锁定：①指数未齐不建终版（不写半成品）；②缺口以 `index_missing` 写入 detail；
③巡检补偿（不依赖当场观测）可重置重建；④非指数失败/已 pending 不误重置。
"""
import contextlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402

_DATE = '20261030'
_FMT = '2026-10-30'


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
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(daemon, '_ensure_index_daily', lambda d: 4)
    monkeypatch.setattr(daemon, '_FINAL_RETRY_STATE', {'date': '', 'next_at': 0.0})
    monkeypatch.setattr(sm_mod.sharding_manager, 'get_write_lock',
                        lambda db: contextlib.nullcontext())
    return ecm


def _seed(ecm, status, detail=None, retry_count=0):
    ecm.conn.execute(
        "INSERT OR REPLACE INTO pipeline_status "
        "(pipeline_date, step_id, step_name, status, detail, retry_count) "
        "VALUES (?, 'OUT-MARKET-FINAL', 'OUT成品仓终版', ?, ?, ?)",
        [_DATE, status, detail, retry_count])
    ecm.conn.commit()


def _row(ecm):
    return ecm.conn.execute(
        "SELECT status, detail, retry_count FROM pipeline_status "
        "WHERE pipeline_date=? AND step_id='OUT-MARKET-FINAL'", [_DATE]).fetchone()


def test_index_gate_blocks_final_build(daemon, fake_ecm, monkeypatch):
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: ['000300.SH'])
    built = []
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: built.append(d) or {'written': 17, 'errors': {}})

    assert daemon._finalize_out_market_panel(_DATE) == 'failed'
    assert built == [], '指数未齐不得构建半成品终版'
    status, detail, rc = _row(fake_ecm)
    assert status == 'failed' and rc == 1
    assert 'index_missing=1/5' in detail


def test_index_complete_allows_build(daemon, fake_ecm, monkeypatch):
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_build_out_market_panel',
                        lambda d: {'written': 17, 'errors': {}})

    assert daemon._finalize_out_market_panel(_DATE) == 'done'
    assert _row(fake_ecm)[0] == 'done'


def test_refresh_compensates_marked_index_gap(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'done',
          detail='终版重建重试超限(3次)，已告警: index_missing=1/5（000300.SH）')
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: _FMT)

    assert daemon._refresh_out_final_if_index_late(_FMT, []) is True
    status, detail, rc = _row(fake_ecm)
    assert status == 'pending'
    assert rc == 0, '重置须清 retry_count，允许重新计次'
    assert 'index_missing' in detail


def test_refresh_ignores_non_index_failure(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'failed', detail='第1/3次失败: errors=[\'market_alerts\']')
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: _FMT)

    assert daemon._refresh_out_final_if_index_late(_FMT, []) is False
    assert _row(fake_ecm)[0] == 'failed', '非指数失败由退避重试接管，不重置'


def test_refresh_skips_pending(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'pending', detail='index_missing=1/5')
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: _FMT)

    assert daemon._refresh_out_final_if_index_late(_FMT, []) is False


def test_refresh_requires_latest_data_date(daemon, fake_ecm, monkeypatch):
    _seed(fake_ecm, 'done', detail='index_missing=1/5')
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-29')

    assert daemon._refresh_out_final_if_index_late(_FMT, []) is False


def test_refresh_legacy_path_still_works(daemon, fake_ecm, monkeypatch):
    """本次巡检当场补齐（missing_before 非空）继续可用。"""
    _seed(fake_ecm, 'done', detail='written=17 errors=[]')
    monkeypatch.setattr(daemon, '_missing_index_codes', lambda d: [])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: _FMT)

    assert daemon._refresh_out_final_if_index_late(_FMT, ['000300.SH']) is True
    assert _row(fake_ecm)[0] == 'pending'
