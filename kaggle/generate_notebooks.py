"""Generate the 3 Kaggle notebooks for sharded IncidentCommander training.

Each notebook is identical except for the IC_TASK_SHARD value (0/1/2) and
the run_name. Re-run this script if you want to tweak the template.
"""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK_DIR = Path(__file__).resolve().parent

# Path on Kaggle where the actor base model + critic model are mounted.
# These are the standard Kaggle Models paths (user picks the version dropdown
# in the Add Data > Models flow). The notebook auto-discovers via glob.
ACTOR_GLOB  = "/kaggle/input/qwen-2.5/transformers/1.5b-instruct/*"
CRITIC_GLOB = "/kaggle/input/qwen-2.5/transformers/7b-instruct/*"

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
(~127 of 381 scenarios). Trains a LoRA on Qwen2.5-1.5B-Instruct using a
local Qwen2.5-7B-Instruct critic, both loaded from Kaggle Models inputs.

**Required Kaggle inputs** (Add Data → Models, then Datasets):
1. Model: `qwen-lm/qwen-2.5` → variation `1.5b-instruct` (the actor)
2. Model: `qwen-lm/qwen-2.5` → variation `7b-instruct` (the critic)

**Required notebook settings** (right-hand sidebar):
- Accelerator: `GPU T4 x2` or `GPU P100`
- Persistence: `Files only` (so `/kaggle/working/` survives restarts)
- Internet: `On` (needed to clone the public GitHub repo)

**Output:** `/kaggle/working/adapter_kaggle{shard + 1}.zip` — download from the
sidebar after the run finishes. Combine all 3 with
`scripts/merge_lora_adapters.py` on your laptop.
"""
    cells = [
        cell_md(title + "\n" + intro),

        cell_md("## 1. GPU + path sanity"),
        cell_code(f"""\
import os, glob, subprocess, sys, json, pathlib

print('--- GPU ---')
subprocess.run(['nvidia-smi', '-L'], check=False)

actor_dirs  = glob.glob('{ACTOR_GLOB}')
critic_dirs = glob.glob('{CRITIC_GLOB}')
assert actor_dirs,  'Actor model not attached. Add `qwen-lm/qwen-2.5 1.5b-instruct` via Add Data > Models.'
assert critic_dirs, 'Critic model not attached. Add `qwen-lm/qwen-2.5 7b-instruct` via Add Data > Models.'
ACTOR_PATH  = sorted(actor_dirs)[-1]   # latest version
CRITIC_PATH = sorted(critic_dirs)[-1]
print('actor :', ACTOR_PATH)
print('critic:', CRITIC_PATH)
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

        cell_md("## 3. Clone the repo (public GitHub)"),
        cell_code(f"""\
import os, subprocess, pathlib
WORK = '/kaggle/working/incident-commander'
if not pathlib.Path(WORK).exists():
    subprocess.run(['git', 'clone', '--depth', '1',
                    '{REPO_URL}', WORK], check=True)
os.chdir(WORK)
print('cwd =', os.getcwd())
""".strip()),

        cell_md("## 4. Configure run (shard, paths, env vars)"),
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

# HF_TOKEN is only needed if you want intermediate-checkpoint upload to a
# HF model repo. Otherwise leave unset and grab the final adapter from
# /kaggle/working/. Use Kaggle Secrets > Add-ons to inject it safely.
try:
    from kaggle_secrets import UserSecretsClient
    os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
    print('HF_TOKEN attached from Kaggle Secrets')
except Exception:
    print('HF_TOKEN not set — checkpoints stay local (download from sidebar).')

# Sanity: print actor + critic mode.
print('actor :', os.environ['IC_ACTOR_MODEL'])
print('critic:', os.environ['IC_CRITIC_MODEL'])
print('shard :', os.environ['IC_TASK_SHARD'], '/', os.environ['IC_TASK_SHARDS'])
""".strip()),

        cell_md("## 5. Train"),
        cell_code("""\
# The training script runs to completion. tqdm progress + ETA are streamed
# to stdout. Kaggle truncates very long outputs — adapter checkpoints are
# always written to /kaggle/working/incident-commander/colab/logs/ regardless.
import subprocess, sys
result = subprocess.run([sys.executable, 'scripts/run_training.py'],
                         check=False)
print('exit code:', result.returncode)
""".strip()),

        cell_md("## 6. Package outputs for download"),
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
    print(' ', f.name, f.stat().st_size)
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
