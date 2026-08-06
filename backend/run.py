import os
# ── 清除 Claude Code 注入的系统代理环境变量 ──
# Claude Code 内部 Bash 沙箱会向子进程注入 HTTP_PROXY 等变量指向自身
# （localhost:49422/49423）。这些变量在子进程 fork 时被继承，
# 导致 urllib3/requests 将所有外部 HTTP 请求路由到 Claude 本地代理端口，
# 从而出现 RemoteDisconnected。
# 此处必须在所有第三方导入前清除，确保进程全程无代理。
for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_k, None)
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
import argparse
from app import create_app


def _port_in_use(port: int) -> bool:
    """检测端口是否已被占用（2026-08-06 根治②：API 单实例保护）

    防 launchctl/手动/start.command 多通道重复启动产生双 API 进程
    （双 API 会共享同一 SQLite WAL，加剧写锁竞争与连接池耗尽）。
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', port))
        return False
    except OSError:
        return True
    finally:
        s.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    args = parser.parse_args()
    debug_mode = os.getenv("FLASK_ENV", "production") == "development"

    # ── API 单实例保护：端口已占用则退出（须在 create_app 前，避免重复初始化线程） ──
    if _port_in_use(args.port):
        print(f"❌ 端口 {args.port} 已被占用——API 可能已在运行，本次启动取消（单实例保护）")
        raise SystemExit(1)

    from app import socketio
    app = create_app()

    # 2026-08-06 根治：async_mode='threading'（app/__init__.py 强制），
    # socketio.run 使用 werkzeug 线程池（单进程桌面应用场景，allow_unsafe_werkzeug 必要），
    # 不再依赖 eventlet（连接池泄漏根因）
    socketio.run(app, host="0.0.0.0", port=args.port, debug=debug_mode,
                 allow_unsafe_werkzeug=True)
