#!/usr/bin/env bash
set -e
CLUSTER_NAME=${CLUSTER_NAME:-incident-commander}
REGION=${AWS_REGION:-us-east-1}
KEEP_BUCKET=${KEEP_BUCKET:-0}

echo "==> Deleting EKS cluster '$CLUSTER_NAME' (~10 min)"
eksctl delete cluster --name "$CLUSTER_NAME" --region "$REGION" --wait

if [ "$KEEP_BUCKET" != "1" ]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  BUCKET_NAME=${BUCKET_NAME:-ic-checkpoints-${ACCOUNT_ID}-${REGION}}
  BUCKET_NAME=$(echo "$BUCKET_NAME" | tr '[:upper:]' '[:lower:]')
  echo "==> Emptying + deleting s3://$BUCKET_NAME"
  aws s3 rm "s3://$BUCKET_NAME" --recursive 2>/dev/null || true
  aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>/dev/null || true
fi
echo "✔ Done."
