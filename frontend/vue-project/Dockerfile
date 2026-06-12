# ---- Build Stage ----
FROM node:20-alpine AS builder

WORKDIR /app

# 先安装依赖（利用 Docker 层缓存）
COPY package.json package-lock.json ./
RUN npm ci

# 构建
COPY . .
RUN npm run build

# ---- Runtime Stage ----
# ═══════════════════════════════════════════════════
# Frontend Nginx Dockerfile（可选 — 仅 Docker 部署时使用）
# 裸跑部署时由 Flask 直接托管前端
# ═══════════════════════════════════════════════════
FROM nginx:alpine

# 安装 wget（用于 HEALTHCHECK）
RUN apk add --no-cache wget

# 复制 Nginx 配置
COPY --from=builder /app/nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制容器入口脚本（运行时注入环境变量）
COPY docker-entrypoint.sh /docker-entrypoint.sh

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/health || exit 1

EXPOSE 80
ENTRYPOINT ["/docker-entrypoint.sh"]
