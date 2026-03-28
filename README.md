# 🚨 IncidentCommander

**An OpenEnv-compatible RL environment where AI agents learn Site Reliability Engineering (SRE) incident response on a live e-commerce platform.**

---

## Overview

IncidentCommander drops an AI agent into the shoes of an on-call SRE at **AcmeCorp**, a microservices-based e-commerce company. The agent must diagnose real infrastructure failures using Prometheus metrics, Loki logs, and distributed traces — then fix them with real kubectl/Helm commands — all while minimizing blast radius and customer impact.

### Why This Matters

- 🔥 **Every observation is real** — Prometheus metrics, Loki logs, Alertmanager alerts from a live cluster
- 🔧 **Every action has consequences** — `rollback_deployment`, `restart_pods`, `scale_deployment` execute against real infrastructure
- 📊 **Deterministic, shaped rewards** — based on error rates, blast radius, root cause accuracy, and postmortem quality
- 🎯 **3 graded tasks** from easy → hard, testing different SRE skills

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    IncidentCommander                            │
│                                                                 │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐              │
│  │ RL Agent │──│ OpenEnv API │──│ Graders      │              │
│  │ (PPO /   │  │ reset()     │  │ - Postmortem │              │
│  │  LLM)    │  │ step()      │  │ - BlastRadius│              │
│  └──────────┘  │ state()     │  └──────────────┘              │
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
│  │                                         │                   │
│  │  Frontend ──→ Payments API ──→ Postgres │                   │
│  │     │            │                      │                   │
│  │     └──→ Inventory Svc ──→ Redis        │                   │
│  │              │                          │                   │
│  │     Order Worker ──→ Kafka              │                   │
│  │              │                          │                   │
│  │     Notification Svc ──→ SMTP           │                   │
│  └─────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tasks

| ID | Name | Difficulty | Target Score | Description |
|----|------|-----------|-------------|-------------|
| `task1` | Redis Pool Exhaustion | Easy (0.80) | 80% | NetworkChaos adds 500ms latency to Redis, saturating connection pools in inventory-service |
| `task2` | Cascading OOM | Medium (0.45) | 45% | StressChaos causes payments-api OOM kills, cascading to order-worker and notification-service |
| `task3` | Silent Decimal Corruption | Hard (0.20) | 20% | A bad deployment (v2.3.2) introduces floating-point rounding errors in payment totals |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2
- Python 3.11+
- (Optional) kubectl, helm for K8s deployment

### 1. Clone & Configure

```bash
git clone <repo-url>
cd incident-commander
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start the Platform

```bash
# Core services only
docker compose up -d --build

# With monitoring (Prometheus, Grafana, Loki, Jaeger)
docker compose --profile monitoring up -d

# Everything including traffic generator
docker compose --profile full up -d
```

### 3. Verify Health

```bash
./scripts/health-check.sh
```

### 4. Run the RL Agent

```bash
# Start the OpenEnv API server
docker compose up rl-agent -d

# Test it
curl http://localhost:8000/health
curl -X POST http://localhost:8000/reset -H 'Content-Type: application/json' -d '{"task_id": "task1"}'
```

### 5. Run Inference (LLM Baseline)

```bash
cd rl-agent
pip install -r requirements.txt

# With Anthropic Claude
export ANTHROPIC_API_KEY=sk-...
python inference.py --task task1 --provider anthropic

# With OpenAI
export OPENAI_API_KEY=sk-...
python inference.py --task task1 --provider openai
```

---

## OpenEnv API

The environment exposes three endpoints per the OpenEnv spec:

### `POST /reset`

```json
{
  "task_id": "task1"
}
```

Returns: `Observation` — alerts, logs, service health, blast radius, available actions

### `POST /step`

```json
{
  "action": {
    "type": "query_logs",
    "params": {
      "service": "inventory-service",
      "last_minutes": 5
    }
  }
}
```

Returns: `StepResult` — observation, reward, done, info

### `GET /state`

Returns current environment state including cumulative reward, action history, and episode status.

---

## Action Space

| Action | Type | Description |
|--------|------|-------------|
| `query_logs` | Read | Query Loki logs for a service |
| `query_metrics` | Read | Execute PromQL query |
| `get_service_dependencies` | Read | Get dependency graph for a service |
| `get_trace` | Read | Fetch distributed trace by ID |
| `rollback_deployment` | Write | Roll back a K8s deployment to previous revision |
| `restart_pods` | Write | Rolling restart of deployment pods |
| `scale_deployment` | Write | Change replica count (0-20) |
| `apply_config_patch` | Write | Set environment variable on a deployment |
| `delete_chaos_experiment` | Write | Remove a Chaos Mesh experiment |
| `submit_postmortem` | Terminal | Submit root cause analysis (ends episode) |

---

## Reward Function

Deterministic, shaped reward signal:

| Component | Value | Condition |
|-----------|-------|-----------|
| Root cause correct | +0.30 | Postmortem root cause matches ground truth |
| Correct mitigation | +0.20 | Right action on right target before step 10 |
| Useful log query | +0.10 | Log query returns task-relevant keywords |
| Postmortem quality | +0.20 | NLP-scored postmortem (root cause + timeline + mitigations + writing) |
| Wrong service penalty | -0.15 | Write action targets wrong service |
| Time penalty | -0.05/step | Per step beyond step 5 |
| Blast radius increase | -0.10 | Write action worsens error rate |

**Reward range**: [-2.0, 1.0]

---

## Training

Train a PPO agent using stable-baselines3:

```bash
cd rl-agent
python -m training.train_ppo --total-timesteps 100000 --task task1

