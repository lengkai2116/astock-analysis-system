FROM python:3.11-slim

WORKDIR /app

# 安装 curl（用于健康检查）
# curl not needed, healthcheck uses python

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/api/v3/health', timeout=5)" || exit 1

CMD ["gunicorn", "-w", "2", "--bind", "0.0.0.0:5001", "--timeout", "120", "run:app"]
