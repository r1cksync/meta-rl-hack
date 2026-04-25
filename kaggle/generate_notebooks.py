"""Generate the 3 Kaggle notebooks for sharded IncidentCommander training.

Each notebook is identical except for the IC_TASK_SHARD value (0/1/2) and
the run_name. Re-run this script if you want to tweak the template.
"""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK_DIR = Path(__file__).resolve().parent

# Kaggle Models mount paths (read-only, mounted at /kaggle/input/, do NOT
# consume the 20 GB /kaggle/working/ quota). Exact paths the user pinned:
#
#   Actor : /kaggle/input/models/Microsoft/phi-3/pytorch/phi-3.5-mini-instruct/2
#   Critic: /kaggle/input/models/deepseek-ai/deepseek-r1-0528/transformers/deepseek-r1-0528-qwen3-8b/1
#
# In the Kaggle notebook sidebar ("+ Add Input" → Models):
#   • search `phi-3`         → publisher Microsoft  → framework PyTorch       → variation `phi-3.5-mini-instruct`        → version 2  → Add
#   • search `deepseek-r1`   → publisher deepseek-ai → framework Transformers  → variation `deepseek-r1-0528-qwen3-8b`     → version 1  → Add
ACTOR_PATH_LITERAL  = "/kaggle/input/models/Microsoft/phi-3/pytorch/phi-3.5-mini-instruct/2"
CRITIC_PATH_LITERAL = "/kaggle/input/models/deepseek-ai/deepseek-r1-0528/transformers/deepseek-r1-0528-qwen3-8b/1"

ACTOR_NAME  = "microsoft/Phi-3.5-mini-instruct"
CRITIC_NAME = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"

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
(~127 of 381 scenarios). Trains a LoRA on **{ACTOR_NAME}** using a local
**{CRITIC_NAME}** critic — both attached as Kaggle Models so they live in
the read-only `/kaggle/input/` mount and DO NOT eat the 20 GB working quota.

**REQUIRED — attach these 2 Kaggle Models before running** (right sidebar →
`+ Add Input` → `Models` tab). Both are open / no access request:
1.  `Microsoft / phi-3`        → framework `PyTorch`       → variation `phi-3.5-mini-instruct`     → version `2`
2.  `deepseek-ai / deepseek-r1-0528` → framework `Transformers` → variation `deepseek-r1-0528-qwen3-8b` → version `1`

Expected mount paths after attach (cell 3 verifies):
- `{ACTOR_PATH_LITERAL}`
- `{CRITIC_PATH_LITERAL}`

**Required notebook settings** (right-hand sidebar):
- Accelerator: `GPU T4 x2` or `GPU P100`
- Persistence: `Files only`
- Internet: `On` (for `git clone` and optional HF Hub upload)

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

        cell_md("## 3. Resolve attached Kaggle Models (read-only, no download)"),
        cell_code(f"""\
import os, pathlib

ACTOR_PATH  = '{ACTOR_PATH_LITERAL}'
CRITIC_PATH = '{CRITIC_PATH_LITERAL}'

def verify(path, label):
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(
            f'{{label}} not found at {{path}}. Open the right sidebar → '
            f'"+ Add Input" → Models → attach the model with the matching '
            f'publisher/framework/variation/version (see the markdown above).')
    has_weights = any(p.glob('*.safetensors')) or any(p.glob('*.bin'))
    if not has_weights:
        raise SystemExit(f'{{label}} found at {{path}} but no *.safetensors / *.bin inside.')
    print(f'{{label}}: OK  →  {{path}}')

verify(ACTOR_PATH,  'actor  (Phi-3.5-mini-instruct)')
verify(CRITIC_PATH, 'critic (DeepSeek-R1-0528-Qwen3-8B)')

# Push HF Hub cache out of /kaggle/working so an accidental snapshot_download
# (e.g. by a tokenizer) writes to /tmp instead of eating the 20 GB quota.
os.environ['HF_HOME']              = '/tmp/hf-cache'
os.environ['HUGGINGFACE_HUB_CACHE'] = '/tmp/hf-cache'
os.environ['TRANSFORMERS_CACHE']   = '/tmp/hf-cache'
pathlib.Path('/tmp/hf-cache').mkdir(parents=True, exist_ok=True)

# Optional HF_TOKEN — only used if you want to upload checkpoints.
try:
    from kaggle_secrets import UserSecretsClient
    os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
    print('HF_TOKEN attached from Kaggle Secrets')
except Exception:
    print('No HF_TOKEN — that is fine, training works fully offline now.')

# Trust remote code is required for DeepSeek-R1-Qwen3 architecture.
os.environ['TRANSFORMERS_TRUST_REMOTE_CODE'] = '1'
""".strip()),

        cell_md("## 4. Clone the repo (public GitHub) — always pull latest"),
        cell_code(f"""\
import os, subprocess, pathlib, shutil
WORK = '/kaggle/working/incident-commander'
p = pathlib.Path(WORK)
if p.exists():
    # Wipe any stale clone from a previous session so we always get the
    # newest scripts/run_training.py + colab/train_lib.py from main.
    shutil.rmtree(WORK)
subprocess.run(['git', 'clone', '--depth', '1',
                '{REPO_URL}', WORK], check=True)
os.chdir(WORK)
# Show the commit we are running so it is obvious in the logs.
subprocess.run(['git', '-C', WORK, 'log', '-1', '--oneline'], check=False)
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
`{ACTOR_NAME}`.
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
