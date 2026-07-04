#!/bin/bash
# A股分析系统 - 后端停止器
# 双击此文件停止后台运行的后端服务器

cd "$(dirname "$0")" || exit 1

echo "⏹  正在停止后端服务器..."

# 查找并杀死 run.py 进程
PID=$(pgrep -f "python.*run.py.*port 5001" 2>/dev/null)

if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null
    sleep 1
    # 确认是否已停止
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  进程未响应，强制终止..."
        kill -9 "$PID" 2>/dev/null
    fi
    echo "✅ 后端服务器已停止 (PID: $PID)"
else
    echo "ℹ️  未发现运行中的后端服务器"
fi

echo ""
echo "按 Enter 键退出..."
read -r
