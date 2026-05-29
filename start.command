#!/bin/bash
# A股分析系统 — 一键启动 (macOS)
# 双击此文件即可启动全部服务并打开浏览器

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  A股分析系统 - 启动中..."
echo "============================================"

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
  echo "[ERROR] Docker 未运行，请先启动 Docker Desktop"
  echo "按回车键退出..."
  read -r
  exit 1
fi

# 启动服务
echo "[1/2] 启动容器..."
docker compose up -d --build

# 等待服务就绪
echo "[2/2] 等待服务就绪..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:9000/health 2>/dev/null | grep -q 200; then
    echo "  ✅ 前端就绪 (http://localhost:9000)"
    break
  fi
  sleep 1
done

# 打开浏览器
echo ""
echo "✅ 启动完成！正在打开浏览器..."
open http://localhost:9000

echo ""
echo "关闭终端窗口即可停止（后台服务继续运行）"
echo "如需停止服务: docker compose down"
