# ENV.md — Environment variable setup guide

This is the **only setup document you need** for the AWS path. It walks you
through every env var, what sets it, and how to verify.

---

## TL;DR quickstart

```powershell
# 1. install CLIs: aws, eksctl, kubectl  (see §1)
# 2. configure AWS credentials
aws configure
# 3. provision EKS + S3 + CloudWatch
.\scripts\setup_eks.ps1
# 4. load the generated .env.aws.local (see §3)
.\scripts\load_env.ps1 .env.aws.local
# 5. install Python deps
pip install -r rl-agent/requirements.txt
# 6. start the env server
cd rl-agent; uvicorn server:app --host 127.0.0.1 --port 7860
# 7. (new terminal) kick off training — §5
```

---

## 1. Install the CLIs (one-time)

| Tool | Windows | macOS / Linux | Verify |
|---|---|---|---|
| AWS CLI v2 | `winget install Amazon.AWSCLI` | `brew install awscli` | `aws --version` |
| eksctl | `winget install eksctl` | `brew install eksctl` | `eksctl version` |
| kubectl | `winget install Kubernetes.kubectl` | `brew install kubectl` | `kubectl version --client` |
| (optional) Helm | `winget install Helm.Helm` | `brew install helm` | `helm version` |

Python 3.10+ is assumed.

---

## 2. AWS credentials

Pick **one** of the three options below.

### Option A — `aws configure` (simplest, uses a local profile file)

```powershell
aws configure
# AWS Access Key ID:     AKIA...
# AWS Secret Access Key: ****
# Default region name:   us-east-1
# Default output format: json
```

This writes `~/.aws/credentials` and `~/.aws/config`. boto3, eksctl, and
kubectl (via the EKS auth plugin) will all pick these up automatically.

### Option B — env vars (good for CI / Docker)

```powershell
$env:AWS_ACCESS_KEY_ID     = "AKIA..."
$env:AWS_SECRET_ACCESS_KEY = "..."
$env:AWS_REGION            = "us-east-1"
```

### Option C — SSO (recommended for company accounts)

```powershell
aws configure sso
aws sso login --profile my-profile
$env:AWS_PROFILE = "my-profile"
```

### Required IAM permissions

The calling user/role needs these managed policies (or an equivalent
inline policy):

- `AmazonEKSClusterPolicy`
- `AmazonEKSWorkerNodePolicy`
- `AmazonEC2FullAccess`         (for nodegroup VMs)
- `IAMFullAccess`               (eksctl creates OIDC roles)
- `AmazonS3FullAccess` *scoped to* `arn:aws:s3:::ic-checkpoints-*`
- `CloudWatchLogsFullAccess`    *scoped to* `/aws/eks/incident-commander/*`

Verify you can call STS:

```powershell
aws sts get-caller-identity
```

---

## 3. Env vars the app reads

After `setup_eks.ps1` finishes it writes **`.env.aws.local`** at the repo
root. Here's every variable, why it exists, and the default:

| Variable | Written by | Read by | Default if unset | Purpose |
|---|---|---|---|---|
| `AWS_REGION` | you / setup | boto3, eksctl | — | Region for EKS, S3, CW |
| `AWS_PROFILE` | you | boto3 | (default profile) | Named credential profile |
| `EKS_CLUSTER_NAME` | setup | (informational) | `incident-commander` | |
| `REAL_K8S` | setup | `k8s_backend.py` | `false` | Master switch: `true` uses live cluster |
| `K8S_CLOUD` | setup | (informational) | — | `aws` / `kind` / unset |
| `S3_CHECKPOINT_BUCKET` | setup | `aws_integrations.py` | (none) | Bucket for LoRA checkpoints |
| `CLOUDWATCH_LOG_GROUP` | setup | `aws_integrations.py` | (none) | Log group for `query_logs` |
| `KUBECONFIG` | `aws eks update-kubeconfig` | `kubernetes` lib | `~/.kube/config` | Cluster credentials |
| `MOCK_MODE` | you | `server.py` lifespan | `true` | Set to `false` for real backend |
| `JUDGE_PERSONA` | you | `env.py` | `senior` | `junior` / `senior` / `principal` |
| `USE_LLM_JUDGE` | you | `env.py` | `false` | Enable OpenAI judge calls |
| `OPENAI_API_KEY` | you | `llm_judge.py` | — | Needed if `USE_LLM_JUDGE=true` |
| `HF_TOKEN` | you | `train_grpo.py` | — | Only for `--hub-repo` pushes |
| `ENV_URL` | you | trainer client | `http://localhost:7860` | URL of env server |
| `LOKI_URL` | you | `loki_client.py` | `http://localhost:3100` | Unused on EKS; leave default |
| `PROMETHEUS_URL` | you | `prometheus_client.py` | `http://localhost:9090` | Unused on EKS; leave default |

