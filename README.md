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
- **Real infrastructure simulation.** Observations model actual Prometheus/Loki/Alertmanager data. Write actions have real consequences.
- **Context-gated rewards.** Agents are penalized for acting without investigating first. If you rollback before reading logs, you lose points — just like in real SRE.
- **Red herrings on hard tasks.** Tasks 3, 6, and 7 contain deliberate distractors that punish agents for jumping to conclusions.
- **Holistic episode grading** separate from per-step rewards. The grader evaluates the full investigation: did the agent look at the right logs? Did it avoid unnecessary damage? Did it identify root cause correctly?

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
| **Acting blind penalty** | **-0.20** | Write action without any prior investigation |
| **Red herring penalty** | **-0.15** | Targeting a known distractor service |
| Wrong service penalty | -0.15 | Write action targets wrong service |
| Time penalty | -0.05/step | Per step beyond step 5 |
| Blast radius increase | -0.10 | Write action worsens error rate |

**Context-gated penalties** are the key differentiator. The "acting blind" penalty fires when an agent takes a write action without having inspected any logs or metrics first. The "red herring" penalty fires when an agent targets a service that the task explicitly marks as a distractor.

**Reward range**: [-2.0, 1.0]  |  **Score range**: [0.001, 0.999]

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

# Run LLM inference
API_BASE_URL=https://api.openai.com/v1 MODEL_NAME=gpt-4o HF_TOKEN=sk-... python inference.py
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/tasks` | GET | Task list with action schema |
| `/reset` | POST | Reset environment for a task |
| `/step` | POST | Execute an action |
| `/state` | GET | Current episode state with investigation tracking |
| `/grader` | POST | Holistic score for last completed episode |
| `/baseline` | POST | Run heuristic agent and return episode trace |
| `/dashboard` | GET | **Live diagnostic dashboard** (Plotly.js) |
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
