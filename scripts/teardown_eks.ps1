param(
    [string]$ClusterName = "incident-commander",
    [string]$Region      = "us-east-1",
    [switch]$KeepBucket,
    [string]$BucketName  = ""
)
$ErrorActionPreference = "Stop"
Write-Host "==> Deleting EKS cluster '$ClusterName' (~10 min)" -ForegroundColor Cyan
eksctl delete cluster --name $ClusterName --region $Region --wait

if (-not $KeepBucket) {
    if ([string]::IsNullOrEmpty($BucketName)) {
        $acct = (aws sts get-caller-identity --query Account --output text)
        $BucketName = "ic-checkpoints-$acct-$Region".ToLower()
    }
    Write-Host "==> Emptying + deleting S3 bucket s3://$BucketName" -ForegroundColor Cyan
    aws s3 rm "s3://$BucketName" --recursive 2>$null | Out-Null
    aws s3api delete-bucket --bucket $BucketName --region $Region 2>$null | Out-Null
}
Write-Host "✔ Done. Verify in the AWS console that no EC2 / NAT / LB is left." -ForegroundColor Green
