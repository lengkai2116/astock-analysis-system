.PHONY: dev-build dev-run docker-build docker-up docker-down clean \
        docker-build-nc docker-logs docker-logs-backend docker-logs-frontend \
        docker-restart-backend docker-restart-frontend status help

# ============ 开发环境 ============

## 启动前端原型服务器（端口 8082，自动代理 API 到 5001）
dev-frontend:
	cd _ui-prototype && python3 serve.py --port 8082

## 启动后端开发服务器（端口 5001，Gunicorn + sync worker）
dev-backend:
	cd backend && python -m gunicorn -c gunicorn_config.py "app:create_app()"

## 启动数据库依赖（PostgreSQL + Redis）
dev-db:
	docker compose up -d postgres redis

## 一键启动开发环境（DB + 后端 + 前端原型）
dev: dev-db
	@echo "=== 启动后端 ==="
	cd backend && python run.py --port 5001 &
	@sleep 2
	@echo "=== 启动前端原型 ==="
	cd _ui-prototype && python3 serve.py --port 8082 &
	@sleep 1
	@echo "✅ 打开 http://localhost:8082"

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
	@echo "  make dev          — 启动开发环境（DB + 后端 + 前端原型）"
	@echo "  make dev-db       — 仅启动数据库"
	@echo "  make dev-backend  — 仅启动后端"
	@echo "  make dev-frontend — 仅启动前端原型（端口 8082）"
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

# L8修复：目标在 cd backend 后执行，路径用相对 backend 的 .venv（此前 backend/.venv 在 cd 后失效）
PYTHON = .venv/bin/python
RUFF = .venv/bin/ruff
MYPY = .venv/bin/mypy

## Python 代码检查
lint:
	cd backend && $(RUFF) check app/ tests/

## Python 类型检查
typecheck:
	cd backend && $(MYPY) app/

## 运行后端测试
test:
	cd backend && $(PYTHON) -m pytest tests/ -v

## 运行所有质量检查
check: lint typecheck test

## 完整的 CI 流水线
ci: lint typecheck
	@echo "✅ CI 全部通过"
