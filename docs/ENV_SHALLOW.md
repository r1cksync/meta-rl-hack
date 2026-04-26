# Env spec — **Shallow regime** (Round 3, 381 procedural scenarios)

> The procedural sim curriculum used by the **Phi‑3.5‑mini + DeepSeek‑R1
> Kaggle PPO+LoRA run** ([`scripts/run_training.py`](../scripts/run_training.py)
> + [`colab/train_lib.py`](../colab/train_lib.py), three Kaggle T4 shards
> merged via [`scripts/merge_lora_adapters.py`](../scripts/merge_lora_adapters.py)).
> Same `IncidentCommanderEnv`, but the task pool is the 381 JSON files under
> [`rl-agent/scenarios/sim/{easy,medium,hard}/`](../rl-agent/scenarios/sim) and
> the action namespace is the full simulator surface (`platform.*`,
> `dynamodb.*`, `s3.*`, …) — not the 10 actions used by the deep regime.
>
> **For the per‑scenario row‑by‑row index of every one of the 381 tasks** (id, title, target score, max steps, canonical correct action chain) see the companion file [`TASKS_SHALLOW.md`](TASKS_SHALLOW.md).

## 1 · Task pool — 381 procedural scenarios

```
rl-agent/scenarios/sim/
├── easy/    156 files
├── medium/  128 files
└── hard/     97 files
                ─────
                381 total
```

**Scenario file shape** (extends the hand‑curated archetype JSON with five
extra channels — see [`rl-agent/scenarios/sim/easy/sim_easy_ddb_throttle_101.json`](../rl-agent/scenarios/sim/easy/sim_easy_ddb_throttle_101.json)
for an easy example and [`sim_advanced_slack_redherring_001.json`](../rl-agent/scenarios/sim/hard/sim_advanced_slack_redherring_001.json)
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

### Category breakdown

The 381 scenarios cover 12 categories. Counts by directory:

| Directory | Categories | Count |
| --- | --- | ---: |
| `easy/` | DynamoDB throttling (20), KMS rotation (20), Lambda cold start (20), Secrets rotation (20), SQS DLQ (20), SSM drift (20), generated app (28), generated cache (8) | 156 |
| `medium/` | API‑Gateway 5xx, EventBridge silent drop, KMS drift, Lambda throttling, Step Functions failures (15 each); generated red‑herring (20), peak‑load (18), cache (16), app (14) | 128 |
| `hard/` | DynamoDB throttle, IAM drift, generated cascade (24+30), generated DB (24), generated restore (8), API‑Gateway (10), advanced cascade/runbook/saboteur/Slack/trolley (1 each) | 97 |

The four **novelty categories** (Slack Red‑Herring, Runbook Trap, Cascading
Failure, Trolley Problem) are the ones that don't exist in any other RL‑for‑LLM
benchmark.

### Three‑shard sharding (used by Round 3)

```python
sorted_ids = sorted(all_sim_task_ids)         # 381 ids
shard_i    = [t for k, t in enumerate(sorted_ids) if k % 3 == i]   # 127 ids each
```

Disjoint and exhaustive. Three free Kaggle accounts ran in parallel
(~5 h each). The union of `rewards_by_task` keys across the three log files
[`shard {1,2,3}/training_kaggle{N}.json`](../kaggle%20ran%20notebooks) is
**exactly** the set of all 381 task ids — that's the coverage proof.

## 2 · Observation channels

Same channels as the deep regime (see [`docs/ENV_DEEP.md` §2](ENV_DEEP.md))
**plus three extras that only fire on procedural scenarios:**

| Channel | Source | Notes |
| --- | --- | --- |
| `slack` | env‑internal `SlackChatter` (templated coworker stream) | Deterministic; controlled by `slack.msgs_per_tick` in the scenario JSON. CEO / intern / frontend dev / DBA / finance personas. **Novel.** |
| `saboteur_state` | env‑internal `Saboteur` | Exposes `{primary_target, last_strike_tick, cooldown_remaining}` so the agent can reason about whether a fix actually held. |
| `aws_view` | mock AWS catalog | DynamoDB tables, IAM policies, Secrets Manager secrets, Lambda invocations, … — used by `aws_api_call` and the AWS‑flavoured investigate actions below. |

## 3 · Action space (full simulator surface)

The deep regime's 10 actions are still valid. Round 3 additionally enables
the AWS / forensic / namespaced actions defined in
[`rl-agent/environment/models.py :: ActionType`](../rl-agent/environment/models.py).

### 3.1 Investigate (read‑only — no blast radius)

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

### 3.2 Fix (write — can worsen blast radius)

| Action | Domain | What it does |
| --- | --- | --- |
| `rollback_deployment` / `restart_pods` / `scale_deployment` / `apply_config_patch` / `delete_chaos_experiment` | core | Same as deep regime |
| `invoke_lambda(function_name, payload?)` | AWS | Synchronous Lambda call |
| `rotate_secret(secret_id)` | AWS | Force secret rotation |
| `purge_queue(queue_url)` | AWS | SQS purge |
| `enable_eventbridge_rule(rule_arn)` | AWS | Re‑enable a disabled rule |
| `aws_api_call(service, verb, **kwargs)` | AWS · generic | Catch‑all — hits any of the 8 500+ catalog actions |
| `pause_health_checks(target)` / `capture_memory_dump(target)` / `resume_health_checks(target)` | platform | Forensic write actions used by hard scenarios (heap dump under K8s liveness pause). |

### 3.3 Terminal

| Action | Effect |
| --- | --- |
| `submit_postmortem(root_cause, timeline, mitigations, affected_services, recommended_followups)` | Episode ends |

## 4 · Reward signal

**Same shaper** as the deep regime (see [`docs/ENV_DEEP.md` §4](ENV_DEEP.md#4--reward-signal))
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

## 5 · Curriculum tiers (auto‑escalating during training)

Same controller as the deep regime. The curriculum table below is the live
layout enforced by [`rl-agent/environment/curriculum.py`](../rl-agent/environment/curriculum.py)
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

## 6 · PPO hyper‑parameters (the same ones validated by Rounds 1 + 2)

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

Per‑shard log JSON: [`shard 1/training_kaggle1.json`](../kaggle%20ran%20notebooks/shard%201/training_kaggle1.json),
[`shard 2/training_kaggle2.json`](../kaggle%20ran%20notebooks/shard%202/training_kaggle2.json),
[`shard 3/training_kaggle3.json`](../kaggle%20ran%20notebooks/shard%203/training_kaggle3.json).
Each row carries `update, elapsed_s, wall_s, mean_reward, mean_value,
ppo.{loss, kl, policy_loss, value_err}, rewards_by_task`.

## 7 · Where the chart lives

* KL decay across shards → [`assets/blog/llm_kl_decay.png`](../assets/blog/llm_kl_decay.png)
* PPO loss decay across shards → [`assets/blog/llm_loss_decay.png`](../assets/blog/llm_loss_decay.png)
* Best mean reward per shard → [`assets/blog/llm_best_reward.png`](../assets/blog/llm_best_reward.png)
* Per‑category Δ reward → [`assets/blog/llm_category_delta.png`](../assets/blog/llm_category_delta.png)
* Pass‑B training DAG (mermaid → PNG) → [`assets/blog/mermaid_training_dag.png`](../assets/blog/mermaid_training_dag.png)
