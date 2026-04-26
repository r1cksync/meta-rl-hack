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
**Video walkthrough (4 min):** **[youtu.be/8bDJ0MMZ1DM](https://youtu.be/8bDJ0MMZ1DM)**

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

## 4 · How we actually trained — two passes

### Pass A · Legacy MLP baseline (proves the env is solvable)

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
is: can an LLM agent do better on the **hard** version?

### Pass B · LLM agent on 381 procedural scenarios

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
  [youtu.be/8bDJ0MMZ1DM](https://youtu.be/8bDJ0MMZ1DM)**
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
