FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy pre-installed packages from builder
COPY --from=builder /install /usr/local

# Copy minimal app code (exclude dev/test artifacts)
COPY app/ /app/app/
COPY run.py config.py /app/
COPY sql/ /app/sql/
COPY migrations/ /app/migrations/

# Clean up dev artifacts
RUN find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
    find /app -type f -name "*.pyc" -delete

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/api/v3/health || exit 1

CMD ["gunicorn", "-w", "2", "--worker-class", "eventlet", "--bind", "0.0.0.0:5001", "--timeout", "120", "run:app"]
