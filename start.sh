#!/bin/bash
# ============================================
# A股分析系统 — Linux 启动脚本（无 Docker）
# ============================================
# 需要: Python 3.10+

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================="
echo "  A股股票分析决策支持系统"
echo "  无需 Docker"
echo "=================================="

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python 3"
    exit 1
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[首次] 请编辑 .env 填入 API Key"
    ${EDITOR:-vim} .env
fi

export DATA_DIR="${SCRIPT_DIR}/data"
mkdir -p "$DATA_DIR"

if [ ! -f "frontend/vue-project/dist/index.html" ]; then
    cd frontend/vue-project
    [ ! -d "node_modules" ] && npm install
    npm run build
    cd "$SCRIPT_DIR"
fi

if [ ! -d "backend/.venv" ]; then
    cd backend
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    cd "$SCRIPT_DIR"
fi

if curl -s -o /dev/null http://localhost:5001/api/v3/health 2>/dev/null; then
    echo "[信息] 服务已在运行: http://localhost:5001"
    exit 0
fi

cd backend
DATA_DIR="${SCRIPT_DIR}/data" .venv/bin/python run.py --port 5001 &
echo "服务已启动: http://localhost:5001"
