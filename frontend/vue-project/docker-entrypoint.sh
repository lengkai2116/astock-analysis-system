#!/bin/sh
set -e

# ============================================
# 运行时环境变量注入
# ============================================
# 在容器启动时，将 API_BASE_URL 环境变量注入到 index.html
# 这样就无需在构建时烘焙环境变量，同一份镜像可部署到不同环境
#
# 用法:
#   docker run -e API_BASE_URL=http://api.example.com ...
#   默认值为空（使用相对路径，由 Nginx 反向代理处理）
# ============================================

API_BASE_URL="${API_BASE_URL:-}"

if [ -n "$API_BASE_URL" ]; then
    echo "[entrypoint] 注入 API_BASE_URL: $API_BASE_URL"
    sed -i "s|window\.__API_BASE__ = window\.__API_BASE__ || '';|window.__API_BASE__ = '$API_BASE_URL';|g" \
        /usr/share/nginx/html/index.html
else
    echo "[entrypoint] 使用默认 API_BASE_URL（空值 = 相对路径）"
fi

echo "[entrypoint] 启动 Nginx..."

exec nginx -g "daemon off;"
