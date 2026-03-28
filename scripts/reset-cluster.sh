#!/usr/bin/env bash
# reset-cluster.sh — Tear down and reset the entire stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== IncidentCommander Reset ==="

cd "$ROOT_DIR"

# Stop all services
echo "[1/3] Stopping all services..."
docker compose --profile full down --remove-orphans 2>/dev/null || true
docker compose down --remove-orphans

# Remove volumes (data reset)
echo "[2/3] Removing volumes..."
docker compose down -v

# Rebuild
echo "[3/3] Rebuilding images..."
docker compose build --no-cache

echo ""
echo "=== Reset Complete ==="
echo "Run ./scripts/setup-cluster.sh to start fresh."
