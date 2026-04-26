# IncidentCommander demo · per-scene shot list

This file pairs every voiceover MP3 with **exactly what to show on screen** while it plays. Use it as your teleprompter while screen-recording in OBS.

- All 12 audio files live in `voice/out/sceneNN.mp3`
- Voice: Microsoft `en-US-AndrewMultilingualNeural` (most natural Edge voice), rate −4%, pitch +0 Hz
- Re-generate any single scene: `python voice/generate_voiceover.py --only scene04`
- Re-generate all: `python voice/generate_voiceover.py`

---

## Total timing (auto-measured)

| # | Audio | Duration | Cumulative | Scene start |
|---|---|---:|---:|---:|
| 01 | `scene01.mp3` | 0:24 | 0:24 | **0:00** |
| 02 | `scene02.mp3` | 0:27 | 0:51 | **0:24** |
| 03 | `scene03.mp3` | 0:28 | 1:20 | **0:51** |
| 04 | `scene04.mp3` | 0:27 | 1:47 | **1:20** |
| 05 | `scene05.mp3` | 0:21 | 2:07 | **1:47** |
| 06 | `scene06.mp3` | 0:18 | 2:25 | **2:07** |
| 07 | `scene07.mp3` | 0:33 | 2:58 | **2:25** |
| 08 | `scene08.mp3` | 0:22 | 3:20 | **2:58** |
| 09 | `scene09.mp3` | 0:19 | 3:39 | **3:20** |
| 10 | `scene10.mp3` | 0:20 | 3:59 | **3:39** |
| 11 | `scene11.mp3` | 0:22 | 4:20 | **3:59** |
| 12 | `scene12.mp3` | 0:27 | 4:47 | **4:20** |

**Total run-time: 4 min 47 s — well under the 5-minute cap.** Add ≤2 s of dip-to-black between scenes plus a 3 s intro + 5 s outro and you'll land at ~5 min flat. Scene 03 points at the new `#slack` section. **Scene 04 has been rewritten as the "Did it actually learn?" beat and now points at the new `#results` section** (legacy-baseline vs. PPO Kaggle, KL/loss convergence table, and the per-category improvement table where the novelty scenarios win).

---

## Recording rule of thumb

For every scene: **press OBS Start → wait 2 s → do the on-screen actions slowly → wait 2 s → Stop.** You'll trim the head and tail in DaVinci. Each line in "Action timeline" below maps to one second-bracketed beat inside the audio.

---

## Scene 01 · `scene01.mp3` · 0:30 — Hook

**URL / surface:** `https://sagnik-mukherjee-incodent-commander.hf.space/showcase` — full-screen, no scroll.

