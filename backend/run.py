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
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    args = parser.parse_args()
    debug_mode = os.getenv("FLASK_ENV", "production") == "development"
    socketio.run(app, host="0.0.0.0", port=args.port, debug=debug_mode, allow_unsafe_werkzeug=True)
