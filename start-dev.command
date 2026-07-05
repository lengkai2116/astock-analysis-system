#!/bin/bash
# A股分析系统 - 全栈开发启动器（后端 + Vue前端 + UI原型）
# 双击此文件 → 后端 Flask(:5001) + Vue前端(:9000) + UI原型(:8082) 同时启动
# Ctrl+C → 全部停止

cd "$(dirname "$0")" || exit 1
ROOT="$PWD"

VENV_PY="$ROOT/backend/.venv/bin/python"
PROTO_PY="/Users/kalence/.local/bin/python3.11"
if [ ! -f "$VENV_PY" ]; then
    echo "❌ 虚拟环境不存在，请先双击 prepare-dev.command"
    read -r; exit 1
fi

clear
echo "═══════════════════════════════════════════════"
echo "  A股分析系统 · 全栈开发"
echo "  后端 Flask  → http://localhost:5001"
echo "  Vue 前端     → http://localhost:9000"
echo "  HTML原型     → http://localhost:8082/dashboard.html"
echo "  Ctrl+C → 全部停止"
echo "═══════════════════════════════════════════════"

export FLASK_ENV=development

# 清理旧进程
pkill -f "run.py.*port 5001" 2>/dev/null
pkill -f "vite.*9000" 2>/dev/null
pkill -f "serve.py" 2>/dev/null
sleep 0.5

# ── 清理 DuckDB 僵尸锁文件 ─────────────────────────
DUCKDB_DIR="$ROOT/backend/instance/duckdb"
if [ -d "$DUCKDB_DIR" ]; then
    find "$DUCKDB_DIR" \( -name "*.wal" -o -name "*.tmp" \) -mmin +1 -delete 2>/dev/null
    echo "  ✅ DuckDB 锁文件已清理"
fi

# ── 构建前端 dist ──────────────────────────────────
if [ ! -d "$ROOT/frontend/vue-project/dist" ]; then
    echo "  📦 前端 dist 不存在，正在构建..."
    (cd "$ROOT/frontend/vue-project" && npx vite build) 2>&1 | tail -1
    echo "  ✅ 前端构建完成"
fi

# 启动后端
cd "$ROOT/backend" || exit 1
"$VENV_PY" run.py --port 5001 &
BPID=$!

# 启动 Vue 前端开发服务器
cd "$ROOT/frontend/vue-project" || exit 1
npx vite --port 9000 &
VPID=$!

# 启动 UI 原型服务（HTML 原型，非 Vue 前端）
cd "$ROOT/_ui-prototype" || exit 1
"$PROTO_PY" serve.py &
PPID=$!

cleanup() {
    echo ""
    echo "⏹ 停止中..."
    kill $BPID $VPID $PPID 2>/dev/null
    wait $BPID $VPID $PPID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

sleep 2

# ── 等待后端就绪（最多 15s） ────────────────────────
echo "  ⏳ 等待后端启动..."
for i in $(seq 1 15); do
    if curl -s --max-time 2 http://127.0.0.1:5001/api/v3/health 2>/dev/null | grep -q '"status":"healthy"\|"success":true'; then
        echo "  ✅ 后端就绪（${i}s）"
        break
    fi
    sleep 1
done

echo "  ✅ 打开仪表盘..."
open http://localhost:5001/dashboard.html 2>/dev/null

wait
