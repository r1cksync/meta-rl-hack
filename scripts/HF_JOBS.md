# Train on Hugging Face Jobs (real GPU, billed by the second)

Goal: launch a real GPU run from your laptop, watch live progress, and never lose a checkpoint even if the credits run out.

## What you get
- **Live progress bar + ETA** every PPO update (`[upd 027/120] reward=+0.31 V=+0.18 kl=+0.0042 upd=18s wall=8m12s ETA=27m11s`).
- **Checkpoints uploaded to HF Hub** every 20 updates (and at the end). If your $30 credit dies mid-run, the latest adapter is already at `https://huggingface.co/<you>/incident-commander-actor`.
- **Rolling JSON log** also uploaded after every update — you can refresh the HF page and see metrics live.

## One-time setup (on your laptop)
```powershell
pip install -U "huggingface_hub[cli]"
hf auth login                         # paste your hf_… token
```

## Launch the run
Pick **one** of these GPU flavors (cheapest → fastest):

| Flavor          | Price  | 120-update run | Notes |
|-----------------|--------|----------------|-------|
| `l4x1`          | ~$0.80/hr | ~25–35 min  | **Recommended** — best $/perf. ~$0.50 total. |
| `a10g-large`    | ~$1.05/hr | ~20–30 min  | Slightly faster, slightly more expensive. |
| `a100-large`    | ~$3.40/hr | ~8–12 min   | Fastest, biggest dent in credits. |

```powershell
$env:HF_TOKEN     = "<paste-your-hf_-token-here>"
$env:IC_PUSH_USER = "sagnik-mukherjee"     # checkpoints land here
$env:IC_REPO_URL  = "https://github.com/r1cksync/meta-rl-hack.git"

hf jobs run `
    --flavor l4x1 `
    --secret HF_TOKEN=$env:HF_TOKEN `
    --env IC_PUSH_USER=$env:IC_PUSH_USER `
    --env IC_REPO_URL=$env:IC_REPO_URL `
    --env IC_TOTAL_UPDATES=120 `
    --env IC_ROLLOUTS=6 `
    --env IC_RUN_NAME=hfjob01 `
    --env HF_HUB_ENABLE_HF_TRANSFER=1 `
    --image "huggingface/transformers-pytorch-gpu:latest" `
    -- bash -c "git clone --depth 1 `$IC_REPO_URL /workspace/ic && cd /workspace/ic && bash scripts/hf_job_entrypoint.sh"
```

> The `--secret` flag injects HF_TOKEN at runtime so it never lands in HF Hub history. The `--env` flags are visible in the job UI but contain no secrets.

## Watch progress
The `hf jobs run` command streams logs to your terminal. To detach + reattach:
```powershell
hf jobs run --detach ... # prints a job ID
hf jobs logs <job-id> --follow
hf jobs ps                # list running jobs + spend so far
```

You'll see a `tqdm` bar plus a per-update line so even non-TTY logs are readable. Look for `ETA=` to know how much wall-time is left.

## Recover if credits die mid-run
Every 20 updates the adapter is uploaded to:
```
https://huggingface.co/sagnik-mukherjee/incident-commander-actor
```
under paths like `adapter_hfjob01_u0040/`, `adapter_hfjob01_u0060/`, etc. The training log streams to `logs/training_hfjob01.json` every update. So even if the job is killed at update 67 you still have:
- the u0060 adapter (LoRA + tokenizer)
- the partial log up through update 67

To resume locally:
```powershell
hf download sagnik-mukherjee/incident-commander-actor adapter_hfjob01_u0060 --local-dir .\resume
```
Then point the trainer at the `--resume-from` adapter (planned, not wired yet — for now you'd start fresh from the saved adapter as the actor).

## Cost guardrails
- The `Qwen2.5-72B-Instruct` critic runs on **HF Inference Providers**, billed against the same $30. Calls are cached, so a 120-update run is typically ~$1–2 in critic spend.
- Training compute on `l4x1` for ~30 min ≈ **$0.40**.
- **Total budget**: ~$2–3 for the full real run, leaving ~$27 for re-runs or longer training.
