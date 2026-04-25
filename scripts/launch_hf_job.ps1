# One-line launcher for the HF Jobs training run.
#
# Usage:
#   $env:HF_TOKEN     = "hf_..."           # required
#   $env:IC_PUSH_USER = "sagnik-mukherjee" # required if you want checkpoints pushed
#   ./scripts/launch_hf_job.ps1            # uses defaults (l4x1, 120 updates, 6 rollouts)
#
# Optional overrides:
#   $env:IC_GPU_FLAVOR    = "a10g-large"   # default l4x1
#   $env:IC_TOTAL_UPDATES = 200            # default 120
#   $env:IC_REPO_URL      = "https://github.com/<you>/<repo>.git"

$ErrorActionPreference = "Stop"

if (-not $env:HF_TOKEN)     { throw "HF_TOKEN env var is required." }
if (-not $env:IC_PUSH_USER) { Write-Warning "IC_PUSH_USER not set — checkpoints WILL NOT be pushed." }

$flavor   = if ($env:IC_GPU_FLAVOR)    { $env:IC_GPU_FLAVOR }    else { "l4x1" }
$updates  = if ($env:IC_TOTAL_UPDATES) { $env:IC_TOTAL_UPDATES } else { "120" }
$rollouts = if ($env:IC_ROLLOUTS)      { $env:IC_ROLLOUTS }      else { "6" }
$repo     = if ($env:IC_REPO_URL)      { $env:IC_REPO_URL }      else { "https://github.com/r1cksync/meta-rl-hack.git" }
$run      = if ($env:IC_RUN_NAME)      { $env:IC_RUN_NAME }      else { "hfjob_$(Get-Date -Format yyyyMMdd_HHmm)" }

Write-Host "Launching HF Job:"
Write-Host "  GPU flavor : $flavor"
Write-Host "  Run name   : $run"
Write-Host "  Updates    : $updates × $rollouts rollouts"
Write-Host "  Repo       : $repo"
Write-Host "  Push user  : $($env:IC_PUSH_USER)"

$cmd = @(
    "git clone --depth 1 `$IC_REPO_URL /workspace/ic",
    "cd /workspace/ic",
    "bash scripts/hf_job_entrypoint.sh"
) -join " && "

hf jobs run `
    --flavor $flavor `
    --secret "HF_TOKEN=$env:HF_TOKEN" `
    --env   "IC_PUSH_USER=$env:IC_PUSH_USER" `
    --env   "IC_REPO_URL=$repo" `
    --env   "IC_TOTAL_UPDATES=$updates" `
    --env   "IC_ROLLOUTS=$rollouts" `
    --env   "IC_RUN_NAME=$run" `
    --env   "HF_HUB_ENABLE_HF_TRANSFER=1" `
    --image "huggingface/transformers-pytorch-gpu:latest" `
    -- bash -c "$cmd"
