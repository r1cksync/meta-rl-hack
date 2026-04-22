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

[Live Dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard) | [API Health](https://sagnik-mukherjee-incodent-commander.hf.space/health) | [API Docs](https://sagnik-mukherjee-incodent-commander.hf.space/docs)

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

## vs. prior OpenEnv winners (kube-sre-gym)

| Capability | kube-sre-gym (prev $15K winner) | IncidentCommander |
|-----------|-------------------------------|-------------------|
| Live K8s cluster | ✅ (kind) | ✅ optional (`REAL_K8S=true`), mock by default |
| Mock-only CI mode | ❌ | ✅ zero-dep mock mode |
| Curriculum with auto-promotion | ✅ 5 tiers | ✅ 5 tiers (warmup→expert) |
| Adversarial LLM-designed scenarios | ✅ expert tier only | ✅ expert tier + procedural fallback |
| Multi-fault scenarios | ✅ | ✅ (advanced + expert tiers) |
| LLM judge with multiple personas | ❌ (single judge) | ✅ 3 personas (junior/senior/principal) |
| Phase-aware rewards (triage→verify) | ❌ | ✅ |
| Repeat-command penalty | ✅ | ✅ |
| Red-herring penalty | ❌ | ✅ on hard tasks |
| Context-gated "acting blind" penalty | ❌ | ✅ |
| Holistic per-episode grader | ❌ | ✅ 5-component rubric |
| Live plotly dashboard | ❌ | ✅ with tier + phase indicators |
| TRL GRPO training script | ✅ | ✅ |
| Base-vs-trained `eval.py` | ✅ | ✅ |
| Runs on HF Spaces Docker | ❌ (kind not available) | ✅ |

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