# With Weights & Biases logging
WANDB_API_KEY=... python -m training.train_ppo --total-timesteps 100000 --wandb
```

---

## Project Structure

```
incident-commander/
├── openenv.yaml                 # OpenEnv spec definition
├── docker-compose.yml           # Full stack orchestration
├── Makefile                     # Common commands
├── .env.example                 # Environment variables template
│
├── rl-agent/                    # Core RL environment
│   ├── environment/
│   │   ├── env.py               # IncidentCommanderEnv (reset/step/state)
│   │   ├── models.py            # Pydantic models (Observation, Action, etc.)
│   │   ├── prometheus_client.py # Prometheus/Alertmanager async client
│   │   ├── loki_client.py       # Loki log query client
│   │   ├── chaos_client.py      # Chaos Mesh API client
│   │   └── graders/
│   │       ├── postmortem_grader.py  # NLP postmortem scoring
│   │       └── blast_radius_tracker.py
│   ├── scenarios/               # Task scenario definitions (JSON)
│   ├── training/                # PPO training scripts
│   ├── tests/                   # Pytest test suite
│   ├── server.py                # FastAPI OpenEnv server
│   ├── inference.py             # LLM baseline agent
│   └── Dockerfile
│
├── frontend/                    # Next.js 14 storefront
│   └── src/app/                 # Pages: products, cart, checkout, orders, health
│
├── backend/
│   ├── payments-api/            # FastAPI — orders, payments, Kafka producer
│   ├── inventory-service/       # Go/Gin — product catalog, Redis cache
│   ├── order-worker/            # Celery — async order processing
│   └── notification-service/    # Express/TS — email notifications
│
├── observability/
│   ├── prometheus/              # Prometheus config + alert rules
│   ├── loki/                    # Loki + Promtail config
│   ├── grafana/                 # Dashboards + provisioning
│   └── alertmanager/            # Alert routing config
│
├── chaos/                       # Chaos Mesh fault definitions
│   ├── easy-redis-latency.yaml
│   ├── medium-payments-memory-stress.yaml
│   └── hard-silent-decimal-corruption.yaml
│
├── traffic/                     # Locust load generator
│   └── locustfile.py
│
├── infra/
│   ├── k8s/                     # Kubernetes manifests
│   ├── helm/                    # Helm charts
│   └── terraform/               # Hetzner k3s provisioning
│
└── scripts/
    ├── setup-cluster.sh
    ├── reset-cluster.sh
    ├── inject-fault.sh          # Inject faults by task (easy/medium/hard)
    ├── health-check.sh
    └── build-all.sh
```

---

## Environment Variables

| Variable | Description | Default |
|----------|------------|---------|
| `PROMETHEUS_URL` | Prometheus endpoint | `http://localhost:9090` |
| `LOKI_URL` | Loki endpoint | `http://localhost:3100` |
| `CHAOS_MESH_URL` | Chaos Mesh API | `http://localhost:2333` |
| `MOCK_MODE` | Use simulated observations | `true` |
| `ANTHROPIC_API_KEY` | Anthropic API key for inference | — |
| `OPENAI_API_KEY` | OpenAI API key for inference | — |
| `DATABASE_URL` | PostgreSQL connection string | — |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers | `kafka:9092` |
| `REDIS_ADDR` | Redis connection | `redis:6379` |

---

## Testing

```bash
cd rl-agent
pip install -r requirements.txt pytest pytest-asyncio
pytest -v
```

Test modules:
- `test_reward.py` — Reward function edge cases
- `test_env_reset.py` — Reset/state lifecycle
- `test_actions.py` — All 10 action types
- `test_postmortem_grader.py` — NLP grading logic
- `test_loki_client.py` — Loki client with mocked responses

---

## Inject Faults

```bash
# Easy: Redis latency
./scripts/inject-fault.sh easy

# Medium: OOM cascade
./scripts/inject-fault.sh medium

# Hard: Silent decimal bug
./scripts/inject-fault.sh hard

# Clean up all faults
./scripts/inject-fault.sh clean
```

---

## Monitoring URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Storefront | http://localhost:3000 | — |
| Grafana | http://localhost:3001 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Jaeger | http://localhost:16686 | — |
| Locust | http://localhost:8089 | — |
| MailHog | http://localhost:8025 | — |
| RL Agent API | http://localhost:8000 | — |

---

## License

MIT
