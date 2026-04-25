# Phase 3 — Polish pass on the HARD tier (sim_hard_* + sim_advanced_*) with
# the strong Qwen-72B critic. Warm-starts from phase-2's adapter. Run on X2-0.
#
# Usage:
#   $env:HF_TOKEN_C = "hf_..."   # X2-0's token
#   ./scripts/launch_phase3.ps1

$ErrorActionPreference = "Stop"
if (-not $env:HF_TOKEN_C) { throw "HF_TOKEN_C (X2-0's token) is required." }

$flavor   = "l4x1"
$updates  = "300"
$rollouts = "6"
$run      = "phase3_polish"
$repo     = "https://github.com/r1cksync/meta-rl-hack.git"

Write-Host "Phase 3: HARD 35 tasks, $updates x $rollouts, Qwen2.5-72B critic"
Write-Host "  Account     : X2-0"
Write-Host "  Warm-start  : Shubhang3011/incident-commander-actor (phase 2)"
Write-Host "  Push target : X2-0/incident-commander-actor"

$cmd = 'git clone --depth 1 $IC_REPO_URL /workspace/ic && cd /workspace/ic && bash scripts/hf_job_entrypoint.sh'

hf jobs run -d `
    --flavor $flavor `
    --secrets "HF_TOKEN=$env:HF_TOKEN_C" `
    --env   "IC_PUSH_USER=X2-0" `
    --env   "IC_REPO_URL=$repo" `
    --env   "IC_TOTAL_UPDATES=$updates" `
    --env   "IC_ROLLOUTS=$rollouts" `
    --env   "IC_RUN_NAME=$run" `
    --env   "IC_TASK_MODE=hard" `
    --env   "IC_CRITIC_MODEL=Qwen/Qwen2.5-72B-Instruct" `
    --env   "IC_INIT_ADAPTER_REPO=Shubhang3011/incident-commander-actor" `
    --env   "IC_INIT_ADAPTER_SUBFOLDER=adapter" `
    --env   "HF_HUB_ENABLE_HF_TRANSFER=1" `
    --timeout 4h `
    "huggingface/transformers-pytorch-gpu:latest" `
    -- bash -c $cmd
