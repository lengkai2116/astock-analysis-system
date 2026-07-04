#!/bin/bash
# A股分析系统 - 后端开发启动器
# 双击此文件 → Terminal 打开，后端启动，代码修改后自动重载
# 停止: Ctrl+C 或直接关闭窗口

cd "$(dirname "$0")" || exit 1
PROJECT_ROOT="$PWD"

VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 错误：找不到虚拟环境"
    echo "   请先双击 prepare-dev.command"
    read -r
    exit 1
fi

clear
echo "═══════════════════════════════════════════════"
echo "   A股分析系统 · 后端开发服务器"
echo ""
echo "   API:  http://localhost:5001"
echo "   健康:  http://localhost:5001/api/v3/health"
echo ""
echo "   修改 .py 文件 → 自动重载"
echo "   Ctrl+C 或关闭窗口 → 停止"
echo "═══════════════════════════════════════════════"
echo ""

# 开发模式（覆盖 .env 中的 production 设置）
export FLASK_ENV=development
# 开发模式使用 SQLite（.env 中的 DATABASE_URL 是 PG，开发时保持用 SQLite）
export DATABASE_URL=sqlite:///test.db
cd "$PROJECT_ROOT/backend" || exit 1
exec "$VENV_PYTHON" run.py --port 5001
