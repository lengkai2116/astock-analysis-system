#!/bin/bash
# ============================================
# A股分析系统 — macOS 启动脚本（无 Docker）
# ============================================
# 双击或在终端运行即可
# 需要: Python 3.10+

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================="
echo "  A股股票分析决策支持系统"
echo "  双击即用 · 无需 Docker"
echo "=================================="
echo ""

# ---- 1. 检查 Python ----
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python 3，请安装 Python 3.10+"
    exit 1
fi

# ---- 2. 创建 .env（首次） ----
if [ ! -f ".env" ]; then
    echo "[首次] 正在从模板创建 .env 配置文件..."
    cp .env.example .env
    echo ""
    echo "⚠ 请编辑 .env 文件，填入以下信息："
    echo "   - TUSHARE_TOKEN=你的 Tushare Pro Token"
    echo "   - DEEPSEEK_API_KEY=你的 DeepSeek API Key"
    echo ""
    open -e .env 2>/dev/null || nano .env
    echo "填写完成后按回车继续..."
    read -r
fi

# ---- 3. 设置数据目录 ----
export DATA_DIR="${SCRIPT_DIR}/data"
mkdir -p "$DATA_DIR"

# ---- 4. 构建前端（首次） ----
if [ ! -f "frontend/vue-project/dist/index.html" ]; then
    echo "[信息] 首次启动，正在构建前端..."
    cd frontend/vue-project
    
    if [ ! -d "node_modules" ]; then
        if ! command -v node &> /dev/null; then
            echo "[警告] 未找到 Node.js，无法构建前端"
            echo "请安装 Node.js 18+ 后重试"
            exit 1
        fi
        echo "[信息] 安装前端依赖..."
        npm install
    fi
    
    npm run build
    if [ $? -ne 0 ]; then
        echo "[错误] 前端构建失败"
        exit 1
    fi
    cd "$SCRIPT_DIR"
    echo "[完成] 前端构建完成"
fi

# ---- 5. 安装后端依赖（首次） ----
if [ ! -d "backend/.venv" ]; then
    echo "[信息] 首次启动，正在创建 Python 虚拟环境..."
    cd backend
    python3 -m venv .venv
    echo "[信息] 安装后端依赖..."
    .venv/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[错误] 安装后端依赖失败"
        exit 1
    fi
    cd "$SCRIPT_DIR"
    echo "[完成] 后端依赖安装完成"
fi

# ---- 6. 检查是否已在运行 ----
if curl -s -o /dev/null http://localhost:5001/api/v3/health 2>/dev/null; then
    echo "[信息] 服务已在运行"
    open http://localhost:5001
    exit 0
fi

# ---- 7. 启动后端 ----
echo "[启动] 正在启动后端服务（端口 5001）..."
cd backend
DATA_DIR="${SCRIPT_DIR}/data" .venv/bin/python run.py --port 5001 &
BACKEND_PID=$!
cd "$SCRIPT_DIR"

# ---- 8. 等待服务就绪 ----
echo "[等待] 检测服务状态..."
for i in $(seq 1 30); do
    sleep 2
    if curl -s -o /dev/null http://localhost:5001/api/v3/health 2>/dev/null; then
        echo ""
        echo "✅ 服务已就绪！"
        echo "────────────────────────────"
        echo "  访问地址: http://localhost:5001"
        echo "  停止服务: kill $BACKEND_PID"
        echo "────────────────────────────"
        echo ""
        open http://localhost:5001
        exit 0
    fi
done

echo "[错误] 服务启动超时"
exit 1
