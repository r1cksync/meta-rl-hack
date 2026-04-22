# Loads a simple KEY=VALUE .env file into the current PowerShell session.
# Usage:  .\scripts\load_env.ps1 .env.aws.local
param([Parameter(Mandatory = $true)][string]$Path)
if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "Env file not found: $Path"
}
$count = 0
Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line -match '^\s*([^=]+?)\s*=\s*(.*)$') {
        $k = $matches[1].Trim()
        $v = $matches[2].Trim().Trim('"').Trim("'")
        Set-Item -Path "env:$k" -Value $v
        $count++
    }
}
Write-Host "✔ Loaded $count vars from $Path" -ForegroundColor Green
