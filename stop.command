#!/bin/bash
# A股分析系统 — 停止（254号双进程架构）
echo "正在停止 A股分析系统..."
kill $(lsof -ti :5001) 2>/dev/null && echo "  API 进程已停止" || echo "  API 进程未运行"
DATA_PID=$(pgrep -f "data_daemon" 2>/dev/null)
if [ -n "$DATA_PID" ]; then
    kill $DATA_PID 2>/dev/null
    echo "  数据进程已停止"
else
    echo "  数据进程未运行"
fi
echo "✅ 服务已停止"
