FROM python:3.11-slim

WORKDIR /app

# 安装 curl（用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/api/v3/health || exit 1

CMD ["flask", "run", "--host=0.0.0.0", "--port=5001"]
