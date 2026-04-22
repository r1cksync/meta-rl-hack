# One-click local K8s cluster for IncidentCommander.
#
# Prereqs (install once):
#   - Docker Desktop running
#   - kind.exe   https://kind.sigs.k8s.io/
#   - kubectl.exe on PATH
#
# Usage:   .\scripts\setup_kind.ps1
#
# After this completes you can start the server with:
#   $env:REAL_K8S="true"
#   cd rl-agent
#   uvicorn server:app --port 7860

param(
    [string]$ClusterName = "incident-commander",
    [string]$KindImage   = "kindest/node:v1.30.4"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==> Checking prerequisites" -ForegroundColor Cyan
foreach ($bin in @("docker", "kind", "kubectl")) {
    if (-not (Get-Command $bin -ErrorAction SilentlyContinue)) {
        Write-Error "'$bin' not found on PATH. Install it and rerun."
    }
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Error "Docker daemon not reachable. Start Docker Desktop." }

$existing = (kind get clusters 2>$null) -split "`n"
if ($existing -contains $ClusterName) {
    Write-Host "==> Cluster '$ClusterName' already exists — reusing" -ForegroundColor Yellow
} else {
    Write-Host "==> Creating kind cluster '$ClusterName' ($KindImage)" -ForegroundColor Cyan
    kind create cluster --name $ClusterName --image $KindImage --wait 60s
}

kubectl cluster-info --context "kind-$ClusterName" | Out-Host

$manifestDir = Join-Path $RepoRoot "rl-agent\sample_app"
Write-Host "==> Applying namespaces" -ForegroundColor Cyan
kubectl apply -f (Join-Path $manifestDir "namespaces.yaml")

Write-Host "==> Applying base deployments" -ForegroundColor Cyan
kubectl apply -R -f (Join-Path $manifestDir "base")

Write-Host "==> Waiting for pods to become ready (this pulls images, ~60s)" -ForegroundColor Cyan
foreach ($ns in @("ic-payments", "ic-frontend", "ic-auth")) {
    kubectl -n $ns wait --for=condition=available --timeout=180s deployment --all
}

kubectl get pods -A | Out-Host

Write-Host ""
Write-Host "✔ Local K8s cluster ready." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  `$env:REAL_K8S='true'"
Write-Host "  cd rl-agent"
Write-Host "  uvicorn server:app --host 127.0.0.1 --port 7860"
Write-Host ""
Write-Host "Inject a fault for a quick test:"
Write-Host "  curl.exe -s -X POST http://localhost:7860/k8s/inject -H 'Content-Type: application/json' -d '{\`"fault_type\`":\`"oom_kill\`"}'"
Write-Host ""
Write-Host "Teardown:  .\scripts\teardown_kind.ps1"
