#!/usr/bin/env bash
set -e
CLUSTER_NAME=${CLUSTER_NAME:-incident-commander}
kind delete cluster --name "$CLUSTER_NAME"
echo "✔ Cluster '$CLUSTER_NAME' deleted"
