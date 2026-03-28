#!/usr/bin/env bash
# build-all.sh — Build all Docker images
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Building All Images ==="

cd "$ROOT_DIR"

services=("frontend" "backend/payments-api" "backend/inventory-service" "backend/order-worker" "backend/notification-service" "rl-agent")

for svc in "${services[@]}"; do
  name=$(basename "$svc")
  echo ""
  echo "--- Building $name ---"
  docker build -t "incident-commander-$name:latest" "$svc"
done

echo ""
echo "=== All images built ==="
docker images | grep incident-commander
