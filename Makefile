.PHONY: dev-build dev-run docker-build docker-up docker-down clean

# ============ 开发环境 ============

## 构建前端
dev-build:
	cd frontend/vue-project && npm ci && npm run build

## 启动前端开发服务器（端口 9000，自动代理 API 到 5001）
dev-frontend:
	cd frontend/vue-project && npm run dev

## 启动后端开发服务器（端口 5001）
dev-backend:
	cd backend && python run.py --port 5001

## 启动数据库依赖（PostgreSQL + Redis）
dev-db:
	docker compose up -d postgres redis

## 一键启动开发环境（DB + 后端 + 前端）
dev: dev-db
	@echo "=== 启动后端 ==="
	cd backend && python run.py --port 5001 &
	@sleep 2
	@echo "=== 启动前端 ==="
	cd frontend/vue-project && npm run dev

# ============ Docker 部署 ============

## 构建全部 Docker 镜像
docker-build:
	docker compose build

## 启动全量 Docker 服务
docker-up:
	docker compose up -d

## 停止 Docker 服务
docker-down:
	docker compose down

## 查看服务日志
docker-logs:
	docker compose logs -f

## 重启单个服务
docker-restart-backend:
	docker compose restart backend

docker-restart-frontend:
	docker compose restart frontend

# ============ 工具 ============

## 清理构建产物
clean:
	rm -rf frontend/vue-project/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

## 查看服务状态
status:
	@echo "=== Docker 服务 ==="
	docker compose ps
	@echo ""
	@echo "=== Git 状态 ==="
	git status --short

## 帮助
help:
	@echo "可用命令："
	@echo "  make dev          — 启动开发环境（DB + 后端 + 前端）"
	@echo "  make dev-db       — 仅启动数据库"
	@echo "  make dev-backend  — 仅启动后端"
	@echo "  make dev-frontend — 仅启动前端"
	@echo "  make dev-build    — 构建前端产物"
	@echo "  make docker-build — 构建 Docker 镜像"
	@echo "  make docker-up    — 启动全量部署"
	@echo "  make docker-down  — 停止部署"
	@echo "  make clean        — 清理构建产物"

.DEFAULT_GOAL := help
