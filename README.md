---
title: Incident Commander
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
tags:
  - openenv
  - sre
  - incident-response
  - reinforcement-learning
---

# 🚨 IncidentCommander

**An OpenEnv RL environment where AI agents learn to diagnose and mitigate real production incidents as on-call SRE engineers.**

Built for the **Meta PyTorch OpenEnv Hackathon x Scaler School of Technology, 2026**.

[🌟 **Showcase Page**](https://sagnik-mukherjee-incodent-commander.hf.space/showcase) | [Live Dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard) | [API Health](https://sagnik-mukherjee-incodent-commander.hf.space/health) | [API Docs](https://sagnik-mukherjee-incodent-commander.hf.space/docs)

### 📚 Submission materials

| | |
|---|---|
| 📝 **Blog / writeup** | [`BLOG.md`](BLOG.md) — story-driven walkthrough (problem · env · novelties · results · pipeline) |
| 📖 **Env reference docs** | [`docs/ENV_DEEP.md`](docs/ENV_DEEP.md) (11 hand‑curated tasks · Rounds 1 + 2) · [`docs/ENV_SHALLOW.md`](docs/ENV_SHALLOW.md) (381 procedural scenarios · Round 3) · [`docs/TASKS_SHALLOW.md`](docs/TASKS_SHALLOW.md) (row‑by‑row index of every one of the 381 tasks: id · title · target · max steps · correct chain) |
| 🎥 **Video walkthrough** | [https://youtu.be/8bDJ0MMZ1DM](https://youtu.be/8bDJ0MMZ1DM) |
| 🧪 **Live env (HF Space)** | [sagnik-mukherjee/incodent-commander](https://huggingface.co/spaces/sagnik-mukherjee/incodent-commander) |
| 💻 **Source (GitHub)** | [r1cksync/meta-rl-hack](https://github.com/r1cksync/meta-rl-hack) |
| 📊 **Training notebooks (Kaggle)** | [`kaggle/`](kaggle/) (3 shards × Phi-3.5 + DeepSeek-R1) · [`notebooks/`](notebooks/) (legacy SB3 PPO baseline) |
| 📦 **Trained adapters** | [`kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/`](kaggle%20ran%20notebooks/) |
| 🎚️ **Per-update training logs** | **Round 3 (shallow, 381 tasks):** [`kaggle ran notebooks/shard {1,2,3}/training_kaggle{N}.json`](kaggle%20ran%20notebooks/) · **Round 2 (deep, 11 tasks):** [`rl-agent/checkpoints/ppo-v{2,3,4}-*/metrics.jsonl`](rl-agent/checkpoints/) · **Round 1 (legacy SB3):** [`rl-agent/checkpoints/training_metrics.json`](rl-agent/checkpoints/training_metrics.json) |

---

## Why We Built This

Every SRE has been there: PagerDuty goes off at 3 AM, dashboards are red, five services are throwing errors, and you have no idea which one is the actual root cause. You check logs, run PromQL queries, stare at traces, form a hypothesis — and pray your rollback doesn't make things worse.

We turned that entire debugging experience into an RL environment. The agent sees what a real SRE sees: Prometheus metrics, Loki logs, Alertmanager alerts, service dependency graphs, and distributed traces. It takes real actions: rollback deployments, restart pods, scale services, delete chaos experiments, and submit postmortems. The reward signal comes from actual error-rate reduction and blast radius minimization — not synthetic labels.

**What makes this different from toy environments:**
- **Self-improving curriculum.** A controller tracks per-task mastery and escalates difficulty tiers automatically (warmup → beginner → intermediate → advanced → expert).
- **Adversarial scenario designer.** At the expert tier, an LLM composes novel incidents that target the agent's tracked weaknesses — infinite non-repeating scenarios.
- **3-persona LLM judge.** Every action is critiqued by a Junior / Senior / Principal SRE persona with progressively stricter evaluation (Snorkel-style experts-in-the-loop).
- **Phase-aware rewards.** Actions are classified as `triage → investigate → fix → verify`; the agent earns a bonus for following the correct workflow order and loses reward for regressing phases.
- **Context-gated rewards.** Penalised for acting without investigating, for repeating commands, and for targeting red-herring services that the task explicitly marks as distractors.
- **Real infrastructure option.** Write actions normally hit a mock cluster but can be routed to a live Kubernetes cluster (`REAL_K8S=true`) — the code path is the same.
- **Multi-fault scenarios** on hard tiers: 2-3 simultaneous faults composed from the base scenario pool.
- **Holistic episode grading** separate from per-step rewards: investigation thoroughness + correct mitigation + root cause + efficiency + no unnecessary damage.
- **GRPO-ready training pipeline** (TRL + vLLM colocate, LoRA on Qwen2.5-1.5B). Fully scripted and waiting on GPU credits.

---


## How It Works

The environment drops the agent into an active production incident at **AcmeCorp**, a microservices e-commerce platform with 5 services, Kafka, Redis, Postgres, and full observability. The agent must:

1. **Investigate** — Query logs, metrics, traces, and dependency graphs to understand what's happening
2. **Diagnose** — Form a hypothesis about the root cause (avoiding red herrings)
3. **Mitigate** — Take targeted write actions (rollback, restart, scale, patch config, delete chaos)
4. **Report** — Submit a structured postmortem with root cause, timeline, and follow-ups

There are **7 tasks** covering common SRE failure modes: chaos-induced outages, cascading failures, silent data corruption, DNS failures, expired certificates, and configuration drift. The hard tasks have red herrings that actively mislead the agent.

---

## Tasks

| ID | Difficulty | Root Cause | What Goes Wrong |
|----|-----------|-----------|----------------|
| `task1` | Easy | Redis Pool Exhaustion | Chaos Mesh injects latency → pool saturates → inventory-service errors |
| `task2` | Medium | Payments OOM Cascade | Memory stress → OOM kills → Kafka lag cascades to other services |
| `task3` | Hard | Decimal Corruption | Bad deploy truncates NUMERIC precision. Postgres VACUUM is a red herring |
| `task4` | Easy | Kafka Network Partition | Chaos Mesh partitions broker → consumer lag spikes across workers |
| `task5` | Medium | DNS Resolution Failure | DNS chaos → NXDOMAIN across services. "Connection refused" is secondary |
| `task6` | Hard | TLS Certificate Expiry | Expired mTLS cert → all DB connections fail. ECONNRESET is a symptom |
| `task7` | Hard | Config Hot-Reload Race | ConfigMap race → inconsistent pricing across pods. Redis/GC alerts are red herrings |

Easy tasks have one obvious signal. Medium tasks need cross-service investigation. Hard tasks actively mislead you with plausible-looking red herrings.

---

## Actions

**Investigate (safe — no blast radius):**
- `query_logs(service, last_minutes, filter_text?)` — Read logs from Loki
- `query_metrics(promql, last_minutes?)` — Execute PromQL query against Prometheus
- `get_service_dependencies(service)` — Get the dependency graph
- `get_trace(trace_id)` — Fetch a distributed trace from Jaeger

**Fix (dangerous — can worsen blast radius):**
- `rollback_deployment(deployment)` — Roll back to previous revision
- `restart_pods(deployment)` — Rolling restart
- `scale_deployment(deployment, replicas)` — Change replica count (0-20)
- `apply_config_patch(deployment, env_var, value)` — Patch environment variable
- `delete_chaos_experiment(experiment_name)` — Remove injected fault

**Terminal:**
- `submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups)` — Submit report, episode ends

---

## Reward Signal

| Event | Reward | Notes |
|-------|--------|-------|
| Any step | -0.01 | Step cost encourages efficiency |
| First-time investigation | +0.05 | Per unique service/metric inspection |
| Useful log query | +0.10 | Log contains task-relevant keywords |
| Correct mitigation (before step 10) | +0.20 | Right action on right target |
| Root cause correct | +0.30 | Postmortem root cause matches ground truth |
| Postmortem quality | +0.20 | NLP-scored: timeline, mitigations, writing |
| **Phase-order bonus** | **+0.10** | Progressing triage → investigate → fix → verify |
| **LLM judge contribution** | **up to +0.15** | Persona-scored (junior/senior/principal), scaled |
| **Acting blind penalty** | **-0.20** | Write action without any prior investigation |
| **Red herring penalty** | **-0.15** | Targeting a known distractor service |
| **Repeat-command penalty** | **-0.15 / repeat** | Capped at -0.45; discourages spam |
| **Phase regression** | **-0.10** | Went back to triage after already fixing |
| Wrong service penalty | -0.15 | Write action targets wrong service |
| Time penalty | -0.05/step | Per step beyond step 5 |
| Blast radius increase | -0.10 | Write action worsens error rate |

**Context-gated penalties** are the key differentiator. The "acting blind" penalty fires when an agent takes a write action without having inspected any logs or metrics first. The "red herring" penalty fires when an agent targets a service that the task explicitly marks as a distractor. The "repeat-command" penalty — inspired by kube-sre-gym — fires when the agent re-sends an identical action signature, preventing reward-hacking through action spam.

**Reward range**: [-2.0, 1.0]  |  **Score range**: [0.001, 0.999]

---

## Curriculum Controller

Inspired by kube-sre-gym's curriculum. A stateful controller tracks per-task mastery across episodes and escalates the difficulty tier automatically. Enable by passing `use_curriculum: true` to `POST /reset`.

| Tier | Task Pool | Multi-Fault | Adversarial |
|------|----------|-------------|-------------|
| `warmup` | task1, task4 (easy single-fault) | No | No |
| `beginner` | task1, task2, task4, task5 | No | No |
| `intermediate` | all 7 tasks | No | No |
| `advanced` | all 7 tasks | 2 concurrent faults | No |
| `expert` | all 7 tasks | 2-3 faults | LLM-designed novel scenarios |

**Promotion rule:** after at least 6 episodes in the current tier, if the rolling success rate (score ≥ target_score) over the last 8 episodes is ≥ 0.65, the agent is auto-promoted. Sampling is weakness-biased — tasks with lower mastery are oversampled within the current tier.

---

## Adversarial Scenario Designer

When the curriculum reaches `expert` (or when `adversarial: true` is passed explicitly to `/reset`), the designer produces a **novel** scenario instead of loading a hand-authored JSON.

- **LLM path** (when `OPENAI_API_KEY` or `HF_TOKEN` is set): Claude/GPT-4o-mini receives the agent's mastery table and designs one hard scenario targeting the weakest tasks. Returns strict JSON matching our `TaskScenario` schema.
- **Procedural fallback** (no API key or LLM error): composes a multi-fault scenario from two base scenarios — merged log keywords, union of red herrings, tighter target score.

You can inspect a fresh adversarial scenario without starting an episode:

```bash
curl -X POST $BASE/adversarial/design -H 'Content-Type: application/json' \
  -d '{"primary_task_id":"task3","companion_task_ids":["task6"],"use_llm":true}'
```

---

## LLM Judge (3 Personas)

Every action is scored by an LLM (or heuristic fallback) playing one of three SRE personas. This mirrors the Snorkel-AI "simulated experts-in-the-loop" theme.

| Persona | Score Range | Style |
|---------|-------------|-------|
| `junior` | [-0.5, 1.0] | Lenient; partial credit; rewards any reasonable attempt |
| `senior` | [-0.75, 1.0] | Standard SRE expectations; rewards systematic diagnosis |
| `principal` | [-1.0, 1.0] | Strict; penalises repeat commands and wrong targets, rewards minimal fixes |

Switch persona mid-training:

```bash
curl -X POST $BASE/judge/config -H 'Content-Type: application/json' \
  -d '{"persona":"principal","use_llm":true}'
```

The judge also labels each action with an SRE *phase* (`triage / investigate / fix / verify`) which feeds the phase-order bonus in the reward function. When no API key is available, the judge falls back to a deterministic heuristic so training and CI keep working.

---

## Holistic Grading

Each task has a holistic grader (separate from per-step reward) that evaluates the full episode:

| Component | Max Score | What It Measures |
|-----------|-----------|-----------------|
| Investigation thoroughness | 0.25 | Did the agent inspect logs, metrics, deps, traces? |
| Correct mitigation | 0.25 | Was the right fix applied? |
| Root cause identification | 0.25 | Did the postmortem identify the real root cause? |
| Efficiency | 0.15 | How many steps (fewer = better)? |
| No unnecessary damage | 0.10 | Did write actions avoid making things worse? |
| **Total** | **1.00** | Clamped to [0.001, 0.999] for grader compliance |

---

## Baseline Results

| Task | Heuristic Agent | Target Score |
|------|----------------|-------------|
| task1 (Easy) | 0.90 | 0.80 |
| task2 (Medium) | 0.85 | 0.45 |
| task3 (Hard) | 0.85 | 0.20 |
| task4 (Easy) | 0.90 | 0.80 |
| task5 (Medium) | 0.85 | 0.45 |
| task6 (Hard) | 0.80 | 0.20 |
| task7 (Hard) | 0.80 | 0.20 |
| **Average** | **0.85** | — |

The heuristic agent follows a fixed strategy per task (investigate → mitigate → postmortem). It knows the task structure but demonstrates that the reward signal is achievable. An LLM agent has to figure it out from observations alone.

---

## Setup

```bash
# Local development
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pydantic httpx structlog numpy openai
cd rl-agent && uvicorn server:app --host 0.0.0.0 --port 7860

# Docker
docker build -t incident-commander .
docker run -p 7860:7860 incident-commander

# Run heuristic baseline (no API key needed)
curl -X POST http://localhost:7860/baseline -H 'Content-Type: application/json' -d '{"task_id":"task1"}'

# Reset with curriculum + adversarial
curl -X POST http://localhost:7860/reset -H 'Content-Type: application/json' \
  -d '{"use_curriculum":true,"persona":"senior"}'

# Inspect current curriculum state
curl http://localhost:7860/curriculum

# Design a novel adversarial scenario (procedural, no API key needed)
curl -X POST http://localhost:7860/adversarial/design -H 'Content-Type: application/json' \
  -d '{"primary_task_id":"task3","companion_task_ids":["task6"]}'

# Run LLM inference
API_BASE_URL=https://api.openai.com/v1 MODEL_NAME=gpt-4o HF_TOKEN=sk-... python inference.py
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOCK_MODE` | `true` | When `true`, all write actions return `[MOCK]` results. |
| `REAL_K8S` | `false` | When `true` and the `kubernetes` Python client is installed, write actions (rollback/restart/scale/apply_config_patch) go to a real cluster via the active kubeconfig. |
| `USE_LLM_JUDGE` | `false` | Enable LLM-based per-step judging. Requires `OPENAI_API_KEY` or `HF_TOKEN`. |
| `JUDGE_PERSONA` | `senior` | `junior` / `senior` / `principal`. |
| `OPENAI_API_KEY` / `HF_TOKEN` | — | Auth for LLM judge + adversarial designer. |
| `API_BASE_URL` | `https://api.openai.com/v1` | LLM endpoint (OpenAI-compatible). |
| `MODEL_NAME` | `gpt-4o-mini` | Default LLM for judge/designer. |

---

## GRPO Training (requires GPU)

We ship a full TRL + vLLM colocate training pipeline in `rl-agent/training/train_grpo.py`.

```bash
# Dry run — no GPU required, verifies rollouts & reward computation
python -m training.train_grpo --dry-run --env-url http://localhost:7860

# Full training (requires ≥A100 40GB)
python -m training.train_grpo \
    --model Qwen/Qwen2.5-1.5B-Instruct \
    --env-url https://sagnik-mukherjee-incodent-commander.hf.space \
    --num-generations 8 --max-steps 200 --grad-accum 8 \
    --vllm-mode colocate --hub-repo <your-name>/incident-commander-grpo
```

Prefer a notebook? Use [notebooks/incident_commander_colab.ipynb](notebooks/incident_commander_colab.ipynb) — mirrors the kube-sre-gym winning notebook but points at our env.

### Evaluation (base vs trained)

```bash
# Heuristic-only (zero GPU)
python -m rl_agent.eval --env-url http://localhost:7860 --episodes-per-task 3

# Compare base vs LoRA checkpoint (needs transformers+torch)
python -m rl_agent.eval \
    --base-model Qwen/Qwen2.5-1.5B-Instruct \
    --trained-model <your-name>/incident-commander-grpo \
    --episodes-per-task 5 --adversarial
```

### Training roadmap

1. **Week 1 (zero GPU)** — heuristic baseline already solves easy tasks; we use this window to tune LLM-judge prompts, adversarial designer prompts, and the reward weights. All of this runs on CPU against the live Space.
2. **Week 2 (once college HF GPU credits arrive, ~3 days out)** — launch GRPO on Qwen2.5-1.5B with LoRA r=16, 200 steps, 8 generations per prompt. Expected wall-clock: ~6h on A100 40GB.
3. **Week 3** — compare against heuristic and against kube-sre-gym's reported numbers using `eval.py --adversarial`. Push best LoRA adapter to the Hub and cite it in the final submission.

---

## Actual Training We Ran (3 rounds, 2 regimes)

The GRPO roadmap above was the original plan; in practice we ran a custom PPO loop in two regimes — **deep training on a small task set** first, then **shallow training on all 381 procedural scenarios**. Three real rounds, all with full logs, all reproducible from this repo. The full live numbers are visible at [`/showcase`](https://sagnik-mukherjee-incodent-commander.hf.space/showcase) and discussed at length in [`BLOG.md`](BLOG.md) §4.

| Round | Regime | Tasks | Algorithm | Updates | Headline result | Code | Logs |
|---|---|---:|---|---:|---|---|---|
| **1 · Legacy SB3** | deep | 7 | SB3 PPO + MLP, 200 k timesteps | 5 evals | mean reward **1.05**, **100% success** over 90 episodes | [`rl-agent/training/train_enhanced.py`](rl-agent/training/train_enhanced.py) + [`gym_wrapper.py`](rl-agent/training/gym_wrapper.py) | [`training_metrics.json`](rl-agent/checkpoints/training_metrics.json) · [`evaluation_report.json`](rl-agent/checkpoints/evaluation_report.json) |
| **2 · Hybrid v2/v3/v4** | deep | 11 | Custom PPO, heuristic + small-LLM actor + judge critic | 12–33 | policy loss **−93% (v2)** / **−55% (v3,v4)**; v4 mean reward **1.78**, max **2.41** on `task9` | [`rl-agent/training/train_hybrid.py`](rl-agent/training/train_hybrid.py) (+ [`groq_critic.py`](rl-agent/training/groq_critic.py)) | [`ppo-v2-heuristic/`](rl-agent/checkpoints/ppo-v2-heuristic) · [`ppo-v3-hybrid-ollama-bedrock/`](rl-agent/checkpoints/ppo-v3-hybrid-ollama-bedrock) · [`ppo-v4-hybrid-ollama-groq/`](rl-agent/checkpoints/ppo-v4-hybrid-ollama-groq) |
| **3 · LoRA fine-tune** | shallow | **381** | Custom PPO + LoRA, Phi-3.5-mini actor + DeepSeek-R1 critic, 3 Kaggle shards | 60 / shard | KL & loss decay **50–66%** across all 3 shards; novelty categories all show positive Δ reward (+0.30 → +1.05) | [`scripts/run_training.py`](scripts/run_training.py) + [`colab/train_lib.py`](colab/train_lib.py) + [`scripts/merge_lora_adapters.py`](scripts/merge_lora_adapters.py) | [`shard 1/training_kaggle1.json`](kaggle%20ran%20notebooks/shard%201/training_kaggle1.json) · [`shard 2/training_kaggle2.json`](kaggle%20ran%20notebooks/shard%202/training_kaggle2.json) · [`shard 3/training_kaggle3.json`](kaggle%20ran%20notebooks/shard%203/training_kaggle3.json) |

**Why two regimes?** Round 1 + 2 (deep) prove the rubric is learnable on a small, well-understood task set — they're how we debugged the reward shaper, validated that a frozen LLM judge produces useful advantages, and locked the PPO hyper-parameters. Round 3 (shallow) takes those exact hyper-parameters and runs them across the full 381-scenario procedural curriculum on three free Kaggle T4 accounts in parallel.

**Headline numbers from the deep runs (Round 2):**

| Run | Actor | Critic | Episodes | Mean reward | Top per-task mean | Mitigation rate |
|---|---|---|---:|---:|---|---:|
| `ppo-v2-heuristic` | heuristic | none | 99 | 1.17 | 1.60 (`task1`,`task4`) | **100%** |
| `ppo-v3-hybrid-ollama-bedrock` | Qwen2.5:0.5b (Ollama) | heuristic-fallback | 36 | 1.32 | 1.72 (`task10`) | 69% |
| `ppo-v4-hybrid-ollama-groq` | Qwen2.5:0.5b (Ollama) | **Groq Llama-3.1-8B-instant** | 36 | **1.78** | **2.41** (`task9`) | 44% |

Across all three deep runs, policy loss collapses (1.20 → 0.083 over 33 updates for v2; 1.10 → 0.50 over 12 updates for v3/v4), entropy compresses (~2.0 → 0.39 for v2; ~1.9 → 1.21 for v3/v4), and v4's small-LLM actor with the Groq Llama-3.1-8B critic clears the heuristic ceiling on the hardest tasks. Plots and the full discussion live in [`BLOG.md` §4](BLOG.md).

### Round 3 — LoRA fine-tune on 381 scenarios (the headline run)

Round 3 is the run that ships the merged LoRA adapter on top of `microsoft/Phi-3.5-mini-instruct`. It uses the same PPO hyper-parameters validated by rounds 1 + 2.

### Models

| Role | Model | Quant | LoRA |
|------|-------|-------|------|
| **Actor** | `microsoft/Phi-3.5-mini-instruct` | 4-bit NF4 | r=16, α=32, dropout=0, target = qkv/o/gate_up/down |
| **Critic** | `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` | 4-bit | prompt-only 0–10 rubric scorer (no grad) |

The critic is loaded once and frozen — it just provides the value baseline `V(s, a)` for advantage estimation. The actor is the only model with trainable parameters (~25 M LoRA weights).

### PPO hyper-parameters

| Hyperparam | Value |
|------------|-------|
| Updates / shard | 60 |
| Rollouts / update | 3 |
| Max steps / episode | 12 |
| Discount γ | 0.95 |
| GAE λ | 0.92 |
| Clip ε | 0.2 |
| KL coefficient | 0.02 |
| Entropy coefficient | 0.01 |
| PPO epochs | 2 |
| Mini-batch | 4 |
| Learning rate | 5e-5 |

### Three-shard parallel training

381 sim scenarios, divided modulo 3 over the sorted task ids:

| Shard | Index slice | Tasks | Notebook | Output |
|-------|-------------|-------|----------|--------|
| 1 | `i % 3 == 0` | 127 | [`kaggle_train_shard1.ipynb`](kaggle/kaggle_train_shard1.ipynb) | `adapter_kaggle1.zip` |
| 2 | `i % 3 == 1` | 127 | [`kaggle_train_shard2.ipynb`](kaggle/kaggle_train_shard2.ipynb) | `adapter_kaggle2.zip` |
| 3 | `i % 3 == 2` | 127 | [`kaggle_train_shard3.ipynb`](kaggle/kaggle_train_shard3.ipynb) | `adapter_kaggle3.zip` |

Each shard runs 60 PPO updates × 3 rollouts × 12 steps = 2160 env transitions on a single Kaggle T4 in roughly 4–6 hours. Three free Kaggle accounts run in parallel; `scripts/merge_lora_adapters.py` then takes a weighted mean of the three resulting LoRA deltas into a single adapter.

### GitHub → Kaggle pipeline

The notebooks deliberately do **not** vendor the training code — every cell-5 run does:

```python
!git clone --depth 1 https://github.com/r1cksync/meta-rl-hack.git
%cd meta-rl-hack/incident-commander
```

…so any commit on `main` is picked up automatically without re-uploading the `.ipynb`. Cell 6 sets the per-shard env vars (`IC_TASK_SHARD`, `IC_RUN_NAME`, …); cell 7 invokes `python scripts/run_training.py` which loads the actor + critic, builds the env, runs the PPO loop, and writes:

- `colab/logs/training_kaggle{N}.json` — per-update metrics (reward, KL, loss, value error, per-task rewards)
- `adapter_kaggle{N}/` — final LoRA at update 60, plus checkpoints every 15 updates
- The notebook's cell 8 zips the adapter and copies the JSON log to `/kaggle/working/` so they show up as downloadable outputs.

After all three shards finish:

```bash
python scripts/merge_lora_adapters.py \
    --adapters adapter_kaggle1 adapter_kaggle2 adapter_kaggle3 \
    --output  adapter_merged \
    --weights 1.0 1.0 1.0
```

The merged adapter is then loaded on top of the same 4-bit Phi-3.5-mini base for inference / evaluation.

---

## Production Pipeline (Terraform → Hetzner → k3s)

The agent's write actions normally land in a mock cluster (`MOCK_MODE=true`), but the same code path can drive a real Kubernetes cluster (`REAL_K8S=true`). We provision that cluster with Terraform on Hetzner Cloud — €20 / month for a usable demo cluster.

```
infra/terraform/main.tf       Hetzner Cloud network + 3 servers + load balancer
infra/k8s/                    Deployments / Services / ConfigMaps for the 5 microservices
infra/helm/acmecorp/          Helm chart that rolls everything out
infra/aws/   infra/eks/       Optional AWS variant if you have free EKS credits
```

The Terraform module declares:

| Resource | Purpose |
|----------|---------|
| `hcloud_network` | Private 10.0.0.0/16 VPC |
| `hcloud_network_subnet` | 10.0.1.0/24 in `eu-central` |
| `hcloud_ssh_key` | Reads `~/.ssh/id_rsa.pub` |
| `hcloud_server` × 3 | `cx21` Ubuntu nodes (1 master + 2 worker) |
| `hcloud_load_balancer` | `lb11` in front of the cluster |
| `hcloud_load_balancer_target` × 3 | Health-checked targets |
| `hcloud_load_balancer_service` × 2 | Public HTTP (80) + HTTPS (443) listeners |

Bring-up:

```bash
cd infra/terraform
terraform init
terraform apply -var="hcloud_token=$HCLOUD_TOKEN"

# Master IP from terraform output
ssh root@$MASTER curl -sfL https://get.k3s.io | sh -

# Roll out AcmeCorp microservices
helm install acmecorp infra/helm/acmecorp --set image.tag=$GIT_SHA

# Point the agent at the live cluster
export REAL_K8S=true
export KUBECONFIG=~/.kube/config
python -m rl_agent.server
```

---

## File / JSON Index

| Path | What it is |
|------|------------|
| `rl-agent/scenarios/{easy,medium,hard}/*.json` | 23 hand-curated incident archetypes (id, difficulty, title, description, preconditions, correct_action_chain, target_score, max_steps). |
| `rl-agent/scenarios/sim/{easy,medium,hard}/*.json` | 381 simulator-grade RL scenarios (156 + 128 + 97). Adds `topology_overrides`, `saboteur`, `slack`, `traffic_profile`, `k8s_controller`, `seed`. |
| `colab/logs/training_kaggle{1,2,3}.json` | Per-update training metrics for one shard: `update, elapsed_s, mean_reward, mean_value, ppo{loss, kl, policy_loss, value_err}, rewards_by_task`. The union of `rewards_by_task` keys across all three files = full 381-task coverage proof. |
| `kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/adapter_config.json` | LoRA configuration emitted by PEFT (`r=16, alpha=32, target_modules=[…]`). |
| `kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/adapter_model.safetensors` | The actual LoRA delta — ~50 MB per shard. Loadable with `PeftModel.from_pretrained(base, path)`. |
| `rl-agent/showcase_data.json` | Pre-computed bundle that hydrates the `/showcase` page. Built by `scripts/build_showcase_data.py`. |
| `openenv.yaml` | OpenEnv manifest declaring `/reset, /step, /state, /health`. |
| `frontend/package.json` | Next.js 14 AcmeCorp e-commerce app — both chaos target and live UI. |
| `frontend/tsconfig.json` | Strict TS configuration. |
| `frontend/tailwind.config.js`, `postcss.config.js` | Frontend styling stack. |
| `backend/{payments-api,inventory-service,notification-service,order-worker}/package.json` | Per-service Node apps that get rolled out, restarted, scaled, and patched by agent actions. |
| `infra/terraform/main.tf` | Hetzner cluster provisioning (network, subnet, ssh key, 3 servers, load balancer, listeners). |
| `infra/k8s/*.yaml` | Deployments, Services, ConfigMaps, ChaosMesh experiments for the live cluster. |

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/tasks` | GET | Task list with action schema |
| `/reset` | POST | Reset environment (accepts `task_id`, `adversarial`, `use_curriculum`, `persona`, `use_llm_judge`) |
| `/step` | POST | Execute an action |
| `/state` | GET | Current episode state with investigation tracking, phase, judge result |
| `/grader` | POST | Holistic score for last completed episode + curriculum block |
| `/baseline` | POST | Run heuristic agent and return episode trace |
| `/curriculum` | GET | Current tier, mastery map, episode counts |
| `/curriculum/reset` | POST | Reset curriculum state (optional `tier` to pin) |
| `/adversarial/design` | POST | Design a novel scenario (LLM or procedural) |
| `/judge/config` | POST | Switch judge persona / toggle LLM judge |
| `/dashboard` | GET | **Live diagnostic dashboard** with tier + phase indicators |
| `/showcase` | GET | **Showcase page** — every task, action, reward, training curve, file index |
| `/showcase/data` | GET | Pre-computed JSON bundle (381 scenarios + 3 shards × 60 updates) |
| `/docs` | GET | Swagger UI |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    IncidentCommander                            │
│                                                                 │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐              │
│  │ RL Agent │──│ OpenEnv API │──│ Graders      │              │
│  │ (LLM /   │  │ reset()     │  │ - Postmortem │              │
│  │  PPO /   │  │ step()      │  │ - BlastRadius│              │
│  │Heuristic)│  │ state()     │  │ - Holistic   │              │
│  └──────────┘  │ grader()    │  └──────────────┘              │
│                │ baseline()  │                                 │
│                └──────┬──────┘                                 │
│                       │                                        │
│         ┌─────────────┼──────────────┐                         │
│         ▼             ▼              ▼                          │
│  ┌────────────┐ ┌──────────┐ ┌─────────────┐                  │
│  │ Prometheus │ │   Loki   │ │ Chaos Mesh  │                  │
│  │  Metrics   │ │   Logs   │ │ Fault Inject│                  │
│  └─────┬──────┘ └────┬─────┘ └──────┬──────┘                  │
│        └──────────────┼──────────────┘                         │
│                       ▼                                        │
│  ┌─────────────────────────────────────────┐                   │
│  │        AcmeCorp E-Commerce Platform     │                   │
│  │  5 microservices + Kafka + Redis +      │                   │
│  │  Postgres + full observability stack    │                   │
│  └─────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
incident-commander/
├── openenv.yaml                 # OpenEnv spec (7 tasks, endpoints, scoring)
├── inference.py                 # LLM agent (OpenAI function calling)
├── Dockerfile                   # HF Spaces deployment
├── pyproject.toml               # Python packaging + uv
├── docker-compose.yml           # Full stack orchestration
│
├── rl-agent/                    # Core RL environment
│   ├── server.py                # FastAPI server (reset/step/state/grader/baseline/dashboard)
│   ├── dashboard.html           # Live Plotly.js diagnostic dashboard
│   ├── environment/
│   │   ├── env.py               # IncidentCommanderEnv — context-gated rewards, 7 tasks
│   │   ├── models.py            # Pydantic models (Observation, Action, StepResult)
│   │   ├── prometheus_client.py # Prometheus/Alertmanager async client
│   │   ├── loki_client.py       # Loki log query client
│   │   ├── chaos_client.py      # Chaos Mesh API client
│   │   └── graders/
│   │       ├── postmortem_grader.py  # NLP postmortem scoring
│   │       └── blast_radius_tracker.py
│   ├── scenarios/               # 7 task scenario definitions (JSON)
│   ├── training/                # PPO training scripts
│   └── tests/                   # Pytest suite
│
├── frontend/                    # Next.js 14 storefront
├── backend/                     # 4 microservices (Python/Go/TS)
│   ├── payments-api/            # FastAPI — orders, payments, Kafka
│   ├── inventory-service/       # Go/Gin — product catalog, Redis
│   ├── order-worker/            # Celery — async order processing
│   └── notification-service/    # Express/TS — email notifications
│
├── observability/               # Prometheus + Loki + Grafana + Alertmanager
├── chaos/                       # Chaos Mesh fault definitions (7 scenarios)
├── infra/                       # K8s manifests, Helm charts, Terraform
├── traffic/                     # Locust load generator
└── scripts/                     # Cluster setup, fault injection, health checks
```

---

## Key Differentiators

| Feature | IncidentCommander | Typical RL Env |
|---------|-------------------|---------------|
| Tasks | 7 (2 easy, 2 medium, 3 hard) | 1-3 |
| Observations | Real Prometheus/Loki/Alertmanager | Synthetic |
| Actions | 10 types with real K8s effects | Simple discrete |
| Red herrings | Yes (tasks 3, 5, 6, 7) | No |
| Context-gated rewards | Yes (-0.20 for acting blind) | No |
| Holistic grading | Investigation + mitigation + efficiency | Final reward only |
| Live dashboard | Plotly.js at /dashboard | None |
| Baseline agent | Built-in heuristic at /baseline | External |
| Infrastructure | 5 microservices + full observability | Simulated |

---

## License

MIT
