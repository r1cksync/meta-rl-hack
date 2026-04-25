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
# Skip unsloth — its gemma3n torch.compile patch crashes on the image's torch
# build ("duplicate template name") and our QwenActor has a pure-HF fallback.
# Pin a known-compatible transformers + peft + bnb stack so peft doesn't try
# to import `transformers.conversion_mapping` (added only in transformers 4.50+).
$PY -m pip install -q \
    "transformers==4.46.3" \
    "peft==0.13.2" \
    "accelerate==1.1.1" \
    "bitsandbytes==0.44.1" \
    "trl==0.12.1" \
    "datasets" "sentencepiece" "protobuf" "hf_transfer" "safetensors"
$PY -m pip install -q "huggingface_hub>=0.25,<1.0" "pydantic>=2,<3" httpx
echo "[hfjob] installed: $($PY -c 'import transformers,peft,bitsandbytes,accelerate; print(\"transformers\",transformers.__version__,\"peft\",peft.__version__,\"bnb\",bitsandbytes.__version__,\"accel\",accelerate.__version__)')"

echo "[hfjob] === stage 3: train ==="
$PY scripts/run_training.py

echo "[hfjob] === stage 4: artifacts ==="
ls -la colab/logs/ || true
ls -la rl-agent/replays/ || true
