.PHONY: dev-build dev-run docker-build docker-up docker-down clean \
        docker-build-nc docker-logs docker-logs-backend docker-logs-frontend \
        docker-restart-backend docker-restart-frontend status help

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

## 无缓存构建（当 package.json 或 Dockerfile 变更时使用）
docker-build-nc:
	docker compose build --no-cache

## 启动全量 Docker 服务
docker-up:
	docker compose up -d

## 停止 Docker 服务
docker-down:
	docker compose down

## 查看所有服务日志
docker-logs:
	docker compose logs -f

## 仅查看后端日志
docker-logs-backend:
	docker compose logs -f backend

## 仅查看前端日志
docker-logs-frontend:
	docker compose logs -f frontend

## 重启单个服务
docker-restart-backend:
	docker compose restart backend

docker-restart-frontend:
	docker compose restart frontend

## 查看镜像大小
docker-images:
	docker images astock* --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

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
	@echo ""
	@echo "--- 开发环境 ---"
	@echo "  make dev          — 启动开发环境（DB + 后端 + 前端）"
	@echo "  make dev-db       — 仅启动数据库"
	@echo "  make dev-backend  — 仅启动后端"
	@echo "  make dev-frontend — 仅启动前端"
	@echo "  make dev-build    — 构建前端产物"
	@echo ""
	@echo "--- Docker 部署 ---"
	@echo "  make docker-build      — 构建全部 Docker 镜像"
	@echo "  make docker-build-nc   — 无缓存构建（解决构建缓存问题）"
	@echo "  make docker-up         — 启动全量部署"
	@echo "  make docker-down       — 停止部署"
	@echo "  make docker-logs       — 查看所有服务日志"
	@echo "  make docker-logs-backend  — 仅查看后端日志"
	@echo "  make docker-logs-frontend — 仅查看前端日志"
	@echo "  make docker-images     — 查看镜像大小"
	@echo "  make docker-restart-backend  — 重启后端"
	@echo "  make docker-restart-frontend — 重启前端"
	@echo ""
	@echo "--- 工具 ---"
	@echo "  make status  — 查看 Docker + Git 状态"
	@echo "  make clean   — 清理构建产物"

.DEFAULT_GOAL := help


# ============ 代码质量 & CI ============

## Python 代码检查
lint:
	cd backend && ruff check app/ tests/

## Python 类型检查
typecheck:
	cd backend && mypy app/

## 运行后端测试
test:
	cd backend && python -m pytest tests/ -v

## 运行所有质量检查
check: lint typecheck test

## 前端构建检查
frontend-check:
	cd frontend/vue-project && npx vite build --logLevel error

## 完整的 CI 流水线
ci: lint typecheck frontend-check
	@echo "✅ CI 全部通过"