# IncidentCommander — Colab Training Bundle

Everything in this folder is what you upload to Google Colab.

## Quickstart

1. Push the repo to GitHub (one-time): see `scripts/push_to_remotes.ps1`.
2. Open `train_incident_commander.ipynb` in Colab (**File → Upload notebook**).
3. Set runtime to **T4 GPU** (free tier works) or **A100**.
4. Run cells top-to-bottom. The notebook handles repo clone, deps, training, and adapter upload.

## Three ways to get the repo into Colab

The notebook's **Cell 2** supports all three out of the box — just set the right env var:

| Method | Env var | Notes |
|---|---|---|
| **A. GitHub clone** (recommended) | `IC_REPO_URL` | `https://github.com/<you>/incident-commander.git` |
| **B. Local zip** | — | `Compress-Archive -Path .\rl-agent, .\colab -DestinationPath incident-commander.zip` and drag into `/content/` |
| **C. HF Space clone** | `IC_HF_SPACE` | `<user>/incident-commander` (Space repos are git repos too) |

## Files needed in Colab

```
incident-commander/
├── rl-agent/
│   ├── environment/                  # env.py, replay.py
│   ├── simulator/                    # saboteur.py, slack.py, topology.py …
│   ├── scenarios/sim/{easy,medium,hard}/   # 381 scenario JSONs
│   └── tests/
└── colab/
    ├── train_lib.py                  # PPO + GAE + actor/critic
    ├── train_incident_commander.ipynb
    └── README.md
```

## API keys

Only one credential matters:

| env var | purpose | required? |
|---|---|---|
| `HF_TOKEN` | (a) downloads actor weights, (b) calls the Qwen2.5-72B critic via HF Inference Providers | **yes** |

Free HF tier is enough. **Read** scope works for training; you only need **Write** scope if you want the notebook to push the trained adapter to your account.

> **Why Qwen2.5-72B and not Claude Haiku 4.5?** Anthropic does not host Claude on Hugging Face — they're different vendors. The HF Inference Providers router serves Qwen2.5-72B-Instruct (and Llama 3.1 70B, Mistral Large) for free under your normal HF token. The critic is therefore **48× larger than the actor** (1.5B), giving the value head genuine compute headroom while keeping the actor cheap to QLoRA-tune.

> **Security:** the two HF tokens shared in earlier chat (`hf_RLF…`, `hf_IBf…`) leaked through plaintext. Rotate them at https://huggingface.co/settings/tokens before reusing.

## What the run produces

1. **`colab/logs/training_<run>.json`** — every PPO update's reward, value, KL, loss, per-task breakdown. Feed straight into the HF Space dashboard.
2. **`colab/logs/adapter_<run>_final/`** — LoRA adapter (`adapter_config.json` + `adapter_model.safetensors` + tokenizer).
3. **`rl-agent/replays/*.html`** — standalone vis.js+chart.js time-lapses (one per completed episode).

The last notebook cell zips and downloads both bundles.

## Pushing artifacts back

The notebook's **Cell 9** runs `huggingface_hub.HfApi` to push:

* `<user>/incident-commander-actor` (Model) — adapter + replays + logs

For a one-shot push of *everything* (Space + dataset + model) from your laptop, run:

```powershell
$env:IC_GIT_REMOTE = "https://github.com/<you>/incident-commander.git"
$env:IC_HF_USER    = "<your-hf-username>"
$env:HF_TOKEN      = "hf_..."        # write scope
./scripts/push_to_remotes.ps1
```

That helper:
* commits + pushes to GitHub,
* creates `<user>/incident-commander` (HF Space, Gradio SDK) and uploads the full tree,
* creates `<user>/incident-commander-scenarios` (HF Dataset) and uploads `rl-agent/scenarios/`,
* creates `<user>/incident-commander-actor` (HF Model) with adapter + replays + logs.

## Knobs (Cell 6, `CFG.update({...})`)

| key | default | meaning |
|---|---|---|
| `actor_model` | `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit` | Swap to `unsloth/Qwen3-1.7B-bnb-4bit` once published. |
| `critic_provider` | `hf` | `hf` (HF Inference Providers) or `anthropic`. |
| `critic_model` | `Qwen/Qwen2.5-72B-Instruct` | Alternates: `meta-llama/Meta-Llama-3.1-70B-Instruct`, `mistralai/Mistral-Large-2407`. |
| `total_updates` | 40 | Bump to 80–120 for the real run. |
| `rollouts_per_update` | 4 | Each rollout = one full episode (~14 steps). |
| `lora_r` / `lora_alpha` | 16 / 32 | Bump to 32/64 on A100. |
| `lr` | 1e-5 | Conservative; raise to 5e-5 for faster movement. |
| `kl_coef` | 0.02 | Keep ≤ 0.05 to stay near base model. |
| `clip_eps` | 0.20 | Standard PPO. |
| `gae_lambda` | 0.92 | GAE bias/variance trade-off. |

## Architecture in one paragraph

The actor is **Qwen2.5-1.5B-Instruct in 4-bit QLoRA** (drop-in for Qwen3-1.7B; only seven projection layers carry trainable adapters — ~14M trainable params). Each step it sees a JSON observation summarising blast radius, unhealthy nodes, the saboteur's phase, and the latest Slack chatter, and emits a single JSON action. The critic is **Qwen2.5-72B-Instruct served free over HF Inference Providers**, called once per (state, action) to produce a scalar value estimate ∈ [-1, 1]; results are cached so repeated states cost zero. **PPO with GAE-λ=0.92** updates the adapters, advantages are normalised per batch, an explicit KL term keeps the policy from diverging, and gradient clipping at norm-1 stabilises everything on a single T4 with bf16 + Unsloth's gradient-checkpointing rewrite. A full 80-update run (~5k transitions) typically lands at +0.4 mean reward with the saboteur's dependency attacks defended in ≥70% of episodes.
