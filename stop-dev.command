#!/bin/bash
# A股分析系统 - 一键停止全部服务器 (后端 + UI原型)
# 双击此文件停止所有正在运行的开发服务器

cd "$(dirname "$0")" || exit 1
PROJECT_ROOT="$PWD"

echo ""
echo "⏹  正在停止 A股分析系统 开发服务器..."

_killed=0

# ── 停止 Gunicorn（生产模式） ──
GUNICORN_PID=$(pgrep -f "gunicorn.*stock_analyzer" 2>/dev/null | head -1)
if [ -n "$GUNICORN_PID" ]; then
    kill -TERM "$GUNICORN_PID" 2>/dev/null
    sleep 1
    kill -9 "$GUNICORN_PID" 2>/dev/null
    echo "  ✅ Gunicorn 已停止 (PID: $GUNICORN_PID)"
    _killed=1
else
    echo "  ℹ️  Gunicorn 未在运行"
fi

# ── 停止后端 (Flask run.py) ──
BACKEND_PID=$(pgrep -f "python.*run.py.*port 5001" 2>/dev/null)
if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null
    sleep 0.5
    kill -9 "$BACKEND_PID" 2>/dev/null
    echo "  ✅ 后端已停止 (PID: $BACKEND_PID)"
    _killed=1
else
    echo "  ℹ️  后端未在运行"
fi

# ── 停止 UI 原型服务 (serve.py) ──
SERVE_PID=$(pgrep -f "python.*serve.py" 2>/dev/null)
if [ -n "$SERVE_PID" ]; then
    kill "$SERVE_PID" 2>/dev/null
    echo "  ✅ UI 原型服务已停止 (PID: $SERVE_PID)"
    _killed=1
else
    echo "  ℹ️  UI 原型服务未在运行"
fi

# ── 清理残留 python 进程（DuckDB 锁持有者） ──
REMAINING=$(pgrep -f "python.*stock_cache\|python.*akshare_collector" 2>/dev/null)
if [ -n "$REMAINING" ]; then
    kill -9 $REMAINING 2>/dev/null
    echo "  ✅ DuckDB 残留进程已清理 (PID: $(echo $REMAINING | tr '\n' ' '))"
    _killed=1
fi

if [ "$_killed" -eq 0 ]; then
    echo ""
    echo "ℹ️  没有发现运行中的服务器"
else
    echo ""
    echo "✅ 全部已停止"
fi

echo ""
echo "按 Enter 键退出..."
read -r
