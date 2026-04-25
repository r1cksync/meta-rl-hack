"""Non-notebook entrypoint for the IncidentCommander RL training run.

Designed to be invoked by `hf jobs run` (or any plain `python` shell). Reads
configuration from env vars so the same script works in Colab, HF Jobs, and
local docker.

Required env vars:
    HF_TOKEN              - HF token with Read scope (Write if pushing adapters)

Optional env vars:
    IC_TOTAL_UPDATES      - default 120
    IC_ROLLOUTS           - default 6
    IC_MAX_STEPS          - default 16
    IC_RUN_NAME           - default "hfjob01"
    IC_PUSH_USER          - if set, pushes adapter+logs to <user>/incident-commander-actor
    IC_CRITIC_MODEL       - default "Qwen/Qwen2.5-72B-Instruct"
"""
from __future__ import annotations

import logging
import os
import sys
import warnings
from pathlib import Path

# Silence the noisy Qwen FutureWarning before importing transformers.
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
warnings.filterwarnings("ignore", message=".*max_new_tokens.*max_length.*")
warnings.filterwarnings("ignore", message=".*attention mask API.*")
logging.getLogger("transformers").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rl-agent"))

# Mock AWS so the simulator runs without boto3 creds.
os.environ.setdefault("INCIDENT_COMMANDER_MOCK", "true")

if not os.environ.get("HF_TOKEN"):
    sys.exit("HF_TOKEN env var is required.")
os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", os.environ["HF_TOKEN"])

from huggingface_hub import login, whoami                       # noqa: E402
login(os.environ["HF_TOKEN"], add_to_git_credential=False)
print(f"[hfjob] logged in as {whoami(token=os.environ['HF_TOKEN']).get('name')}")

from colab.train_lib import CFG, train_loop                     # noqa: E402

# ── Task list selection ────────────────────────────────────────────────
import glob as _glob
import json as _json

TASK_MODE = os.environ.get("IC_TASK_MODE", "curated").lower()
_SCEN_ROOT = ROOT / "rl-agent" / "scenarios" / "sim"

_CURATED = [
    "sim_easy_lambda_throttle_001", "sim_easy_lambda_throttle_010",
    "sim_med_eb_lambda_016",       "sim_med_eb_lambda_021",
    "sim_hard_apigw_chain_001",    "sim_hard_ddb_chain_021",
    "sim_hard_iam_chain_011",
    "sim_advanced_cascade_users_db_001",
    "sim_advanced_runbook_trap_postgres_001",
    "sim_advanced_trolley_orders_db_001",
    "sim_advanced_saboteur_duel_001",
    "sim_advanced_slack_redherring_001",
    "sim_gen_app_leak_checkout_007",   "sim_gen_app_leak_payments_019",
    "sim_gen_db_duel_users_db_003",    "sim_gen_db_duel_orders_db_015",
    "sim_gen_redherring_payments_013", "sim_gen_redherring_auth_001",
    "sim_gen_cascade_payments_db_004", "sim_gen_cascade_users_db_023",
    "sim_gen_cache_warm_session_cache_004",
    "sim_gen_peak_frontend_001",
    "sim_gen_restore_payments_db_001",
]

def _discover_all_task_ids():
    ids = []
    for p in _glob.glob(str(_SCEN_ROOT / "**" / "*.json"), recursive=True):
        try:
            data = _json.loads(open(p, encoding="utf-8").read())
            tid = data.get("task_id") or data.get("id")
            if tid:
                ids.append(tid)
        except Exception:                                       # noqa: BLE001
            pass
    return sorted(set(ids))

if TASK_MODE == "all":
    tasks = _discover_all_task_ids()
elif TASK_MODE == "hard":
    tasks = [t for t in _discover_all_task_ids()
             if t.startswith("sim_hard_") or t.startswith("sim_advanced_")]
else:
    tasks = _CURATED

