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
    # 548：_check_eod_completion 用解析器定目标日；解析器读真实库且有 30s 缓存，
    # 测试里必须固定目标日，否则结果取决于运行时的真实最新数据日。
    monkeypatch.setattr('app.services.market_date_resolver.eod_date',
                        lambda now=None: '2026-10-21')
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
    monkeypatch.setattr('app.services.market_date_resolver.eod_date',
                        lambda now=None: '2026-10-21')
    alerts, resumed = [], []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))
    monkeypatch.setattr(daemon, '_drive_pipeline', lambda: resumed.append(1))
    monkeypatch.setattr(daemon, '_finalize_out_market_panel', lambda d: None)
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


# ── 2026-10-31：OUT-MARKET-FINAL 入管道（修 10-30 终版滞后） ──────

def _mark_all_done_except(ecm, date: str, skip: str = '') -> None:
    from app.data.enhanced_cache_manager import PIPELINE_STEPS
    for sid, _ in PIPELINE_STEPS:
        if sid == skip:
            continue
        ecm.conn.execute(
            "UPDATE pipeline_status SET status='done' WHERE pipeline_date=? AND step_id=?",
            [date, sid])
    ecm.conn.commit()


def test_pipeline_complete_requires_out_market_final(daemon, ecm):
    date = '20261022'
    _seed(ecm, date)
    _mark_all_done_except(ecm, date, skip='OUT-MARKET-FINAL')

    assert daemon._is_pipeline_complete(date) is False, \
        'OUT-MARKET-FINAL 未完成时不得判管道完成（否则终版重建永不走）'

    ecm.conn.execute(
        "UPDATE pipeline_status SET status='done' "
        "WHERE pipeline_date=? AND step_id='OUT-MARKET-FINAL'", [date])
    ecm.conn.commit()
    assert daemon._is_pipeline_complete(date) is True


def test_drive_pipeline_finalizes_out_after_qa_done(daemon, ecm, monkeypatch):
    """QA 已 done、FINAL 待办时，_drive_pipeline 必须触发终版重建。"""
    date = '20261022'
    _seed(ecm, date)
    _mark_all_done_except(ecm, date, skip='OUT-MARKET-FINAL')

    monkeypatch.setattr(daemon, '_recover_stale_running', lambda: None)
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-22')
    monkeypatch.setattr(daemon, '_is_market_day', lambda: True)
    monkeypatch.setattr(daemon, '_query_table',
                        lambda table, sql, params=None: 5000)
    monkeypatch.setattr(daemon, '_get_active_codes', lambda d: ['000001.SZ'])
    monkeypatch.setattr(daemon, '_precompute_market_stats', lambda: None)
    monkeypatch.setattr(daemon, '_verify_out_completeness', lambda d: None)
    monkeypatch.setattr(daemon, '_verify_out_market_panel', lambda d: None)
    monkeypatch.setattr(daemon, '_RAW_ROUND', None)
    called = []
    monkeypatch.setattr(daemon, '_finalize_out_market_panel',
                        lambda d: called.append(d))

    daemon._drive_pipeline()

    assert called == [date], 'QA 完成后应到到达终版重建分支'


def test_selfcheck_ignores_conditional_out_market_check(daemon, ecm, monkeypatch, caplog):
    """OUT-MARKET-CHECK 属条件写入步骤，不应被报为未知步骤。"""
    _seed(ecm)
    ecm.conn.execute(
        "INSERT OR IGNORE INTO pipeline_status "
        "(pipeline_date, step_id, step_name, status) "
        "VALUES ('20261022', 'OUT-MARKET-CHECK', 'OUT市场成品校验', 'done')")
    ecm.conn.commit()
    monkeypatch.setattr(daemon, '_get_latest_data_date', lambda: '2026-10-22')
    alerts = []
    monkeypatch.setattr(daemon, '_pipeline_alert',
                        lambda title, msg, *a, **k: alerts.append((title, msg)))

    with caplog.at_level('WARNING'):
        daemon._self_check_pipeline_registration()

    assert alerts == []
    assert not any('未知步骤' in r.message for r in caplog.records)
