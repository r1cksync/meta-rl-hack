# Creates a clean project-local venv so the training installs DON'T conflict
# with the user's global Python (medrax / gradio / tensorflow-intel etc.).
#
# Usage:  .\scripts\setup_venv.ps1
# After:  .\.venv\Scripts\Activate.ps1
param([string]$Path = ".venv", [switch]$Train)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $Path))) {
    Write-Host "==> Creating venv at $Path" -ForegroundColor Cyan
    python -m venv (Join-Path $RepoRoot $Path)
}

$py  = Join-Path $RepoRoot "$Path\Scripts\python.exe"
$pip = Join-Path $RepoRoot "$Path\Scripts\pip.exe"
& $py -m pip install --upgrade pip | Out-Host

Write-Host "==> Installing server deps" -ForegroundColor Cyan
& $pip install -r (Join-Path $RepoRoot "rl-agent\requirements.txt") | Out-Host

if ($Train) {
    Write-Host "==> Installing training deps (torch, peft, transformers, ...)" -ForegroundColor Cyan
    & $pip install -r (Join-Path $RepoRoot "rl-agent\requirements-train.txt") | Out-Host
}

Write-Host ""
Write-Host "✔ venv ready." -ForegroundColor Green
Write-Host "  Activate with:  .\$Path\Scripts\Activate.ps1"
Write-Host "  Run server:     python -m uvicorn server:app --host 127.0.0.1 --port 7860"
