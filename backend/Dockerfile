FROM python:3.11-slim

WORKDIR /app

# PyPI 镜像源（国内构建时传 --build-arg PIP_INDEX_URL=...）
ARG PIP_INDEX_URL=https://pypi.org/simple/
ARG PIP_TRUSTED_HOST=pypi.org

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i ${PIP_INDEX_URL} \
    --trusted-host ${PIP_TRUSTED_HOST} \
    -r requirements.txt

COPY . .

RUN find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app -type f -name "*.pyc" -delete; \
    rm -rf /app/tests/ /app/templates/ /app/sql/ /app/instance/ /app/logs/

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/api/v3/health || exit 1

CMD ["gunicorn", "-w", "2", "--worker-class", "eventlet", "--bind", "0.0.0.0:5001", "--timeout", "120", "run:app"]
