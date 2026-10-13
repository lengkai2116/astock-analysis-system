"""514号 — rule_scheduler 盘中评估任务补 app_context（512 同型残留）。

背景：`register_intraday_eval` 的任务体直接 `run_evaluation(mode='intraday')`，
未包 `scheduler_manager._app.app_context()`（其余 4 个通知任务均已包）→
APScheduler 线程执行时报 `Working outside of application context`（2026-10-13 09:34 实证）。
本测试断言任务体在 app context 内执行。
"""
from unittest.mock import MagicMock

from app.services import notification_service as ns
from app.services import rule_scheduler as rs
from flask import Flask, current_app


def _stub_scheduler_manager(app):
    sm = MagicMock()
    sm._app = app
    captured = {}

    def add_interval_job(job_id, func, minutes, max_instances=1, coalesce=True):
        captured['job_id'] = job_id
        captured['func'] = func
        return True

    sm.add_interval_job.side_effect = add_interval_job
    return sm, captured


def test_intraday_eval_job_runs_within_app_context(monkeypatch):
    app = Flask(__name__)
    sm, captured = _stub_scheduler_manager(app)

    monkeypatch.setattr(rs.RuleScheduler, 'is_trading_time', staticmethod(lambda: True))

    seen = {}

    def fake_run_evaluation(mode='intraday'):
        # 无 app context 时访问 current_app（LocalProxy 解析）会抛 RuntimeError
        seen['app'] = current_app._get_current_object()
        return {'evaluated': 1, 'triggered': 0}

    monkeypatch.setattr(ns, 'run_evaluation', fake_run_evaluation)

    rs.RuleScheduler.register_intraday_eval(sm, interval_minutes=15)
    assert captured.get('func') is not None
    assert captured.get('job_id') == 'notification_intraday_eval_15m'

    captured['func']()  # 执行任务体
    assert seen.get('app') is app
