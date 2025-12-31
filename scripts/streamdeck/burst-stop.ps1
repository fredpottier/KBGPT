# Stream Deck - Burst Mode Stop
# Arrete l'infrastructure EC2 Spot et nettoie les ressources AWS

$ErrorActionPreference = "Continue"
Set-Location "C:\Projects\SAP_KB"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KNOWWHERE BURST MODE - ARRET" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verifier les credentials AWS
Write-Host "[1/5] Verification credentials AWS..." -ForegroundColor Yellow
try {
    $identity = aws sts get-caller-identity --output json 2>$null | ConvertFrom-Json
    Write-Host "  Account: $($identity.Account)" -ForegroundColor Green
} catch {
    Write-Host "  ERREUR: Credentials AWS non configures!" -ForegroundColor Red
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# Essayer d'annuler via l'API (si backend accessible)
Write-Host ""
Write-Host "[2/5] Annulation via API..." -ForegroundColor Yellow
try {
    $headers = @{ "Content-Type" = "application/json" }
    $envToken = $env:KNOWWHERE_ADMIN_TOKEN
    if ($envToken) {
        $headers["Authorization"] = "Bearer $envToken"
    }

    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/burst/cancel" -Method Post -Headers $headers -TimeoutSec 30
    Write-Host "  API Cancel: $($response.message)" -ForegroundColor Green
} catch {
    Write-Host "  Backend non accessible, nettoyage direct AWS..." -ForegroundColor Yellow
}

# Terminer les instances EC2 Burst
Write-Host ""
Write-Host "[3/5] Arret instances EC2 Burst..." -ForegroundColor Yellow
$instances = aws ec2 describe-instances --filters "Name=tag:Name,Values=*burst*" "Name=instance-state-name,Values=pending,running,stopping,shutting-down" --query "Reservations[*].Instances[*].InstanceId" --output text 2>$null

if ($instances -and $instances.Trim()) {
    $instanceList = $instances.Trim() -split '\s+'
    foreach ($instanceId in $instanceList) {
        if ($instanceId) {
            Write-Host "  Terminating: $instanceId" -ForegroundColor Yellow
            aws ec2 terminate-instances --instance-ids $instanceId --output text 2>$null | Out-Null
        }
    }
    Write-Host "  $($instanceList.Count) instance(s) en cours d'arret" -ForegroundColor Green
} else {
    Write-Host "  Aucune instance Burst active" -ForegroundColor Gray
}

# Supprimer les stacks CloudFormation
Write-Host ""
Write-Host "[4/5] Suppression stacks CloudFormation..." -ForegroundColor Yellow
$stacks = aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE CREATE_IN_PROGRESS --query "StackSummaries[?contains(StackName,'burst')].StackName" --output text 2>$null

if ($stacks -and $stacks.Trim()) {
    $stackList = $stacks.Trim() -split '\s+'
    foreach ($stackName in $stackList) {
        if ($stackName) {
            Write-Host "  Deleting: $stackName" -ForegroundColor Yellow
            aws cloudformation delete-stack --stack-name $stackName 2>$null
        }
    }
    Write-Host "  $($stackList.Count) stack(s) en cours de suppression" -ForegroundColor Green
} else {
    Write-Host "  Aucune stack Burst active" -ForegroundColor Gray
}

# Verifier le statut final
Write-Host ""
Write-Host "[5/5] Verification finale..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

$remainingInstances = aws ec2 describe-instances --filters "Name=tag:Name,Values=*burst*" "Name=instance-state-name,Values=pending,running" --query "Reservations[*].Instances[*].InstanceId" --output text 2>$null
$remainingStacks = aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName,'burst')].StackName" --output text 2>$null

Write-Host ""
if ((-not $remainingInstances -or -not $remainingInstances.Trim()) -and (-not $remainingStacks -or -not $remainingStacks.Trim())) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BURST MODE ARRETE AVEC SUCCES!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Toutes les ressources AWS sont en cours" -ForegroundColor Green
    Write-Host "  de suppression ou deja supprimees." -ForegroundColor Green
} else {
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  ARRET EN COURS..." -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""
    if ($remainingInstances -and $remainingInstances.Trim()) {
        Write-Host "  Instances encore actives: $remainingInstances" -ForegroundColor Yellow
    }
    if ($remainingStacks -and $remainingStacks.Trim()) {
        Write-Host "  Stacks encore actives: $remainingStacks" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  La suppression complete peut prendre 1-2 min." -ForegroundColor Gray
}

Write-Host ""
Read-Host "Appuyez sur Entree pour fermer"
