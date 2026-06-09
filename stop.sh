#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Stopping A-stock Analysis System..."
docker compose down --timeout 30
echo "System stopped. Data volumes preserved."
echo "Wipe data: docker compose down -v (careful!)"
