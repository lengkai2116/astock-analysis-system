#!/bin/bash
# A股分析系统 — 一键启动（API 进程 + 数据进程 + 浏览器）
# 说明：launchd 数据进程因 macOS Desktop TCC 限制已停用（.disabled），
#       数据进程改由本脚本检查并启动（单实例，避免 SQLite 锁冲突）

cd "$(dirname "$0")"
PROJECT_ROOT="$PWD"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"

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
    echo "正在停止 API 服务（数据进程保持运行）..."
    kill $API_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

clear
echo "═══════════════════════════════════════════════"
echo "   A股分析系统 — 启动"
echo ""
echo "   API 进程 → 浏览器"
echo "   数据进程 → 检查并启动（单实例）"
echo "═══════════════════════════════════════════════"
echo ""

# ── 数据进程：检查是否已在运行，未运行则启动 ──
if pgrep -f "backend/data_daemon.py|data_daemon.py" > /dev/null 2>&1; then
    echo "✅ 数据进程已在运行，跳过启动"
else
    echo "⏳ 启动数据进程..."
    cd "$PROJECT_ROOT/backend"
    DATA_DIR="$PROJECT_ROOT/data" nohup "$VENV_PYTHON" data_daemon.py >> "$PROJECT_ROOT/backend/logs/data_daemon.log" 2>&1 &
    echo "   数据进程已启动（后台运行）"
    cd "$PROJECT_ROOT"
fi

# ── 327阶段5：等待数据进程就绪（确保采集/自愈/积压消费已启动，最长 30s） ──
echo "⏳ 等待数据进程就绪..."
DAEMON_LAST_LINE=""
for i in $(seq 1 30); do
    if pgrep -f "backend/data_daemon.py|data_daemon.py" > /dev/null 2>&1; then
        # 检查日志最后一行是否为本实例"进入主循环"（避免历史日志残留误判）
        DAEMON_LAST_LINE=$(tail -1 "$PROJECT_ROOT/backend/logs/data_daemon.log" 2>/dev/null)
        if echo "$DAEMON_LAST_LINE" | grep -q "进入主循环"; then
            echo "✅ 数据进程就绪 (${i}s)"
            break
        fi
    fi
    sleep 1
done
if ! pgrep -f "backend/data_daemon.py|data_daemon.py" > /dev/null 2>&1; then
    echo "⚠️ 数据进程未能启动！API 将运行但预计算/采集不可用"
    echo "   请检查 backend/logs/data_daemon.log"
fi

# ── 检查 API 是否已在运行 ──
if curl -sf http://127.0.0.1:5001/api/v3/health/live > /dev/null 2>&1; then
    echo "✅ API 已在运行，直接打开浏览器"
    open "http://localhost:5001/dashboard"
    exit 0
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
sleep 1
open "http://localhost:5001/dashboard"

# ── 后台检查数据新鲜度（327阶段5：不阻塞启动流程） ──
{
    sleep 5
    FRESH=$(curl -s --max-time 5 "http://127.0.0.1:5001/api/v3/health/data-freshness" 2>/dev/null)
    if echo "$FRESH" | grep -q '"success":true'; then
        DAILY=$(echo "$FRESH" | grep -o '"daily_cache":{[^}]*"latest_date": *"[^"]*"' | grep -o '"latest_date": *"[^"]*"' | head -1 | cut -d'"' -f4)
        SNAP=$(echo "$FRESH" | grep -o '"treemap_snapshot":{[^}]*"latest_date": *"[^"]*"' | grep -o '"latest_date": *"[^"]*"' | head -1 | cut -d'"' -f4)
        PIPE=$(echo "$FRESH" | grep -o '"pipeline":{[^}]*' | head -1)
        echo "ℹ️  数据新鲜度: 日线=${DAILY:-未知} 快照=${SNAP:-未知}"
        echo "   管道状态: ${PIPE:-未知}"
        if echo "$FRESH" | grep -q '"running": *[1-9]'; then
            echo "   ⚠️ 管道有环节运行中，日终预计算完成后自动更新快照"
        fi
    else
        echo "ℹ️  健康检查暂不可用（数据守护进程启动中）"
    fi
} &

echo ""
echo "═══════════════════════════════════════════════"
echo "   系统就绪"
echo "   仪表盘: http://localhost:5001/dashboard"
echo "   Ctrl+C 停止 API 进程（数据进程继续后台运行）"
echo "═══════════════════════════════════════════════"

# 等待 API 进程退出
wait $API_PID 2>/dev/null
