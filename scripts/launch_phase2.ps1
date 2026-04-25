# Phase 2 — Breadth pass over ALL 381 tasks with the cheap Qwen-7B critic.
# Warm-starts from phase-1's adapter. Run on Shubhang3011's HF account.
#
# Usage:
#   $env:HF_TOKEN_B = "hf_..."   # Shubhang3011's token
#   ./scripts/launch_phase2.ps1

$ErrorActionPreference = "Stop"
if (-not $env:HF_TOKEN_B) { throw "HF_TOKEN_B (Shubhang3011's token) is required." }

$flavor   = "l4x1"
$updates  = "600"
$rollouts = "6"
$run      = "phase2_breadth"
$repo     = "https://github.com/r1cksync/meta-rl-hack.git"

Write-Host "Phase 2: ALL 381 tasks, $updates x $rollouts, Qwen2.5-7B critic"
Write-Host "  Account     : Shubhang3011"
Write-Host "  Warm-start  : sagnik-mukherjee/incident-commander-actor (phase 1)"
Write-Host "  Push target : Shubhang3011/incident-commander-actor"

$cmd = 'git clone --depth 1 $IC_REPO_URL /workspace/ic && cd /workspace/ic && bash scripts/hf_job_entrypoint.sh'

hf jobs run -d `
    --flavor $flavor `
    --secrets "HF_TOKEN=$env:HF_TOKEN_B" `
    --env   "IC_PUSH_USER=Shubhang3011" `
    --env   "IC_REPO_URL=$repo" `
    --env   "IC_TOTAL_UPDATES=$updates" `
    --env   "IC_ROLLOUTS=$rollouts" `
    --env   "IC_RUN_NAME=$run" `
    --env   "IC_TASK_MODE=all" `
    --env   "IC_CRITIC_MODEL=Qwen/Qwen2.5-7B-Instruct" `
    --env   "IC_INIT_ADAPTER_REPO=sagnik-mukherjee/incident-commander-actor" `
    --env   "IC_INIT_ADAPTER_SUBFOLDER=adapter" `
    --env   "HF_HUB_ENABLE_HF_TRANSFER=1" `
    --timeout 4h `
    "huggingface/transformers-pytorch-gpu:latest" `
    -- bash -c $cmd
