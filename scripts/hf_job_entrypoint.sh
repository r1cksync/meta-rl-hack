#!/usr/bin/env bash
# HF Jobs entrypoint. Clones the repo, installs deps, runs the real training.
# Invoked by `hf jobs run` — see scripts/HF_JOBS.md for the exact command.
set -euo pipefail

REPO_URL="${IC_REPO_URL:-https://github.com/r1cksync/meta-rl-hack.git}"
WORK="/workspace/incident-commander"

echo "[hfjob] === stage 1: clone ==="
git clone --depth 1 "$REPO_URL" "$WORK"
cd "$WORK"

echo "[hfjob] === stage 2: install ==="
python -m pip install -q --upgrade pip
python -m pip install -q --no-deps \
    "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
python -m pip install -q --no-deps \
    "xformers<0.0.27" trl peft accelerate bitsandbytes
python -m pip install -q "huggingface_hub>=0.25" "pydantic>=2,<3" httpx

echo "[hfjob] === stage 3: train ==="
python scripts/run_training.py

echo "[hfjob] === stage 4: artifacts ==="
ls -la colab/logs/ || true
ls -la rl-agent/replays/ || true
