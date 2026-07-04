#!/bin/bash
# A股分析系统 - 环境准备工具（首次运行前执行一次）
# 双击此文件 → PostgreSQL + Redis + 后端依赖 + 前端依赖
# 后续修改代码不需要再跑这个，只需双击 start-dev.command

cd "$(dirname "$0")" || exit 1
PROJECT_ROOT="$PWD"

clear
cat << "EOF"
╔══════════════════════════════════════════════════════════╗
║         A股分析系统 · 开发环境一键准备                   ║
║                                                         ║
║  本工具逐个检查并安装开发所需的全部依赖：                 ║
║    ① PostgreSQL 16（生产化数据层）                      ║
║    ② Redis（多 Worker WebSocket 广播）                  ║
║    ③ 后端 Python 虚拟环境 + pip 依赖                    ║
║    ④ 前端 npm 依赖（node_modules）                      ║
║                                                         ║
║  执行一次后，后续双击 start-dev.command 即可启动         ║
╚══════════════════════════════════════════════════════════╝
EOF

# ──────────────────────────────────────
# 0️⃣  PostgreSQL + Redis（生产化数据层）
# ──────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  0️⃣/4️⃣  PostgreSQL + Redis"
echo "═══════════════════════════════════════════════"

if ! command -v psql &>/dev/null; then
    echo "📦 安装 PostgreSQL 16..."
    brew install postgresql@16
    brew services start postgresql@16
    echo "✅ PostgreSQL 16 已安装并启动"
else
    echo "✅ PostgreSQL 已存在 ($(psql --version))"
    brew services start postgresql@16 2>/dev/null || true
fi

# 创建数据库（幂等）
createdb stock_analysis 2>/dev/null && echo "✅ 数据库 stock_analysis 已创建" || echo "✅ 数据库 stock_analysis 已存在"

if ! command -v redis-cli &>/dev/null; then
    echo "📦 安装 Redis..."
    brew install redis
    brew services start redis
    echo "✅ Redis 已安装并启动"
else
    echo "✅ Redis 已存在 ($(redis-cli --version))"
    brew services start redis 2>/dev/null || true
fi

# ──────────────────────────────────────
# ① 后端 Python 虚拟环境（含生产依赖）
# ──────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  ①/④ 后端 Python 虚拟环境 + 生产化依赖"
echo "═══════════════════════════════════════════════"

VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"

if [ -f "$VENV_PYTHON" ]; then
    echo "  ✅ 虚拟环境已存在：backend/.venv"
    # 快速检查关键依赖是否就绪（不重跑 pip install，避免长时间等待）
    echo "  🔍 快速检查关键 Python 依赖..."
    cd "$PROJECT_ROOT/backend" || exit 1
    "$VENV_PYTHON" -c "import flask; import flask_socketio; import dotenv; print('flask socketio dotenv OK')" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  ✅ Python 依赖已就绪"
    else
        echo "  ⌛ 部分依赖缺失，正在安装..."
        "$VENV_PYTHON" -m pip install flask flask-socketio python-dotenv -q 2>&1 | tail -3
        echo "  ✅ Python 依赖安装完成"
    fi
else
    echo "  🔧 创建虚拟环境..."
    cd "$PROJECT_ROOT/backend" || exit 1
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "  ❌ 虚拟环境创建失败！请确保已安装 Python 3.11+"
        echo ""
        echo "按 Enter 键退出..."
        read -r
        exit 1
    fi
    echo "  ✅ 虚拟环境已创建"
    echo "  ⌛ 安装 Python 依赖..."
    "$VENV_PYTHON" -m pip install -r requirements.txt 2>&1 | tail -5
    echo "  ✅ Python 依赖安装完成"
fi

# ── 补充：n确保 gunicorn + psycopg2 已在 venv 中
if [ -f "$VENV_PYTHON" ]; then
    "$VENV_PYTHON" -c "import gunicorn; import psycopg2; print('gunicorn+psycopg2 OK')" 2>/dev/null || {
        echo "  ⌛ 安装生产化依赖（gunicorn psycopg2）..."
        "$VENV_PYTHON" -m pip install gunicorn psycopg2-binary 2>&1 | tail -3
        echo "  ✅ gunicorn + psycopg2 已安装"
    }
fi

# ──────────────────────────────────────
# ② 前端 npm 依赖
# ──────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  ②/② 前端 npm 依赖"
echo "═══════════════════════════════════════════════"

# 检查 node_modules 是否完整（用 vite 做探针）
if [ -f "$PROJECT_ROOT/frontend/vue-project/node_modules/vite/package.json" ]; then
    echo "  ✅ node_modules 已就绪"
else
    echo "  🔧 清理残留文件..."
    rm -rf "$PROJECT_ROOT/frontend/vue-project/node_modules" 2>/dev/null
    rm -f "$PROJECT_ROOT/frontend/vue-project/package-lock.json" 2>/dev/null

    echo "  ⌛ 安装前端依赖（npm install）..."
    echo "     耗时约 30-120 秒..."
    cd "$PROJECT_ROOT/frontend/vue-project" || exit 1
    npm install 2>&1

    if [ $? -eq 0 ]; then
        echo "  ✅ 前端依赖已就绪"
    else
        echo ""
        echo "  ⚠️  npm install 失败。请尝试以下方式："
        echo ""
        echo "  方式 1：先运行 fix-npm.command（修复缓存权限）"
        echo "  方式 2：开启 VPN 后再试"
        echo "  方式 3：使用国内镜像"
        echo "     cd frontend/vue-project && npm install --registry=https://registry.npmmirror.com"
        echo ""
        echo "  前端无法启动不影响后端调试，可直接双击 start-backend.command"
    fi
fi

echo ""
echo "═══════════════════════════════════════════════"
echo ""
echo "✅ 环境准备完成！"
echo ""
echo "  现在可以："
echo "    - 双击 start-dev.command     → 全栈启动（后端+前端）"
echo "    - 双击 start-backend.command → 仅启动后端（调试 API）"
echo "    - 双击 stop-dev.command      → 停止全部服务器"
echo ""
echo "按 Enter 键退出..."
read -r
