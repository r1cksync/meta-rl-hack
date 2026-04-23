################################################################################
# IncidentCommander — AWS DevOps stack (multi-service)
#
# One opinionated Terraform module that provisions every AWS service the
# env server, RL trainer, and live cluster need. Nothing here is mandatory at
# runtime — every integration in rl-agent/environment/aws_integrations.py
# is gated on env vars and silently no-ops if the service isn't reachable.
#
# Services provisioned
# --------------------
#   VPC + subnets + NAT                     (networking foundation for EKS)
#   EKS cluster + managed node group        (where AcmeCorp microservices run)
#   ECR repository                          (holds the HF Space / trainer image)
#   S3 bucket                               (LoRA adapters, metrics.jsonl archive)
#   DynamoDB table                          (curriculum mastery state, durable)
#   CloudWatch Log Group + Metric Namespace (pod logs for the agent to query)
#   SNS topic                               (alerts when the agent mitigates)
#   Secrets Manager secret                  (OPENAI_API_KEY for the LLM judge)
#   IAM role (IRSA)                         (least-privilege for pods)
#   Lambda function + EventBridge rule      (CloudWatch alarm -> /reset hook)
#   Bedrock IAM policy                      (runtime access for LLM judge)
#
# Usage
# -----
#   cd infra/aws && terraform init
#   terraform apply -var="project=incident-commander" -var="region=us-east-1"
#
# After apply, copy terraform output into .env.aws.local — see outputs.tf.
################################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

provider "aws" { region = var.region }

variable "project" { default = "incident-commander" }
variable "region"  { default = "us-east-1" }
variable "eks_version"    { default = "1.29" }
variable "node_instance"  { default = "t3.medium" }
variable "desired_nodes"  { default = 2 }

data "aws_caller_identity" "this" {}
data "aws_availability_zones" "az" { state = "available" }

locals {
  name = var.project
  tags = {
    Project     = var.project
    ManagedBy   = "terraform"
    Purpose     = "openenv-hackathon"
    Environment = "demo"
  }
  azs = slice(data.aws_availability_zones.az.names, 0, 2)
}

################################################################################
# 1. VPC + subnets + NAT gateway
################################################################################
resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = merge(local.tags, { Name = "${local.name}-vpc" })
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.tags, { Name = "${local.name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags = merge(local.tags, {
    Name                                        = "${local.name}-pub-${count.index}"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${local.name}"       = "shared"
  })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10)
  availability_zone = local.azs[count.index]
  tags = merge(local.tags, {
    Name                                        = "${local.name}-prv-${count.index}"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${local.name}"       = "shared"
  })
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.tags, { Name = "${local.name}-nat-eip" })
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(local.tags, { Name = "${local.name}-nat" })
  depends_on    = [aws_internet_gateway.igw]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route { cidr_block = "0.0.0.0/0"  gateway_id = aws_internet_gateway.igw.id }
  tags   = merge(local.tags, { Name = "${local.name}-pub-rt" })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route { cidr_block = "0.0.0.0/0"  nat_gateway_id = aws_nat_gateway.nat.id }
  tags   = merge(local.tags, { Name = "${local.name}-prv-rt" })
}

resource "aws_route_table_association" "pub" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "prv" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