# Optional sharding: take every Nth task starting at SHARD index. Used for
# splitting the corpus across parallel Kaggle notebooks (no warm-start needed
# between them; outputs can be averaged at the end).
_n_shards = int(os.environ.get("IC_TASK_SHARDS", 1))
_shard    = int(os.environ.get("IC_TASK_SHARD", 0))
if _n_shards > 1:
    tasks = [t for i, t in enumerate(tasks) if i % _n_shards == _shard]
    print(f"[hfjob] sharded {_shard}/{_n_shards} → {len(tasks)} tasks")

print(f"[hfjob] task_mode={TASK_MODE}  count={len(tasks)}")

# ── Optional warm-start from a prior phase's HF model repo ─────────────
init_repo = os.environ.get("IC_INIT_ADAPTER_REPO", "").strip()
init_subfolder = os.environ.get("IC_INIT_ADAPTER_SUBFOLDER", "adapter").strip()
init_path = None
if init_repo:
    print(f"[hfjob] warm-start: downloading {init_repo}/{init_subfolder} ...")
    from huggingface_hub import snapshot_download
    local_dir = snapshot_download(
        repo_id=init_repo, repo_type="model",
        allow_patterns=[f"{init_subfolder}/*"],
    )
    init_path = str(Path(local_dir) / init_subfolder)
    print(f"[hfjob] warm-start adapter at {init_path}")

CFG.update({
    "total_updates":       int(os.environ.get("IC_TOTAL_UPDATES", 120)),
    "rollouts_per_update": int(os.environ.get("IC_ROLLOUTS", 6)),
    "max_steps_per_ep":    int(os.environ.get("IC_MAX_STEPS", 16)),
    "checkpoint_every":    int(os.environ.get("IC_CKPT_EVERY", 20)),
    "actor_model":         os.environ.get("IC_ACTOR_MODEL",
                                          CFG.get("actor_model")),
    "critic_provider":     os.environ.get("IC_CRITIC_PROVIDER", "hf"),
    "critic_model":        os.environ.get("IC_CRITIC_MODEL",
                                          "Qwen/Qwen2.5-72B-Instruct"),
    "lr":                  1e-5,
    "kl_coef":             0.02,
    "clip_eps":            0.20,
    "gae_lambda":          0.92,
    "run_name":            os.environ.get("IC_RUN_NAME", "hfjob01"),
    "tasks":               tasks,
    "init_adapter_path":   init_path,
})

print(f"[hfjob] starting run '{CFG['run_name']}': "
      f"{CFG['total_updates']}×{CFG['rollouts_per_update']}×{CFG['max_steps_per_ep']} "
      f"(~{CFG['total_updates'] * CFG['rollouts_per_update'] * CFG['max_steps_per_ep']:,} transitions)")

log_path = train_loop()
print(f"[hfjob] training log → {log_path}")

# ── Optional: push artifacts to a HF model repo ─────────────────────────
push_user = os.environ.get("IC_PUSH_USER", "").strip()
if push_user:
    import glob
    from huggingface_hub import HfApi, create_repo
    api  = HfApi(token=os.environ["HF_TOKEN"])
    repo = f"{push_user}/incident-commander-actor"
    create_repo(repo, exist_ok=True, repo_type="model",
                token=os.environ["HF_TOKEN"])
    finals = sorted(glob.glob(str(ROOT / "colab" / "logs" / "adapter_*_final")))
    if finals:
        api.upload_folder(folder_path=finals[-1], repo_id=repo,
                          repo_type="model", path_in_repo="adapter")
    api.upload_folder(folder_path=str(ROOT / "colab" / "logs"),
                      repo_id=repo, repo_type="model", path_in_repo="logs",
                      allow_patterns=["*.json"])
    replay_dir = ROOT / "rl-agent" / "replays"
    if replay_dir.exists():
        api.upload_folder(folder_path=str(replay_dir), repo_id=repo,
                          repo_type="model", path_in_repo="replays",
                          allow_patterns=["*.html"])
    print(f"[hfjob] pushed → https://huggingface.co/{repo}")
else:
    print("[hfjob] IC_PUSH_USER not set — skipping HF push.")

print("[hfjob] done.")
