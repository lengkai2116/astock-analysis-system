#!/bin/bash
# A股分析系统 — 停止脚本（macOS）
# 优雅停止后端服务

PID=$(pgrep -f "python3.*run.py")

if [ -z "$PID" ]; then
    echo "后端未运行"
    exit 0
fi

echo "正在停止后端 (PID=$PID)..."

# 先尝试优雅停止（SIGTERM）
kill -TERM $PID 2>/dev/null

# 等待最多 10 秒
for i in $(seq 1 10); do
    if ! kill -0 $PID 2>/dev/null; then
        echo "后端已停止"
        exit 0
    fi
    sleep 1
done

# 超时则强制结束（SIGKILL）
echo "超时未响应，强制停止..."
kill -KILL $PID 2>/dev/null
echo "后端已强制停止"
