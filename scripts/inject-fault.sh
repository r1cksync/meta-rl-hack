#!/usr/bin/env bash
# inject-fault.sh — Inject a chaos fault scenario
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

usage() {
  echo "Usage: $0 <task>"
  echo ""
  echo "Tasks:"
  echo "  easy    — Redis connection pool exhaustion (NetworkChaos 500ms latency)"
  echo "  medium  — Cascading OOM in payments-api (StressChaos 4×256MB)"
  echo "  hard    — Silent decimal corruption (deploy buggy v2.3.2)"
  echo "  clean   — Remove all injected faults"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

TASK="$1"

case "$TASK" in
  easy)
    echo "=== Injecting Task 1: Redis Connection Pool Exhaustion ==="
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
      kubectl apply -f "$ROOT_DIR/chaos/easy-redis-latency.yaml"
    else
      echo "No K8s cluster detected. Simulating with Docker..."
      # Add latency to Redis using tc (traffic control) in the container
      docker compose exec redis sh -c \
        "apk add --no-cache iproute2 2>/dev/null; tc qdisc add dev eth0 root netem delay 500ms 50ms 75%" \
        2>/dev/null || echo "Latency injection requires iproute2 in Redis container"
    fi
    echo "Fault injected. Redis now has 500ms±50ms latency."
    ;;

  medium)
    echo "=== Injecting Task 2: Cascading OOM ==="
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
      kubectl apply -f "$ROOT_DIR/chaos/medium-payments-memory-stress.yaml"
    else
      echo "No K8s cluster detected. Simulating with Docker..."
      # Reduce memory limit on payments-api to trigger OOM
      docker update --memory=128m --memory-swap=128m payments-api 2>/dev/null \
        || echo "Container memory update may require Docker restart"
    fi
    echo "Memory pressure applied to payments-api."
    ;;

  hard)
    echo "=== Injecting Task 3: Silent Decimal Corruption ==="
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
      kubectl set image deployment/payments-api \
        payments-api=payments-api:v2.3.2 -n ecommerce
      kubectl apply -f "$ROOT_DIR/chaos/hard-silent-decimal-corruption.yaml"
    else
      echo "No K8s cluster detected. In Docker mode, manually set:"
      echo "  SERVICE_VERSION=2.3.2 in payments-api environment"
      echo "  Then restart: docker compose restart payments-api"
    fi
    echo "Buggy version deployed."
    ;;

  clean)
    echo "=== Cleaning all faults ==="
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
      kubectl delete -f "$ROOT_DIR/chaos/" --ignore-not-found
      kubectl set image deployment/payments-api \
        payments-api=payments-api:v2.3.0 -n ecommerce 2>/dev/null || true
    else
      docker compose exec redis sh -c "tc qdisc del dev eth0 root 2>/dev/null" || true
      docker update --memory=0 payments-api 2>/dev/null || true
      docker compose restart payments-api 2>/dev/null || true
    fi
    echo "All faults cleaned."
    ;;

  *)
    usage
    ;;
esac
