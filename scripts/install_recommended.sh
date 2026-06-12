#!/bin/bash
# =========================================================
# A股股票分析系统 - 推荐工具一键安装脚本
# =========================================================
# 用法: bash scripts/install_recommended.sh
# 建议 Python 3.11 环境中运行

set -e

echo "=========================================="
echo "  🔧 开始安装推荐工具..."
echo "=========================================="

# === 第一阶段：代码质量 ===
echo ""
echo "【1/5】代码质量工具..."
pip install ruff mypy black pre-commit

# === 第二阶段：测试 ===
echo ""
echo "【2/5】测试增强..."
pip install pytest-cov pytest-xdist responses

# === 第三阶段：量化金融 ===
echo ""
echo "【3/5】量化金融库..."

# TA-Lib 需要系统库
if ! brew list ta-lib &>/dev/null; then
    echo "  安装 TA-Lib 系统库..."
    brew install ta-lib
fi
pip install TA-Lib

pip install qlib empyrical pyfolio mplfinance ffn scikit-learn \
    statsmodels xgboost lightgbm

# === 第四阶段：AI/数据工具 ===
echo ""
echo "【4/5】AI + 数据处理..."
pip install openai tiktoken sentence-transformers chromadb \
    polars pyarrow orjson psutil xxhash \
    APScheduler structlog icecream ipdb uv

# === 第五阶段：前端 ===
echo ""
echo "【5/5】前端工具..."
cd frontend/vue-project
npm install -D typescript @types/node vitest @vue/test-utils \
    vite-plugin-pwa pinia-plugin-persistedstate sass
cd ../..

echo ""
echo "=========================================="
echo "  ✅ 推荐工具安装完成！"
echo "=========================================="
echo ""
echo "建议下一步操作："
echo "  1. pre-commit install    # 启用提交前检查"
echo "  2. python -m pytest      # 运行测试确认无回归"
echo "  3. ruff check backend/   # 代码质量检查"
