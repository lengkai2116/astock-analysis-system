#!/bin/bash
# daemon_wrapper — data_daemon launchd 看门狗包装脚本
# =====================================================
# 负责：
#   - 设置 Python 路径和环境变量
#   - 清除 HTTP_PROXY 环境变量（防止代理干扰通达信 TCP 协议）
#   - 启动 data_daemon.py
#   - 崩溃时写入 crash report

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
DATA_DAEMON="$PROJECT_ROOT/backend/data_daemon.py"
LOG_DIR="$HOME/Library/Logs/data-daemon"
CRASH_REPORT="$LOG_DIR/crash_$(date +%Y%m%d_%H%M%S).log"

# ── 日志目录 ──
mkdir -p "$LOG_DIR"

# ── 环境变量 ──
export DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/data}"
export NO_PROXY="*"

# ── 清除代理（通达信 TCP 协议无需代理）──
for _k in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    unset "$_k" 2>/dev/null || true
done

# ── 启动 ──
# 如果已在运行（由 start.command 或其他进程启动），退出
if [ "${DATA_DAEMON_RUNNING:-0}" = "1" ]; then
    echo "[daemon_wrapper] DATA_DAEMON_RUNNING=1，跳过（已在运行）" >> "$LOG_DIR/wrapper.log"
    exit 0
fi

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[daemon_wrapper] 错误: 找不到虚拟环境 $VENV_PYTHON" >&2
    exit 1
fi

if [ ! -f "$DATA_DAEMON" ]; then
    echo "[daemon_wrapper] 错误: 找不到 $DATA_DAEMON" >&2
    exit 1
fi

echo "[daemon_wrapper] 启动 data_daemon..." >> "$LOG_DIR/wrapper.log"
"$VENV_PYTHON" "$DATA_DAEMON"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    {
        echo "========================================"
        echo " Crash Report — data_daemon 异常退出"
        echo " 时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo " 退出码: $EXIT_CODE"
        echo " PID: $$"
        echo "========================================"
        echo ""
    } > "$CRASH_REPORT"
    echo "[daemon_wrapper] data_daemon 退出码 $EXIT_CODE，报告已写入 $CRASH_REPORT" >> "$LOG_DIR/wrapper.log"
fi

exit $EXIT_CODE
