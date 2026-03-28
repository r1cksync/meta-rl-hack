#!/usr/bin/env bash
# setup-cluster.sh — Bootstrap a local k3s cluster with all dependencies
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== IncidentCommander Cluster Setup ==="

# Check prerequisites
for cmd in docker kubectl helm; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is required but not installed."
    exit 1
  fi
done

# 1. Start Docker Compose stack (data tier + app services)
echo "[1/5] Starting Docker Compose stack..."
cd "$ROOT_DIR"
docker compose up -d --build

# 2. Wait for services to be healthy
echo "[2/5] Waiting for services to be healthy..."
services=("payments-api" "inventory-service" "notification-service")
for svc in "${services[@]}"; do
  echo -n "  Waiting for $svc..."
  timeout=60
  while [ $timeout -gt 0 ]; do
    if docker compose ps "$svc" 2>/dev/null | grep -q "healthy"; then
      echo " ready"
      break
    fi
    sleep 2
    timeout=$((timeout - 2))
  done
  if [ $timeout -le 0 ]; then
    echo " TIMEOUT (continuing anyway)"
  fi
done

# 3. Start monitoring stack
echo "[3/5] Starting monitoring stack..."
docker compose --profile monitoring up -d

# 4. Start traffic generator
echo "[4/5] Starting traffic generator..."
docker compose --profile traffic up -d

# 5. Run database migrations
echo "[5/5] Running database migrations..."
docker compose exec -T payments-api alembic upgrade head 2>/dev/null || echo "  (migrations skipped or already applied)"

echo ""
echo "=== Setup Complete ==="
echo "  Storefront:      http://localhost:3000"
echo "  Payments API:    http://localhost:4001"
echo "  Inventory API:   http://localhost:4002"
echo "  RL Agent:        http://localhost:8000"
echo "  Grafana:         http://localhost:3001  (admin/admin)"
echo "  Prometheus:      http://localhost:9090"
echo "  Jaeger:          http://localhost:16686"
echo "  Locust:          http://localhost:8089"
echo "  MailHog:         http://localhost:8025"
