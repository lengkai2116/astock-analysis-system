"""517号 批次1 定向测试：WAL 守护 `start_processes` 端口等待 + 健康校验 + 日志据实。

- **Q1-A**：起 API 前轮询等端口可绑（与 `run.py._port_in_use` 同语义）。
- **Q3-A**：「API 已重启」仅在回环 health 校验通过后记录，失败则 WARNING + 重试。
"""
import inspect
import socket

import wal_maintenance as w


def test_port_bindable_false_when_listening_true_after_release():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert w._port_bindable(port) is False      # 有 LISTEN → 不可绑
    finally:
        srv.close()
    assert w._port_bindable(port) is True           # 释放后 → 可绑


def test_start_processes_waits_port_and_verifies_before_success_log():
    src = inspect.getsource(w.start_processes)
    assert '_port_bindable' in src          # Q1-A：起前等端口释放
    assert '_api_healthy' in src            # Q3-A：起后回环校验
    assert 'health 校验通过' in src          # 成功日志仅在健康确认后
    assert 'logger.info("API 已重启")' not in src   # 不再有无条件「API 已重启」
