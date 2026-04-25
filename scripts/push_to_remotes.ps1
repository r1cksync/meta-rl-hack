# Push IncidentCommander to GitHub + Hugging Face.
#
# Usage:
#   1. Set GitHub remote + HF user once:
#        $env:IC_GIT_REMOTE = "https://github.com/<you>/incident-commander.git"
#        $env:IC_HF_USER    = "<your-hf-username>"
#        $env:HF_TOKEN      = "hf_..."   # write-scope
#   2. Run this script from the repo root:
#        ./scripts/push_to_remotes.ps1
#
# What it does:
#   * Initializes git if needed, creates main branch, writes .gitignore.
#   * Adds the remote and pushes everything to GitHub.
#   * Creates a HF *Space* (Streamlit) at  <user>/incident-commander  and
#     pushes the same tree there (HF Spaces are nothing more than git repos).
#   * Creates a HF *dataset* repo  <user>/incident-commander-scenarios
#     and uploads rl-agent/scenarios/*.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# ── 1. .gitignore ─────────────────────────────────────────────────────
$gi = ".gitignore"
if (-not (Test-Path $gi)) {
@"
__pycache__/
*.pyc
*.pyo
.venv/
.env
.env.local
node_modules/
.next/
out/
dist/
build/
*.zip
colab/logs/adapter_*/
rl-agent/replays/*.html
.DS_Store
"@ | Set-Content $gi
    Write-Host "Wrote .gitignore"
}

# ── 2. git init + commit ─────────────────────────────────────────────
if (-not (Test-Path ".git")) {
    git init -b main | Out-Null
    Write-Host "Initialized git repo"
}
git add -A
$diff = git diff --cached --name-only
if ($diff) {
    git commit -m "feat: phase8-10 saboteur+slack+replay+colab+381 scenarios" | Out-Null
    Write-Host "Committed staged changes"
} else {
    Write-Host "Nothing to commit"
}

# ── 3. GitHub push ───────────────────────────────────────────────────
if ($env:IC_GIT_REMOTE) {
    $remotes = git remote
    if (-not ($remotes -contains "origin")) {
        git remote add origin $env:IC_GIT_REMOTE
    } else {
        git remote set-url origin $env:IC_GIT_REMOTE
    }
    Write-Host "Pushing to GitHub: $env:IC_GIT_REMOTE"
    git push -u origin main
} else {
    Write-Warning "IC_GIT_REMOTE not set — skipping GitHub push."
}

# ── 4. Hugging Face push ─────────────────────────────────────────────
if (-not $env:IC_HF_USER -or -not $env:HF_TOKEN) {
    Write-Warning "IC_HF_USER or HF_TOKEN missing — skipping HF push."
    exit 0
}

python scripts/push_to_hf.py
