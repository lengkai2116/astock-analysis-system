# ═══════════════════════════════════════════════════
# Backend Dockerfile（可选 — 仅 Docker 部署时使用）
# 裸跑部署方式见 _项目运行手册.md 
# ═══════════════════════════════════════════════════
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 清理开发/测试产物
RUN find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app -type f -name "*.pyc" -delete; \
    rm -rf /app/tests/ /app/templates/ /app/sql/ /app/instance/ /app/logs/

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/api/v3/health || exit 1

CMD ["gunicorn", "-w", "2", "--worker-class", "eventlet", "--bind", "0.0.0.0:5001", "--timeout", "120", "run:app"]
