#!/usr/bin/env bash
# health-check.sh — Quick health check of all running services
set -euo pipefail

echo "=== IncidentCommander Health Check ==="
echo ""

check_service() {
  local name="$1"
  local url="$2"
  local response
  response=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null) || response="000"
  if [ "$response" = "200" ]; then
    printf "  %-25s ✓ UP (%s)\n" "$name" "$response"
  else
    printf "  %-25s ✗ DOWN (%s)\n" "$name" "$response"
  fi
}

echo "Application Services:"
check_service "Checkout Frontend" "http://localhost:3000"
check_service "Payments API" "http://localhost:4001/health"
check_service "Inventory Service" "http://localhost:4002/health"
check_service "Notification Service" "http://localhost:4003/health"
check_service "RL Agent" "http://localhost:8000/health"

echo ""
echo "Monitoring Stack:"
check_service "Prometheus" "http://localhost:9090/-/ready"
check_service "Grafana" "http://localhost:3001/api/health"
check_service "Loki" "http://localhost:3100/ready"
check_service "Jaeger" "http://localhost:16686"
check_service "Alertmanager" "http://localhost:9093/-/ready"

echo ""
echo "Infrastructure:"
check_service "MailHog" "http://localhost:8025"

# Check Docker containers
echo ""
echo "Docker Container Status:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
  || echo "  (docker compose not available or no containers running)"
