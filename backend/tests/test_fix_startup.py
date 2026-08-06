"""启动体系根治回归测试（2026-08-06）

覆盖根治点：
  1. 连接池泄漏根因：SocketIO async_mode 应强制 threading（禁用 eventlet 自动选用）
  2. health 路由不得直调外部数据源（AGENTS.md 红线 + eventlet 阻塞源）
  3. ECM 提供 WAL checkpoint 方法（周期收缩，防 86G 膨胀）
  4. run.py 具备 API 单实例端口保护（防 launchctl 双 API）
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import re

import re


# ══════════════════════════════════════════════════════════
# 1. SocketIO async_mode 根治（连接池泄漏根因）
# ══════════════════════════════════════════════════════════

def _socketio_async_mode() -> str | None:
    """读取当前 SocketIO 实例 async_mode（init_app 后可用）"""
    from app import create_app
    app = create_app()
    ext = app.extensions.get('socketio')
    if ext is None:
        from app import socketio
        return socketio.async_mode if hasattr(socketio, 'async_mode') else None
    return ext.server.async_mode if hasattr(ext.server, 'async_mode') else None


def test_socketio_async_mode_is_threading():
    """async_mode 必须强制 threading——eventlet 自动选用且无 monkey-patch 是连接池泄漏根因

    修复前：SocketIO() 未指定 async_mode → 检测到已安装 eventlet 自动选用 → 
    eventlet 无 monkey.patch_all() 时 greenlet 调度异常 → psycopg2 连接借用不归还 → CPU 99.6%。
    修复后：显式 async_mode='threading'（werkzeug，线程模型，连接池正常）。
    """
    assert _socketio_async_mode() == 'threading', \
        f"async_mode 应为 threading（根治连接池泄漏），实际 {_socketio_async_mode()}"


def test_socketio_threading_in_init():
    """模块级 SocketIO 初始化必须显式声明 async_mode='threading'"""
    src = open(os.path.join(os.path.dirname(__file__), '..', 'app', '__init__.py'),
               encoding='utf-8').read()
    m = re.search(r"SocketIO\(([^)]*)\)", src)
    assert m, "应找到 SocketIO 初始化"
    assert 'async_mode' in m.group(1), "SocketIO() 必须显式 async_mode 参数（防 eventlet 自动选用）"
    assert "'threading'" in m.group(1) or '"threading"' in m.group(1)


# ══════════════════════════════════════════════════════════
# 2. health 路由移除外部数据源直调（红线 + 阻塞源）
# ══════════════════════════════════════════════════════════

def test_health_no_external_api_direct_call():
    """health 路由不得直调 Tushare/DeepSeek/LLM-Wiki（AGENTS.md 四层架构红线）

    修复前：_get_external_api_status() 用 requests 直调 3 个外部 API（timeout 3-10s），
    在 eventlet 下同步 HTTP 阻塞事件循环 → /api/v3/health 超时（12s+）。
    修复后：外部 API 状态改为读取采集器缓存/配置，不发起实时 HTTP 请求。
    """
    src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'routes', 'health.py'),
               encoding='utf-8').read()
    # 不应再向外部域名发起 requests 请求
    assert 'api.tushare.pro' not in src, "health 不得直调 Tushare"
    assert 'api.deepseek.com' not in src, "health 不得直调 DeepSeek"
    assert 'http_requests.post(' not in src, "health 不得有外部 POST 请求"
    assert 'http_requests.get(' not in src, "health 不得有外部 GET 请求"


# ══════════════════════════════════════════════════════════
# 3. ECM WAL checkpoint 方法（防膨胀）
# ══════════════════════════════════════════════════════════

def test_ecm_has_wal_checkpoint_method():
    """ECM 应提供 wal_checkpoint() 方法——daemon 主循环周期调用收缩 WAL

    修复前：ECM 无任何 checkpoint 调用，WAL 只增不减（实测 86G）。
    修复后：wal_checkpoint() 执行 PRAGMA wal_checkpoint(PASSIVE/TRUNCATE)。
    """
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    assert hasattr(ecm, 'wal_checkpoint'), "ECM 必须提供 wal_checkpoint() 方法"
    # 方法应可执行（返回 checkpoint 结果）
    result = ecm.wal_checkpoint()
    assert isinstance(result, tuple) and len(result) == 3, \
        f"wal_checkpoint 应返回 (busy, log, checkpointed) 三元组，实际 {result}"


def test_daemon_loop_calls_checkpoint():
    """daemon 主循环必须周期调用 ECM.wal_checkpoint()（防 WAL 膨胀）

    修复前：主循环无 checkpoint，WAL 86G。
    修复后：主循环每 N 次 tick（或定时）调用 checkpoint。
    """
    src = open(os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py'),
               encoding='utf-8').read()
    assert 'wal_checkpoint' in src, "daemon 主循环必须调用 ECM.wal_checkpoint()"


# ══════════════════════════════════════════════════════════
# 4. run.py API 单实例端口保护
# ══════════════════════════════════════════════════════════

def test_run_py_has_single_instance_guard():
    """run.py 启动前必须检测端口占用——防 launchctl/手动重复启动双 API

    修复前：run.py 无检查，launchctl 通道可起第二个 API（无单实例保护）。
    修复后：_port_in_use() 在启动前 bind 探测，已占用则 SystemExit(1)。
    """
    import run as run_mod
    assert hasattr(run_mod, '_port_in_use'), "run.py 必须提供 _port_in_use() 单实例检测"

    # 空闲端口应返回 False
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(('127.0.0.1', 0))
    free_port = probe.getsockname()[1]
    probe.close()
    assert run_mod._port_in_use(free_port) is False, "空闲端口应返回 False"

    # 已占用端口应返回 True
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(('127.0.0.1', 0))
    occupied_port = occupied.getsockname()[1]
    occupied.listen(1)
    assert run_mod._port_in_use(occupied_port) is True, "已占用端口应返回 True"
    occupied.close()
