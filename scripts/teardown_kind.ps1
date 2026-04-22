param([string]$ClusterName = "incident-commander")
kind delete cluster --name $ClusterName
Write-Host "✔ Cluster '$ClusterName' deleted" -ForegroundColor Green
