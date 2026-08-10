"""320号 L4 回归测试：双进程模式下 daemon 不注册盘中推送任务

背景：daemon 进程（DATA_DAEMON_RUNNING=1）通过 create_app 启动 scheduler_manager，
_register_jobs 无条件注册"盘中快照推送"（每 5s）→ 收盘后 APScheduler 每 5s 空转
触发（包装器内部跳过推送），产生大量无意义调度日志（daemon.log 13 万行刷屏）。
L4 修复：盘中推送/板块推送注册加 DATA_DAEMON_RUNNING 守卫（与日终同步一致）。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


def test_daemon_mode_skips_intraday_push_registration(monkeypatch):
    """DATA_DAEMON_RUNNING=1 时 _register_jobs 不应注册盘中推送任务

    修复前：_register_jobs 无条件 add_job 盘中推送（每5s）→ daemon 进程收盘后空转刷日志
    修复后：加守卫，daemon 模式不注册
    """
    from app.scheduler_manager import SchedulerManager
    from apscheduler.schedulers.background import BackgroundScheduler

    sm = SchedulerManager()
    sm._scheduler = BackgroundScheduler()
    added_ids = []

    # 捕获 add_job 调用
    orig_add = sm._scheduler.add_job
    def _capture_add(*a, **kw):
        added_ids.append(kw.get('id'))
        return orig_add(*a, **kw)
    monkeypatch.setattr(sm._scheduler, 'add_job', _capture_add)
    monkeypatch.setenv('DATA_DAEMON_RUNNING', '1')

    sm._register_jobs({})   # 空配置（仅测试推送任务守卫）

    assert 'market_snapshot_push_5s' not in added_ids, \
        "DATA_DAEMON_RUNNING=1 时不应注册盘中推送(5s)任务（修复前无条件注册）"
    assert 'market_snapshot_push_30s' not in added_ids, \
        "DATA_DAEMON_RUNNING=1 时不应注册盘中板块推送(30s)任务"


def test_normal_mode_registers_intraday_push(monkeypatch):
    """非 daemon 模式（API 进程）应正常注册盘中推送任务"""
    from app.scheduler_manager import SchedulerManager
    from apscheduler.schedulers.background import BackgroundScheduler

    sm = SchedulerManager()
    sm._scheduler = BackgroundScheduler()
    added_ids = []

    orig_add = sm._scheduler.add_job
    def _capture_add(*a, **kw):
        added_ids.append(kw.get('id'))
        return orig_add(*a, **kw)
    monkeypatch.setattr(sm._scheduler, 'add_job', _capture_add)
    monkeypatch.delenv('DATA_DAEMON_RUNNING', raising=False)

    sm._register_jobs({})

    assert 'market_snapshot_push_5s' in added_ids, \
        "API 进程（非 daemon）应注册盘中推送(5s)任务"
    assert 'market_snapshot_push_30s' in added_ids, \
        "API 进程（非 daemon）应注册盘中板块推送(30s)任务"
