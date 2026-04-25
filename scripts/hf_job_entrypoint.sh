#!/usr/bin/env bash
# HF Jobs entrypoint. Repo may already be cloned by the outer `hf jobs run`
# command into /workspace/ic; otherwise we clone it here.
set -euo pipefail

if [ -d "/workspace/ic" ]; then
    cd /workspace/ic
elif [ -d "/workspace/incident-commander" ]; then
    cd /workspace/incident-commander
else
    REPO_URL="${IC_REPO_URL:-https://github.com/r1cksync/meta-rl-hack.git}"
    git clone --depth 1 "$REPO_URL" /workspace/ic
    cd /workspace/ic
fi

# HF transformers image has python3 only; alias as needed.
if command -v python >/dev/null 2>&1; then
    PY=python
else
    PY=python3
fi
echo "[hfjob] interpreter: $($PY --version)"
echo "[hfjob] cwd: $(pwd)"

echo "[hfjob] === stage 2: install ==="
$PY -m pip install -q --upgrade pip
$PY -m pip install -q --no-deps \
    "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" || true
$PY -m pip install -q --no-deps \
    "xformers<0.0.27" trl peft accelerate bitsandbytes || true
$PY -m pip install -q "huggingface_hub>=0.25" "pydantic>=2,<3" httpx safetensors

echo "[hfjob] === stage 3: train ==="
$PY scripts/run_training.py

echo "[hfjob] === stage 4: artifacts ==="
ls -la colab/logs/ || true
ls -la rl-agent/replays/ || true
