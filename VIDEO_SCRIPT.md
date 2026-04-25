# IncidentCommander — Demo Video Script

**Target length:** 6–8 minutes
**Resolution:** 1080p screen recording, system audio off, mic on
**Tooling:** OBS (or Loom). Use a smooth-cursor / cursor-highlight extension.

A quick word on pacing: the showcase page is built as a single scrollable surface with reveal-on-scroll animations, so you can do *most* of the recording inside that one tab. Don't rush — let each section's animation finish before you start narrating it.

---

## Pre-recording checklist

- [ ] HF Space is up: `https://sagnik-mukherjee-incodent-commander.hf.space/health` returns `{"status":"ok"}`.
- [ ] Showcase page loads cleanly: `https://sagnik-mukherjee-incodent-commander.hf.space/showcase`.
- [ ] Browser zoom = 100 %, full-screen window, dark OS theme, hide bookmarks bar.
- [ ] VS Code in dark theme, font size ~16 pt.
- [ ] One Kaggle notebook open in another tab (`kaggle_train_shard1.ipynb`).
- [ ] GitHub repo open in another tab: `https://github.com/r1cksync/meta-rl-hack`.
- [ ] Terminal in VS Code with `cd incident-commander` already done.

---

## Scene 1 — Hook · 0:00 – 0:25

**Screen:** showcase hero (full viewport gradient, "Teaching an AI to be on-call.").
**Cursor focus:** stays still on the headline.

> *Script.* Every SRE has been there: PagerDuty goes off at 3 AM, five dashboards are red, and you have no idea which service is the actual root cause. We turned that whole experience into a reinforcement-learning environment. 381 production-grade incident scenarios, a 4-bit Phi-3.5-mini actor, an 8-bit DeepSeek-R1 critic, and PPO sharded across three free Kaggle T4 GPUs. Let me show you.

**Transition:** scroll slowly down so the KPI strip animates in.

---

## Scene 2 — Numbers at a glance · 0:25 – 0:55

**Screen:** the KPI strip just below the hero (Scenarios / Tasks Trained / PPO Updates / Wall Time).
**Cursor focus:** hover each KPI card in order — they tilt up on hover.

> *Script.* Four numbers tell the whole story. **381 scenarios** — these are not toy puzzles, they're real incident archetypes: DynamoDB throttling, IAM permission chains, memory leaks hidden behind cascading 504s. **381 trained** — every single scenario was visited in training. **60 PPO updates per shard, three shards in parallel — 180 updates total.** And the aggregate wall-clock across three free T4s is roughly twelve hours.

---

## Scene 3 — What & Why · 0:55 – 1:25

**Screen:** "An RL environment that puts the agent at 3 AM PagerDuty." section, with the 6 feature cards.
**Cursor focus:** sweep across the six cards: self-improving curriculum, adversarial scenario designer, three-persona LLM judge, phase-aware rewards, context-gated penalties, live infra.

> *Script.* Six things make this different from toy environments. The curriculum auto-escalates difficulty as the agent improves. At expert tier, an adversarial designer LLM composes brand-new incidents targeting the agent's tracked weaknesses. Every action is critiqued by a junior, senior, and principal SRE persona — Snorkel-style experts in the loop. Rewards are phase-aware: triage, investigate, fix, verify — getting the order wrong costs reward. Context-gated penalties stop reward-hacking: act blind, get docked. Hit a red-herring service, get docked. And the same code path that drives a mock cluster can drive a real Kubernetes cluster behind a single env var.

---

## Scene 4 — Training curves · 1:25 – 2:15

**Screen:** the four Plotly charts (Mean Reward, PPO Loss, KL, Wall-clock).
**Cursor focus:** point at each chart's lines, especially the three coloured shard traces.

> *Script.* This is every PPO update from every shard. Three coloured lines — blue, purple, orange — for shards one, two, three. The mean reward starts steeply negative because the agent is exploring at random, then climbs as the policy learns to investigate before acting. KL divergence stays bounded — the clip plus the 0.02 KL coefficient keep us from drifting too far from the reference policy. Loss decays cleanly. Wall-clock per update stays roughly flat at a hundred-and-something seconds — no memory blow-up over the run.

**Cursor action:** hover the rewards chart on a specific update — Plotly tooltip pops up.

> *Script.* You can hover any point to read off the exact numbers; this isn't a static screenshot, it's the live JSON we logged on Kaggle.

---

## Scene 5 — Hyper-parameters · 2:15 – 2:40

**Screen:** the three config cards (Actor / Critic / PPO hyper-parameters) right below the charts.
**Cursor focus:** highlight the actor model name, then the critic model name, then read the PPO block.

