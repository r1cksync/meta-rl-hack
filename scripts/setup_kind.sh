#!/usr/bin/env bash
# Linux/macOS equivalent of setup_kind.ps1
set -euo pipefail

CLUSTER_NAME=${CLUSTER_NAME:-incident-commander}
KIND_IMAGE=${KIND_IMAGE:-kindest/node:v1.30.4}
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Checking prerequisites"
for bin in docker kind kubectl; do
  command -v "$bin" >/dev/null 2>&1 || { echo "'$bin' not found on PATH"; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker daemon not reachable"; exit 1; }

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "==> Cluster '$CLUSTER_NAME' already exists — reusing"
else
  echo "==> Creating kind cluster '$CLUSTER_NAME' ($KIND_IMAGE)"
  kind create cluster --name "$CLUSTER_NAME" --image "$KIND_IMAGE" --wait 60s
fi

kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo "==> Applying namespaces"
kubectl apply -f "$REPO_ROOT/rl-agent/sample_app/namespaces.yaml"

echo "==> Applying base deployments"
kubectl apply -R -f "$REPO_ROOT/rl-agent/sample_app/base"

echo "==> Waiting for pods (~60s)"
for ns in ic-payments ic-frontend ic-auth; do
  kubectl -n "$ns" wait --for=condition=available --timeout=180s deployment --all
done

kubectl get pods -A

cat <<EOF

✔ Local K8s cluster ready.

Next steps:
  export REAL_K8S=true
  cd rl-agent
  uvicorn server:app --host 127.0.0.1 --port 7860

Inject a fault:
  curl -s -X POST http://localhost:7860/k8s/inject \\
    -H 'Content-Type: application/json' \\
    -d '{"fault_type":"oom_kill"}'

Teardown: scripts/teardown_kind.sh
EOF
