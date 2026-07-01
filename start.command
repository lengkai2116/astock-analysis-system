#!/bin/bash
# A股分析系统 — 启动脚本
# 裸跑模式，无需 Docker

set -e
cd "$(dirname "$0")"

# ── 如果服务已在运行，直接打开浏览器 ──
if curl -s -o /dev/null http://localhost:5001/api/v3/health 2>/dev/null; then
    open http://localhost:5001
    exit 0
fi

# ── 环境初始化 ──
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# ── 数据目录 ──
DATA_DIR="${DATA_DIR:-$HOME/Library/Application Support/Astock}"
export DATA_DIR
mkdir -p "$DATA_DIR/duckdb/temp" "$DATA_DIR/logs"

# ── 日志 ──
LOG_FILE="$DATA_DIR/logs/start.log"
exec > "$LOG_FILE" 2>&1

echo "[$(date)] 启动 A股分析系统..."
echo "  DATA_DIR=$DATA_DIR"

# ── 数据库首次初始化 ──
SQLITE_DB="$DATA_DIR/app.db"
export DATABASE_URL="sqlite:///$SQLITE_DB"
if [ ! -f "$SQLITE_DB" ]; then
    echo "  [首次运行] 初始化数据库..."
    python3 backend/run.py --init-db
fi

# ── 后端服务端口 ──
export FLASK_PORT=5001

# ── 启动后端 ──
python3 backend/run.py --port 5001 &
SERVER_PID=$!
echo "  PID=$SERVER_PID"

# ── 等待服务就绪 (最多 30 秒) ──
for i in $(seq 1 15); do
    if curl -s -o /dev/null "http://localhost:5001/api/v3/health"; then
        break
    fi
    sleep 2
done

# ── 打开浏览器 ──
open "http://localhost:5001"
echo "[$(date)] 系统就绪 → http://localhost:5001"

# ── 保持进程 ──
wait $SERVER_PID