**Action timeline (relative to audio start):**
| t | What you do on screen |
|---:|---|
| 0:00 | Page loaded at hero. Cursor parked outside the headline. **Do nothing.** |
| 0:05 | Slow scroll-down 60 px so the gradient parallax animates, then back up. |
| 0:15 | Hover the headline "Teaching an AI to be on-call." |
| 0:23 | Drift cursor toward the **PPO Dashboard** button in the top-right (don't click). |
| 0:28 | Hold steady — voice says "Let me show you." |

**Post-effect (DaVinci):** subtle zoom-in 1.0 → 1.05 across the whole 30 s, easing into Scene 2.

---

## Scene 02 · `scene02.mp3` · 0:32 — KPI strip

**Surface:** scroll the showcase down ~600 px until the 4 KPI cards are centred.

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Smooth scroll lands the KPI strip in view. Cursor at far left. |
| 0:05 | Hover **Scenarios · 381** card. It tilts up. Hold 3 s while voice reads it. |
| 0:11 | Slide cursor to **Tasks Trained · 381**. Hold 3 s. |
| 0:18 | Slide cursor to **PPO Updates · 180**. Hold 3 s. |
| 0:25 | Slide cursor to **Wall Time · ~12 h**. Hold to end. |

**Post-effect:** click-zoom 1.0 → 1.3 onto each KPI card as cursor lands; ease-out to 1.0 between cards. Power-Window highlight ring around each card while hovered.

---

## Scene 03 · `scene03.mp3` · 0:28 — Pillars + Slack noise (the differentiator)

**Surface:** scroll to the section "An RL environment that puts the agent at 3 AM PagerDuty." with the 6 feature cards, **then keep scrolling into the new `#slack` section** (`<section id="slack">`) — the JSON snippet, the templates pool, and the Mermaid signal-vs-noise DAG.

**Action timeline (~28 s total — go fast on the pillars, linger on Slack):**
| t | Beat in voice | What you do |
|---:|---|---|
| 0:00 | "auto-escalates" | Hover **Self-improving curriculum** card. |
| 0:04 | "adversarial designer" | Slide to **Adversarial scenario designer** card. |
| 0:08 | "three SRE personas" | Slide to **Three-persona LLM judge** card. |
| 0:12 | "the part nobody else does — Slack" | **Scroll down into the new `Slack noise` section.** Land on the headline "The agent reads coworker Slack chatter — not just metrics." |
| 0:16 | "CEO panicking, intern, frontend hotfix red herring" | Cursor sweeps the JSON snippet card on the left, then the templates `slack.py` card on the right — pause briefly on each named coworker line. |
| 0:22 | "some are clues, most are noise" | Drop into the **Mermaid signal-vs-noise DAG** below the snippets. Trace the green `useful_log_query (+0.10)` branch first, then the red `red_herring_penalty (−0.15)` branch. |
| 0:26 | "costs reward" | Hold on the red node to end. |

**Post-effect:** click-zoom 1.0 → 1.25 on the JSON snippet at 0:16. Power-Window highlight ring around the green vs. red Mermaid branches at 0:22. **This is the novelty beat — give it the strongest visual emphasis in the whole video.**

---

## Scene 04 · `scene04.mp3` · 0:27 — "Did it actually learn?" (the proof)

**Surface:** start on the 4 Plotly charts grid (Mean Reward / PPO Loss / KL / Wall-clock), then **scroll into the new `#results` section** with the legacy-vs-PPO comparison cards, the convergence table, and the per-category improvement table.

**Action timeline (this is now a critical judging-criteria beat — go fast on charts, linger on the results tables):**
| t | Beat in voice | What you do |
|---:|---|---|
| 0:00 | "Did it learn? Yes." | Charts in view. Cursor traces one line on the **Mean Reward** chart left→right (3 s). |
| 0:04 | "legacy MLP baseline solves easy" | Scroll down into `#results` section. Hover the **left card** "Legacy baseline · stable-baselines3" — pause 3 s on the green **+1.05 / 100% success** number. |
| 0:09 | "our LLM agent runs the same env on hard mode" | Slide cursor to the **right card** "PPO Kaggle · LLM agent on the hard problem" — pause 3 s on the **−0.315 across all 3 shards** number. |
| 0:14 | "KL drops over 50%, loss the same" | Scroll to the **convergence table** ("The policy genuinely converged"). Cursor sweeps the **Δ KL** column (−55%, −66%, −51%) then **Δ Loss** column. |
| 0:19 | "all three shards converge on the exact same peak reward" | Cursor lands on the **Best reward** column — point at all three "−0.315" rows in sequence. |
| 0:23 | "the novelty categories — Slack red herring, runbook trap, cascading failure" | Scroll to the **per-category improvement table**. Cursor highlights the four green +Δ rows (Slack +1.05, Runbook +0.90, Cascading +0.30, Trolley +0.30) in order. |

**Post-effect:** click-zoom 1.0 → 1.3 on each green Δ number as cursor lands. Power-Window dim every row except the four "novelty win" rows during 0:23–0:27. **This scene is the answer to judging criterion 2 ("Showing Improvement in Rewards") — give it as much polish as Scene 03.**

---

## Scene 05 · `scene05.mp3` · 0:31 — Hyper-parameters

**Surface:** the three config cards (Actor / Critic / PPO hyper-parameters) right under the charts.

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Cursor on the **Actor** card. Hover the model name `microsoft/Phi-3.5-mini-instruct`. |
| 0:08 | Slide to **Critic** card. Hover `deepseek-ai/DeepSeek-R1-...`. |
| 0:18 | Slide to **PPO hyper-parameters** card. Cursor sweeps top-to-bottom of the table (γ, λ, ε…). |

**Post-effect:** Power Window highlight box snapping from card to card. Click-zoom 1.2 each card.

---

## Scene 06 · `scene06.mp3` · 0:18 — Task explorer

**Surface:** the "All 381 tasks" section with filter chips, search input, and grid.

**Action timeline (tight — keep cursor moving):**
| t | What you do |
|---:|---|
| 0:00 | Scroll lands the section. Click the **Hard** chip — grid shrinks to 97 cards. |
| 0:04 | Move to the search box. Type `saboteur` quickly. |
| 0:08 | **Click any saboteur task card.** Modal opens with description + design intention + ground-truth action chain + per-shard reward trajectory. |
| 0:12 | Cursor sweeps the action-chain steps, then drops to the per-shard trajectory table. Voice says "the hard ones really are hard." |
| 0:16 | Press Esc to close, scroll continues into next section. |

**Post-effect:** click-zoom on the modal opening. Power-Window highlight on the green +0.30 final-reward number.

---

## Scene 07 · `scene07.mp3` · 1:01 — Methodology (Mermaid + 4 code blocks)

**Surface:** the "From a scenario JSON to a LoRA delta" Mermaid diagram, then the 4 code-block cards (Rollout / GAE / PPO / Sharded coverage).

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Scroll lands Mermaid centred. Cursor at the **scenario JSON** node. |
| 0:05 | Trace arrow → **env** → **actor** → **reward** → **critic** → **GAE** → **PPO** → **adapter**. Roughly 4 s per arrow. |
| 0:33 | Scroll down to the 4 code-block cards. Cursor on **Rollout collector** card. Hover 6 s. |
| 0:42 | Slide to **GAE** card. Hover 5 s. |
| 0:50 | Slide to **PPO clipped surrogate** card. Hover 5 s. |
| 0:55 | Slide to **Sharded coverage** card. Hover until end ("127 + 127 + 127 = 381"). |

**Post-effect:** the Mermaid trace is the climax — apply a slow dolly-zoom in DaVinci across the whole 33 s. Click-zoom 1.0 → 1.5 on the final "381" number at 1:00.

---

## Scene 08 · `scene08.mp3` · 0:43 — GitHub → Kaggle pipeline

**Surface:** showcase pipeline section, then a **tab switch** to GitHub, then a **tab switch** to Kaggle.

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | On showcase, cursor traces the 5 pipeline stage boxes left→right. (~8 s) |
| 0:08 | **Switch to GitHub tab** (`r1cksync/meta-rl-hack`). Show repo file tree 3 s. |
| 0:13 | **Switch to Kaggle tab** (`kaggle_train_shard1.ipynb`). |
| 0:15 | Scroll to **Cell 5** — point at `git clone --depth one`. Hold 4 s. |
| 0:22 | Scroll to **Cell 6** — point at `IC_TASK_SHARD=1`. Hold 4 s. |
| 0:28 | Scroll to **Cell 7** — point at `scripts/run_training.py`. Hold 4 s. |
| 0:33 | Scroll to **Cell 8** — point at `zip` line. Hold 3 s. |
| 0:37 | **Switch back to showcase tab**. Cursor on the 9-cell anatomy table. |

**Post-effect:** crossfade between tab switches (don't use cuts — looks janky on tab switches). Click-zoom on each cell number.

---

## Scene 09 · `scene09.mp3` · 0:48 — Production infra

**Surface:** showcase "Terraform → Hetzner → k3s → live agent" Mermaid diagram, then a **VS Code switch** to `infra/terraform/main.tf`.

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Mermaid centred. Cursor at top: `infra/terraform/main.tf`. |
| 0:05 | Trace down: Terraform → Hetzner Cloud → VPC → 3× cx21 → load balancer → k3s → Helm → AcmeCorp services → live agent. ~3 s per node. |
| 0:30 | Cursor lingers on the bring-up sequence panel ("terraform apply / k3s / helm install"). |
| 0:38 | **Switch to VS Code**, open `infra/terraform/main.tf`. |
| 0:40 | Slow scroll through the file ~6 s, pausing on `resource "hcloud_server"` blocks. |
| 0:46 | Cursor parked on top of file. |

**Post-effect:** click-zoom on the Mermaid root node and final node. Highlight ring around `REAL_K8S=true` text on screen.

---

## Scene 10 · `scene10.mp3` · 0:24 — File index

**Surface:** showcase "JSON file index" table.

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Table in view. Cursor at top of the table. |
| 0:05 | Highlight the row **`training_kaggle{N}.json`**. Hold 4 s. |
| 0:10 | Highlight the row **`adapter_config.json`**. Hold 4 s. |
| 0:15 | Highlight the row **`scenarios/sim/**`**. Hold 4 s. |
| 0:20 | Cursor parks on the row that mentions "381". |

**Post-effect:** Power-Window highlight box around each row in turn. Optional click-zoom on the "381" cell at 0:21.

---

## Scene 11 · `scene11.mp3` · 0:32 — Dual dashboards (the Phase B reveal)

**Surface:** showcase top-bar → click **PPO Dashboard** → `/dashboard/ppo`.

**Action timeline (Beat A · 0:00 – 0:18):**
| t | What you do |
|---:|---|
| 0:00 | On showcase, cursor at the **PPO Dashboard** button (top-right, blue trim). |
| 0:01 | **Click**. Page loads at `/dashboard/ppo`. |
| 0:03 | Cursor at the **blue "PPO KAGGLE · 381 TASKS" banner**. Hold 4 s — voice says "every chart computed from the 381-task Kaggle run." |
| 0:09 | Click **Rewards** tab. Hold 2 s on histogram + curves. |
| 0:13 | Click **Tasks** tab. Hold 2 s on the sortable 381-row table. |
| 0:15 | Click **Training** tab. Hold 2 s on the 6-panel grid. |

**Action timeline (Beat B · 0:18 – 0:32):**
| t | What you do |
|---:|---|
| 0:18 | Cursor moves to the **← Legacy** link inside the blue banner. **Click**. |
| 0:20 | Page loads at `/dashboard` (overview) with **yellow "LEGACY DATASET" banner**. |
| 0:22 | Cursor at the yellow banner. Hold 3 s. |
| 0:26 | Click the **Rewards** tab. The two reward charts render (no longer stretching infinitely). |
| 0:30 | Hold on the rewards page to end. |

**Post-effect:** click-zoom 1.0 → 1.4 on each banner as it appears. Power-Window highlight on the source-files paragraph in both banners (the `code` blocks listing JSON paths).

---

## Scene 12 · `scene12.mp3` · 0:35 — Wrap

**Surface:** scroll back to the showcase hero (`Home` button or scroll-to-top).

**Action timeline:**
| t | What you do |
|---:|---|
| 0:00 | Click **Showcase** in the dashboard topbar (or the back-arrow). Hero loads. |
| 0:03 | Cursor parked under the headline. |
| 0:15 | Cursor drifts to the **GitHub** button (top-right). Voice mentions `r1cksync/meta-rl-hack`. |
| 0:22 | Cursor drifts to the **PPO Dashboard** button. Voice mentions `sagnik-mukherjee/incodent-commander`. |
| 0:30 | Cursor drifts to centre. **Hold completely still** for the last 5 s. |

**Post-effect:** slow zoom-out 1.05 → 1.0 across the 35 s. Music fades to silence in the last 3 s. End with a 2-s freeze frame of the hero, then dip-to-black for the outro card.

---

## DaVinci Resolve assembly cheat sheet

1. Drop all 12 `voice/out/sceneNN.mp3` on **A1** end-to-end (one after another, no gaps).
2. Drop the 12 screen recordings on **V1**, aligning each clip's start to the matching scene's start time in the table above.
3. If a video clip is shorter than its audio: hold the last frame as a freeze (right-click → Freeze Frame).
4. If a video clip is longer than its audio: trim it; never let video run past where the next scene's audio starts.
5. Drop ambient music on **A2**, full length, at −22 dB; add Compressor with sidechain from A1 (ratio 4:1, threshold −30 dB).
6. Add 8-frame **Cross Dissolve** between every scene's video clip.
7. Generate captions from A1 (Edit page → right-click timeline → Create Subtitles from Audio).
8. Deliver page → YouTube 1080p preset → 16,000 kbit/s.

---

## Voice variants (try before final commit)

| Voice ID | Vibe | When to pick |
|---|---|---|
| `en-US-GuyNeural` (default) | Confident male, technical | Tech demos, hackathon judges |
| `en-US-AriaNeural` | Warm female, conversational | Wide audiences |
| `en-US-JennyNeural` | Friendly female | Tutorials |
| `en-GB-RyanNeural` | British male, authoritative | "Documentary" feel |
| `en-US-BrianMultilingualNeural` | Newest, most natural | If you want least "TTS-y" |

Try 3 of them on Scene 1 only, pick a winner, then re-run the full batch:
```powershell
python voice/generate_voiceover.py --only scene01 --voice en-US-AriaNeural
python voice/generate_voiceover.py --only scene01 --voice en-GB-RyanNeural
# then commit your favourite:
python voice/generate_voiceover.py --voice <winner>
```