################################################################################
# 2. EKS cluster + managed node group
################################################################################
resource "aws_iam_role" "eks_cluster" {
  name = "${local.name}-eks-cluster-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  name     = local.name
  version  = var.eks_version
  role_arn = aws_iam_role.eks_cluster.arn

  vpc_config {
    subnet_ids              = concat(aws_subnet.public[*].id, aws_subnet.private[*].id)
    endpoint_public_access  = true
    endpoint_private_access = true
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  tags = local.tags

  depends_on = [aws_iam_role_policy_attachment.eks_cluster_policy]
}

resource "aws_iam_role" "nodes" {
  name = "${local.name}-eks-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_read" {
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${local.name}-ng"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = [var.node_instance]

  scaling_config {
    desired_size = var.desired_nodes
    min_size     = 1
    max_size     = 4
  }

  update_config { max_unavailable = 1 }

  tags       = local.tags
  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr_read,
  ]
}

################################################################################
# 3. ECR repository (holds the HF / trainer image)
################################################################################
resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

################################################################################
# 4. S3 bucket — PPO LoRA checkpoints + archived metrics.jsonl
################################################################################
resource "aws_s3_bucket" "checkpoints" {
  bucket        = "${local.name}-ckpts-${data.aws_caller_identity.this.account_id}-${var.region}"
  force_destroy = true
  tags          = local.tags
}

resource "aws_s3_bucket_versioning" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "checkpoints" {
  bucket                  = aws_s3_bucket.checkpoints.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

################################################################################
# 5. DynamoDB — durable curriculum mastery state
################################################################################
resource "aws_dynamodb_table" "curriculum" {
  name         = "${local.name}-curriculum"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "task_id"

  attribute { name = "run_id"   type = "S" }
  attribute { name = "task_id"  type = "S" }

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }

  tags = local.tags
}

################################################################################
# 6. CloudWatch — log group + custom metric namespace
################################################################################
resource "aws_cloudwatch_log_group" "app" {
  name              = "/aws/eks/${local.name}/application"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/aws/incident-commander/agent"
  retention_in_days = 7
  tags              = local.tags
}

# Custom CloudWatch alarm: error rate on payments-api > 5%
resource "aws_cloudwatch_metric_alarm" "payments_error_rate" {
  alarm_name          = "${local.name}-payments-error-rate"
  metric_name         = "ErrorRate"
  namespace           = "IncidentCommander"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 2
  threshold           = 0.05
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { Service = "payments-api" }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = local.tags
}

################################################################################
# 7. SNS — alert channel the agent publishes to when it mitigates
################################################################################
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
  tags = local.tags
}

################################################################################
# 8. Secrets Manager — OPENAI_API_KEY for LLM judge + adversarial designer
################################################################################
resource "aws_secretsmanager_secret" "openai" {
  name                    = "${local.name}/openai-api-key"
  recovery_window_in_days = 0
  tags                    = local.tags
}

# (The actual secret VALUE is set out-of-band via aws secretsmanager put-secret-value)

################################################################################
# 9. IAM role for pods via IRSA — least privilege
################################################################################
data "aws_iam_policy_document" "pod_permissions" {
  statement {
    sid    = "S3"
    effect = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:HeadBucket"]
    resources = [aws_s3_bucket.checkpoints.arn, "${aws_s3_bucket.checkpoints.arn}/*"]
  }
  statement {
    sid    = "Dynamo"
    effect = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                 "dynamodb:Query", "dynamodb:Scan", "dynamodb:DescribeTable"]
    resources = [aws_dynamodb_table.curriculum.arn]
  }
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions   = ["logs:DescribeLogGroups", "logs:FilterLogEvents",
                 "logs:PutLogEvents", "logs:CreateLogStream"]
    resources = ["*"]
  }
  statement {
    sid    = "CWMetrics"
    effect = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    sid    = "SNS"
    effect = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
  statement {
    sid    = "Secrets"
    effect = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.openai.arn]
  }
  statement {
    sid    = "Bedrock"
    effect = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "pod" {
  name   = "${local.name}-pod-policy"
  policy = data.aws_iam_policy_document.pod_permissions.json
  tags   = local.tags
}

resource "aws_iam_role" "pod" {
  name = "${local.name}-pod-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "pod" {
  role       = aws_iam_role.pod.name
  policy_arn = aws_iam_policy.pod.arn
}

################################################################################
# 10. Lambda — CloudWatch alarm webhook that POSTs /reset to the env
################################################################################
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/.lambda.zip"
  source {
    filename = "handler.py"
    content  = <<EOT
import json, os, urllib.request
ENV_URL = os.environ["ENV_URL"]
def lambda_handler(event, _ctx):
    body = json.dumps({"use_curriculum": True, "adversarial": True}).encode()
    req = urllib.request.Request(f"{ENV_URL}/reset", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return {"status": r.status}
    except Exception as e:
        return {"error": str(e)}
EOT
  }
}

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "alarm_hook" {
  function_name    = "${local.name}-alarm-hook"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      ENV_URL = "https://sagnik-mukherjee-incodent-commander.hf.space"
    }
  }
  tags = local.tags
}

resource "aws_sns_topic_subscription" "alarm_to_lambda" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alarm_hook.arn
}

resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowInvokeFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_hook.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}