> *Script.* The actor is Phi-3.5-mini, 3.8 billion parameters, loaded in 4-bit NF4. The critic is DeepSeek-R1-Qwen3-8B, also 4-bit, frozen — we only use it for value baselines. LoRA rank 16, alpha 32 — about 25 million trainable parameters. Discount factor 0.95, GAE lambda 0.92, clip epsilon 0.2 — pretty standard PPO numbers, just packaged for a 16-gigabyte T4.

---

## Scene 6 — Task explorer · 2:40 – 3:55

**Screen:** the "All 381 tasks" section. Type-and-filter UI.
**Cursor focus:** click the **Hard** filter — grid filters live. Then type "saboteur" in the search box.

> *Script.* This is every task. Every action chain. Every reward. I can filter by difficulty — let me click hard — that narrows it to the 97 hardest scenarios. I can search by category — let me look for "saboteur" — and these are the adversarial duels, where a saboteur agent actively re-injects faults on a cooldown so a single fix isn't enough.

**Cursor action:** click any one task card. Modal opens.

> *Script.* When I click a card, I get the full details: the description, the design intention — *why* we built this scenario, what skill it's training — the ground-truth action chain, and the reward trajectory broken out by shard. So for this task, on shard one the agent went from a first-episode reward of negative point-six to a final reward of zero point-three — it learned. Close the modal.

**Cursor action:** press Esc. Scroll down to the category bar chart.

> *Script.* And here's the same data aggregated by category — which categories of incident did the agent get good at, and which are still hard. Cascading failures and runbook traps remain genuinely hard. Easier ones like Lambda throttling and EventBridge failures are solidly positive.

---

## Scene 7 — Methodology · 3:55 – 4:30

**Screen:** "From a scenario JSON to a LoRA delta." Mermaid diagram + the four code-block cards (Rollout / GAE / PPO / Sharded coverage).
**Cursor focus:** trace the Mermaid arrows with the cursor: scenario → env → actor → reward → critic → GAE → PPO → adapter.

> *Script.* This is the loop. A scenario JSON becomes an environment. The actor proposes an action. The environment scores it. The critic provides a value baseline. GAE turns reward + value into advantages. PPO updates only the LoRA weights — the base Phi-3.5 stays frozen. We log every metric to a JSON file on Kaggle and zip the adapter at the end.

**Cursor action:** scroll down. Hover the four code blocks.

> *Script.* Real code. The rollout collector uses a persistent cursor — it round-robins through the entire shard's task list across all sixty updates so every task is visited at least once. GAE is the standard recursive form. PPO is the clipped surrogate plus a KL penalty. And the sharded coverage is just modulo-three over the sorted task ids — disjoint and exhaustive, 127 plus 127 plus 127 equals 381.

---

## Scene 8 — GitHub → Kaggle pipeline · 4:30 – 5:15

**Screen:** the "End-to-end" section with the 5-stage pipeline and the 9-cell anatomy table.
**Cursor focus:** point at each of the five pipeline stages.

> *Script.* Code lives on GitHub. The Kaggle notebook clones the repo on every run — that's stage two right there.

**Action:** switch tab to GitHub, briefly show the repo file tree, then to the Kaggle notebook.

> *Script.* Here's the actual notebook. Cell five is just `git clone --depth one`. That means I never have to re-upload the notebook when I change training code — I just push to GitHub and re-run the Kaggle kernel. Cell six sets the `IC_TASK_SHARD` environment variable — that's the only thing that differs between the three notebooks. Cell seven shells out to `scripts/run_training.py`, which is the actual PPO loop. And cell eight zips the adapter for download.

**Action:** scroll down to the 9-cell anatomy table on the showcase page.

> *Script.* Every cell is documented right here on the showcase page so anyone can reproduce it.

---

## Scene 9 — Production infra · 5:15 – 5:55

**Screen:** the "Terraform → Hetzner → k3s → live agent" section with its bigger Mermaid diagram.
**Cursor focus:** trace the diagram from `infra/terraform/main.tf` down through the k3s cluster down to the agent box.

> *Script.* The agent doesn't have to live in a mock world. The same code path drives a real Kubernetes cluster — flip `REAL_K8S=true` and write actions like rollback, restart, scale, apply config patch hit a real cluster. We provision that cluster with Terraform on Hetzner Cloud — that's twenty euros a month for a working three-node demo. The Terraform module gives us a private VPC, three cx21 nodes, a load balancer with HTTP and HTTPS listeners. The bring-up sequence — terraform apply, k3s, helm install — is right there in the panel. Five steps, fully scripted.

**Action:** open `infra/terraform/main.tf` in VS Code briefly, scroll through.

> *Script.* This is the actual Terraform file. It's not vapour — it's fifteen resources that produce a working cluster.

---

## Scene 10 — File index · 5:55 – 6:25

**Screen:** the "JSON file index" table on the showcase page.
**Cursor focus:** highlight a few rows — `training_kaggle{N}.json`, `adapter_config.json`, `scenarios/sim/**`.

