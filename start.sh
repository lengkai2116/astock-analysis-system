#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy from .env.example and configure."
    exit 1
fi

echo "Starting A-stock Analysis System..."
docker compose up -d --wait

echo ""
echo "System started:"
echo "  Frontend: http://localhost:9000"
echo "  Backend:  http://localhost:5001"
echo "  Health:   http://localhost:5001/api/v3/health"
echo ""
echo "Logs: docker compose logs -f"
echo "Stop:  ./stop.sh"
