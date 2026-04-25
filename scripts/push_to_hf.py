"""Upload IncidentCommander artifacts to Hugging Face.

Required env vars:
    IC_HF_USER  - your HF username (e.g. "sara-sre")
    HF_TOKEN    - HF token with **write** scope

Creates / updates three repos under your account:
    1. <user>/incident-commander                (Space, gradio SDK)
    2. <user>/incident-commander-scenarios      (Dataset)
    3. <user>/incident-commander-actor          (Model — adapter + replays)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import HfApi, create_repo

USER  = os.environ.get("IC_HF_USER", "").strip()
TOKEN = os.environ.get("HF_TOKEN", "").strip()
if not USER or not TOKEN:
    sys.exit("Set IC_HF_USER and HF_TOKEN before running.")

ROOT = Path(__file__).resolve().parents[1]
api  = HfApi(token=TOKEN)


def _push_folder(folder: Path, repo: str, repo_type: str,
                 path_in_repo: str = ".",
                 allow_patterns: list[str] | None = None) -> None:
    if not folder.exists():
        print(f"  · skip {folder} (missing)")
        return
    create_repo(repo, exist_ok=True, repo_type=repo_type, token=TOKEN)
    print(f"  · uploading {folder}  →  {repo_type}://{repo}/{path_in_repo}")
    api.upload_folder(
        folder_path=str(folder),
        repo_id=repo,
        repo_type=repo_type,
        path_in_repo=path_in_repo,
        allow_patterns=allow_patterns,
        commit_message="sync from local",
    )


# 1. SPACE — full tree (Streamlit / Gradio SDK).
space_repo = f"{USER}/incident-commander"
print(f"[1/3] Space  →  {space_repo}")
create_repo(space_repo, exist_ok=True, repo_type="space",
            space_sdk="gradio", token=TOKEN)
api.upload_folder(
    folder_path=str(ROOT),
    repo_id=space_repo,
    repo_type="space",
    ignore_patterns=["__pycache__/*", "*.pyc", ".git/*", ".venv/*",
                     "node_modules/*", ".next/*", "out/*", "dist/*",
                     "build/*", "*.zip"],
    commit_message="phase8-10 sync",
)

# 2. DATASET — scenarios.
print(f"[2/3] Dataset  →  {USER}/incident-commander-scenarios")
_push_folder(ROOT / "rl-agent" / "scenarios",
             f"{USER}/incident-commander-scenarios",
             repo_type="dataset")

# 3. MODEL — adapter + replays + training logs.
model_repo = f"{USER}/incident-commander-actor"
print(f"[3/3] Model  →  {model_repo}")
create_repo(model_repo, exist_ok=True, repo_type="model", token=TOKEN)
finals = sorted((ROOT / "colab" / "logs").glob("adapter_*_final"))
if finals:
    _push_folder(finals[-1], model_repo, "model", path_in_repo="adapter")
_push_folder(ROOT / "colab" / "logs", model_repo, "model",
             path_in_repo="logs", allow_patterns=["*.json"])
_push_folder(ROOT / "rl-agent" / "replays", model_repo, "model",
             path_in_repo="replays", allow_patterns=["*.html"])

print("\nDone.")
print(f"  Space    https://huggingface.co/spaces/{space_repo}")
print(f"  Dataset  https://huggingface.co/datasets/{USER}/incident-commander-scenarios")
print(f"  Model    https://huggingface.co/{model_repo}")
