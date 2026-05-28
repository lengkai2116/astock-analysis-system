#!/bin/bash

# A股分析系统 - 后端依赖安装脚本
# 创建日期: 2026-05-24

echo "=========================================="
echo "  A股分析系统 - 后端环境配置"
echo "=========================================="
echo ""

# 检查Python版本
echo "1. 检查Python版本..."
PYTHON_VERSION=$(python --version 2>&1 || python3 --version 2>&1)
echo "$PYTHON_VERSION"
echo ""

# 检查是否在正确的目录
if [ ! -f "requirements.txt" ]; then
    echo "✗ 错误: 找不到 requirements.txt"
    echo "请确保在 backend/ 目录下运行此脚本"
    exit 1
fi

# 安装Python依赖
echo "2. 安装Python依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "✗ 依赖安装失败，请检查网络连接"
    exit 1
fi

echo ""
echo "✓ Python依赖安装完成"
echo ""

# 环境检查
echo "3. 环境完整性检查..."
python -c "
import sys
print('Python: ✓ 正常')

try:
    import flask
    print('Flask: ✓ 正常')
except ImportError:
    print('Flask: ✗ 缺失')
    sys.exit(1)

try:
    import flask_socketio
    print('Flask-SocketIO: ✓ 正常')
except ImportError:
    print('Flask-SocketIO: ✗ 缺失')
    sys.exit(1)

try:
    import redis
    print('Redis: ✓ 正常')
except ImportError:
    print('Redis: ✗ 缺失')
    sys.exit(1)

try:
    import pandas
    print('Pandas: ✓ 正常')
except ImportError:
    print('Pandas: ✗ 缺失')
    sys.exit(1)

try:
    import numpy
    print('NumPy: ✓ 正常')
except ImportError:
    print('NumPy: ✗ 缺失')
    sys.exit(1)

print('')
print('==========================================')
print('  ✓ 所有依赖检查通过！')
print('==========================================')
"

if [ $? -ne 0 ]; then
    echo ""
    echo "✗ 环境检查发现问题，请重新运行安装"
    exit 1
fi

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 启动后端: python run.py"
echo ""
