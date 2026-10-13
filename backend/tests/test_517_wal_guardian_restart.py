"""517号 定向测试：WAL 守护 `start_processes` 端口等待 + 健康校验 + 日志据实。

- **Q1-A**：起 API 前轮询等端口可绑（与 `run.py._port_in_use` 同语义）。
- **Q3-A**：「API 已重启」仅在回环 health 校验通过后记录，失败则 WARNING + 重试。
- **Q2（批次2）**：`run.py._port_in_use` / `wal_maintenance._port_bindable` 均改为
  「`SO_REUSEADDR` + 探服务端实际绑定地址 `0.0.0.0`」——真实 LISTEN 仍判占用、
  TIME_WAIT 残留放过（既不得漏判真实 LISTEN，也不得被 TIME_WAIT 误拒）。
"""
import inspect
import socket
import time

import pytest
import run as run_mod
import wal_maintenance as w


def _bare_bindable(addr) -> bool:
    """裸 bind 探测（不带 SO_REUSEADDR）：True=可绑。用于确认 TIME_WAIT 残留是否形成。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(addr)
        return True
    except OSError:
        return False
    finally:
        s.close()


def test_port_bindable_false_when_listening_true_after_release():
    # 与 run.py 服务器一致：监听 0.0.0.0（真实双实例场景）
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('0.0.0.0', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert w._port_bindable(port) is False      # 有 LISTEN → 不可绑
    finally:
        srv.close()
    assert w._port_bindable(port) is True           # 释放后 → 可绑


def test_port_in_use_still_detects_real_listen_despite_reuseaddr():
    """Q2 关键回归：加 SO_REUSEADDR 后**不得漏判「真实 LISTEN」**（单实例保护不可失效）。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('0.0.0.0', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert run_mod._port_in_use(port) is True   # 真实 API 在跑 → 必判占用
    finally:
        srv.close()
    assert run_mod._port_in_use(port) is False      # 释放后 → 判未占用


def test_port_in_use_lets_time_wait_through():
    """Q2：TIME_WAIT 残留（刚停旧 API 的连接）不得被判占用，否则守卫误拒、API 静默不恢复。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('0.0.0.0', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    cli = socket.create_connection(('127.0.0.1', port))
    conn, _ = srv.accept()
    conn.close()          # 服务端先 FIN（主动关闭方）→ 该连接进 TIME_WAIT
    time.sleep(0.2)
    cli.close()
    srv.close()
    time.sleep(0.2)
    # 前置：确认 TIME_WAIT 确已残留（裸 bind 仍失败）；未形成则跳过（不误报失败）
    if _bare_bindable(('127.0.0.1', port)):
        pytest.skip("本机未形成 TIME_WAIT 残留，跳过放过性验证")
    assert w._port_bindable(port) is True           # 可绑（放过 TIME_WAIT）
    assert run_mod._port_in_use(port) is False      # 判未占用（守卫放行）


def test_start_processes_waits_port_and_verifies_before_success_log():
    src = inspect.getsource(w.start_processes)
    assert '_port_bindable' in src          # Q1-A：起前等端口释放
    assert '_api_healthy' in src            # Q3-A：起后回环校验
    assert 'health 校验通过' in src          # 成功日志仅在健康确认后
    assert 'logger.info("API 已重启")' not in src   # 不再有无条件「API 已重启」
