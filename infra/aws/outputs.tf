################################################################################
# Outputs — copy these into .env.aws.local
################################################################################

output "eks_cluster_name"       { value = aws_eks_cluster.this.name }
output "eks_endpoint"           { value = aws_eks_cluster.this.endpoint }
output "ecr_repository_url"     { value = aws_ecr_repository.app.repository_url }
output "s3_checkpoint_bucket"   { value = aws_s3_bucket.checkpoints.id }
output "dynamodb_curriculum"    { value = aws_dynamodb_table.curriculum.name }
output "cloudwatch_log_group"   { value = aws_cloudwatch_log_group.app.name }
output "cloudwatch_agent_group" { value = aws_cloudwatch_log_group.agent.name }
output "sns_alerts_topic"       { value = aws_sns_topic.alerts.arn }
output "secrets_openai_arn"     { value = aws_secretsmanager_secret.openai.arn }
output "pod_role_arn"           { value = aws_iam_role.pod.arn }
output "lambda_function_name"   { value = aws_lambda_function.alarm_hook.function_name }
output "vpc_id"                 { value = aws_vpc.main.id }

output "env_file" {
  description = "Paste into incident-commander/.env.aws.local"
  value = <<-EOT
    AWS_REGION=${var.region}
    EKS_CLUSTER_NAME=${aws_eks_cluster.this.name}
    ECR_REPOSITORY_URL=${aws_ecr_repository.app.repository_url}
    S3_CHECKPOINT_BUCKET=${aws_s3_bucket.checkpoints.id}
    DYNAMODB_CURRICULUM_TABLE=${aws_dynamodb_table.curriculum.name}
    CLOUDWATCH_LOG_GROUP=${aws_cloudwatch_log_group.app.name}
    CLOUDWATCH_AGENT_LOG_GROUP=${aws_cloudwatch_log_group.agent.name}
    CLOUDWATCH_METRIC_NAMESPACE=IncidentCommander
    SNS_ALERTS_TOPIC_ARN=${aws_sns_topic.alerts.arn}
    OPENAI_SECRET_ARN=${aws_secretsmanager_secret.openai.arn}
    POD_ROLE_ARN=${aws_iam_role.pod.arn}
    REAL_K8S=true
    K8S_CLOUD=aws
  EOT
}
