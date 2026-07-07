#!/bin/bash
# A股分析系统 — 一键启动（254号双进程架构）
# 启动顺序：数据进程 → API 进程 → 打开浏览器

cd "$(dirname "$0")"
PROJECT_ROOT="$PWD"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
ECM_DB="$PROJECT_ROOT/data/duckdb/stock_cache.db"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 找不到虚拟环境"
    read -r; exit 1
fi

for _k in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    unset "$_k" 2>/dev/null
done
export NO_PROXY="*"

cleanup() {
    echo ""
    echo "正在停止服务..."
    kill $DATA_PID 2>/dev/null
    kill $API_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

clear
echo "═══════════════════════════════════════════════"
echo "   A股分析系统 — 启动"
echo ""
echo "   数据进程 → API 进程 → 浏览器"
echo "═══════════════════════════════════════════════"
echo ""

# ── 检查是否已在运行 ──
if curl -sf http://127.0.0.1:5001/api/v3/health/live > /dev/null 2>&1; then
    echo "✅ API 已在运行，直接打开浏览器"
    open "http://localhost:5001/dashboard"
    exit 0
fi

# ── 检查 ECM 是否有今日数据（判断数据进程是否需要启动） ──
TODAY=$(date +%Y-%m-%d)
HAS_DATA=$(sqlite3 "$ECM_DB" "SELECT COUNT(*) FROM daily_cache WHERE trade_date='$TODAY';" 2>/dev/null || echo "0")
NEED_DATA=true
if [ "$HAS_DATA" -gt 5000 ] 2>/dev/null; then
    # 今日数据齐全，跳过数据进程启动（之前已运行）
    echo "📦 ECM 数据已就绪"
    NEED_DATA=false
fi

# ── 启动数据进程 ──
DATA_PID=""
if [ "$NEED_DATA" = true ]; then
    echo "⏳ 启动数据进程..."
    cd "$PROJECT_ROOT/backend"
    DATA_DAEMON_RUNNING=1 "$VENV_PYTHON" data_daemon.py &
    DATA_PID=$!
    cd "$PROJECT_ROOT"

    # 等待数据就绪（检查 ECM minute_kline_cache 有今日数据，最长 30s）
    echo "   等待 mootdx 首次采集..."
    for i in $(seq 1 30); do
        MCNT=$(sqlite3 "$ECM_DB" "SELECT COUNT(*) FROM minute_kline_cache WHERE trade_date='$TODAY';" 2>/dev/null || echo "0")
        if [ "$MCNT" -gt 100 ] 2>/dev/null; then
            echo "✅ 数据进程就绪 (${i}s)"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "⚠️ 数据进程启动超时，API 仍将尝试启动"
        fi
        sleep 1
    done
fi

# ── 启动 API 进程 ──
echo "⏳ 启动 API 进程..."
cd "$PROJECT_ROOT/backend"
DATA_DAEMON_RUNNING=1 "$VENV_PYTHON" run.py --port 5001 &
API_PID=$!
cd "$PROJECT_ROOT"

# 等待 API 就绪（最长 15s）
for i in $(seq 1 15); do
    if curl -sf http://127.0.0.1:5001/api/v3/health/live > /dev/null 2>&1; then
        echo "✅ API 进程就绪 (${i}s)"
        break
    fi
    sleep 1
done

# ── 打开浏览器 ──
echo "🌐 打开浏览器..."
open "http://localhost:5001/dashboard"

echo ""
echo "═══════════════════════════════════════════════"
echo "   系统就绪"
echo "   仪表盘: http://localhost:5001/dashboard"
echo "   Ctrl+C 停止服务"
echo "═══════════════════════════════════════════════"

# 等待任意进程退出
wait $API_PID $DATA_PID 2>/dev/null
