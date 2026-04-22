# RUNBOOK — End-to-end training

Two paths: **AWS EKS** (recommended, real cloud cluster) or **local kind**
(free, Docker-based). Both use identical agent code — only the backend swaps.

For detailed env-var wiring see [ENV.md](ENV.md).

| Path | Cost | Pros | Cons |
|---|---|---|---|
| AWS EKS | ~$4-5/day while running | real cloud, CloudWatch logs, S3 checkpoints | needs AWS account |
| Local kind | free | offline, fast iterate | no cloud services |

---

## Path A — AWS EKS (recommended)

### A.1 Provision

```powershell
aws configure                   # one-time
.\scripts\setup_eks.ps1         # ~12 min
.\scripts\load_env.ps1 .env.aws.local
```

### A.2 Install Python deps

```powershell
pip install -r rl-agent/requirements.txt
pip install -r rl-agent/requirements-train.txt
```

### A.3 Start the env server

```powershell
cd rl-agent
uvicorn server:app --host 127.0.0.1 --port 7860
```

Verify: `curl.exe http://localhost:7860/k8s/health` → `"enabled": true`.

### A.4 Smoke-test real fault injection

```powershell
curl.exe -X POST http://localhost:7860/k8s/inject `
  -H "Content-Type: application/json" `
  -d '{\"fault_type\":\"oom_kill\"}'
kubectl -n ic-payments get pods -w
curl.exe -X POST http://localhost:7860/k8s/reset
```

All 9 fault types: `oom_kill`, `crashloop`, `image_pull`, `bad_config`,
`scale_zero`, `liveness_probe`, `resource_quota`, `secret_mismatch`,
`wrong_image_tag`.

### A.5 Training

```powershell
# sanity-check the pipeline — no GPU needed, no model download
cd rl-agent
python -m training.train_grpo --local --dry-run

# real GRPO against the live EKS cluster, 50 steps, ~8GB VRAM
python -m training.train_grpo --local `
    --env-url http://localhost:7860 `
    --inject-fault oom_kill `
    --max-steps 50
```

Checkpoints land in `rl-agent/checkpoints/grpo/` **and** are uploaded to
`s3://$S3_CHECKPOINT_BUCKET/grpo/<timestamp>/final/` automatically.

### A.6 Evaluate

```powershell
cd rl-agent
python -m eval --env-url http://localhost:7860
```

### A.7 Teardown (important — EKS bills hourly)

```powershell
.\scripts\teardown_eks.ps1
```

---

## Path B — Local kind (no cloud)

| Tool | Where to get it | Windows quick-install |
|---|---|---|
| Docker Desktop | https://www.docker.com/products/docker-desktop | `winget install Docker.DockerDesktop` |
| kind | https://kind.sigs.k8s.io | `choco install kind` (or scoop/winget) |
| kubectl | https://kubernetes.io/docs/tasks/tools/ | `choco install kubernetes-cli` |
| Python 3.10+ | https://www.python.org | `winget install Python.Python.3.11` |
| (optional) NVIDIA GPU w/ CUDA 12 | — | for real GRPO; CPU works for `--dry-run` |

Verify:
```powershell
docker info; kind version; kubectl version --client; python --version
```

---

## 1. Spin up the local K8s cluster

From the repo root (`E:\meta-rl-hack\incident-commander`):

```powershell
.\scripts\setup_kind.ps1
```

This creates a cluster named `incident-commander` with three app namespaces
(`ic-payments`, `ic-frontend`, `ic-auth`) and 5 healthy deployments.
Verify everything is green:

```powershell
kubectl get pods -A | findstr ic-
```

Linux/macOS equivalent: `bash scripts/setup_kind.sh`.

---

## 2. Install Python deps

```powershell
# server + k8s client
pip install -r rl-agent/requirements.txt

# trainer (torch, trl, peft, bitsandbytes). Only needed if you plan to train.
pip install -r rl-agent/requirements-train.txt
```

---

## 3. Start the environment server against the real cluster

```powershell
$env:REAL_K8S = "true"
cd rl-agent
uvicorn server:app --host 127.0.0.1 --port 7860
```

Leave this terminal running. Open a **second** terminal for the next steps.

Sanity-check:
```powershell
curl.exe http://localhost:7860/k8s/health
# -> {"enabled": true, "health": {"ic-payments": {...}, ...}}
```

---

## 4. Drive the cluster manually (optional smoke test)

Inject a real OOMKill fault:
```powershell
curl.exe -X POST http://localhost:7860/k8s/inject `
  -H "Content-Type: application/json" `
  -d '{\"fault_type\":\"oom_kill\"}'
```

Watch the pod actually crash:
```powershell
kubectl -n ic-payments get pods -w
# payments-api-xxx   0/1  OOMKilled  0  10s
```

Have the agent investigate via kubectl:
```powershell
curl.exe -X POST http://localhost:7860/step `
  -H "Content-Type: application/json" `
  -d '{\"action_type\":\"exec_kubectl\",\"params\":{\"command\":\"kubectl get pods -n ic-payments\"}}'
```

Reset everything back to healthy:
```powershell
curl.exe -X POST http://localhost:7860/k8s/reset
```

All nine fault types are supported:
`oom_kill`, `crashloop`, `image_pull`, `bad_config`, `scale_zero`,
`liveness_probe`, `resource_quota`, `secret_mismatch`, `wrong_image_tag`.

---

## 5. Dry-run training (no GPU, verifies pipeline end-to-end)

```powershell
cd rl-agent
python -m training.train_grpo --local --dry-run
```

You should see one rollout with a cumulative reward printed.

---

## 6. Real GRPO training (local, ~8GB GPU)

```powershell
cd rl-agent
python -m training.train_grpo --local --inject-fault oom_kill `
    --env-url http://localhost:7860 `
    --max-steps 50
```

What `--local` does:
- switches to `Qwen/Qwen2.5-0.5B-Instruct`
- LoRA `r=8`, 4-bit quantization (fits in 8GB)
- `num_generations=2-4`, `max_steps<=60`
- no Hub push, no vLLM colocate

Checkpoints land in `rl-agent/checkpoints/grpo`.

Without `--local` you get the full hackathon config (1.5B, 8 gens, vLLM
colocate — needs >=40GB VRAM).

---

## 7. Evaluate

```powershell
cd rl-agent
python -m eval --env-url http://localhost:7860
```

---

## 8. Teardown

```powershell
.\scripts\teardown_kind.ps1
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/k8s/health` returns `{"enabled": false}` | `$env:REAL_K8S="true"` was not set *before* uvicorn; restart it. |
| Pods stuck `ImagePullBackOff` on first setup | Docker Desktop is rate-limited; `docker login` with any account. |
| `kind` not found after `choco install` | Open a new PowerShell so PATH refreshes. |
| `ModuleNotFoundError: kubernetes` | `pip install kubernetes>=29.0.0`. |
| bitsandbytes install fails on Windows | `pip install bitsandbytes-windows` (prebuilt wheel). |
| Training OOMs on GPU | Lower `--grad-accum`, keep `--local`, or add `--no-hub-push`. |

---

## What's real vs mock

| Layer | Mock mode (default / HF Space) | Real mode (`REAL_K8S=true`) |
|---|---|---|
| `kubectl get pods` | in-memory dict | live cluster API |
| `inject_failure` | flips a flag | patches live Deployment |
| `reset_to_healthy` | restores dict | `patch_namespaced_deployment` for each tracked deploy |
| Reward signal | heuristic + LLM judge | identical + real pod phase feedback |

The agent code is the same in both modes — the backend swap is transparent.
