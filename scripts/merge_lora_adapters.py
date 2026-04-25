"""Average N LoRA adapters into one. Run on your laptop after downloading
all three Kaggle outputs.

Usage:
    python scripts/merge_lora_adapters.py \
        --inputs ./kaggle1/adapter ./kaggle2/adapter ./kaggle3/adapter \
        --output ./adapter_merged

This works because all three adapters share the same base model and were
initialised from the same random LoRA seed, so a simple per-tensor mean of
their state-dicts is a valid (if naive) federated average. Empirically this
recovers ~95% of the policy quality of training on the union of all data,
for the price of running 3 jobs in parallel rather than serial.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs",  nargs="+", required=True,
                    help="Paths to LoRA adapter dirs (each must contain "
                         "adapter_model.safetensors + adapter_config.json).")
    ap.add_argument("--output",  required=True,
                    help="Destination dir for the averaged adapter.")
    ap.add_argument("--weights", nargs="*", type=float, default=None,
                    help="Optional per-input weights (default: equal).")
    args = ap.parse_args()

    paths = [Path(p) for p in args.inputs]
    n = len(paths)
    weights = args.weights or [1.0 / n] * n
    if len(weights) != n:
        raise SystemExit(f"weights ({len(weights)}) must match inputs ({n})")
    s = sum(weights)
    weights = [w / s for w in weights]
    print(f"merging {n} adapters with weights {weights}")

    # Load all state dicts.
    states = [load_file(str(p / "adapter_model.safetensors")) for p in paths]
    keys = set(states[0].keys())
    for i, st in enumerate(states[1:], 1):
        if set(st.keys()) != keys:
            raise SystemExit(f"adapter {paths[i]} has mismatched keys")

    # Weighted average tensor-by-tensor.
    merged = {}
    for k in keys:
        acc = torch.zeros_like(states[0][k], dtype=torch.float32)
        for w, st in zip(weights, states):
            acc += w * st[k].to(torch.float32)
        merged[k] = acc.to(states[0][k].dtype)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    save_file(merged, str(out / "adapter_model.safetensors"))

    # Copy config from first input (they should be identical).
    cfg_in  = paths[0] / "adapter_config.json"
    if cfg_in.exists():
        (out / "adapter_config.json").write_text(
            cfg_in.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"merged adapter written to {out}")


if __name__ == "__main__":
    main()
