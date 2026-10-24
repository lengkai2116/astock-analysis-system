"""543号：日终完成保障（停滞看门狗 / 日终硬校验 / 启动注册自检）"""
import os
import sys
import time
from datetime import datetime as real_datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def ecm(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


@pytest.fixture()
def daemon(ecm, monkeypatch):
    import importlib
    d = importlib.import_module('data_daemon')
    monkeypatch.setattr(d, '_ecm', ecm)
    return d


def _seed(ecm, date='20261022', statuses=None):
    ecm.ensure_pipeline_steps(date)
    if statuses:
        for sid, st in statuses.items():
            ecm.conn.execute(
                "UPDATE pipeline_status SET status=? WHERE pipeline_date=? AND step_id=?",
                [st, date, sid])
        ecm.conn.commit()


def test_watchdog_alerts_when_pending_no_progress(daemon, ecm, monkeypatch):
    _seed(ecm)
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-22')
    alerts = []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))
    daemon._PIPELINE_STALL_STATE.update(date=None, fingerprint=None, since=0.0, last_alert=0.0)

    daemon._check_pipeline_stall()  # 建立指纹
    assert alerts == []

    # 548：RAW-2 阈值 240min，需超过最长步骤阈值才告警
    daemon._PIPELINE_STALL_STATE['since'] = time.time() - 5 * 3600
    daemon._check_pipeline_stall()
    assert alerts and '无进展' in alerts[0][1]


def test_watchdog_resets_on_progress(daemon, ecm, monkeypatch):
    _seed(ecm)
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-22')
    alerts = []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))
    daemon._PIPELINE_STALL_STATE.update(date=None, fingerprint=None, since=0.0, last_alert=0.0)
    daemon._check_pipeline_stall()

    ecm.conn.execute(
        "UPDATE pipeline_status SET status='done' "
        "WHERE pipeline_date='20261022' AND step_id='COL-1'")
    ecm.conn.commit()
    daemon._PIPELINE_STALL_STATE['since'] = time.time() - 7200
    daemon._check_pipeline_stall()
    assert alerts == []


def test_eod_check_alerts_and_resumes(daemon, ecm, monkeypatch):
    _seed(ecm, '20261021')
    monkeypatch.setattr(daemon, '_shard_fetchall',
                        lambda table, sql: [('2026-10-22',), ('2026-10-21',)])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-21')
    monkeypatch.setattr(daemon, 'datetime', type('FakeDT', (), {
        'now': staticmethod(lambda: real_datetime(2026, 10, 23, 9, 0))}))
    alerts, resumed = [], []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))
    monkeypatch.setattr(daemon, '_drive_pipeline', lambda: resumed.append(1))
    daemon._EOD_CHECK_STATE['checked_date'] = None

    daemon._check_eod_completion()
    assert alerts and 'QA-CHECK 未完成' in alerts[0][1]
    assert resumed == [1]


def test_eod_check_skips_when_qa_done(daemon, ecm, monkeypatch):
    _seed(ecm, '20261021', {'QA-CHECK': 'done'})
    monkeypatch.setattr(daemon, '_shard_fetchall',
                        lambda table, sql: [('2026-10-22',), ('2026-10-21',)])
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-21')
    monkeypatch.setattr(daemon, 'datetime', type('FakeDT', (), {
        'now': staticmethod(lambda: real_datetime(2026, 10, 23, 9, 0))}))
    alerts, resumed = [], []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))
    monkeypatch.setattr(daemon, '_drive_pipeline', lambda: resumed.append(1))
    daemon._EOD_CHECK_STATE['checked_date'] = None

    daemon._check_eod_completion()
    assert alerts == [] and resumed == []


def test_selfcheck_alerts_missing_step(daemon, ecm, monkeypatch):
    _seed(ecm)
    ecm.conn.execute(
        "DELETE FROM pipeline_status WHERE pipeline_date='20261022' AND step_id='RAW-2D'")
    ecm.conn.commit()
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-22')
    alerts = []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))

    daemon._self_check_pipeline_registration()
    assert alerts and 'RAW-2D' in alerts[0][1]
    assert ecm.conn.execute(
        "SELECT COUNT(*) FROM pipeline_status WHERE pipeline_date='20261022' AND step_id='RAW-2D'"
    ).fetchone()[0] == 1
