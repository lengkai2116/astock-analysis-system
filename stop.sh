#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "正在停止 A股分析系统后端..."
pkill -f "python run.py --port 5001" 2>/dev/null
echo "已停止"
