# Kaggle Training Notebooks

This folder ships the three notebooks we used to train IncidentCommander on free Kaggle T4 GPUs. They are deliberately thin — every cell either installs deps, sets env vars, or shells out to code in this repo. The actual training code lives at [`scripts/run_training.py`](../scripts/run_training.py) and [`colab/train_lib.py`](../colab/train_lib.py).

## Quick start

1. Open one of the three notebooks on Kaggle:
   - [`kaggle_train_shard1.ipynb`](kaggle_train_shard1.ipynb) — trains on the 127 tasks at sorted indices `0, 3, 6, …, 378`
   - [`kaggle_train_shard2.ipynb`](kaggle_train_shard2.ipynb) — trains on indices `1, 4, 7, …, 379`
   - [`kaggle_train_shard3.ipynb`](kaggle_train_shard3.ipynb) — trains on indices `2, 5, 8, …, 380`
2. In **Notebook Settings**:
   - Accelerator → **GPU T4 x1**
   - Internet → **on**
   - Persistence → **off** (saves quota)
3. Add the two Kaggle Models (right rail → **Add Input** → Models):
   - `microsoft/phi-3-5/transformers/phi-3-5-mini-instruct`
   - `deepseek-ai/deepseek-r1/transformers/deepseek-r1-0528-qwen3-8b` (or any DeepSeek-R1 variant; the path is set in cell 6)
4. (Optional) Add a Kaggle Secret named `HF_TOKEN` for any HuggingFace pulls that aren't already mounted.
5. **Save & Run All**.

## What each cell does

| Cell | Purpose |
|------|---------|
| **1 — markdown** | Title + attach instructions for the 2 Kaggle Models + GPU/Internet/Persistence. |
| **2 — install** | Best-effort `pip install unsloth`, then pin `transformers>=4.51`, `peft`, `accelerate`, `bitsandbytes`. Prints the unsloth return-code so failures are visible but non-fatal. |
| **3 — GPU sanity** | `nvidia-smi -L` + `torch.cuda.is_available()`. |
| **4 — verify mounts** | Asserts that the two Kaggle Models are attached, redirects HF cache to `/tmp/hf-cache`, wipes any cached custom modeling code, optionally pulls `HF_TOKEN` from Kaggle Secrets, installs warning filters. |
| **5 — clone repo** | `git clone --depth 1 https://github.com/r1cksync/meta-rl-hack.git` — fresh on every run, prints the commit hash. **This is why you don't need to re-upload the notebook when code changes.** |
| **6 — configure run** | Sets all `IC_*` environment variables: shard index, run name, total updates, rollouts, max steps, checkpoint cadence, model paths. |
| **7 — train** | `subprocess.run(['python', 'scripts/run_training.py'])`. Streams the live PPO training output. Produces `colab/logs/training_kaggle{N}.json` and `adapter_kaggle{N}/` checkpoints every 15 updates. |
| **8 — package** | Zips the final adapter to `/kaggle/working/adapter_kaggle{N}.zip` and copies the JSON log to `/kaggle/working/`. |
| **9 — markdown** | Merge instructions for `scripts/merge_lora_adapters.py` once all three shards are done. |

## After all three shards finish

```bash
git clone https://github.com/r1cksync/meta-rl-hack.git
cd meta-rl-hack/incident-commander

# Drop the three adapter zips into the repo root and unzip them, then:
python scripts/merge_lora_adapters.py \
    --adapters adapter_kaggle1 adapter_kaggle2 adapter_kaggle3 \
    --output  adapter_merged \
    --weights 1.0 1.0 1.0
```

`adapter_merged/` is now a single LoRA delta you can load on top of the same Phi-3.5-mini base used during training:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM

base = AutoModelForCausalLM.from_pretrained(
    "microsoft/Phi-3.5-mini-instruct",
    load_in_4bit=True,
    device_map="auto",
)
model = PeftModel.from_pretrained(base, "adapter_merged")
```

## Coverage proof

The shards are mathematically disjoint and exhaustive — modulo-3 over the sorted task ids of all 381 sim scenarios:

```python
sorted_ids = sorted(all_sim_task_ids)            # 381 ids
shard_i    = [t for k, t in enumerate(sorted_ids)
                if k % 3 == i]                    # 127 ids
```

The union of `rewards_by_task` keys across the three resulting `training_kaggle{1,2,3}.json` files is exactly the set of all 381 task ids. You can verify with:

```python
import json, pathlib
seen = set()
for n in (1, 2, 3):
    p = pathlib.Path(f"kaggle ran notebooks/shard {n}/training_kaggle{n}.json")
    d = json.loads(p.read_text())
    for u in d["updates"]:
        seen |= (u.get("rewards_by_task") or {}).keys()
print(len(seen))   # → 381
```

## Hyper-parameters

Set in cell 6 of every notebook (kept identical across shards):

| Variable | Value |
|----------|-------|
| `IC_NUM_UPDATES` | `60` |
| `IC_ROLLOUTS_PER_UPDATE` | `3` |
| `IC_MAX_STEPS_PER_EP` | `12` |
| `IC_LR` | `5e-5` |
| `IC_GAMMA` | `0.95` |
| `IC_GAE_LAMBDA` | `0.92` |
| `IC_CLIP_EPS` | `0.2` |
| `IC_KL_COEF` | `0.02` |
| `IC_ENTROPY_COEF` | `0.01` |
| `IC_PPO_EPOCHS` | `2` |
| `IC_MINIBATCH` | `4` |
| `IC_LORA_R` | `16` |
| `IC_LORA_ALPHA` | `32` |
| `IC_MAX_SEQ_LEN` | `3072` |
| `IC_CKPT_EVERY` | `15` |

## Outputs (saved to `/kaggle/working/`)

- `training_kaggle{N}.json` — the full per-update metric log (~1 MB per shard)
- `adapter_kaggle{N}.zip` — the final LoRA adapter (~50 MB)

Both are downloadable from the Kaggle UI's right-rail **Output** section once the kernel finishes.

## Live results

The merged adapter and full per-task reward curves for all three shards are visualised at:

**[https://sagnik-mukherjee-incodent-commander.hf.space/showcase](https://sagnik-mukherjee-incodent-commander.hf.space/showcase)**

— see "Per-shard training curves", "Task explorer", and "Reward distribution across categories".

---

For the full project context (rewards, grading, curriculum, adversarial designer, infra, OpenEnv API), see the [top-level README](../README.md).
