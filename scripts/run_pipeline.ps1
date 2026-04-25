# 3-account, 3-phase training pipeline ($90 total budget)
#
# Phase 1 — sagnik-mukherjee   ($30) — curated 23 tasks   72B critic   ~$15
# Phase 2 — Shubhang3011       ($30) — ALL 381 tasks       7B critic   ~$10
# Phase 3 — X2-0               ($30) — HARD 35 tasks      72B critic   ~$22
#
# Each phase warm-starts from the previous phase's adapter on HF Hub.
# Phases must run SEQUENTIALLY — phase N+1 needs phase N's checkpoint.

# Set tokens once (replace with your actual values):
#   $env:HF_TOKEN_A = "hf_..."   # sagnik-mukherjee  (already used for phase 1)
#   $env:HF_TOKEN_B = "hf_..."   # Shubhang3011
#   $env:HF_TOKEN_C = "hf_..."   # X2-0

param(
    [switch]$SkipPhase1,
    [switch]$SkipPhase2,
    [switch]$SkipPhase3
)
$ErrorActionPreference = "Stop"

function Wait-Job($id) {
    Write-Host ">>> Waiting for job $id to finish..."
    while ($true) {
        $j = hf jobs inspect $id 2>&1 | ConvertFrom-Json
        $stage = $j[0].status.stage
        Write-Host "    [$id] stage=$stage"
        if ($stage -in @("COMPLETED", "ERROR", "CANCELED", "DELETED")) {
            return $stage
        }
        Start-Sleep -Seconds 60
    }
}

# ── Phase 1 ────────────────────────────────────────────────────────────
if (-not $SkipPhase1) {
    if (-not $env:HF_TOKEN_A) { throw "HF_TOKEN_A required." }
    $env:HF_TOKEN     = $env:HF_TOKEN_A
    $env:IC_PUSH_USER = "sagnik-mukherjee"
    $env:IC_RUN_NAME  = "phase1_foundation"
    $p1 = (./scripts/launch_hf_job.ps1 | Select-String 'Job started with ID:').ToString().Split(":")[-1].Trim()
    Write-Host "Phase 1 submitted: $p1"
    if ((Wait-Job $p1) -ne "COMPLETED") { throw "Phase 1 did not complete cleanly." }
}

# ── Phase 2 ────────────────────────────────────────────────────────────
if (-not $SkipPhase2) {
    if (-not $env:HF_TOKEN_B) { throw "HF_TOKEN_B required." }
    $p2 = (./scripts/launch_phase2.ps1 | Select-String 'Job started with ID:').ToString().Split(":")[-1].Trim()
    Write-Host "Phase 2 submitted: $p2"
    if ((Wait-Job $p2) -ne "COMPLETED") { throw "Phase 2 did not complete cleanly." }
}

# ── Phase 3 ────────────────────────────────────────────────────────────
if (-not $SkipPhase3) {
    if (-not $env:HF_TOKEN_C) { throw "HF_TOKEN_C required." }
    $p3 = (./scripts/launch_phase3.ps1 | Select-String 'Job started with ID:').ToString().Split(":")[-1].Trim()
    Write-Host "Phase 3 submitted: $p3"
    if ((Wait-Job $p3) -ne "COMPLETED") { throw "Phase 3 did not complete cleanly." }
}

Write-Host ""
Write-Host "ALL PHASES COMPLETE. Final adapter:"
Write-Host "  https://huggingface.co/X2-0/incident-commander-actor"
