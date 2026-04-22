#!/usr/bin/env bash
# Linux/macOS equivalent of setup_eks.ps1
set -euo pipefail

CLUSTER_NAME=${CLUSTER_NAME:-incident-commander}
REGION=${AWS_REGION:-us-east-1}
BUCKET_NAME=${BUCKET_NAME:-}

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_PATH="$REPO_ROOT/infra/eks/cluster.yaml"

echo "==> Checking prerequisites"
for bin in aws eksctl kubectl; do
  command -v "$bin" >/dev/null 2>&1 || { echo "'$bin' not found on PATH"; exit 1; }
done
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "    AWS account: $ACCOUNT_ID   region: $REGION"

# 1) Cluster
if eksctl get cluster --region "$REGION" -o json 2>/dev/null | grep -q "\"Name\": \"$CLUSTER_NAME\""; then
  echo "==> EKS cluster '$CLUSTER_NAME' already exists — reusing"
else
  echo "==> Creating EKS cluster '$CLUSTER_NAME' (~12 min)"
  eksctl create cluster -f "$CONFIG_PATH"
fi

aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER_NAME"
kubectl cluster-info

# 2) S3 bucket
: "${BUCKET_NAME:=ic-checkpoints-${ACCOUNT_ID}-${REGION}}"
BUCKET_NAME=$(echo "$BUCKET_NAME" | tr '[:upper:]' '[:lower:]')
if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "==> Creating S3 bucket s3://$BUCKET_NAME"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

# 3) CloudWatch log group
LOG_GROUP="/aws/eks/$CLUSTER_NAME/application"
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || true
aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 7 --region "$REGION" 2>/dev/null || true

# 4) Deploy sample app
echo "==> Deploying sample app"
kubectl apply -f "$REPO_ROOT/rl-agent/sample_app/namespaces.yaml"
kubectl apply -R -f "$REPO_ROOT/rl-agent/sample_app/base"
for ns in ic-payments ic-frontend ic-auth; do
  kubectl -n "$ns" wait --for=condition=available --timeout=300s deployment --all
done

# 5) Write .env file
cat > "$REPO_ROOT/.env.aws.local" <<EOF
AWS_REGION=$REGION
EKS_CLUSTER_NAME=$CLUSTER_NAME
S3_CHECKPOINT_BUCKET=$BUCKET_NAME
CLOUDWATCH_LOG_GROUP=$LOG_GROUP
REAL_K8S=true
K8S_CLOUD=aws
EOF

cat <<EOF

✔ AWS environment ready.
  cluster : $CLUSTER_NAME ($REGION)
  s3      : s3://$BUCKET_NAME
  logs    : $LOG_GROUP
  .env    : $REPO_ROOT/.env.aws.local

Next: see ENV.md for env-var wiring, then start the server.
Teardown: bash scripts/teardown_eks.sh
EOF
