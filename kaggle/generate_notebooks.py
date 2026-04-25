"""Generate the 3 Kaggle notebooks for sharded IncidentCommander training.

Each notebook is identical except for the IC_TASK_SHARD value (0/1/2) and
the run_name. Re-run this script if you want to tweak the template.
"""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK_DIR = Path(__file__).resolve().parent

# Hugging Face repo IDs for the actor (1.5B) and critic (7B). Both are
# downloaded at notebook startup via huggingface_hub.snapshot_download — no
# Kaggle Models attachment needed.
ACTOR_REPO  = "Qwen/Qwen2.5-1.5B-Instruct"
CRITIC_REPO = "Qwen/Qwen2.5-7B-Instruct"

REPO_URL = "https://github.com/r1cksync/meta-rl-hack.git"


def cell_md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": text.splitlines(keepends=True)}


def cell_code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": text.splitlines(keepends=True)}


def build(shard: int, total_shards: int = 3) -> dict:
    title = f"# IncidentCommander RL — Kaggle shard {shard + 1} / {total_shards}"
    intro = f"""
**Workload:** every {total_shards}rd task starting at index {shard}
(~127 of 381 scenarios). Trains a LoRA on `{ACTOR_REPO}` using a
local `{CRITIC_REPO}` critic. **Both models download from Hugging Face Hub
at notebook startup — no Kaggle Models attachment needed.**

**Required notebook settings** (right-hand sidebar):
- Accelerator: `GPU T4 x2` or `GPU P100`
- Persistence: `Files only` (so `/kaggle/working/` survives restarts)
- Internet: `On` (needed to download the models + clone the repo)

**Optional** (only if you want intermediate checkpoint upload to your HF
repo): Add-ons → Secrets → add `HF_TOKEN` and toggle it on.

**Output:** `/kaggle/working/adapter_kaggle{shard + 1}.zip` — download from
the sidebar after the run finishes. Combine all 3 with
`scripts/merge_lora_adapters.py` on your laptop.
"""
    cells = [
        cell_md(title + "\n" + intro),

        cell_md("## 1. GPU + path sanity"),
        cell_code(f"""\
import subprocess
print('--- GPU ---')
subprocess.run(['nvidia-smi', '-L'], check=False)
import torch
print('CUDA OK?', torch.cuda.is_available(), '| device:',
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')
""".strip()),

        cell_md("## 2. Install deps (Kaggle has torch/transformers preinstalled — we just pin compatible versions)"),
        cell_code("""\
%pip install -q \\
    "transformers==4.46.3" \\
    "peft==0.13.2" \\
    "accelerate==1.1.1" \\
    "bitsandbytes==0.45.5" \\
    "trl==0.12.1" \\
    "huggingface_hub>=0.25,<1.0" \\
    "pydantic>=2,<3" \\
    "datasets" "sentencepiece" "protobuf" "safetensors"
""".strip()),

        cell_md("## 3. Download actor + critic from Hugging Face Hub"),
        cell_code(f"""\
import os, pathlib
from huggingface_hub import snapshot_download

# Optional HF_TOKEN — only needed if you have it set in Kaggle Secrets.
# Qwen 2.5 instruct models are public, so anonymous download works fine.
try:
    from kaggle_secrets import UserSecretsClient
    os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
    print('HF_TOKEN attached from Kaggle Secrets')
except Exception:
    print('No HF_TOKEN — anonymous download (Qwen 2.5 instruct is public).')

CACHE = '/kaggle/working/hf-cache'
pathlib.Path(CACHE).mkdir(parents=True, exist_ok=True)
os.environ['HF_HOME']            = CACHE
os.environ['HUGGINGFACE_HUB_CACHE'] = CACHE

print('downloading actor : {ACTOR_REPO}  (~3 GB) ...')
ACTOR_PATH = snapshot_download(
    repo_id='{ACTOR_REPO}',
    cache_dir=CACHE,
    allow_patterns=['*.json', '*.safetensors', '*.txt', 'tokenizer*'])

print('downloading critic: {CRITIC_REPO}  (~15 GB) ...')
CRITIC_PATH = snapshot_download(
    repo_id='{CRITIC_REPO}',
    cache_dir=CACHE,
    allow_patterns=['*.json', '*.safetensors', '*.txt', 'tokenizer*'])

print('actor :', ACTOR_PATH)
print('critic:', CRITIC_PATH)
""".strip()),

        cell_md("## 4. Clone the repo (public GitHub)"),
        cell_code(f"""\
import os, subprocess, pathlib
WORK = '/kaggle/working/incident-commander'
if not pathlib.Path(WORK).exists():
    subprocess.run(['git', 'clone', '--depth', '1',
                    '{REPO_URL}', WORK], check=True)
os.chdir(WORK)
print('cwd =', os.getcwd())
""".strip()),

        cell_md("## 5. Configure run (shard, paths, env vars)"),
        cell_code(f"""\
import os

os.environ['INCIDENT_COMMANDER_MOCK'] = 'true'
os.environ['IC_ACTOR_MODEL']     = ACTOR_PATH
os.environ['IC_CRITIC_PROVIDER'] = 'local'        # 7B critic on the same GPU
os.environ['IC_CRITIC_MODEL']    = CRITIC_PATH
os.environ['IC_TASK_MODE']       = 'all'           # full 381 corpus
os.environ['IC_TASK_SHARDS']     = '{total_shards}'
os.environ['IC_TASK_SHARD']      = '{shard}'
os.environ['IC_TOTAL_UPDATES']   = '60'            # ~6h on T4 / P100
os.environ['IC_ROLLOUTS']        = '3'
os.environ['IC_MAX_STEPS']       = '12'
os.environ['IC_CKPT_EVERY']      = '15'
os.environ['IC_RUN_NAME']        = 'kaggle{shard + 1}'

print('actor :', os.environ['IC_ACTOR_MODEL'])
print('critic:', os.environ['IC_CRITIC_MODEL'])
print('shard :', os.environ['IC_TASK_SHARD'], '/', os.environ['IC_TASK_SHARDS'])
""".strip()),

        cell_md("## 6. Train"),
        cell_code("""\
# The training script runs to completion. tqdm progress + ETA are streamed
# to stdout. Kaggle truncates very long outputs — adapter checkpoints are
# always written to /kaggle/working/incident-commander/colab/logs/ regardless.
import subprocess, sys
result = subprocess.run([sys.executable, 'scripts/run_training.py'],
                         check=False)
print('exit code:', result.returncode)
""".strip()),

        cell_md("## 7. Package outputs for download"),
        cell_code(f"""\
import shutil, glob, pathlib

LOGS = pathlib.Path('colab/logs')
finals = sorted(LOGS.glob('adapter_kaggle{shard + 1}_final'))
ckpts  = sorted(LOGS.glob('adapter_kaggle{shard + 1}_u*'))
keep   = (finals or ckpts)
assert keep, 'No adapter directories found — check the training cell output for errors.'
src = keep[-1]
print('packaging', src)

dst = pathlib.Path('/kaggle/working/adapter_kaggle{shard + 1}.zip')
shutil.make_archive(str(dst.with_suffix('')), 'zip', root_dir=src)
print('zipped to', dst, 'size:', dst.stat().st_size, 'bytes')

# Also copy the JSON training log for plotting on your laptop.
for j in glob.glob('colab/logs/training_kaggle{shard + 1}*.json'):
    shutil.copy(j, '/kaggle/working/')
print('files in /kaggle/working/:')
for f in sorted(pathlib.Path('/kaggle/working/').iterdir()):
    if f.name == 'hf-cache': continue   # don't list the model cache
    print(' ', f.name, f.stat().st_size if f.is_file() else '<dir>')
""".strip()),

        cell_md(f"""\
## Done

Download `adapter_kaggle{shard + 1}.zip` from the **Output** tab on the
right.  Repeat for the other two shards (notebooks 2 and 3), then on your
laptop run:

```powershell
python scripts/merge_lora_adapters.py `
    --inputs ./adapter_kaggle1 ./adapter_kaggle2 ./adapter_kaggle3 `
    --output ./adapter_merged
```

The merged adapter loads with the standard `peft` API on top of
`Qwen/Qwen2.5-1.5B-Instruct`.
"""),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3",
                           "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
            "kaggle": {"accelerator": "nvidiaTeslaT4",
                       "dataSources": [],
                       "isInternetEnabled": True,
                       "language": "python",
                       "sourceType": "notebook"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    for shard in range(3):
        nb = build(shard)
        path = NOTEBOOK_DIR / f"kaggle_train_shard{shard + 1}.ipynb"
        path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
