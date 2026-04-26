# Teaching an LLM to be on‑call: how we built IncidentCommander

> A story about why most RL benchmarks for LLMs are too clean, what happens when
> you replace the puzzle with a real 3 AM PagerDuty incident, and how we trained
> a 4-bit Phi‑3.5‑mini agent across 381 procedurally‑generated production
> outages — on three free Kaggle T4s.

**Hackathon:** Meta PyTorch OpenEnv × Scaler School of Technology, 2026
**Live env:** [https://sagnik-mukherjee-incodent-commander.hf.space](https://sagnik-mukherjee-incodent-commander.hf.space)
**Showcase:** [/showcase](https://sagnik-mukherjee-incodent-commander.hf.space/showcase)
**Dashboard:** [/dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard)
**Code:** [github.com/r1cksync/meta-rl-hack](https://github.com/r1cksync/meta-rl-hack)
**Video walkthrough (4 min):** **[youtu.be/aBnQ33q9MMw](https://youtu.be/aBnQ33q9MMw)**

---

## 1 · The problem — what capability gap are we targeting?

Every Site Reliability Engineer has been there. PagerDuty goes off at 3 AM,
five services are red, the CEO is in Slack typing "what's happening", a
frontend dev wants to know if their hotfix broke prod, and the intern is
suggesting "should I just restart the cluster?". Logs say one thing. Metrics
say another. A runbook says a third. You have ten minutes before this becomes
a public outage.

That cognitive load — *parse noisy human chatter, weight it against telemetry,
ignore plausible distractors, follow the right phase order, undo the right
thing without making it worse* — is exactly the capability LLMs are weakest
at. Most RL benchmarks for language agents use synthetic puzzles or web
navigation. We don't. **Every observation in IncidentCommander is the kind of
ambiguous, partially‑adversarial signal a real on‑call engineer actually
sees.**

Concretely, we wanted to answer: *can an LLM agent learn to triage like a
senior SRE — investigate first, weight noisy human channels, follow
triage → investigate → fix → verify, and survive multi‑fault scenarios where
one fix is never enough?*

---

## 2 · The environment — what does the agent see, do, and get rewarded for?

> **Full env reference (inlined below)** — everything that used to live in `docs/ENV_DEEP.md`, `docs/ENV_SHALLOW.md`, and `docs/TASKS_SHALLOW.md` is reproduced inline in §2.0 so this blog is self-contained.

### 2.0 · Full env reference (inlined)

The three sub-sections below are the complete contents of the standalone reference docs, ordered **deep regime first, then shallow regime, then the full per-task index**. Deep is read first because it's the smaller hand-curated set whose results validated the rubric we then scaled to 381 procedural scenarios.

<a id="inlined-deep-spec"></a>

#### 2.0a · Deep regime spec — Rounds 1 + 2 (11 hand-curated archetypes)

> The hand‑curated task set used by the legacy SB3 baseline (Round 1, 7 tasks) and
> the hybrid Ollama/Groq PPO loops (Round 2, 11 tasks). The training code paths
> are [`rl-agent/training/train_enhanced.py`](rl-agent/training/train_enhanced.py)
> (Round 1) and [`rl-agent/training/train_hybrid.py`](rl-agent/training/train_hybrid.py)
> (Round 2). All runs use the same `IncidentCommanderEnv` defined in
> [`rl-agent/environment/env.py`](rl-agent/environment/env.py); only the task
> pool changes round‑to‑round.

#### 1 · Task pool (11 hand‑curated archetypes)

Each task is a single JSON file in
[`rl-agent/scenarios/`](rl-agent/scenarios) declaring `id, difficulty, title,
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

#### 2 · Observation channels

Every step returns an `Observation` (defined in
[`rl-agent/environment/models.py`](rl-agent/environment/models.py))
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

#### 3 · Action space (10 actions)

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
[`#inlined-shallow-spec`](#inlined-shallow-spec). The deep‑regime training scripts
[`train_enhanced.py`](rl-agent/training/train_enhanced.py) and
[`train_hybrid.py`](rl-agent/training/train_hybrid.py) only emit the 10
actions in the table above.

#### 4 · Reward signal

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

#### 5 · Holistic grader (per‑episode, separate from per‑step reward)

Runs at `submit_postmortem`. Output is the 0–1 episode score reported by
`/grader`.

| Component | Max | What it measures |
| --- | ---: | --- |
| Investigation thoroughness | 0.25 | Logs / metrics / deps / traces inspected |
| Correct mitigation | 0.25 | Right action on right target |
| Root cause identification | 0.25 | Postmortem matches ground truth |
| Efficiency | 0.15 | Fewer steps is better |
| No unnecessary damage | 0.10 | Write actions didn't worsen blast radius |

#### 6 · Deep‑regime training results (headline numbers)

| Round | Run | Episodes | Mean reward | Top per‑task mean | Mitigation rate | Logs |
| --- | --- | ---: | ---: | --- | ---: | --- |
| 1 | SB3 PPO + MLP, 200 k timesteps | 90 (eval) | **1.05** | n/a (uniform 1.05 across all 7 eval tasks) | **100 %** | [`evaluation_report.json`](rl-agent/checkpoints/evaluation_report.json) · [`training_metrics.json`](rl-agent/checkpoints/training_metrics.json) |
| 2 · v2 | heuristic actor, no critic | 99 | 1.17 | 1.60 (`task1`,`task4`) | **100 %** | [`ppo-v2-heuristic/`](rl-agent/checkpoints/ppo-v2-heuristic) |
| 2 · v3 | Ollama Qwen2.5:0.5b actor, heuristic critic | 36 | 1.32 | 1.72 (`task10`) | 69 % | [`ppo-v3-hybrid-ollama-bedrock/`](rl-agent/checkpoints/ppo-v3-hybrid-ollama-bedrock) |
| 2 · v4 | Ollama Qwen2.5:0.5b actor, **Groq Llama‑3.1‑8B‑instant** critic | 36 | **1.78** | **2.41** (`task9`) | 44 % | [`ppo-v4-hybrid-ollama-groq/`](rl-agent/checkpoints/ppo-v4-hybrid-ollama-groq) |

Across all three Round‑2 runs, policy loss collapses (1.20 → 0.083 in v2 over
33 updates; 1.10 → 0.50 in v3/v4 over 12 updates), entropy compresses (~2.0 →
0.39 in v2; ~1.9 → 1.21 in v3/v4), and v4's small‑LLM actor with the Groq
critic clears the heuristic ceiling on the hardest tasks. The 3‑panel chart
that visualises this is [`assets/blog/legacy_deep_training.png`](assets/blog/legacy_deep_training.png).

<a id="inlined-shallow-spec"></a>

#### 2.0b · Shallow regime spec — Round 3 (381 procedural scenarios)

> The procedural sim curriculum used by the **Phi‑3.5‑mini + DeepSeek‑R1
> Kaggle PPO+LoRA run** ([`scripts/run_training.py`](scripts/run_training.py)
> + [`colab/train_lib.py`](colab/train_lib.py), three Kaggle T4 shards
> merged via [`scripts/merge_lora_adapters.py`](scripts/merge_lora_adapters.py)).
> Same `IncidentCommanderEnv`, but the task pool is the 381 JSON files under
> [`rl-agent/scenarios/sim/{easy,medium,hard}/`](rl-agent/scenarios/sim) and
> the action namespace is the full simulator surface (`platform.*`,
> `dynamodb.*`, `s3.*`, …) — not the 10 actions used by the deep regime.
>
> **For the per‑scenario row‑by‑row index of every one of the 381 tasks** (id, title, target score, max steps, canonical correct action chain) see the companion file [`#inlined-tasks-index`](#inlined-tasks-index).

#### 1 · Task pool — 381 procedural scenarios

```
rl-agent/scenarios/sim/
├── easy/    156 files
├── medium/  128 files
└── hard/     97 files
                ─────
                381 total
```

**Scenario file shape** (extends the hand‑curated archetype JSON with five
extra channels — see [`rl-agent/scenarios/sim/easy/sim_easy_ddb_throttle_101.json`](rl-agent/scenarios/sim/easy/sim_easy_ddb_throttle_101.json)
for an easy example and [`sim_advanced_slack_redherring_001.json`](rl-agent/scenarios/sim/hard/sim_advanced_slack_redherring_001.json)
for a hard one):

| Field | Inherited from archetype? | What it adds |
| --- | --- | --- |
| `id, difficulty, title, description` | yes | — |
| `preconditions, scheduled_failures` | yes | — |
| `correct_action_chain, target_score, max_steps` | yes | — |
| **`topology_overrides`** | **no** | List of `{kind, node, ...}` mutations applied to the dependency graph at reset (`set_leak`, `set_status`, `add_dependency`). Lets the same archetype run against many different broken topologies. |
| **`saboteur`** | **no** | `{primary_target, failover_target, dependency_chain, aggressiveness, cooldown_ticks}`. An adversarial actor that re‑injects the fault when the agent fixes only one symptom. One fix is never enough on hard tasks. |
| **`slack`** | **no** | `{msgs_per_tick}`. Templated coworker chatter rate (CEO, intern, frontend devs, DBAs, finance). Real on‑call signal lives in unstructured human text. |
| **`traffic_profile`** | **no** | `{period, amplitude, phase, jitter}`. Sinusoidal request load — drives metric noise. |
| **`k8s_controller`** | **no** | `bool` — when `true`, an in‑process K8s adversary runs alongside (probe regressions, image pull flaps, …). |
| **`seed`** | **no** | Deterministic — two runs of the same scenario produce identical observations. |

##### Category breakdown

The 381 scenarios cover 12 categories. Counts by directory:

| Directory | Categories | Count |
| --- | --- | ---: |
| `easy/` | DynamoDB throttling (20), KMS rotation (20), Lambda cold start (20), Secrets rotation (20), SQS DLQ (20), SSM drift (20), generated app (28), generated cache (8) | 156 |
| `medium/` | API‑Gateway 5xx, EventBridge silent drop, KMS drift, Lambda throttling, Step Functions failures (15 each); generated red‑herring (20), peak‑load (18), cache (16), app (14) | 128 |
| `hard/` | DynamoDB throttle, IAM drift, generated cascade (24+30), generated DB (24), generated restore (8), API‑Gateway (10), advanced cascade/runbook/saboteur/Slack/trolley (1 each) | 97 |

The four **novelty categories** (Slack Red‑Herring, Runbook Trap, Cascading
Failure, Trolley Problem) are the ones that don't exist in any other RL‑for‑LLM
benchmark.

##### Three‑shard sharding (used by Round 3)

```python
sorted_ids = sorted(all_sim_task_ids)         # 381 ids
shard_i    = [t for k, t in enumerate(sorted_ids) if k % 3 == i]   # 127 ids each
```

Disjoint and exhaustive. Three free Kaggle accounts ran in parallel
(~5 h each). The union of `rewards_by_task` keys across the three log files
[`shard {1,2,3}/training_kaggle{N}.json`](kaggle%20ran%20notebooks) is
**exactly** the set of all 381 task ids — that's the coverage proof.

#### 2 · Observation channels

Same channels as the deep regime (see [`#inlined-deep-spec` §2](#inlined-deep-spec))
**plus three extras that only fire on procedural scenarios:**

| Channel | Source | Notes |
| --- | --- | --- |
| `slack` | env‑internal `SlackChatter` (templated coworker stream) | Deterministic; controlled by `slack.msgs_per_tick` in the scenario JSON. CEO / intern / frontend dev / DBA / finance personas. **Novel.** |
| `saboteur_state` | env‑internal `Saboteur` | Exposes `{primary_target, last_strike_tick, cooldown_remaining}` so the agent can reason about whether a fix actually held. |
| `aws_view` | mock AWS catalog | DynamoDB tables, IAM policies, Secrets Manager secrets, Lambda invocations, … — used by `aws_api_call` and the AWS‑flavoured investigate actions below. |

#### 3 · Action space (full simulator surface)

The deep regime's 10 actions are still valid. Round 3 additionally enables
the AWS / forensic / namespaced actions defined in
[`rl-agent/environment/models.py :: ActionType`](rl-agent/environment/models.py).

##### 3.1 Investigate (read‑only — no blast radius)

| Action | Domain | What it does |
| --- | --- | --- |
| `query_logs` / `query_metrics` / `get_service_dependencies` / `get_trace` | core | Same as deep regime |
| `exec_kubectl(verb, resource, namespace?)` | k8s | Read‑only kubectl (describe, get, top) |
| `check_cloudtrail_events(actor?, action?, resource?, last_minutes?)` | AWS | Audit log search |
| `describe_resource_policy(resource_arn)` | AWS | IAM/S3/SecretsMgr resource policy fetch |
| `get_quota_usage(service, region?)` | AWS | Service Quotas usage |
| `check_secret_rotation(secret_id)` | AWS | Last rotation timestamp + lambda |
| `validate_iam_permission(principal, action, resource)` | AWS | `iam:SimulatePrincipalPolicy` |
| `analyze_cloudwatch_insights(log_group, query, last_minutes?)` | AWS | CloudWatch Insights query |
| `inspect_dlq_messages(queue_url, max?)` | AWS | DLQ peek |
| `diff_config_versions(resource_id, version_a, version_b)` | AWS | SSM/CFN/Helm config diff |
| `describe_state_machine_execution(execution_arn)` | AWS | Step Functions execution history |
| `read_slack(last_n)` | platform | Pull last `n` Slack messages — only useful on scenarios where `slack.msgs_per_tick > 0` |

##### 3.2 Fix (write — can worsen blast radius)

| Action | Domain | What it does |
| --- | --- | --- |
| `rollback_deployment` / `restart_pods` / `scale_deployment` / `apply_config_patch` / `delete_chaos_experiment` | core | Same as deep regime |
| `invoke_lambda(function_name, payload?)` | AWS | Synchronous Lambda call |
| `rotate_secret(secret_id)` | AWS | Force secret rotation |
| `purge_queue(queue_url)` | AWS | SQS purge |
| `enable_eventbridge_rule(rule_arn)` | AWS | Re‑enable a disabled rule |
| `aws_api_call(service, verb, **kwargs)` | AWS · generic | Catch‑all — hits any of the 8 500+ catalog actions |
| `pause_health_checks(target)` / `capture_memory_dump(target)` / `resume_health_checks(target)` | platform | Forensic write actions used by hard scenarios (heap dump under K8s liveness pause). |

##### 3.3 Terminal

| Action | Effect |
| --- | --- |
| `submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups)` | Episode ends |

#### 4 · Reward signal

**Same shaper** as the deep regime (see [`#inlined-deep-spec` §4](#inlined-deep-spec-reward-signal))
— that's deliberate: Round 3's whole point was to validate that the rubric
that made Round 2's policy loss collapse also produces a useful gradient on
the broader 381‑task curriculum.

The shaper additionally evaluates **per‑category reward deltas** (first visit
vs last visit per scenario) so the headline result for Round 3 is reported
*per category*, not as a single mean. The four novelty categories all show
positive Δ reward:

| Category | Tasks | First visit | Last visit | Δ reward |
| --- | ---: | ---: | ---: | ---: |
| **Slack Red Herring** | 1 | −6.18 | −5.13 | **+1.05** |
| **Runbook Trap** | 1 | −7.83 | −6.93 | **+0.90** |
| **Cascading Failure** | 1 | −7.38 | −7.08 | **+0.30** |
| **Trolley Problem** | 1 | −6.33 | −6.03 | **+0.30** |
| DynamoDB Throttling | 20 | −4.49 | −4.49 | ±0.00 |
| Generated · App Memory Leak | 34 | −5.64 | −6.61 | −0.97 |
| Lambda Throttling | 20 | −3.86 | −5.00 | −1.14 |

Aggregate mean reward stays negative because every task is graded against the
aggressive rubric (red‑herring −0.15, blind‑action −0.20, repeat penalty
capped at −0.45). The honest evidence of learning is in three places:

1. **KL decay** to reference policy: 50 – 66 % across all 3 shards.
2. **PPO loss decay**: 49 – 58 % across all 3 shards.
3. **All 3 shards converge on the same peak reward of −0.315** — independent
   shards arriving at the same ceiling rules out memorisation.

#### 5 · Curriculum tiers (auto‑escalating during training)

Same controller as the deep regime. The curriculum table below is the live
layout enforced by [`rl-agent/environment/curriculum.py`](rl-agent/environment/curriculum.py)
(matches the `/dashboard` Curriculum table):

| Tier | Task pool | Multi‑fault | Adversarial designer |
| --- | --- | --- | --- |
| `warmup` | task1, task4, task9 | No | No |
| `beginner` | task1, task2, task4, task5, task9 | No | No |
| `intermediate` | task1–task10 | No | No |
| `advanced` | task2, task3, task5, task6, task7, task8, task10, task11 (+ procedural sim variants) | 2 concurrent faults | No |
| `expert` | task3, task6, task7, task8, task10, task11 (+ procedural sim variants) | 2–3 faults | LLM‑designed novel scenarios |

**Promotion rule:** ≥ 6 episodes in the current tier, then if the rolling
success rate (score ≥ target) over the last 8 episodes is ≥ 0.65, the agent is
auto‑promoted. Sampling is weakness‑biased — tasks with lower mastery are
oversampled within the tier.

#### 6 · PPO hyper‑parameters (the same ones validated by Rounds 1 + 2)

| Hyperparam | Value |
| --- | --- |
| Updates / shard | 60 |
| Rollouts / update | 3 |
| Max steps / episode | 12 |
| Discount γ | 0.95 |
| GAE λ | 0.92 |
| Clip ε | 0.2 |
| KL coefficient | 0.02 |
| Entropy coefficient | 0.01 |
| PPO epochs | 2 |
| Mini‑batch | 4 |
| Learning rate | 5e‑5 |
| Actor | `microsoft/Phi-3.5-mini-instruct` 4‑bit NF4, LoRA `r=16, α=32` on `q/k/v/o + gate/up/down` (~25 M trainable) |
| Critic (frozen) | `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` 4‑bit, prompt‑only 0–10 rubric scorer |

Per‑shard log JSON: [`shard 1/training_kaggle1.json`](kaggle%20ran%20notebooks/shard%201/training_kaggle1.json),
[`shard 2/training_kaggle2.json`](kaggle%20ran%20notebooks/shard%202/training_kaggle2.json),
[`shard 3/training_kaggle3.json`](kaggle%20ran%20notebooks/shard%203/training_kaggle3.json).
Each row carries `update, elapsed_s, wall_s, mean_reward, mean_value,
ppo.{loss, kl, policy_loss, value_err}, rewards_by_task`.

#### 7 · Where the chart lives

* KL decay across shards → [`assets/blog/llm_kl_decay.png`](assets/blog/llm_kl_decay.png)
* PPO loss decay across shards → [`assets/blog/llm_loss_decay.png`](assets/blog/llm_loss_decay.png)
* Best mean reward per shard → [`assets/blog/llm_best_reward.png`](assets/blog/llm_best_reward.png)
* Per‑category Δ reward → [`assets/blog/llm_category_delta.png`](assets/blog/llm_category_delta.png)
* Pass‑B training DAG (mermaid → PNG) → [`assets/blog/mermaid_training_dag.png`](assets/blog/mermaid_training_dag.png)

<a id="inlined-tasks-index"></a>

#### 2.0c · Full task index — every one of the 381 procedural scenarios

> Companion to [`#inlined-shallow-spec`](#inlined-shallow-spec). Lists every one of the 381 procedural sim scenarios used by the Phi-3.5-mini PPO+LoRA Kaggle run, grouped by tier and sorted by id. Each row carries the title, target score, max steps, and the **canonical correct action chain** the agent has to discover. The action ids on each row are the same simulator action ids documented in [`#inlined-shallow-spec` section 3](#inlined-shallow-spec#3--action-space-full-simulator-surface).

#### Category index (49 categories across 3 tiers)

| Tier | Category prefix | Scenarios | What it simulates |
|---|---|---:|---|
| easy | `sim_easy_ddb_throttle_*` | 20 | DynamoDB throttling (per-service capacity hit) |
| easy | `sim_easy_kms_disabled_*` | 20 | KMS key disabled / decrypt failure |
| easy | `sim_easy_lambda_throttle_*` | 20 | Lambda concurrency throttling |
| easy | `sim_easy_secret_rotation_*` | 20 | Secrets Manager rotation regression |
| easy | `sim_easy_sqs_dlq_*` | 20 | SQS DLQ growth |
| easy | `sim_easy_ssm_drift_*` | 20 | SSM Parameter Store drift |
| easy | `sim_gen_app_leak_api_gateway_*` | 4 | App memory leak - api-gateway |
| easy | `sim_gen_app_leak_auth_*` | 4 | App memory leak - auth-service |
| easy | `sim_gen_app_leak_catalog_*` | 4 | App memory leak - catalog-service |
| easy | `sim_gen_app_leak_checkout_*` | 4 | App memory leak - checkout-frontend |
| easy | `sim_gen_app_leak_frontend_*` | 4 | App memory leak - frontend |
| easy | `sim_gen_app_leak_inventory_*` | 4 | App memory leak - inventory-service |
| easy | `sim_gen_app_leak_payments_*` | 4 | App memory leak - payments-api |
| easy | `sim_gen_cache_warm_search_index_*` | 4 | Cold cache - search index warmup |
| easy | `sim_gen_cache_warm_session_cache_*` | 4 | Cold cache - session cache warmup |
| medium | `sim_med_eb_lambda_*` | 15 | EventBridge -> Lambda silent drop |
| medium | `sim_med_kms_lambda_*` | 15 | KMS rotation breaks Lambda decrypt |
| medium | `sim_med_lambda_secret_*` | 15 | Lambda -> secret rotation cascade |
| medium | `sim_med_sfn_lambda_*` | 15 | Step Functions -> Lambda failure |
| medium | `sim_gen_cache_warm_search_index_*` | 8 | Cold cache - search index warmup |
| medium | `sim_gen_cache_warm_session_cache_*` | 8 | Cold cache - session cache warmup |
| medium | `sim_gen_redherring_auth_*` | 4 | Red-herring - auth distractor |
| medium | `sim_gen_redherring_catalog_*` | 4 | Red-herring - catalog distractor |
| medium | `sim_gen_redherring_checkout_*` | 4 | Red-herring - checkout distractor |
| medium | `sim_gen_redherring_inventory_*` | 4 | Red-herring - inventory distractor |
| medium | `sim_gen_redherring_payments_*` | 4 | Red-herring - payments distractor |
| medium | `sim_gen_peak_api_gateway_*` | 3 | Peak-load surge - api-gateway |
| medium | `sim_gen_peak_auth_*` | 3 | Peak-load surge - auth-service |
| medium | `sim_gen_peak_catalog_*` | 3 | Peak-load surge - catalog-service |
| medium | `sim_gen_peak_cdn_*` | 3 | Peak-load surge - cdn |
| medium | `sim_gen_peak_checkout_*` | 3 | Peak-load surge - checkout-frontend |
| medium | `sim_gen_peak_frontend_*` | 3 | Peak-load surge - frontend |
| medium | `sim_gen_app_leak_api_gateway_*` | 2 | App memory leak - api-gateway |
| medium | `sim_gen_app_leak_auth_*` | 2 | App memory leak - auth-service |
| medium | `sim_gen_app_leak_catalog_*` | 2 | App memory leak - catalog-service |
| medium | `sim_gen_app_leak_checkout_*` | 2 | App memory leak - checkout-frontend |
| medium | `sim_gen_app_leak_frontend_*` | 2 | App memory leak - frontend |
| medium | `sim_gen_app_leak_inventory_*` | 2 | App memory leak - inventory-service |
| medium | `sim_gen_app_leak_payments_*` | 2 | App memory leak - payments-api |
| hard | `sim_gen_db_duel_orders_db_*` | 12 | DB duel - orders DB connection storm |
| hard | `sim_gen_db_duel_users_db_*` | 12 | DB duel - users DB connection storm |
| hard | `sim_hard_apigw_chain_*` | 10 | API Gateway 5xx multi-hop chain |
| hard | `sim_hard_ddb_chain_*` | 10 | DynamoDB throttle multi-hop chain |
| hard | `sim_hard_iam_chain_*` | 10 | IAM drift multi-hop chain |
| hard | `sim_gen_cascade_catalog_db_*` | 6 | Cascading failure via catalog DB |
| hard | `sim_gen_cascade_inventory_db_*` | 6 | Cascading failure via inventory DB |
| hard | `sim_gen_cascade_orders_db_*` | 6 | Cascading failure via orders DB |
| hard | `sim_gen_cascade_payments_db_*` | 6 | Cascading failure via payments DB |
| hard | `sim_gen_cascade_users_db_*` | 6 | Cascading failure via users DB |
| hard | `sim_gen_restore_catalog_db_*` | 2 | PITR restore - catalog DB |
| hard | `sim_gen_restore_inventory_db_*` | 2 | PITR restore - inventory DB |
| hard | `sim_gen_restore_orders_db_*` | 2 | PITR restore - orders DB |
| hard | `sim_gen_restore_payments_db_*` | 2 | PITR restore - payments DB |
| hard | `sim_advanced_cascade_users_db_*` | 1 | Advanced - users DB cascade (saboteur reinjects) |
| hard | `sim_advanced_runbook_trap_postgres_*` | 1 | Advanced - Runbook Trap (postgres) |
| hard | `sim_advanced_saboteur_duel_*` | 1 | Advanced - Saboteur duel (failover loop) |
| hard | `sim_advanced_slack_redherring_*` | 1 | Advanced - Slack Red Herring (CEO panic vs reality) |
| hard | `sim_advanced_trolley_orders_db_*` | 1 | Advanced - Trolley Problem (orders DB partial sacrifice) |

**Total: 381 scenarios** (156 easy + 128 medium + 97 hard).

#### Easy tier - 156 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_easy_ddb_throttle_101` | checkout DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 2 | `sim_easy_ddb_throttle_102` | orders DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 3 | `sim_easy_ddb_throttle_103` | inventory DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 4 | `sim_easy_ddb_throttle_104` | payments DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 5 | `sim_easy_ddb_throttle_105` | search DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 6 | `sim_easy_ddb_throttle_106` | recommendations DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 7 | `sim_easy_ddb_throttle_107` | auth DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 8 | `sim_easy_ddb_throttle_108` | billing DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 9 | `sim_easy_ddb_throttle_109` | shipping DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 10 | `sim_easy_ddb_throttle_110` | notifications DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 11 | `sim_easy_ddb_throttle_111` | reviews DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 12 | `sim_easy_ddb_throttle_112` | catalog DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 13 | `sim_easy_ddb_throttle_113` | fulfillment DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 14 | `sim_easy_ddb_throttle_114` | telemetry DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 15 | `sim_easy_ddb_throttle_115` | analytics DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 16 | `sim_easy_ddb_throttle_116` | userprofile DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 17 | `sim_easy_ddb_throttle_117` | cart DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 18 | `sim_easy_ddb_throttle_118` | pricing DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 19 | `sim_easy_ddb_throttle_119` | promotions DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 20 | `sim_easy_ddb_throttle_120` | media DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 21 | `sim_easy_kms_disabled_061` | checkout KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 22 | `sim_easy_kms_disabled_062` | orders KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 23 | `sim_easy_kms_disabled_063` | inventory KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 24 | `sim_easy_kms_disabled_064` | payments KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 25 | `sim_easy_kms_disabled_065` | search KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 26 | `sim_easy_kms_disabled_066` | recommendations KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 27 | `sim_easy_kms_disabled_067` | auth KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 28 | `sim_easy_kms_disabled_068` | billing KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 29 | `sim_easy_kms_disabled_069` | shipping KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 30 | `sim_easy_kms_disabled_070` | notifications KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 31 | `sim_easy_kms_disabled_071` | reviews KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 32 | `sim_easy_kms_disabled_072` | catalog KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 33 | `sim_easy_kms_disabled_073` | fulfillment KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 34 | `sim_easy_kms_disabled_074` | telemetry KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 35 | `sim_easy_kms_disabled_075` | analytics KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 36 | `sim_easy_kms_disabled_076` | userprofile KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 37 | `sim_easy_kms_disabled_077` | cart KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 38 | `sim_easy_kms_disabled_078` | pricing KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 39 | `sim_easy_kms_disabled_079` | promotions KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 40 | `sim_easy_kms_disabled_080` | media KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 41 | `sim_easy_lambda_throttle_001` | checkout Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 42 | `sim_easy_lambda_throttle_002` | orders Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 43 | `sim_easy_lambda_throttle_003` | inventory Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 44 | `sim_easy_lambda_throttle_004` | payments Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 45 | `sim_easy_lambda_throttle_005` | search Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 46 | `sim_easy_lambda_throttle_006` | recommendations Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 47 | `sim_easy_lambda_throttle_007` | auth Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 48 | `sim_easy_lambda_throttle_008` | billing Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 49 | `sim_easy_lambda_throttle_009` | shipping Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 50 | `sim_easy_lambda_throttle_010` | notifications Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 51 | `sim_easy_lambda_throttle_011` | reviews Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 52 | `sim_easy_lambda_throttle_012` | catalog Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 53 | `sim_easy_lambda_throttle_013` | fulfillment Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 54 | `sim_easy_lambda_throttle_014` | telemetry Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 55 | `sim_easy_lambda_throttle_015` | analytics Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 56 | `sim_easy_lambda_throttle_016` | userprofile Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 57 | `sim_easy_lambda_throttle_017` | cart Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 58 | `sim_easy_lambda_throttle_018` | pricing Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 59 | `sim_easy_lambda_throttle_019` | promotions Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 60 | `sim_easy_lambda_throttle_020` | media Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 61 | `sim_easy_secret_rotation_041` | checkout secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 62 | `sim_easy_secret_rotation_042` | orders secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 63 | `sim_easy_secret_rotation_043` | inventory secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 64 | `sim_easy_secret_rotation_044` | payments secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 65 | `sim_easy_secret_rotation_045` | search secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 66 | `sim_easy_secret_rotation_046` | recommendations secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 67 | `sim_easy_secret_rotation_047` | auth secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 68 | `sim_easy_secret_rotation_048` | billing secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 69 | `sim_easy_secret_rotation_049` | shipping secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 70 | `sim_easy_secret_rotation_050` | notifications secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 71 | `sim_easy_secret_rotation_051` | reviews secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 72 | `sim_easy_secret_rotation_052` | catalog secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 73 | `sim_easy_secret_rotation_053` | fulfillment secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 74 | `sim_easy_secret_rotation_054` | telemetry secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 75 | `sim_easy_secret_rotation_055` | analytics secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 76 | `sim_easy_secret_rotation_056` | userprofile secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 77 | `sim_easy_secret_rotation_057` | cart secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 78 | `sim_easy_secret_rotation_058` | pricing secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 79 | `sim_easy_secret_rotation_059` | promotions secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 80 | `sim_easy_secret_rotation_060` | media secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 81 | `sim_easy_sqs_dlq_021` | checkout DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 82 | `sim_easy_sqs_dlq_022` | orders DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 83 | `sim_easy_sqs_dlq_023` | inventory DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 84 | `sim_easy_sqs_dlq_024` | payments DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 85 | `sim_easy_sqs_dlq_025` | search DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 86 | `sim_easy_sqs_dlq_026` | recommendations DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 87 | `sim_easy_sqs_dlq_027` | auth DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 88 | `sim_easy_sqs_dlq_028` | billing DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 89 | `sim_easy_sqs_dlq_029` | shipping DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 90 | `sim_easy_sqs_dlq_030` | notifications DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 91 | `sim_easy_sqs_dlq_031` | reviews DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 92 | `sim_easy_sqs_dlq_032` | catalog DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 93 | `sim_easy_sqs_dlq_033` | fulfillment DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 94 | `sim_easy_sqs_dlq_034` | telemetry DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 95 | `sim_easy_sqs_dlq_035` | analytics DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 96 | `sim_easy_sqs_dlq_036` | userprofile DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 97 | `sim_easy_sqs_dlq_037` | cart DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 98 | `sim_easy_sqs_dlq_038` | pricing DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 99 | `sim_easy_sqs_dlq_039` | promotions DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 100 | `sim_easy_sqs_dlq_040` | media DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 101 | `sim_easy_ssm_drift_081` | checkout pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 102 | `sim_easy_ssm_drift_082` | orders pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 103 | `sim_easy_ssm_drift_083` | inventory pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 104 | `sim_easy_ssm_drift_084` | payments pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 105 | `sim_easy_ssm_drift_085` | search pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 106 | `sim_easy_ssm_drift_086` | recommendations pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 107 | `sim_easy_ssm_drift_087` | auth pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 108 | `sim_easy_ssm_drift_088` | billing pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 109 | `sim_easy_ssm_drift_089` | shipping pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 110 | `sim_easy_ssm_drift_090` | notifications pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 111 | `sim_easy_ssm_drift_091` | reviews pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 112 | `sim_easy_ssm_drift_092` | catalog pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 113 | `sim_easy_ssm_drift_093` | fulfillment pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 114 | `sim_easy_ssm_drift_094` | telemetry pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 115 | `sim_easy_ssm_drift_095` | analytics pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 116 | `sim_easy_ssm_drift_096` | userprofile pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 117 | `sim_easy_ssm_drift_097` | cart pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 118 | `sim_easy_ssm_drift_098` | pricing pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 119 | `sim_easy_ssm_drift_099` | promotions pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 120 | `sim_easy_ssm_drift_100` | media pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 121 | `sim_gen_app_leak_api_gateway_037` | Memory leak in api_gateway (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 122 | `sim_gen_app_leak_api_gateway_038` | Memory leak in api_gateway (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 123 | `sim_gen_app_leak_api_gateway_039` | Memory leak in api_gateway (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 124 | `sim_gen_app_leak_api_gateway_040` | Memory leak in api_gateway (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 125 | `sim_gen_app_leak_auth_001` | Memory leak in auth (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 126 | `sim_gen_app_leak_auth_002` | Memory leak in auth (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 127 | `sim_gen_app_leak_auth_003` | Memory leak in auth (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 128 | `sim_gen_app_leak_auth_004` | Memory leak in auth (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 129 | `sim_gen_app_leak_catalog_013` | Memory leak in catalog (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 130 | `sim_gen_app_leak_catalog_014` | Memory leak in catalog (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 131 | `sim_gen_app_leak_catalog_015` | Memory leak in catalog (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 132 | `sim_gen_app_leak_catalog_016` | Memory leak in catalog (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 133 | `sim_gen_app_leak_checkout_007` | Memory leak in checkout (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 134 | `sim_gen_app_leak_checkout_008` | Memory leak in checkout (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 135 | `sim_gen_app_leak_checkout_009` | Memory leak in checkout (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 136 | `sim_gen_app_leak_checkout_010` | Memory leak in checkout (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 137 | `sim_gen_app_leak_frontend_031` | Memory leak in frontend (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 138 | `sim_gen_app_leak_frontend_032` | Memory leak in frontend (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 139 | `sim_gen_app_leak_frontend_033` | Memory leak in frontend (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 140 | `sim_gen_app_leak_frontend_034` | Memory leak in frontend (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 141 | `sim_gen_app_leak_inventory_025` | Memory leak in inventory (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 142 | `sim_gen_app_leak_inventory_026` | Memory leak in inventory (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 143 | `sim_gen_app_leak_inventory_027` | Memory leak in inventory (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 144 | `sim_gen_app_leak_inventory_028` | Memory leak in inventory (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 145 | `sim_gen_app_leak_payments_019` | Memory leak in payments (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 146 | `sim_gen_app_leak_payments_020` | Memory leak in payments (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 147 | `sim_gen_app_leak_payments_021` | Memory leak in payments (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 148 | `sim_gen_app_leak_payments_022` | Memory leak in payments (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 149 | `sim_gen_cache_warm_search_index_013` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 150 | `sim_gen_cache_warm_search_index_016` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 151 | `sim_gen_cache_warm_search_index_019` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 152 | `sim_gen_cache_warm_search_index_022` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 153 | `sim_gen_cache_warm_session_cache_001` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 154 | `sim_gen_cache_warm_session_cache_004` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 155 | `sim_gen_cache_warm_session_cache_007` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 156 | `sim_gen_cache_warm_session_cache_010` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |

#### Medium tier - 128 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_gen_app_leak_api_gateway_041` | Memory leak in api_gateway (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 2 | `sim_gen_app_leak_api_gateway_042` | Memory leak in api_gateway (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 3 | `sim_gen_app_leak_auth_005` | Memory leak in auth (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 4 | `sim_gen_app_leak_auth_006` | Memory leak in auth (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 5 | `sim_gen_app_leak_catalog_017` | Memory leak in catalog (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 6 | `sim_gen_app_leak_catalog_018` | Memory leak in catalog (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 7 | `sim_gen_app_leak_checkout_011` | Memory leak in checkout (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 8 | `sim_gen_app_leak_checkout_012` | Memory leak in checkout (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 9 | `sim_gen_app_leak_frontend_035` | Memory leak in frontend (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 10 | `sim_gen_app_leak_frontend_036` | Memory leak in frontend (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 11 | `sim_gen_app_leak_inventory_029` | Memory leak in inventory (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 12 | `sim_gen_app_leak_inventory_030` | Memory leak in inventory (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 13 | `sim_gen_app_leak_payments_023` | Memory leak in payments (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 14 | `sim_gen_app_leak_payments_024` | Memory leak in payments (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 15 | `sim_gen_cache_warm_search_index_014` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 16 | `sim_gen_cache_warm_search_index_015` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 17 | `sim_gen_cache_warm_search_index_017` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 18 | `sim_gen_cache_warm_search_index_018` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 19 | `sim_gen_cache_warm_search_index_020` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 20 | `sim_gen_cache_warm_search_index_021` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 21 | `sim_gen_cache_warm_search_index_023` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 22 | `sim_gen_cache_warm_search_index_024` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 23 | `sim_gen_cache_warm_session_cache_002` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 24 | `sim_gen_cache_warm_session_cache_003` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 25 | `sim_gen_cache_warm_session_cache_005` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 26 | `sim_gen_cache_warm_session_cache_006` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 27 | `sim_gen_cache_warm_session_cache_008` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 28 | `sim_gen_cache_warm_session_cache_009` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 29 | `sim_gen_cache_warm_session_cache_011` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 30 | `sim_gen_cache_warm_session_cache_012` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 31 | `sim_gen_peak_api_gateway_004` | Sine-wave peak hammers api_gateway (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 32 | `sim_gen_peak_api_gateway_005` | Sine-wave peak hammers api_gateway (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 33 | `sim_gen_peak_api_gateway_006` | Sine-wave peak hammers api_gateway (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 34 | `sim_gen_peak_auth_010` | Sine-wave peak hammers auth (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 35 | `sim_gen_peak_auth_011` | Sine-wave peak hammers auth (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 36 | `sim_gen_peak_auth_012` | Sine-wave peak hammers auth (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 37 | `sim_gen_peak_catalog_016` | Sine-wave peak hammers catalog (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 38 | `sim_gen_peak_catalog_017` | Sine-wave peak hammers catalog (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 39 | `sim_gen_peak_catalog_018` | Sine-wave peak hammers catalog (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 40 | `sim_gen_peak_cdn_007` | Sine-wave peak hammers cdn (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 41 | `sim_gen_peak_cdn_008` | Sine-wave peak hammers cdn (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 42 | `sim_gen_peak_cdn_009` | Sine-wave peak hammers cdn (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 43 | `sim_gen_peak_checkout_013` | Sine-wave peak hammers checkout (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 44 | `sim_gen_peak_checkout_014` | Sine-wave peak hammers checkout (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 45 | `sim_gen_peak_checkout_015` | Sine-wave peak hammers checkout (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 46 | `sim_gen_peak_frontend_001` | Sine-wave peak hammers frontend (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 47 | `sim_gen_peak_frontend_002` | Sine-wave peak hammers frontend (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 48 | `sim_gen_peak_frontend_003` | Sine-wave peak hammers frontend (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 49 | `sim_gen_redherring_auth_001` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 50 | `sim_gen_redherring_auth_002` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 51 | `sim_gen_redherring_auth_003` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 52 | `sim_gen_redherring_auth_004` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 53 | `sim_gen_redherring_catalog_009` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 54 | `sim_gen_redherring_catalog_010` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 55 | `sim_gen_redherring_catalog_011` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 56 | `sim_gen_redherring_catalog_012` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 57 | `sim_gen_redherring_checkout_005` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 58 | `sim_gen_redherring_checkout_006` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 59 | `sim_gen_redherring_checkout_007` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 60 | `sim_gen_redherring_checkout_008` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 61 | `sim_gen_redherring_inventory_017` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 62 | `sim_gen_redherring_inventory_018` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 63 | `sim_gen_redherring_inventory_019` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 64 | `sim_gen_redherring_inventory_020` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 65 | `sim_gen_redherring_payments_013` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 66 | `sim_gen_redherring_payments_014` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 67 | `sim_gen_redherring_payments_015` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 68 | `sim_gen_redherring_payments_016` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 69 | `sim_med_eb_lambda_016` | checkout pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 70 | `sim_med_eb_lambda_017` | orders pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 71 | `sim_med_eb_lambda_018` | inventory pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 72 | `sim_med_eb_lambda_019` | payments pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 73 | `sim_med_eb_lambda_020` | search pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 74 | `sim_med_eb_lambda_021` | recommendations pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 75 | `sim_med_eb_lambda_022` | auth pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 76 | `sim_med_eb_lambda_023` | billing pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 77 | `sim_med_eb_lambda_024` | shipping pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 78 | `sim_med_eb_lambda_025` | notifications pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 79 | `sim_med_eb_lambda_026` | reviews pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 80 | `sim_med_eb_lambda_027` | catalog pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 81 | `sim_med_eb_lambda_028` | fulfillment pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 82 | `sim_med_eb_lambda_029` | telemetry pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 83 | `sim_med_eb_lambda_030` | analytics pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 84 | `sim_med_kms_lambda_031` | checkout Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 85 | `sim_med_kms_lambda_032` | orders Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 86 | `sim_med_kms_lambda_033` | inventory Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 87 | `sim_med_kms_lambda_034` | payments Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 88 | `sim_med_kms_lambda_035` | search Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 89 | `sim_med_kms_lambda_036` | recommendations Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 90 | `sim_med_kms_lambda_037` | auth Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 91 | `sim_med_kms_lambda_038` | billing Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 92 | `sim_med_kms_lambda_039` | shipping Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 93 | `sim_med_kms_lambda_040` | notifications Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 94 | `sim_med_kms_lambda_041` | reviews Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 95 | `sim_med_kms_lambda_042` | catalog Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 96 | `sim_med_kms_lambda_043` | fulfillment Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 97 | `sim_med_kms_lambda_044` | telemetry Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 98 | `sim_med_kms_lambda_045` | analytics Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 99 | `sim_med_lambda_secret_001` | checkout Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 100 | `sim_med_lambda_secret_002` | orders Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 101 | `sim_med_lambda_secret_003` | inventory Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 102 | `sim_med_lambda_secret_004` | payments Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 103 | `sim_med_lambda_secret_005` | search Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 104 | `sim_med_lambda_secret_006` | recommendations Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 105 | `sim_med_lambda_secret_007` | auth Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 106 | `sim_med_lambda_secret_008` | billing Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 107 | `sim_med_lambda_secret_009` | shipping Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 108 | `sim_med_lambda_secret_010` | notifications Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 109 | `sim_med_lambda_secret_011` | reviews Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 110 | `sim_med_lambda_secret_012` | catalog Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 111 | `sim_med_lambda_secret_013` | fulfillment Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 112 | `sim_med_lambda_secret_014` | telemetry Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 113 | `sim_med_lambda_secret_015` | analytics Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 114 | `sim_med_sfn_lambda_046` | checkout state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 115 | `sim_med_sfn_lambda_047` | orders state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 116 | `sim_med_sfn_lambda_048` | inventory state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 117 | `sim_med_sfn_lambda_049` | payments state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 118 | `sim_med_sfn_lambda_050` | search state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 119 | `sim_med_sfn_lambda_051` | recommendations state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 120 | `sim_med_sfn_lambda_052` | auth state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 121 | `sim_med_sfn_lambda_053` | billing state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 122 | `sim_med_sfn_lambda_054` | shipping state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 123 | `sim_med_sfn_lambda_055` | notifications state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 124 | `sim_med_sfn_lambda_056` | reviews state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 125 | `sim_med_sfn_lambda_057` | catalog state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 126 | `sim_med_sfn_lambda_058` | fulfillment state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 127 | `sim_med_sfn_lambda_059` | telemetry state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 128 | `sim_med_sfn_lambda_060` | analytics state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |

#### Hard tier - 97 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_advanced_cascade_users_db_001` | Cascade: users_db memory-leak hides behind frontend 504s | 0.55 | 20 | platform.get_logs -> platform.get_trace -> platform.get_metrics -> platform.search_runbook -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.failover_replica |
| 2 | `sim_advanced_runbook_trap_postgres_001` | Trap: TXID wraparound — restart corrupts the DB | 0.55 | 20 | platform.get_logs -> platform.search_runbook -> platform.read_runbook -> platform.vacuum_freeze_db |
| 3 | `sim_advanced_saboteur_duel_001` | 1v1 Duel — Active Saboteur attacks auth_db, then choke-holds the replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 4 | `sim_advanced_slack_redherring_001` | Slack Red-Herring — A frontend dev claims their hotfix broke checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 5 | `sim_advanced_trolley_orders_db_001` | Trolley: orders_db index corrupted — rebuild vs restore | 0.55 | 20 | platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 6 | `sim_gen_cascade_catalog_db_013` | Dependency cascade — catalog_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 7 | `sim_gen_cascade_catalog_db_014` | Dependency cascade — catalog_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 8 | `sim_gen_cascade_catalog_db_015` | Dependency cascade — catalog_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 9 | `sim_gen_cascade_catalog_db_016` | Dependency cascade — catalog_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 10 | `sim_gen_cascade_catalog_db_017` | Dependency cascade — catalog_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 11 | `sim_gen_cascade_catalog_db_018` | Dependency cascade — catalog_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 12 | `sim_gen_cascade_inventory_db_007` | Dependency cascade — inventory_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 13 | `sim_gen_cascade_inventory_db_008` | Dependency cascade — inventory_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 14 | `sim_gen_cascade_inventory_db_009` | Dependency cascade — inventory_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 15 | `sim_gen_cascade_inventory_db_010` | Dependency cascade — inventory_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 16 | `sim_gen_cascade_inventory_db_011` | Dependency cascade — inventory_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 17 | `sim_gen_cascade_inventory_db_012` | Dependency cascade — inventory_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 18 | `sim_gen_cascade_orders_db_025` | Dependency cascade — orders_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 19 | `sim_gen_cascade_orders_db_026` | Dependency cascade — orders_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 20 | `sim_gen_cascade_orders_db_027` | Dependency cascade — orders_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 21 | `sim_gen_cascade_orders_db_028` | Dependency cascade — orders_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 22 | `sim_gen_cascade_orders_db_029` | Dependency cascade — orders_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 23 | `sim_gen_cascade_orders_db_030` | Dependency cascade — orders_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 24 | `sim_gen_cascade_payments_db_001` | Dependency cascade — payments_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 25 | `sim_gen_cascade_payments_db_002` | Dependency cascade — payments_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 26 | `sim_gen_cascade_payments_db_003` | Dependency cascade — payments_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 27 | `sim_gen_cascade_payments_db_004` | Dependency cascade — payments_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 28 | `sim_gen_cascade_payments_db_005` | Dependency cascade — payments_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 29 | `sim_gen_cascade_payments_db_006` | Dependency cascade — payments_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 30 | `sim_gen_cascade_users_db_019` | Dependency cascade — users_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 31 | `sim_gen_cascade_users_db_020` | Dependency cascade — users_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 32 | `sim_gen_cascade_users_db_021` | Dependency cascade — users_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 33 | `sim_gen_cascade_users_db_022` | Dependency cascade — users_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 34 | `sim_gen_cascade_users_db_023` | Dependency cascade — users_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 35 | `sim_gen_cascade_users_db_024` | Dependency cascade — users_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 36 | `sim_gen_db_duel_orders_db_013` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 37 | `sim_gen_db_duel_orders_db_014` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 38 | `sim_gen_db_duel_orders_db_015` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 39 | `sim_gen_db_duel_orders_db_016` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 40 | `sim_gen_db_duel_orders_db_017` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 41 | `sim_gen_db_duel_orders_db_018` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 42 | `sim_gen_db_duel_orders_db_019` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 43 | `sim_gen_db_duel_orders_db_020` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 44 | `sim_gen_db_duel_orders_db_021` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 45 | `sim_gen_db_duel_orders_db_022` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 46 | `sim_gen_db_duel_orders_db_023` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 47 | `sim_gen_db_duel_orders_db_024` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 48 | `sim_gen_db_duel_users_db_001` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 49 | `sim_gen_db_duel_users_db_002` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 50 | `sim_gen_db_duel_users_db_003` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 51 | `sim_gen_db_duel_users_db_004` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 52 | `sim_gen_db_duel_users_db_005` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 53 | `sim_gen_db_duel_users_db_006` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 54 | `sim_gen_db_duel_users_db_007` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 55 | `sim_gen_db_duel_users_db_008` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 56 | `sim_gen_db_duel_users_db_009` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 57 | `sim_gen_db_duel_users_db_010` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 58 | `sim_gen_db_duel_users_db_011` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 59 | `sim_gen_db_duel_users_db_012` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 60 | `sim_gen_restore_catalog_db_005` | Corruption in catalog_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 61 | `sim_gen_restore_catalog_db_006` | Corruption in catalog_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 62 | `sim_gen_restore_inventory_db_003` | Corruption in inventory_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 63 | `sim_gen_restore_inventory_db_004` | Corruption in inventory_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 64 | `sim_gen_restore_orders_db_007` | Corruption in orders_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 65 | `sim_gen_restore_orders_db_008` | Corruption in orders_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 66 | `sim_gen_restore_payments_db_001` | Corruption in payments_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 67 | `sim_gen_restore_payments_db_002` | Corruption in payments_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 68 | `sim_hard_apigw_chain_001` | checkout 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 69 | `sim_hard_apigw_chain_002` | orders 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 70 | `sim_hard_apigw_chain_003` | inventory 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 71 | `sim_hard_apigw_chain_004` | payments 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 72 | `sim_hard_apigw_chain_005` | search 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 73 | `sim_hard_apigw_chain_006` | recommendations 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 74 | `sim_hard_apigw_chain_007` | auth 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 75 | `sim_hard_apigw_chain_008` | billing 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 76 | `sim_hard_apigw_chain_009` | shipping 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 77 | `sim_hard_apigw_chain_010` | notifications 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 78 | `sim_hard_ddb_chain_021` | checkout latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 79 | `sim_hard_ddb_chain_022` | orders latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 80 | `sim_hard_ddb_chain_023` | inventory latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 81 | `sim_hard_ddb_chain_024` | payments latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 82 | `sim_hard_ddb_chain_025` | search latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 83 | `sim_hard_ddb_chain_026` | recommendations latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 84 | `sim_hard_ddb_chain_027` | auth latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 85 | `sim_hard_ddb_chain_028` | billing latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 86 | `sim_hard_ddb_chain_029` | shipping latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 87 | `sim_hard_ddb_chain_030` | notifications latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 88 | `sim_hard_iam_chain_011` | checkout pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 89 | `sim_hard_iam_chain_012` | orders pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 90 | `sim_hard_iam_chain_013` | inventory pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 91 | `sim_hard_iam_chain_014` | payments pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 92 | `sim_hard_iam_chain_015` | search pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 93 | `sim_hard_iam_chain_016` | recommendations pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 94 | `sim_hard_iam_chain_017` | auth pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 95 | `sim_hard_iam_chain_018` | billing pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 96 | `sim_hard_iam_chain_019` | shipping pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 97 | `sim_hard_iam_chain_020` | notifications pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |

---

`IncidentCommanderEnv` is an OpenEnv `Environment` subclass that drops the
agent into an active production incident at **AcmeCorp** — a fictitious
e‑commerce company with five microservices, Kafka, Redis, Postgres, and full
observability. The HTTP API is bog‑standard Gym‑style:
[`/reset`](https://sagnik-mukherjee-incodent-commander.hf.space/docs#/default/reset_reset_post),
[`/step`](https://sagnik-mukherjee-incodent-commander.hf.space/docs#/default/step_step_post),
[`/state`](https://sagnik-mukherjee-incodent-commander.hf.space/docs#/default/state_state_get),
[`/health`](https://sagnik-mukherjee-incodent-commander.hf.space/health) — declared in [`openenv.yaml`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/openenv.yaml).
What's behind those endpoints, however, is anything but standard.

### What the agent sees

| Channel              | What's in it                                                               | Why it matters                                         |
| -------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------ |
| Prometheus metrics   | Real PromQL queryable counters / gauges per service                        | Quantitative signal                                    |
| Loki logs            | Ranked log lines with tunable `last_minutes` window + filters              | Structured but voluminous                              |
| Alertmanager         | Severity‑tagged active alerts                                              | What pages humans                                      |
| Service topology     | Dependency graph with upstream / downstream edges                          | Lets the agent reason about cascades                   |
| Distributed traces   | Per‑request spans across services                                          | Pinpoints latency hot spots                            |
| **Slack chatter**    | A deterministic stream of templated coworker messages — DBAs, CEO, intern, frontend devs, finance | **Novel.** Real on‑call signal lives in unstructured human text |
| **Saboteur state**   | An adversarial actor that re‑injects the fault when the agent fixes only one symptom | One fix is never enough on hard tasks |

### What the agent does

10 actions split into three classes:

* **Investigate** (no blast radius): `query_logs`, `query_metrics`,
  `get_service_dependencies`, `get_trace`, `read_slack`,
  `describe_topology`.
* **Fix** (dangerous): `rollback_deployment`, `restart_pods`,
  `scale_deployment`, `apply_config_patch`, `delete_chaos_experiment`,
  `vacuum_freeze_db`.
* **Terminal**: `submit_postmortem(root_cause, timeline, mitigations,
  affected_services, recommended_followups)` — episode ends.

### What it gets rewarded (and penalised) for

The reward signal lives in `[-2.0, +1.0]`. The headline components:

| Event | Reward | Why |
| --- | ---: | --- |
| First‑time investigation | +0.05 | Encourages thorough recon |
| Useful log query (keyword‑gated) | +0.10 | Rewards information gain, not button‑mashing |
| Correct mitigation before step 10 | +0.20 | Right action on right target |
| Root cause correct in postmortem | +0.30 | The actual point of the job |
| Postmortem quality (NLP‑scored) | up to +0.20 | Writing matters |
| **Phase‑order bonus** | **+0.10** | Triage → investigate → fix → verify |
| **LLM judge contribution** | **up to +0.15** | Junior / Senior / Principal SRE persona |
| **Acting blind** | **−0.20** | Write action with zero prior investigation |
| **Red‑herring penalty** | **−0.15** | Targeting a service the task marks as a distractor |
| **Repeat command** | **−0.15 / repeat (cap −0.45)** | Kills reward‑hacking via spam |
| **Phase regression** | **−0.10** | Going back to triage after fixing |
| Wrong service / blast radius up | −0.15 / −0.10 | Don't worsen the outage |
| Step cost / time penalty | −0.01 / −0.05 | Be efficient |

This is what makes the rubric *aggressive*. An agent that emits noise gets
hit by step cost + repeat penalty + red‑herring penalty before it ever earns
the +0.30 root‑cause bonus. The mean reward looks negative throughout
training — and that's a property of the rubric, not a property of the policy.
Improvement is measured by **trend**, not by absolute reward.

---

## 3 · Every novelty, in one place

Each of the points below also appears in the live
[showcase dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/showcase).

### 3.1 The agent reads coworker Slack — not just metrics

The most distinctive thing in the env. Every scenario emits a deterministic
stream of templated human messages: DBAs corroborate the actual fault, the
CEO is shouting, Finance reminds everyone every minute is $8k, and the intern
is asking about restarting the cluster. **Some of those lines are clues; most
are red herrings.** The action `platform.read_slack` is rewarded as useful
information gathering when followed by an action targeting a service
mentioned in a recent message — and penalised as a red herring when the
agent acts on a misleading line (e.g. rolling back the wrong service because
a frontend dev mentioned a hotfix).

This is implemented in [`rl-agent/simulator/slack.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/simulator/slack.py)
with two pools — `_GENERIC` (always in rotation) and `_PHASE_LINES` (fired
when the saboteur escalates). Severity escalates the longer the incident
drags, mirroring real pressure.

![Slack signal-vs-noise reward flow — Phi-3.5 actor, env, reward shaper, GAE/PPO loop](assets/blog/mermaid_slack_reward.png)

*The Slack signal-vs-noise reward flow — pulled verbatim from the live [showcase page](https://sagnik-mukherjee-incodent-commander.hf.space/showcase).*

### 3.2 Saboteur — one fix is never enough

On hard tasks, an adversarial bot watches the agent's actions and
**re‑injects the fault** when the agent only fixes a symptom. Aggressiveness
is per‑scenario (`saboteur.aggressiveness ∈ [0, 1]`); on the hardest cascade
scenarios the saboteur attacks every other tick. The agent has to find and
neutralise the *primary* target, not the symptom service.

### 3.3 Self‑improving curriculum

Inspired by kube‑sre‑gym's curriculum. A stateful controller tracks per‑task
mastery across episodes and auto‑promotes the agent through five tiers:

| Tier | Pool | Multi‑fault | Adversarial designer |
| --- | --- | --- | --- |
| `warmup` | task1, task4 | No | No |
| `beginner` | 4 easy/medium tasks | No | No |
| `intermediate` | all 7 hand‑curated tasks | No | No |
| `advanced` | all 7 | 2 concurrent faults | No |
| `expert` | all 7 | 2–3 faults | LLM‑designed novel scenarios |

Promotion fires after ≥ 6 episodes in a tier when the rolling success rate
over the last 8 episodes exceeds 0.65. Sampling is **weakness‑biased** —
tasks the agent is worst at get oversampled within the current tier. Exposed
at [`/curriculum`](https://sagnik-mukherjee-incodent-commander.hf.space/curriculum).

### 3.4 Adversarial scenario designer

When the curriculum reaches `expert` (or `adversarial:true` is passed to
`/reset`), the designer produces a **novel** scenario instead of loading a
hand‑authored JSON.

* **LLM path** (when `OPENAI_API_KEY` / `HF_TOKEN` is set): GPT‑4o‑mini /
  Claude receives the agent's mastery table and designs one hard scenario
  targeting the weakest tasks. Returns strict JSON matching our
  `TaskScenario` schema.
* **Procedural fallback**: composes a multi‑fault scenario from two base
  scenarios — merged log keywords, union of red herrings, tighter target
  score.

Try it: `curl -X POST $BASE/adversarial/design -d '{"primary_task_id":"task3","companion_task_ids":["task6"]}'`.

### 3.5 3‑persona LLM judge — Snorkel‑style experts in the loop

Every action is scored by an LLM (or heuristic fallback) playing one of three
SRE personas:

| Persona | Range | Style |
| --- | --- | --- |
| `junior` | [−0.5, +1.0] | Lenient — partial credit, rewards any reasonable attempt |
| `senior` | [−0.75, +1.0] | Standard SRE expectations |
| `principal` | [−1.0, +1.0] | Strict — penalises repeats, rewards minimal fixes |

Switchable mid‑training via `POST /judge/config`. The judge also labels each
action with an SRE phase (triage / investigate / fix / verify) which feeds
the phase‑order bonus.

### 3.6 Phase‑aware rewards

Actions are classified into the four canonical SRE phases. The agent earns
+0.10 for progressing forward (triage → investigate → fix → verify) and
loses −0.10 for regressing (going back to triage after fixing). This
encodes a real on‑call workflow into the reward signal.

### 3.7 Context‑gated penalties

The bit that prevents reward‑hacking. Three penalties whose firing depends
on prior episode state:

* **Acting blind** (−0.20): a write action with zero prior `query_logs` /
  `query_metrics` / `read_slack` is heavily penalised.
* **Repeat command** (−0.15 per repeat, cap −0.45): identical action
  signatures kill the spam strategy that destroys most LLM‑RL benchmarks.
  Inspired by kube‑sre‑gym.
* **Red herring** (−0.15): targeting a service the task explicitly marks as
  a distractor.

### 3.8 Holistic grading — separate from per‑step reward

Each task has a holistic grader that scores the *full episode* on:
investigation thoroughness (0.25) + correct mitigation (0.25) + root cause
identification (0.25) + efficiency (0.15) + no unnecessary damage (0.10).
Exposed at [`/grader`](https://sagnik-mukherjee-incodent-commander.hf.space/grader).

### 3.9 Real Kubernetes option

Write actions normally land on a mock cluster (`MOCK_MODE=true`) but the
**same code path** can drive a real Kubernetes cluster (`REAL_K8S=true`).
The infra is provisioned with Terraform on Hetzner Cloud:

```
hcloud_network → 10.0.0.0/16 VPC
hcloud_server × 3 → cx21 Ubuntu (1 master + 2 worker)
hcloud_load_balancer → lb11 with HTTP/HTTPS listeners
helm install acmecorp infra/helm/acmecorp
```

€20/month gets you a usable demo cluster. See
[`infra/terraform/main.tf`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/infra/terraform/main.tf).

![Hetzner Cloud k3s topology — Terraform on the left provisions the k3s cluster on the right; the agent talks to ingress over HTTP](assets/blog/mermaid_hetzner_infra.png)

*Same Hetzner topology that powers the live demo cluster — Terraform on the left provisions the k3s nodes, the agent talks to ingress over HTTP when `REAL_K8S=true`.*

### 3.10 381 procedurally‑generated scenarios

Beyond the 7 hand‑curated archetypes, we generated **381 simulator‑grade
scenarios** (156 easy + 128 medium + 97 hard) covering 12 incident
categories: DynamoDB throttling, Lambda throttling, App Memory Leak, IAM
permission chains, Cascading Failure, Slack Red Herring, Runbook Trap,
Trolley Problem, certificate expiry, ConfigMap race, Postgres VACUUM, Kafka
partition. Each adds `topology_overrides`, `saboteur`, `slack`,
`traffic_profile`, `k8s_controller`, and a deterministic `seed` so two runs
of the same scenario produce identical observations. They live in
[`rl-agent/scenarios/sim/{easy,medium,hard}/*.json`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/rl-agent/scenarios/sim).

### 3.11 Multi‑fault scenarios

On `advanced` and `expert` tiers, scenarios compose 2–3 simultaneous faults.
Fixing one doesn't end the episode; the others keep firing. The agent has to
learn to enumerate active faults before claiming victory.

### 3.12 Live diagnostic dashboard

A Plotly.js dashboard at [`/dashboard`](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard)
streams live telemetry while the agent steps: tier indicator, phase
indicator, blast‑radius bar, alert table, action tape. Useful as a
visualisation channel during demos and judging.

---

## 4 · How we actually trained — three rounds, two regimes

We ran two regimes of training, in three rounds:

* **Deep regime** (round 1 + round 2) — many PPO updates per task, on a small
  hand‑curated set of **7–11 tasks**. The point: prove the rubric is
  learnable, debug the reward signal, and validate that an LLM actor with a
  judge critic gives a usable advantage estimate before paying for a long
  GPU run.
* **Shallow regime** (round 3) — short PPO loop per task, but on the full
  **381 procedural scenarios** with saboteur + Slack noise + multi‑fault.
  The point: prove that the same loop generalises to a hard, broad,
  adversarial task pool — and ship a LoRA adapter for the demo.

The deep rounds came first; they're the reason we trusted the reward
signal enough to spend three free Kaggle accounts on the shallow round.

### Pass A · Round 1 — Legacy SB3 PPO/MLP (proves the env is solvable)

Before any LLM work, we needed to know the reward signal isn't broken.
We ran a stable‑baselines3 PPO agent against a **gym wrapper** of the env,
on the three hardest hand‑curated tasks (Redis pool exhaustion, payments
OOM cascade, decimal corruption). All on CPU, no GPU.

```python
# rl-agent/training/train_enhanced.py
model = PPO(
    "MlpPolicy", env,
    learning_rate=linear_schedule(3e-4),   # 3e-4 → 0
    n_steps=512, batch_size=128, n_epochs=15,
    gamma=0.99, gae_lambda=0.95,
    clip_range=linear_schedule(0.2),
    ent_coef=0.005,
    policy_kwargs={"net_arch": [128, 128]},
)
model.learn(total_timesteps=200_000)
```

200 000 timesteps, 4 parallel envs, 75 minutes wall‑clock. **Result: mean
reward 1.05, success rate 100% over 90 evaluation episodes**, recorded in
[`rl-agent/checkpoints/evaluation_report.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/evaluation_report.json).
Per‑update metrics in
[`rl-agent/checkpoints/training_metrics.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/training_metrics.json)
(40k → 200k timestep evaluation snapshots).

![Legacy SB3 PPO — per-task mean reward and 100% success rate across 200k timesteps](assets/blog/legacy_training.png)

*Left: per-task mean reward across the five evaluation snapshots — task3 (decimal corruption, hard) climbs from 1.00 → 1.05 by 80k and stays there. Right: success rate over 90 evaluation episodes — pinned at 100% from the first checkpoint onward.*

The orchestrating notebook is
[`notebooks/incident_commander_colab.ipynb`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/notebooks/incident_commander_colab.ipynb)
— it spins up the OpenEnv server, attaches the gym wrapper from
[`rl-agent/training/gym_wrapper.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/training/gym_wrapper.py),
runs `train_enhanced.py`, and writes everything under `rl-agent/checkpoints/`.

What this proves: **the rubric is achievable**. The env is solvable. There is
a real signal in there for any policy that bothers to investigate before
acting. The action distribution from the trained MLP is
`6× query_logs → submit_postmortem` — it memorised the *minimum sufficient
investigation* for the easy/medium tasks. That's a floor. Now the question
was: can an *LLM* actor learn the same signal — and does a judge‑style
critic produce useful advantages?

### Pass A · Round 2 — Hybrid LLM‑actor + judge‑critic on 11 hand‑curated tasks

Before committing GPU minutes to a 381‑task LoRA fine‑tune, we ran three
shorter PPO loops with a tiny LLM actor and three different critic
backends, all on **11 hand‑curated tasks** (`task1`…`task11` — the easy +
medium + hard archetypes plus their variants). All three runs share the
same trainer:
[`rl-agent/training/train_hybrid.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/training/train_hybrid.py).

| Round | Actor | Critic | Updates | Episodes | Mean R | Best per‑task | Mitigation rate | Logs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| **v2** | heuristic | none (PPO baseline) | 33 | 99 | 1.17 | 1.60 (`task1`,`task4`) | **100%** | [`ppo-v2-heuristic/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/rl-agent/checkpoints/ppo-v2-heuristic) |
| **v3** | Qwen2.5:0.5b (Ollama) | heuristic fallback | 12 | 36 | 1.32 | 1.72 (`task10`) | 69% | [`ppo-v3-hybrid-ollama-bedrock/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/rl-agent/checkpoints/ppo-v3-hybrid-ollama-bedrock) |
| **v4** | Qwen2.5:0.5b (Ollama) | **Groq Llama‑3.1‑8B‑instant** | 12 | 36 | **1.78** | **2.41** (`task9`) | 44% | [`ppo-v4-hybrid-ollama-groq/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/rl-agent/checkpoints/ppo-v4-hybrid-ollama-groq) |

Every row is a real run — `metrics.jsonl` + `summary.json` + reward‑breakdown
history all sit in the linked checkpoint folders. The trainer is invoked as:

```bash
# v2 — pure heuristic actor, PPO baseline
python -m rl_agent.training.train_hybrid --mode heuristic \
    --out-dir rl-agent/checkpoints/ppo-v2-heuristic

# v3 — Ollama Qwen2.5:0.5b actor + heuristic critic (Bedrock fallback)
python -m rl_agent.training.train_hybrid \
    --mode hybrid-ollama-bedrock --ollama-model qwen2.5:0.5b \
    --out-dir rl-agent/checkpoints/ppo-v3-hybrid-ollama-bedrock

# v4 — Ollama Qwen2.5:0.5b actor + Groq Llama‑3.1‑8B‑instant critic
python -m rl_agent.training.train_hybrid \
    --mode hybrid-ollama-groq --ollama-model qwen2.5:0.5b \
    --groq-model llama-3.1-8b-instant \
    --out-dir rl-agent/checkpoints/ppo-v4-hybrid-ollama-groq
```

![Hybrid PPO loops on 11 tasks — policy loss collapses, entropy compresses, Groq critic delivers the highest mean reward](assets/blog/legacy_deep_training.png)

*Three signs the deep regime worked:*

* **Policy loss collapses on every run.** v2 falls from 1.20 → 0.083
  (**−93%**) over 33 updates; v3 and v4 both fall from 1.10 → 0.50 (**−55%**)
  in just 12 updates. Same shape, same trajectory — the loop is healthy.
* **Entropy compresses smoothly** from ~2.0 → 0.39 (v2) and ~1.9 → 1.21
  (v3/v4) — the actor distribution is sharpening on a coherent strategy,
  not collapsing prematurely.
* **Per‑task max reward keeps rising.** v4's Qwen2.5 actor with the Groq
  Llama‑3.1‑8B critic posts mean reward **2.41 on `task9`**, **2.39 on
  `task1`**, **2.29 on `task10`** — well above the heuristic v2 ceiling of
  1.60. The judge‑critic is providing a useful signal.

What this established: (a) the reward signal is dense enough that a 0.5B
LLM actor moves it; (b) a frozen LLM judge as critic produces advantages
that actually push the policy upward (v4 > v3 > v2 on mean reward); (c) PPO
hyper‑parameters lifted from these runs (γ=0.95, λ=0.92, clip=0.2, KL=0.02,
entropy=0.01) are the same ones we used in Pass B. It's the bridge that
made the 381‑task run worth attempting.

### Pass B · Round 3 — LLM agent on 381 procedural scenarios

This is the headline run. The same env, but two changes:

1. The agent is now **Phi‑3.5‑mini‑instruct** in 4‑bit NF4 with a LoRA
   adapter (`r=16, α=32`, target = q/k/v/o + gate/up/down). 25 M trainable
   parameters.
2. The task pool is the **381 procedural scenarios** with saboteur + Slack
   noise + K8s adversary + multi‑fault, graded against the aggressive rubric
   (red‑herring penalty, acting‑blind penalty, repeat penalty all live).

A second model — **DeepSeek‑R1‑0528‑Qwen3‑8B** in 4‑bit — sits next to it as
a frozen prompt‑only critic. It scores each `(observation, action)` on a 0–10
rubric and provides a value baseline `V(s, a)` for advantage estimation. No
gradients flow through it.

#### PPO hyper‑parameters

| Hyperparam | Value |
| --- | --- |
| Updates / shard | 60 |
| Rollouts / update | 3 |
| Max steps / episode | 12 |
| Discount γ | 0.95 |
| GAE λ | 0.92 |
| Clip ε | 0.2 |
| KL coefficient | 0.02 |
| Entropy coefficient | 0.01 |
| PPO epochs | 2 |
| Mini‑batch | 4 |
| Learning rate | 5e‑5 |

#### Three‑shard sharded coverage

381 ÷ 3 = 127 tasks per shard, modulo‑3 over the sorted task ids. Disjoint
and exhaustive:

```python
sorted_ids = sorted(all_sim_task_ids)               # 381 ids
shard_i    = [t for k, t in enumerate(sorted_ids)
                if k % 3 == i]                       # 127 ids
```

Three free Kaggle accounts ran in parallel on T4s, ~5 hours each. After all
three finished:

```bash
python scripts/merge_lora_adapters.py \
    --adapters adapter_kaggle1 adapter_kaggle2 adapter_kaggle3 \
    --output  adapter_merged \
    --weights 1.0 1.0 1.0
```

The merged adapter loads on top of the same Phi‑3.5‑mini base for inference.

---

## 5 · Did it actually learn? Yes — and you have to look at the right metric.

### 5.1 Aggregate reward looks negative — by design

Mean reward on a 381‑task curriculum with red‑herring penalties looks
negative because every task is graded against an aggressive rubric (−0.15
for chasing red herrings, −0.10 for blind action, −0.20 for the wrong fix).
That's the point. The honest evidence of learning lives in three places.

### 5.2 KL and PPO loss don't lie

Across all three shards the KL divergence to the reference policy and the
PPO loss both decay by **more than 50%** — the signature of a policy that
has stabilised on a coherent strategy.

| Shard | KL · first 5 | KL · last 5 | Δ KL | Loss · first 5 | Loss · last 5 | Δ Loss | Best reward |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **kaggle‑1** | 1.44 | 0.65 | **−55%** | 0.31 | 0.13 | **−58%** | **−0.315 @ u7** |
| **kaggle‑2** | 2.57 | 0.87 | **−66%** | 1.52 | 0.78 | **−49%** | **−0.315 @ u6** |
| **kaggle‑3** | 1.23 | 0.60 | **−51%** | 0.31 | 0.14 | **−54%** | **−0.315 @ u49** |

![KL divergence to reference policy decays across all 3 shards](assets/blog/llm_kl_decay.png)

![PPO loss decays 49–58% across all 3 shards](assets/blog/llm_loss_decay.png)

![Best mean reward attained — all 3 shards converge on the same −0.315 peak](assets/blog/llm_best_reward.png)

*Faint lines are raw per-update values; thick lines are 5-update trailing means. The bottom chart plots running max — note all three shards independently saturate at exactly **−0.315**, which is the strongest signal in the whole run that the policy found a real ceiling on the hard rubric rather than memorising one shard's idiosyncrasies.*

That **all three shards converge on the exact same peak reward of −0.315** is
a strong signal: the LLM‑on‑LoRA actor has found a consistent best‑effort
policy on the hard rubric. Plain memorisation would produce three different
ceilings.

Per‑update training curves for all three shards are plotted live at
[/showcase#training](https://sagnik-mukherjee-incodent-commander.hf.space/showcase#training)
from the JSON logs at:

* [`kaggle ran notebooks/shard 1/training_kaggle1.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%201/training_kaggle1.json)
* [`kaggle ran notebooks/shard 2/training_kaggle2.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%202/training_kaggle2.json)
* [`kaggle ran notebooks/shard 3/training_kaggle3.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%203/training_kaggle3.json)

Each file contains, per PPO update: `update`, `elapsed_s`, `wall_s`,
`mean_reward`, `mean_value`, `ppo.{loss, kl, policy_loss, value_err}`, and
`rewards_by_task`. The union of `rewards_by_task` keys across the three
files is exactly the set of all 381 task ids — that's our coverage proof.

### 5.3 The novelty categories are the ones that improved

For every scenario we record reward on the agent's *first* visit and on its
*last* visit, then average per category. The categories that **only exist in
our environment** — Slack Red Herring, Runbook Trap, Cascading Failure,
Trolley Problem — show the largest positive deltas. That's the most direct
evidence that the added training signal is doing real work.

| Category | tasks | first visit | last visit | Δ reward | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| **Slack Red Herring** | 1 | −6.18 | −5.13 | **+1.05** | novelty win |
| **Runbook Trap** | 1 | −7.83 | −6.93 | **+0.90** | novelty win |
| **Cascading Failure** | 1 | −7.38 | −7.08 | **+0.30** | novelty win |
| **Trolley Problem** | 1 | −6.33 | −6.03 | **+0.30** | novelty win |
| DynamoDB Throttling | 20 | −4.49 | −4.49 | ±0.00 | already at ceiling |
| Generated · App Memory Leak | 34 | −5.64 | −6.61 | −0.97 | exploration overshoot |
| Lambda Throttling | 20 | −3.86 | −5.00 | −1.14 | exploration overshoot |

![Per-category Δ reward — the 4 novelty categories all improved](assets/blog/llm_category_delta.png)

*Only the categories where the policy improved or hit ceiling are plotted (the two regression categories are still in the table above for honesty). The four bars in green are the **novelty** categories — exactly the ones that don't exist in any other RL-for-LLM benchmark.*

The hardest scenarios have the most reward signal to extract — every Slack
message that's a clue, every runbook line that's a trap, every cascade hop
that needs `describe_topology` first. PPO finds those gradients faster than
on already‑saturated easy categories. Lambda Throttling and App Memory Leak
show *exploration overshoot* — late‑stage entropy nudged the policy off a
memorised solution. A 4th shard would have smoothed it out; we ran out of
free Kaggle GPU minutes.

### 5.4 TL;DR for the judges

> The legacy SB3 baseline proves the env is **solvable** (mean reward 1.05,
> 100% success over 90 episodes). The PPO Kaggle run proves the agent
> **learns on the hard version of the same env**: KL and loss both decay
> 50–66% across all three shards, all three converge on the same −0.315
> peak reward, and the four hardest novelty categories each show a positive
> Δ reward between first and last visit (+0.30 to +1.05). Aggregate reward
> staying negative is a property of the rubric, not a property of the policy.

---

## 6 · The training pipeline — GitHub → Kaggle → merged adapter

![Pass-B training DAG — scenario → env → 4-bit Phi-3.5 actor → DeepSeek-R1 critic → GAE → PPO → LoRA delta](assets/blog/mermaid_training_dag.png)

*The full Pass-B training DAG: scenario → env → 4-bit Phi-3.5 actor → DeepSeek-R1 frozen critic → GAE → PPO → LoRA delta + per-update JSON. This is the diagram that drives the three Kaggle shard runs in §4-Pass-B.*

One thing we got right early: **the real training code lives on GitHub, and
the Kaggle notebooks clone it at run‑time.** That means the notebooks are
thin (~9 cells) and any commit on `main` is picked up automatically without
re‑uploading any `.ipynb`.

Each shard's notebook has the same 9‑cell structure. The only differences
between them are two environment variables: `IC_TASK_SHARD ∈ {0,1,2}` and
`IC_RUN_NAME ∈ {kaggle1, kaggle2, kaggle3}`.

| Cell | Purpose |
| --- | --- |
| 1 | Title (markdown) + Kaggle attach instructions |
| 2 | `pip install` — best‑effort `unsloth`, then pin transformers ≥ 4.51, peft, accelerate, bitsandbytes |
| 3 | GPU sanity — `nvidia-smi -L` + `torch.cuda.is_available()` |
| 4 | Verify mounts (Phi‑3.5‑mini + DeepSeek‑R1 attached as Kaggle Models), redirect HF cache, optionally pull `HF_TOKEN` from Kaggle Secrets |
| 5 | **`git clone --depth 1 https://github.com/r1cksync/meta-rl-hack.git`** — fresh on every run, prints the commit hash |
| 6 | Set all `IC_*` env vars (shard index, run name, hyper‑params, model paths) |
| 7 | `subprocess.run(['python','scripts/run_training.py'])` — produces `colab/logs/training_kaggle{N}.json` + adapter checkpoints every 15 updates |
| 8 | Zip adapter to `/kaggle/working/adapter_kaggle{N}.zip`, copy JSON log to working dir |
| 9 | Merge instructions (markdown) |

The actual training loop is in
[`colab/train_lib.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/colab/train_lib.py)
(rollout collector, GAE, PPO update) and
[`scripts/run_training.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/scripts/run_training.py)
(the entry point). A typical Kaggle run logs lines like:

```
[update 7/60] mean_reward=-0.315 kl=0.62 loss=0.13 elapsed=243s
[ckpt] saved adapter_kaggle1 @ update 15
```

Why this design? Three reasons:

1. **No re‑upload churn.** Iterating on reward shaping or curriculum logic
   doesn't require uploading `.ipynb`s — just `git push origin main` and
   re‑run any Kaggle kernel.
2. **Reproducibility.** Cell 5 prints the commit hash; you can pin a run to
   an exact SHA after the fact.
3. **The `.ipynb` is portable.** The same notebook works on Colab, Paperspace,
   Lambda Labs — anywhere with a GPU and internet.

### Notebook gallery (with logs as proof of training)

| Notebook | Where | Log JSON | Adapter |
| --- | --- | --- | --- |
| [`kaggle/kaggle_train_shard1.ipynb`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle/kaggle_train_shard1.ipynb) | Kaggle T4 · ~5 h | [`shard 1/training_kaggle1.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%201/training_kaggle1.json) | [`shard 1/adapter_kaggle1/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle%20ran%20notebooks/shard%201/adapter_kaggle1) |
| [`kaggle/kaggle_train_shard2.ipynb`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle/kaggle_train_shard2.ipynb) | Kaggle T4 · ~5 h | [`shard 2/training_kaggle2.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%202/training_kaggle2.json) | [`shard 2/adapter_kaggle2/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle%20ran%20notebooks/shard%202/adapter_kaggle2) |
| [`kaggle/kaggle_train_shard3.ipynb`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle/kaggle_train_shard3.ipynb) | Kaggle T4 · ~5 h | [`shard 3/training_kaggle3.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/kaggle%20ran%20notebooks/shard%203/training_kaggle3.json) | [`shard 3/adapter_kaggle3/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle%20ran%20notebooks/shard%203/adapter_kaggle3) |
| [`notebooks/incident_commander_colab.ipynb`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/notebooks/incident_commander_colab.ipynb) | CPU · 75 min | [`rl-agent/checkpoints/training_metrics.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/training_metrics.json) + [`evaluation_report.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/evaluation_report.json) | [`rl-agent/checkpoints/final_model.zip`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/final_model.zip) |

The legacy notebook is the SB3 PPO + MLP run from §4‑Pass A. The three Kaggle
notebooks are the LLM agent run from §4‑Pass B.

---

## 7 · OpenEnv compliance — the boring but mandatory bits

* `Environment` subclass with proper `reset / step / state / close` —
  [`rl-agent/environment/env.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/environment/env.py).
* Client / server separation — clients (the LLM agent in
  [`inference.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/inference.py),
  the heuristic baseline) talk to the env over HTTP only. No imports of
  server internals.
* Standard Gym‑style API — `reset()` returns `Observation`, `step(action)`
  returns `StepResult(observation, reward, done, info)`, `state()` returns
  the full diagnostic state.
* Valid `openenv.yaml` manifest declaring `/reset, /step, /state, /health`
  — [`openenv.yaml`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/openenv.yaml).
* No reserved tool names (`reset`, `step`, `state`, `close`) used for any
  custom MCP tools.
* The HF Space (Docker SDK) at
  [`huggingface.co/spaces/sagnik-mukherjee/incodent-commander`](https://huggingface.co/spaces/sagnik-mukherjee/incodent-commander)
  exposes the env publicly — discoverable and runnable.

---

## 8 · Why does it matter?

**For LLM training researchers:** IncidentCommander is one of the few RL
benchmarks where the observation channel includes *unstructured noisy human
text mixed with adversarial chatter and red herrings*. It's harder than
function calling, more grounded than synthetic puzzles, and the reward
signal can't be reward‑hacked by spam (we tested — the repeat penalty caps
at −0.45 and acting‑blind kills the score).

**For SRE / DevOps tool builders:** The Hetzner k3s pipeline means write
actions can drive a real cluster. The same agent that solves a synthetic
task in CI can be pointed at a real on‑call rotation tomorrow.

**For hackathon judges:** the env is novel, the reward signal is
*deliberately* aggressive, the training was actually run end‑to‑end on free
Kaggle GPUs, the legacy baseline proves the env is achievable, and the
LLM run shows the policy converging on a stable strategy with the novelty
categories specifically improving.

---

## 9 · Where to go next

* **Watch the 4‑minute video walkthrough →
  [youtu.be/aBnQ33q9MMw](https://youtu.be/aBnQ33q9MMw)**
* **Browse all 381 tasks live →
  [/showcase#tasks](https://sagnik-mukherjee-incodent-commander.hf.space/showcase#tasks)**
* **Inspect an episode in real‑time →
  [/dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard)**
* **Run the heuristic baseline (no API key needed):**
  ```bash
  curl -X POST https://sagnik-mukherjee-incodent-commander.hf.space/baseline \
       -H 'Content-Type: application/json' -d '{"task_id":"task1"}'
  ```
* **Design a novel adversarial scenario:**
  ```bash
  curl -X POST https://sagnik-mukherjee-incodent-commander.hf.space/adversarial/design \
       -H 'Content-Type: application/json' \
       -d '{"primary_task_id":"task3","companion_task_ids":["task6"]}'
  ```
* **Read the source:** [github.com/r1cksync/meta-rl-hack](https://github.com/r1cksync/meta-rl-hack).
  Start at `incident-commander/README.md`.

---

## 10 · Reference appendix

> Everything below is the same factual reference material that lives in
> [`README.md`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/README.md),
> reproduced here so the blog is self‑contained for judges reading on the
> Hugging Face Space.

### 10.1 Submission materials

| | |
|---|---|
| 📝 **Blog / writeup** | [`BLOG.md`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/BLOG.md) — story‑driven walkthrough (problem · env · novelties · results · pipeline) |
| 🎥 **Video walkthrough** | [https://youtu.be/aBnQ33q9MMw](https://youtu.be/aBnQ33q9MMw) |
| 🧪 **Live env (HF Space)** | [sagnik-mukherjee/incodent-commander](https://huggingface.co/spaces/sagnik-mukherjee/incodent-commander) |
| 💻 **Source (GitHub)** | [r1cksync/meta-rl-hack](https://github.com/r1cksync/meta-rl-hack) |
| 📊 **Training notebooks** | [`kaggle/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle) (3 shards × Phi‑3.5 + DeepSeek‑R1) · [`notebooks/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/notebooks) (legacy SB3 PPO baseline) |
| 📦 **Trained adapters** | [`kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle%20ran%20notebooks) |
| 🎚️ **Per‑update training logs** | **Round 3 (shallow, 381 tasks):** [`shard {1,2,3}/training_kaggle{N}.json`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/kaggle%20ran%20notebooks) · **Round 2 (deep, 11 tasks):** [`rl-agent/checkpoints/ppo-v{2,3,4}-*/metrics.jsonl`](https://github.com/r1cksync/meta-rl-hack/tree/main/incident-commander/rl-agent/checkpoints) · **Round 1 (legacy SB3):** [`rl-agent/checkpoints/training_metrics.json`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/checkpoints/training_metrics.json) |
| 🌟 **Showcase page** | [/showcase](https://sagnik-mukherjee-incodent-commander.hf.space/showcase) |
| 📡 **Live dashboard** | [/dashboard](https://sagnik-mukherjee-incodent-commander.hf.space/dashboard) |
| 🩺 **API health** | [/health](https://sagnik-mukherjee-incodent-commander.hf.space/health) |
| 📖 **API docs (Swagger)** | [/docs](https://sagnik-mukherjee-incodent-commander.hf.space/docs) |

### 10.2 The 7 hand‑curated tasks (the original archetypes)

§3.10 covers the 381 procedural scenarios. Underneath them sit **7 hand‑curated archetypes** that every procedural variant is a perturbation of:

| ID | Difficulty | Root cause | What goes wrong |
| --- | --- | --- | --- |
| `task1` | Easy | Redis pool exhaustion | Chaos Mesh injects latency → pool saturates → inventory‑service errors |
| `task2` | Medium | Payments OOM cascade | Memory stress → OOM kills → Kafka lag cascades to other services |
| `task3` | Hard | Decimal corruption | Bad deploy truncates NUMERIC precision. Postgres VACUUM is a red herring |
| `task4` | Easy | Kafka network partition | Chaos Mesh partitions broker → consumer lag spikes across workers |
| `task5` | Medium | DNS resolution failure | DNS chaos → NXDOMAIN across services. "Connection refused" is secondary |
| `task6` | Hard | TLS certificate expiry | Expired mTLS cert → all DB connections fail. ECONNRESET is a symptom |
| `task7` | Hard | ConfigMap hot‑reload race | ConfigMap race → inconsistent pricing across pods. Redis/GC alerts are red herrings |

Easy tasks have one obvious signal. Medium tasks need cross‑service investigation. Hard tasks actively mislead with plausible red herrings. Heuristic agent baseline scores against these 7 are below.

### 10.3 Heuristic baseline scores

The `/baseline` endpoint runs a fixed‑strategy heuristic (investigate → mitigate → postmortem) per task. It demonstrates the rubric is achievable; an LLM agent has to figure it out from observations alone.

| Task | Heuristic score | Target score |
| --- | ---: | ---: |
| `task1` (Easy) | 0.90 | 0.80 |
| `task2` (Medium) | 0.85 | 0.45 |
| `task3` (Hard) | 0.85 | 0.20 |
| `task4` (Easy) | 0.90 | 0.80 |
| `task5` (Medium) | 0.85 | 0.45 |
| `task6` (Hard) | 0.80 | 0.20 |
| `task7` (Hard) | 0.80 | 0.20 |
| **Average** | **0.85** | — |

### 10.4 Curriculum tier table

Inspired by kube‑sre‑gym. Pass `use_curriculum: true` to `POST /reset`.

| Tier | Task pool | Multi‑fault | Adversarial designer |
| --- | --- | --- | --- |
| `warmup` | task1, task4 (easy single‑fault) | No | No |
| `beginner` | task1, task2, task4, task5 | No | No |
| `intermediate` | all 7 tasks | No | No |
| `advanced` | all 7 tasks | 2 concurrent faults | No |
| `expert` | all 7 tasks | 2–3 faults | LLM‑designed novel scenarios |

**Promotion rule:** after ≥6 episodes in the current tier, if the rolling success rate (score ≥ target) over the last 8 episodes is ≥ 0.65, the agent is auto‑promoted. Sampling is **weakness‑biased** — tasks with lower mastery are oversampled within the current tier.

### 10.5 LLM‑judge persona ranges

| Persona | Score range | Style |
| --- | --- | --- |
| `junior` | [−0.5, 1.0] | Lenient; partial credit; rewards any reasonable attempt |
| `senior` | [−0.75, 1.0] | Standard SRE expectations; rewards systematic diagnosis |
| `principal` | [−1.0, 1.0] | Strict; penalises repeat commands and wrong targets, rewards minimal fixes |

Switch persona mid‑training:

```bash
curl -X POST $BASE/judge/config -H 'Content-Type: application/json' \
  -d '{"persona":"principal","use_llm":true}'
```

The judge also labels each action with an SRE phase (`triage / investigate / fix / verify`) which feeds the phase‑order bonus. With no API key, it falls back to a deterministic heuristic so training and CI keep working.

### 10.6 Holistic grader breakdown

Separate from per‑step reward — runs on episode end:

| Component | Max | What it measures |
| --- | ---: | --- |
| Investigation thoroughness | 0.25 | Did the agent inspect logs, metrics, deps, traces? |
| Correct mitigation | 0.25 | Was the right fix applied? |
| Root cause identification | 0.25 | Did the postmortem identify the real root cause? |
| Efficiency | 0.15 | How many steps (fewer = better)? |
| No unnecessary damage | 0.10 | Did write actions avoid making things worse? |
| **Total** | **1.00** | Clamped to [0.001, 0.999] for grader compliance |

### 10.7 Setup / quickstart

```bash
# Local development
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pydantic httpx structlog numpy openai
cd rl-agent && uvicorn server:app --host 0.0.0.0 --port 7860

# Docker
docker build -t incident-commander .
docker run -p 7860:7860 incident-commander

# Run heuristic baseline (no API key needed)
curl -X POST http://localhost:7860/baseline \
     -H 'Content-Type: application/json' -d '{"task_id":"task1"}'

# Reset with curriculum + adversarial
curl -X POST http://localhost:7860/reset \
     -H 'Content-Type: application/json' \
     -d '{"use_curriculum":true,"persona":"senior"}'

# Inspect current curriculum state
curl http://localhost:7860/curriculum

# Design a novel adversarial scenario (procedural, no API key needed)
curl -X POST http://localhost:7860/adversarial/design \
     -H 'Content-Type: application/json' \
     -d '{"primary_task_id":"task3","companion_task_ids":["task6"]}'

# Run LLM inference
API_BASE_URL=https://api.openai.com/v1 MODEL_NAME=gpt-4o HF_TOKEN=sk-... \
    python inference.py
```

### 10.8 Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MOCK_MODE` | `true` | When `true`, all write actions return `[MOCK]` results. |
| `REAL_K8S` | `false` | When `true` (and the `kubernetes` Python client is installed), write actions (rollback/restart/scale/apply_config_patch) go to a real cluster via the active kubeconfig. |
| `USE_LLM_JUDGE` | `false` | Enable LLM‑based per‑step judging. Requires `OPENAI_API_KEY` or `HF_TOKEN`. |
| `JUDGE_PERSONA` | `senior` | `junior` / `senior` / `principal`. |
| `OPENAI_API_KEY` / `HF_TOKEN` | — | Auth for LLM judge + adversarial designer. |
| `API_BASE_URL` | `https://api.openai.com/v1` | LLM endpoint (OpenAI‑compatible). |
| `MODEL_NAME` | `gpt-4o-mini` | Default LLM for judge/designer. |

### 10.9 GRPO training pipeline (the original plan)

The repo also ships a full TRL + vLLM colocate GRPO pipeline at
[`rl-agent/training/train_grpo.py`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/rl-agent/training/train_grpo.py)
— it was the original Week‑2 plan before we pivoted to the custom 3‑round PPO
loop documented in §4. It still works:

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

#### Evaluation (base vs trained)

```bash
# Heuristic-only (zero GPU)
python -m rl_agent.eval --env-url http://localhost:7860 --episodes-per-task 3

# Compare base vs LoRA checkpoint (needs transformers+torch)
python -m rl_agent.eval \
    --base-model Qwen/Qwen2.5-1.5B-Instruct \
    --trained-model <your-name>/incident-commander-grpo \
    --episodes-per-task 5 --adversarial
```

#### Original training roadmap (for context)

1. **Week 1 (zero GPU)** — heuristic baseline already solves easy tasks; tune LLM‑judge prompts, adversarial designer prompts, and reward weights against the live Space.
2. **Week 2 (HF GPU credits)** — launch GRPO on Qwen2.5‑1.5B with LoRA r=16, 200 steps, 8 generations per prompt. Expected ~6 h on A100 40GB.
3. **Week 3** — compare against heuristic and against kube‑sre‑gym's reported numbers using `eval.py --adversarial`. Push best LoRA adapter to the Hub.

In practice, weeks 2–3 became the 3‑round PPO regime in §4 because the free Kaggle T4 path proved faster and cheaper than waiting on credits.

### 10.10 Production pipeline (Terraform → Hetzner → k3s)

Write actions normally land in a mock cluster (`MOCK_MODE=true`), but the same code path drives a real Kubernetes cluster (`REAL_K8S=true`). We provision that cluster with Terraform on Hetzner Cloud — €20 / month for a usable demo cluster.

```
infra/terraform/main.tf       Hetzner Cloud network + 3 servers + load balancer
infra/k8s/                    Deployments / Services / ConfigMaps for the 5 microservices
infra/helm/acmecorp/          Helm chart that rolls everything out
infra/aws/   infra/eks/       Optional AWS variant if you have free EKS credits
```

The Terraform module declares:

| Resource | Purpose |
| --- | --- |
| `hcloud_network` | Private 10.0.0.0/16 VPC |
| `hcloud_network_subnet` | 10.0.1.0/24 in `eu-central` |
| `hcloud_ssh_key` | Reads `~/.ssh/id_rsa.pub` |
| `hcloud_server` × 3 | `cx21` Ubuntu nodes (1 master + 2 worker) |
| `hcloud_load_balancer` | `lb11` in front of the cluster |
| `hcloud_load_balancer_target` × 3 | Health‑checked targets |
| `hcloud_load_balancer_service` × 2 | Public HTTP (80) + HTTPS (443) listeners |

Bring‑up:

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

### 10.11 Full API endpoint reference

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Health check |
| `/tasks` | GET | Task list with action schema |
| `/reset` | POST | Reset environment (`task_id`, `adversarial`, `use_curriculum`, `persona`, `use_llm_judge`) |
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
| `/showcase/data` | GET | Pre‑computed JSON bundle (381 scenarios + 3 shards × 60 updates) |
| `/docs` | GET | Swagger UI |

### 10.12 File / JSON index

| Path | What it is |
| --- | --- |
| `rl-agent/scenarios/{easy,medium,hard}/*.json` | 23 hand‑curated incident archetypes (id, difficulty, title, description, preconditions, correct_action_chain, target_score, max_steps). |
| `rl-agent/scenarios/sim/{easy,medium,hard}/*.json` | 381 simulator‑grade RL scenarios (156 + 128 + 97). Adds `topology_overrides`, `saboteur`, `slack`, `traffic_profile`, `k8s_controller`, `seed`. |
| `colab/logs/training_kaggle{1,2,3}.json` | Per‑update training metrics for one shard: `update, elapsed_s, mean_reward, mean_value, ppo{loss, kl, policy_loss, value_err}, rewards_by_task`. The union of `rewards_by_task` keys across all three files = full 381‑task coverage proof. |
| `kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/adapter_config.json` | LoRA configuration emitted by PEFT (`r=16, alpha=32, target_modules=[…]`). |
| `kaggle ran notebooks/shard {1,2,3}/adapter_kaggle{N}/adapter_model.safetensors` | The actual LoRA delta — ~50 MB per shard. Loadable with `PeftModel.from_pretrained(base, path)`. |
| `rl-agent/checkpoints/ppo-v{2,3,4}-*/metrics.jsonl` | Per‑update metrics for the Round 2 deep runs (heuristic / hybrid Ollama+heuristic / hybrid Ollama+Groq). |
| `rl-agent/checkpoints/training_metrics.json` + `evaluation_report.json` | Round 1 (legacy SB3 PPO + MLP) per‑checkpoint metrics and 90‑episode evaluation summary. |
| `rl-agent/showcase_data.json` | Pre‑computed bundle that hydrates the `/showcase` page. Built by `scripts/build_showcase_data.py`. |
| `openenv.yaml` | OpenEnv manifest declaring `/reset, /step, /state, /health`. |
| `frontend/package.json` | Next.js 14 AcmeCorp e‑commerce app — both chaos target and live UI. |
| `frontend/tsconfig.json` | Strict TS configuration. |
| `frontend/tailwind.config.js`, `postcss.config.js` | Frontend styling stack. |
| `backend/{payments-api,inventory-service,notification-service,order-worker}/package.json` | Per‑service Node apps that get rolled out, restarted, scaled, and patched by agent actions. |
| `infra/terraform/main.tf` | Hetzner cluster provisioning (network, subnet, ssh key, 3 servers, load balancer, listeners). |
| `infra/k8s/*.yaml` | Deployments, Services, ConfigMaps, ChaosMesh experiments for the live cluster. |

### 10.13 System architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    IncidentCommander                            │
│                                                                 │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐                │
│  │ RL Agent │──│ OpenEnv API │──│ Graders      │                │
│  │ (LLM /   │  │ reset()     │  │ - Postmortem │                │
│  │  PPO /   │  │ step()      │  │ - BlastRadius│                │
│  │Heuristic)│  │ state()     │  │ - Holistic   │                │
│  └──────────┘  │ grader()    │  └──────────────┘                │
│                │ baseline()  │                                  │
│                └──────┬──────┘                                  │
│                       │                                         │
│         ┌─────────────┼──────────────┐                          │
│         ▼             ▼              ▼                          │
│  ┌────────────┐ ┌──────────┐ ┌─────────────┐                    │
│  │ Prometheus │ │   Loki   │ │ Chaos Mesh  │                    │
│  │  Metrics   │ │   Logs   │ │ Fault Inject│                    │
│  └─────┬──────┘ └────┬─────┘ └──────┬──────┘                    │
│        └──────────────┼──────────────┘                          │
│                       ▼                                         │
│  ┌─────────────────────────────────────────┐                    │
│  │        AcmeCorp E-Commerce Platform     │                    │
│  │  5 microservices + Kafka + Redis +      │                    │
│  │  Postgres + full observability stack    │                    │
│  └─────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

### 10.14 Project structure

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
│   ├── training/                # PPO training scripts (legacy SB3 + hybrid + GRPO)
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
├── colab/                       # Round‑3 PPO trainer library
├── kaggle/                      # Round‑3 Kaggle notebooks (3 shards)
├── kaggle ran notebooks/        # Round‑3 outputs: per‑shard adapters + JSON logs
└── scripts/                     # Cluster setup, training entry point, LoRA merge, helpers
```

### 10.15 Key differentiators

| Feature | IncidentCommander | Typical RL env |
| --- | --- | --- |
| Tasks | 7 archetypes × 381 procedural variants | 1–3 |
| Observations | Real Prometheus / Loki / Alertmanager / Slack chatter | Synthetic |
| Actions | 10 types with real K8s effects | Simple discrete |
| Red herrings | Yes (tasks 3, 5, 6, 7 + procedural variants) | No |
| Context‑gated rewards | Yes (−0.20 for acting blind) | No |
| Holistic grading | Investigation + mitigation + efficiency + damage | Final reward only |
| Live dashboard | Plotly.js at `/dashboard` | None |
| Baseline agent | Built‑in heuristic at `/baseline` | External |
| Infrastructure | 5 microservices + full observability | Simulated |

### 10.16 License

MIT. See [`LICENSE`](https://github.com/r1cksync/meta-rl-hack/blob/main/incident-commander/README.md) (declared at the bottom of the README).

---

## Credits

* **Demo BGM:** *Inspired* by [Kevin MacLeod](https://incompetech.com),
  licensed under [Creative Commons: By Attribution 4.0](http://creativecommons.org/licenses/by/4.0/).
* **Voiceover:** Microsoft Edge Neural TTS (`en-US-AndrewMultilingualNeural`).
* **Models:** `microsoft/Phi-3.5-mini-instruct` (actor),
  `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` (critic) — both via Kaggle Models
  read‑only mounts.
* **Compute:** 3 × free Kaggle T4 (LLM run) + local CPU (legacy MLP).

— Built for the **Meta PyTorch OpenEnv Hackathon × Scaler School of
Technology, 2026**.
