"""Download the latest checkpoint from the HF Hub model repo.

Use this if your HF Jobs run died mid-way and you want the most recent
adapter on your laptop.

    python scripts/download_latest_ckpt.py --user sagnik-mukherjee
                                            --run  hfjob01
                                            --out  ./resume
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True,
                    help="HF username (e.g. sagnik-mukherjee)")
    ap.add_argument("--run",  default=None,
                    help="Run name (e.g. hfjob01). If omitted, picks latest.")
    ap.add_argument("--out",  default="./resume",
                    help="Local directory to write the adapter into.")
    ap.add_argument("--prefer-final", action="store_true",
                    help="Pick *_final if present, else newest u#### dir.")
    args = ap.parse_args()

    if not os.environ.get("HF_TOKEN"):
        sys.exit("HF_TOKEN env var required.")

    from huggingface_hub import HfApi, snapshot_download

    repo = f"{args.user}/incident-commander-actor"
    api  = HfApi(token=os.environ["HF_TOKEN"])
    print(f"Listing files in {repo} …")
    files = api.list_repo_files(repo, repo_type="model")

    # Top-level checkpoint dirs look like  adapter_<run>_u0040/...  or
    #                                       adapter_<run>_final/...
    prefix = "adapter_"
    if args.run:
        prefix = f"adapter_{args.run}_"
    candidates = sorted({f.split("/")[0] for f in files
                         if f.startswith(prefix)})
    if not candidates:
        sys.exit(f"No checkpoint dirs found under prefix '{prefix}*'.")

    if args.prefer_final and any(c.endswith("_final") for c in candidates):
        chosen = [c for c in candidates if c.endswith("_final")][-1]
    else:
        # Sort so u0120 > u0100 > _final lexically — pick the lexicographically
        # largest, which works because u#### are zero-padded.
        chosen = candidates[-1]

    out = Path(args.out) / chosen
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {chosen} → {out}")
    snapshot_download(
        repo_id=repo, repo_type="model",
        allow_patterns=[f"{chosen}/*"],
        local_dir=str(Path(args.out)),
        token=os.environ["HF_TOKEN"],
    )
    print(f"Done. Adapter at: {out}")


if __name__ == "__main__":
    main()