> *Script.* Every JSON file in the project documented in one place. The training logs, the LoRA configs, the scenario definitions, the showcase bundle — what it is, where it lives, what generates it. So if you want to verify our coverage claim, the union of `rewards_by_task` keys across the three training logs is exactly 381. It's right here in the table.

---

## Scene 11 — Live dashboards · 6:25 – 7:15

**Screen:** the showcase nav now has **two** dashboard buttons — `Legacy` (yellow-trim) and `PPO Dashboard` (blue-trim).

**Beat A — PPO dashboard.** Click `PPO Dashboard`. The page opens at `/dashboard/ppo`.
**Cursor focus:** point at the blue **"PPO KAGGLE · 381 TASKS"** banner at the top, which lists the exact source files: `kaggle ran notebooks/shard {1,2,3}/training_kaggle{N}.json`, `rl-agent/scenarios/sim/{easy,medium,hard}/*.json`, `rl-agent/showcase_data.json`. Then click through 3 tabs: `Rewards` (reward distribution histogram + per-update curves for all 3 shards), `Tasks` (sortable 381-row table), `Training` (six-panel grid: reward, PPO loss, KL, value error, policy loss, wall-clock).

> *Script.* This is the new PPO dashboard, every chart computed from the 381-task Kaggle run. Three shards, sixty PPO updates each, every transition replayable. The banner up top tells you exactly which JSON files each number came from — no magic.

**Beat B — Legacy dashboard.** Click `← Legacy` in the banner. The page slides to `/dashboard` with a yellow **"LEGACY DATASET"** banner referencing `rl-agent/scenarios/{easy,medium,hard}/*.json`, `rl-agent/checkpoints/<run>/metrics.jsonl`, `colab/logs/reward_breakdown_history.jsonl`.
**Cursor focus:** point at the yellow banner, then click `Rewards` to show the original 11-task heuristic curves (no longer stretching infinitely — that bug is fixed).

> *Script.* And the original kube-sre-gym-style dashboard is still here, untouched, with its own banner so you can never confuse the two datasets. Same nav, same look, different data — and one click to swap between them.

---

## Scene 12 — Wrap · 7:15 – 7:45

**Screen:** scroll back to the showcase hero.
**Cursor focus:** hover the GitHub button in the top-right.

> *Script.* That's IncidentCommander: an OpenEnv RL environment with 381 real incident scenarios, full PPO + LoRA training pipeline, free-T4-friendly sharded notebooks, terraform-provisioned production cluster, live dashboard, and complete documentation of every task, action, reward, and JSON file. Code's on GitHub at `r1cksync/meta-rl-hack`. The space is at `sagnik-mukherjee/incodent-commander`. Built for the Meta PyTorch OpenEnv Hackathon and Scaler School of Technology, 2026.

**End frame:** showcase hero, no cursor movement, hold for 2 seconds. Cut.

---

## Cheat sheet — what to point your cursor at

| Time | Element |
|------|---------|
| 0:00 | Hero headline |
| 0:25 | KPI cards (sweep left → right) |
| 0:55 | "Self-improving curriculum" card → "Live infrastructure option" card |
| 1:25 | The four training plots (especially shard-3 reward trace) |
| 2:15 | Actor / Critic / PPO config cards |
| 2:40 | Search box, then a single task card |
| 3:55 | Mermaid diagram of the PPO loop |
| 4:30 | The 5-stage pipeline boxes |
| 5:15 | Bigger Mermaid (Terraform → k3s) |
| 5:55 | A few rows in the file-index table |
| 6:25 | "PPO Dashboard" CTA → blue PPO banner → 3 tabs (Rewards / Tasks / Training) |
| 7:00 | "← Legacy" link in banner → yellow Legacy banner → Rewards tab |
| 7:15 | Hero (return) |

## Talking-points checklist (cover all)

- [x] OpenEnv compliance + real incident archetypes
- [x] Phi-3.5-mini actor + DeepSeek-R1 critic, 4-bit
- [x] PPO with GAE, LoRA r=16, kl 0.02
- [x] 381 scenarios, modulo-3 disjoint shards, full coverage
- [x] Persistent cursor rollout collector
- [x] Adversarial designer + 3-persona judge + curriculum
- [x] Phase-aware rewards + context-gated penalties
- [x] GitHub → Kaggle clone-on-run flow
- [x] adapter merging via `merge_lora_adapters.py`
- [x] Terraform Hetzner k3s for live cluster
- [x] AcmeCorp microservices on Next.js + Node
- [x] showcase page is the single deliverable for evaluation

## Recording tips

- Don't read the script word-for-word. Use it as the structure; speak naturally.
- Pause for 1 second after every section transition so the reveal animation finishes.
- If you make a mistake, pause for 3 seconds rather than restarting — easier to cut.
- Keep your hand off the trackpad whenever you're not pointing at something — a still cursor is more professional than a wandering one.
