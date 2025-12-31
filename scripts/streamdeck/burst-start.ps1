# Stream Deck - Burst Mode Start
# Demarre l'infrastructure EC2 Spot pour le mode Burst

$ErrorActionPreference = "Stop"
Set-Location "C:\Projects\SAP_KB"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KNOWWHERE BURST MODE - DEMARRAGE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verifier les credentials AWS
Write-Host "[1/4] Verification credentials AWS..." -ForegroundColor Yellow
try {
    $identity = aws sts get-caller-identity --output json 2>$null | ConvertFrom-Json
    Write-Host "  Account: $($identity.Account)" -ForegroundColor Green
    Write-Host "  User: $($identity.Arn)" -ForegroundColor Green
} catch {
    Write-Host "  ERREUR: Credentials AWS non configures!" -ForegroundColor Red
    Write-Host "  Executez: aws configure" -ForegroundColor Yellow
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# Verifier qu'il n'y a pas deja une stack active
Write-Host ""
Write-Host "[2/4] Verification stacks existantes..." -ForegroundColor Yellow
$existingStacks = aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE CREATE_IN_PROGRESS --query "StackSummaries[?contains(StackName,'burst')].[StackName,StackStatus]" --output text 2>$null

if ($existingStacks) {
    Write-Host "  ATTENTION: Stack(s) Burst deja active(s)!" -ForegroundColor Red
    Write-Host $existingStacks -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Voulez-vous continuer quand meme? (o/N)"
    if ($confirm -ne "o" -and $confirm -ne "O") {
        Write-Host "Abandon." -ForegroundColor Yellow
        Read-Host "Appuyez sur Entree pour fermer"
        exit 0
    }
}

# Verifier que le backend est accessible
Write-Host ""
Write-Host "[3/4] Verification backend KnowWhere..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/status" -Method Get -TimeoutSec 5
    Write-Host "  Backend: OK" -ForegroundColor Green
} catch {
    Write-Host "  ERREUR: Backend non accessible sur localhost:8000" -ForegroundColor Red
    Write-Host "  Demarrez d'abord les services: ./kw.ps1 start" -ForegroundColor Yellow
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# Lancer le mode Burst via l'API
Write-Host ""
Write-Host "[4/4] Lancement infrastructure Burst..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Cette operation peut prendre 5-10 minutes:" -ForegroundColor Cyan
Write-Host "    - Creation stack CloudFormation" -ForegroundColor Gray
Write-Host "    - Allocation instance Spot" -ForegroundColor Gray
Write-Host "    - Demarrage vLLM + Embeddings" -ForegroundColor Gray
Write-Host ""

# Obtenir un token admin (si auth activee)
$headers = @{
    "Content-Type" = "application/json"
}

# Ajouter le token si disponible
$envToken = $env:KNOWWHERE_ADMIN_TOKEN
if ($envToken) {
    $headers["Authorization"] = "Bearer $envToken"
}

try {
    # Etape 1: Preparer le batch (scan data/burst/pending)
    Write-Host "  Preparation du batch..." -ForegroundColor Yellow
    $prepareBody = @{} | ConvertTo-Json
    $prepareResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/burst/prepare" -Method Post -Headers $headers -Body $prepareBody -TimeoutSec 30

    if (-not $prepareResponse.success) {
        Write-Host "  ERREUR: $($prepareResponse.message)" -ForegroundColor Red
        Read-Host "Appuyez sur Entree pour fermer"
        exit 1
    }

    Write-Host "  Batch prepare: $($prepareResponse.documents_count) documents" -ForegroundColor Green
    Write-Host "  Batch ID: $($prepareResponse.batch_id)" -ForegroundColor Cyan

    # Etape 2: Demarrer l'infrastructure
    Write-Host ""
    Write-Host "  Demarrage infrastructure EC2 Spot..." -ForegroundColor Yellow
    $startBody = @{ force = $false } | ConvertTo-Json
    $startResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/burst/start" -Method Post -Headers $headers -Body $startBody -TimeoutSec 600

    if (-not $startResponse.success) {
        Write-Host "  ERREUR: $($startResponse.message)" -ForegroundColor Red
        Read-Host "Appuyez sur Entree pour fermer"
        exit 1
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BURST MODE DEMARRE AVEC SUCCES!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Instance IP: $($startResponse.instance_ip)" -ForegroundColor Cyan
    Write-Host "  vLLM URL: $($startResponse.vllm_url)" -ForegroundColor Cyan
    Write-Host "  Embeddings URL: $($startResponse.embeddings_url)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Pour lancer le traitement:" -ForegroundColor Yellow
    Write-Host "    curl -X POST http://localhost:8000/api/burst/process" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Pour surveiller:" -ForegroundColor Yellow
    Write-Host "    curl http://localhost:8000/api/burst/status" -ForegroundColor Gray
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "  ERREUR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
}

Read-Host "Appuyez sur Entree pour fermer"
