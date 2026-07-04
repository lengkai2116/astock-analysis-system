#!/bin/bash
# 243号方案 - Gunicorn 生产启动脚本
# 双击此文件启动 Gunicorn 4 workers（替代 Flask dev server）

cd "$(dirname "$0")" || exit 1

# 使用项目虚拟环境（.venv 在 backend/ 下）
VENV_PYTHON=".venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 虚拟环境不存在，请先运行 prepare-dev.command"
    exit 1
fi

# PostgreSQL + Redis 必须运行
if ! pg_isready -q 2>/dev/null; then
    echo "⚠️  PostgreSQL 未运行，尝试启动..."
    brew services start postgresql@16 2>/dev/null || {
        echo "❌ 无法启动 PostgreSQL"
        exit 1
    }
fi

if ! redis-cli ping &>/dev/null; then
    echo "⚠️  Redis 未运行，尝试启动..."
    brew services start redis 2>/dev/null || {
        echo "❌ 无法启动 Redis"
        exit 1
    }
fi

echo "═══════════════════════════════════════════════"
echo "  启动 Gunicorn（4 workers, eventlet）"
echo "  PostgreSQL ✅"
echo "  Redis       ✅"
echo "═══════════════════════════════════════════════"

exec "$VENV_PYTHON" -m gunicorn -c gunicorn_config.py "app:create_app()"
