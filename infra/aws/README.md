# AWS DevOps Stack — IncidentCommander

This Terraform module provisions the full AWS backend used by
IncidentCommander. It's a **superset** of the older `infra/eks/cluster.yaml`
(which only describes EKS). All integrations are runtime-optional — the env
server silently no-ops if the resources aren't reachable.

## Services provisioned

| # | AWS service | Purpose in IncidentCommander |
|---|-------------|-----------------------------|
| 1 | **VPC + subnets + NAT** | Networking foundation for EKS (2 AZs, public + private) |
| 2 | **EKS (+ managed node group)** | Runs the 5 AcmeCorp microservices + Chaos Mesh + observability |
| 3 | **ECR** | Registry for the env server + trainer Docker images |
| 4 | **S3** | LoRA adapter + `metrics.jsonl` checkpoint archive (versioned, SSE-AES256, lifecycle-expired) |
| 5 | **DynamoDB** | Durable per-run / per-task curriculum mastery state (PITR + SSE) |
| 6 | **CloudWatch Logs** | Pod logs the agent's `query_logs` action reads from |
| 7 | **CloudWatch Metrics + Alarm** | Custom `IncidentCommander` namespace; `ErrorRate > 5%` alarm |
| 8 | **SNS** | Alert topic the agent publishes to when it applies a mitigation |
| 9 | **Secrets Manager** | `OPENAI_API_KEY` for the LLM judge + adversarial designer |
| 10 | **IAM (IRSA)** | Least-privilege pod role (S3 / Dynamo / Logs / CW / SNS / Secrets / Bedrock) |
| 11 | **Lambda + EventBridge** | SNS-triggered webhook that POSTs `/reset` to the env on alarm |
| 12 | **Bedrock (IAM)** | Runtime permission for the pod to call `bedrock:InvokeModel` |

## Apply

```powershell
cd incident-commander/infra/aws
terraform init
terraform apply -var='project=incident-commander' -var='region=us-east-1'
terraform output env_file | Out-File -Encoding ascii ..\..\.env.aws.local
```

## Teardown

```powershell
terraform destroy -auto-approve
```

Cost on `us-east-1` with `t3.medium` × 2, idle: roughly **$5–7 / day**.
NAT gateway is the single biggest line item; switch to a public-only node
group for demos if budget is tight.
