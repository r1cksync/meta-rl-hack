# Env spec — **Deep regime** (Rounds 1 + 2)

> The hand‑curated task set used by the legacy SB3 baseline (Round 1, 7 tasks) and
> the hybrid Ollama/Groq PPO loops (Round 2, 11 tasks). The training code paths
> are [`rl-agent/training/train_enhanced.py`](../rl-agent/training/train_enhanced.py)
> (Round 1) and [`rl-agent/training/train_hybrid.py`](../rl-agent/training/train_hybrid.py)
> (Round 2). All runs use the same `IncidentCommanderEnv` defined in
> [`rl-agent/environment/env.py`](../rl-agent/environment/env.py); only the task
> pool changes round‑to‑round.

## 1 · Task pool (11 hand‑curated archetypes)

Each task is a single JSON file in
[`rl-agent/scenarios/`](../rl-agent/scenarios) declaring `id, difficulty, title,
description, preconditions, correct_action_chain, target_score, max_steps`. The
mapping `task_id → file` lives in `TASK_FILE_MAP` of `env.py`.

| ID | Difficulty | Target score | Title | Root cause | Correct fix |
| --- | --- | ---: | --- | --- | --- |
| `task1` | Easy | 0.80 | Redis Connection Pool Exhaustion | Chaos‑Mesh latency injection saturates the inventory→Redis pool | `delete_chaos_experiment` |
| `task2` | Medium | 0.45 | Cascading Failure via Payments OOM | Memory stress on `payments-api` → OOM → Kafka lag in inventory | `rollback_deployment payments-api` |
| `task3` | Hard | 0.20 | Silent Decimal Corruption | Bad deploy truncates `NUMERIC(12,4) → NUMERIC(12,2)`. Postgres VACUUM is a red herring. | `rollback_deployment payments-api` + audit recommendation |
| `task4` | Easy | 0.80 | Kafka Broker Network Partition | Chaos‑Mesh partitions the broker; consumer lag >5 000 across `order-worker`+`notification-service` | `delete_chaos_experiment` |
| `task5` | Medium | 0.45 | DNS Resolution Failure | DNS chaos → NXDOMAIN; "connection refused" is a secondary symptom | `delete_chaos_experiment` |
| `task6` | Hard | 0.20 | TLS Certificate Expiry Cascade | Expired mTLS cert breaks payments→postgres; ECONNRESET elsewhere is downstream | `apply_config_patch payments-api` (cert rotate) |
| `task7` | Hard | 0.20 | ConfigMap Hot‑Reload Race | Race causes 2/4 `inventory-service` pods to load stale config; Redis/GC alerts are red herrings | `restart_pods inventory-service` |
| `task8` | Medium | 0.45 | JWT Secret Rotation Cascade | Auth secret rotation regression breaks all sessions | `rollback_deployment auth-service` |
| `task9` | Easy | 0.80 | Invalid Image Tag Deploy | `checkout-frontend` deployed with bad tag → ImagePullBackOff. Hint: ECR / ImagePullSecret. | `rollback_deployment checkout-frontend` |
| `task10` | Medium | 0.45 | Namespace ResourceQuota Starvation | `payments-worker` blocked by namespace quota | `apply_config_patch payments-worker` |
| `task11` | Hard | 0.20 | Liveness Probe Path Regression | Bad probe path on `inventory-service` → flapping pods | `rollback_deployment inventory-service` |

**Round 1 (Legacy SB3)** used `task1, task2, task3` (the three hardest curated
archetypes — easy/medium/hard Redis/payments/decimal). Evaluation episodes
covered all 7 tasks. **Round 2 (Hybrid v2/v3/v4)** used the full 11 tasks with
3–4 episodes per task per update. Per‑task results land in
`rl-agent/checkpoints/ppo-v{2,3,4}-*/summary.json`.

## 2 · Observation channels

Every step returns an `Observation` (defined in
[`rl-agent/environment/models.py`](../rl-agent/environment/models.py))
with the following channels:

| Channel | Source | Notes |
| --- | --- | --- |
| `metrics` | `PrometheusClient` | PromQL counters/gauges per service (error_rate, p95, mem_pct, …) |
| `logs` | `LokiClient` | Ranked log lines, tunable `last_minutes` window + `filter_text` |
| `alerts` | Alertmanager | Severity‑tagged active alerts |
| `topology` | static deps map | Upstream/downstream dependency graph |
| `traces` | mock Jaeger | Per‑request spans (only for tasks that surface trace IDs) |
| `chaos_experiments` | Chaos Mesh API | List of currently‑injected faults (visible only after `query_logs`) |
| `episode_state` | env | `step_idx`, `phase`, `blast_radius`, `judge.score`, `tier` |

Reward range is `[−2.0, +1.0]`; episode score (used by `/grader`) is clamped to
`[0.001, 0.999]`.

## 3 · Action space (10 actions)

| Action | Class | Effect |
| --- | --- | --- |
| `query_logs(service, last_minutes, filter_text?)` | investigate | Read Loki — keyword filter rewards information gain |
| `query_metrics(promql, last_minutes?)` | investigate | Run PromQL |
| `get_service_dependencies(service)` | investigate | Topology fetch |
| `get_trace(trace_id)` | investigate | Span list |
| `rollback_deployment(deployment)` | fix · write | Roll back to previous revision |
| `restart_pods(deployment)` | fix · write | Rolling restart |
| `scale_deployment(deployment, replicas)` | fix · write | Replica count 0–20 |
| `apply_config_patch(deployment, env_var, value)` | fix · write | Patch env var |
| `delete_chaos_experiment(experiment_name)` | fix · write | Remove an injected fault |
| `submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups)` | terminal | Episode ends |