### Loading `.env.aws.local`

**PowerShell:**
```powershell
Get-Content .env.aws.local | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
# also tell the current shell:
(Get-Content .env.aws.local) | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2]
    }
}
```

Or, simpler — use the helper script:
```powershell
.\scripts\load_env.ps1 .env.aws.local
```

**Bash/zsh:**
```bash
set -a; source .env.aws.local; set +a
```

**Verify** the server sees the live cluster:
```powershell
curl.exe http://localhost:7860/k8s/health
# -> {"enabled": true, "health": {"ic-payments": {...}, ...}}
```
If `enabled` is `false`, `REAL_K8S` or `KUBECONFIG` is not visible to the
uvicorn process — restart uvicorn **in the same shell** where you loaded
the env file.

---

## 4. One-file reference (.env.aws.local)

After `setup_eks.ps1`, yours will look like:

```ini
AWS_REGION=us-east-1
EKS_CLUSTER_NAME=incident-commander
S3_CHECKPOINT_BUCKET=ic-checkpoints-123456789012-us-east-1
CLOUDWATCH_LOG_GROUP=/aws/eks/incident-commander/application
REAL_K8S=true
K8S_CLOUD=aws
```

Add these manually if you want them:
```ini
MOCK_MODE=false
USE_LLM_JUDGE=false
JUDGE_PERSONA=senior
```

**Never commit `.env.aws.local`** — `.gitignore` already excludes it.

---

## 5. Start the environment + drive a smoke test

Terminal 1 — env server:
```powershell
.\scripts\load_env.ps1 .env.aws.local
cd rl-agent
uvicorn server:app --host 127.0.0.1 --port 7860
```

Terminal 2 — smoke test:
```powershell
# real pod health via AWS
curl.exe http://localhost:7860/k8s/health

# inject a real OOMKill on EKS
curl.exe -X POST http://localhost:7860/k8s/inject `
  -H "Content-Type: application/json" `
  -d '{\"fault_type\":\"oom_kill\"}'

# watch it on the actual cluster
kubectl -n ic-payments get pods -w

# reset back to healthy
curl.exe -X POST http://localhost:7860/k8s/reset
```

---

## 6. Cost controls

EKS control plane is billed $0.10/hr (~$72/month) whether or not nodes are
running. To pause without deleting:

```powershell
eksctl scale nodegroup --cluster incident-commander --name ic-workers --nodes=0
# ... later
eksctl scale nodegroup --cluster incident-commander --name ic-workers --nodes=2
```

Full teardown:
```powershell
.\scripts\teardown_eks.ps1
```

---

## 7. When things go wrong

| Symptom | Root cause | Fix |
|---|---|---|
| `/k8s/health -> enabled: false` | `REAL_K8S` not set in uvicorn's shell | Reload `.env.aws.local`, restart uvicorn |
| `Unauthorized` from kubectl | kubeconfig stale after cluster delete/recreate | `aws eks update-kubeconfig --region $AWS_REGION --name $EKS_CLUSTER_NAME` |
| `AccessDenied: sts:AssumeRole` | IAM identity missing `AmazonEKSClusterPolicy` | Attach policy or use a role with it |
| `NoCredentialProviders` from boto3 | neither profile nor env vars set | Run `aws configure` or export `AWS_ACCESS_KEY_ID` |
| `fastapi/uvicorn/openai` warnings "not on PATH" | pip scripts dir not in PATH | Harmless — `python -m uvicorn ...` always works |
| Training OOMs on local GPU | bf16 on 8GB card | Always pass `--local` (forces 4-bit LoRA) |
| `CrashLoopBackOff` still after `/k8s/reset` | kubelet hasn't restarted yet | wait ~15s, call `/k8s/reset` again |

If PowerShell complained about paths with brackets `[...]`: always pass
`-LiteralPath` (noted in the workspace memory).

---

## Done. Now go to §5 in [RUNBOOK.md](RUNBOOK.md) to kick off training.
