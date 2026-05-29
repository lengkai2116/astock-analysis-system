#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 如果服务已在运行，直接打开浏览器
if curl -s -o /dev/null http://localhost:9000/health 2>/dev/null; then
  open http://localhost:9000
  exit 0
fi

# 首次启动
echo "首次启动，正在构建容器..."
docker compose up -d --build

echo "正在打开浏览器..."
open http://localhost:9000