The full enum is in `models.py :: ActionType`. The four extra
investigate/AWS‑flavoured actions (`exec_kubectl`, `check_cloudtrail_events`,
…) were added later for the 381‑task regime — see
[`docs/ENV_SHALLOW.md`](ENV_SHALLOW.md). The deep‑regime training scripts
[`train_enhanced.py`](../rl-agent/training/train_enhanced.py) and
[`train_hybrid.py`](../rl-agent/training/train_hybrid.py) only emit the 10
actions in the table above.

## 4 · Reward signal

`IncidentCommanderEnv._compute_reward` composes each step's reward from these
named components — every component shows up in
`rl-agent/checkpoints/ppo-v{3,4}-*/reward_breakdown_history.jsonl` so any claim
is auditable:

| Event | Reward | Why |
| --- | ---: | --- |
| Any step | −0.01 | Step cost — efficiency |
| First‑time investigation (per service / metric) | +0.05 | Encourages thorough recon |
| Useful log query (keyword‑gated) | +0.10 | Information gain, not button‑mashing |
| Correct mitigation before step 10 | +0.20 | Right action on right target |
| Postmortem root cause correct | +0.30 | The actual point of the job |
| Postmortem quality (NLP‑scored) | up to +0.20 | Timeline + mitigations + writing |
| **Phase‑order bonus** | **+0.10** | `triage → investigate → fix → verify` progression |
| **LLM judge contribution** | **up to +0.15** | Junior / Senior / Principal persona, scaled |
| **Acting blind** | **−0.20** | Write action with zero prior investigation |
| **Red‑herring penalty** | **−0.15** | Targeting a service the task marks as a distractor |
| **Repeat‑command** | **−0.15 / repeat** (cap −0.45) | Kills reward‑hacking via spam |
| **Phase regression** | **−0.10** | Going back to triage after fixing |
| Wrong service | −0.15 | Write action on wrong target |
| Blast‑radius increase | −0.10 | Write action worsens error rate |
| Time penalty | −0.05 / step | After step 5 |

**Heuristic baseline scores** (from `/baseline`, fixed strategy per task —
demonstrates the rubric is achievable):

| Task | Heuristic score | Target score |
| --- | ---: | ---: |
| `task1` | 0.90 | 0.80 |
| `task2` | 0.85 | 0.45 |
| `task3` | 0.85 | 0.20 |
| `task4` | 0.90 | 0.80 |
| `task5` | 0.85 | 0.45 |
| `task6` | 0.80 | 0.20 |
| `task7` | 0.80 | 0.20 |
| **Average (1–7)** | **0.85** | — |

## 5 · Holistic grader (per‑episode, separate from per‑step reward)

Runs at `submit_postmortem`. Output is the 0–1 episode score reported by
`/grader`.

| Component | Max | What it measures |
| --- | ---: | --- |
| Investigation thoroughness | 0.25 | Logs / metrics / deps / traces inspected |
| Correct mitigation | 0.25 | Right action on right target |
| Root cause identification | 0.25 | Postmortem matches ground truth |
| Efficiency | 0.15 | Fewer steps is better |
| No unnecessary damage | 0.10 | Write actions didn't worsen blast radius |

## 6 · Deep‑regime training results (headline numbers)

| Round | Run | Episodes | Mean reward | Top per‑task mean | Mitigation rate | Logs |
| --- | --- | ---: | ---: | --- | ---: | --- |
| 1 | SB3 PPO + MLP, 200 k timesteps | 90 (eval) | **1.05** | n/a (uniform 1.05 across all 7 eval tasks) | **100 %** | [`evaluation_report.json`](../rl-agent/checkpoints/evaluation_report.json) · [`training_metrics.json`](../rl-agent/checkpoints/training_metrics.json) |
| 2 · v2 | heuristic actor, no critic | 99 | 1.17 | 1.60 (`task1`,`task4`) | **100 %** | [`ppo-v2-heuristic/`](../rl-agent/checkpoints/ppo-v2-heuristic) |
| 2 · v3 | Ollama Qwen2.5:0.5b actor, heuristic critic | 36 | 1.32 | 1.72 (`task10`) | 69 % | [`ppo-v3-hybrid-ollama-bedrock/`](../rl-agent/checkpoints/ppo-v3-hybrid-ollama-bedrock) |
| 2 · v4 | Ollama Qwen2.5:0.5b actor, **Groq Llama‑3.1‑8B‑instant** critic | 36 | **1.78** | **2.41** (`task9`) | 44 % | [`ppo-v4-hybrid-ollama-groq/`](../rl-agent/checkpoints/ppo-v4-hybrid-ollama-groq) |

Across all three Round‑2 runs, policy loss collapses (1.20 → 0.083 in v2 over
33 updates; 1.10 → 0.50 in v3/v4 over 12 updates), entropy compresses (~2.0 →
0.39 in v2; ~1.9 → 1.21 in v3/v4), and v4's small‑LLM actor with the Groq
critic clears the heuristic ceiling on the hardest tasks. The 3‑panel chart
that visualises this is [`assets/blog/legacy_deep_training.png`](../assets/blog/legacy_deep_training.png).
