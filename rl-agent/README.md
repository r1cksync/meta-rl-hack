---
title: IncidentCommander
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
tags:
  - openenv
  - sre
  - incident-response
  - reinforcement-learning
pinned: false
---

# IncidentCommander

An OpenEnv-compatible RL environment where AI agents learn SRE incident response.

## API Endpoints

- `POST /reset` — Reset with `{"task_id": "task1"}` (task1/task2/task3)
- `POST /step` — Execute action `{"action_type": "query_logs", "params": {"service": "payments-api"}}`
- `GET /state` — Current environment state
- `GET /health` — Health check

## Tasks

| Task | Difficulty | Description |
|------|-----------|-------------|
| task1 | Easy | Redis connection pool exhaustion |
| task2 | Medium | Cascading OOM in payments-api |
| task3 | Hard | Silent decimal corruption |
