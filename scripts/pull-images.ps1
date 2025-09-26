# Script PowerShell pour récupérer les images depuis ECR
# Usage: .\scripts\pull-images.ps1

param(
    [string]$Region = "eu-west-1",
    [string]$Tag = "latest"
)

Write-Host "Recuperation des images Docker depuis ECR..." -ForegroundColor Green

# Récupérer l'Account ID
$identity = aws sts get-caller-identity | ConvertFrom-Json
$accountId = $identity.Account

Write-Host "Account ID: $accountId" -ForegroundColor Cyan

# Login ECR
Write-Host "Connexion a ECR..."
$loginCommand = aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$accountId.dkr.ecr.$Region.amazonaws.com"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur de connexion a ECR" -ForegroundColor Red
    exit 1
}

Write-Host "Connexion ECR reussie" -ForegroundColor Green

# Liste des images à récupérer
$images = @(
    "sap-kb-app",
    "sap-kb-frontend",
    "sap-kb-worker"
)

Write-Host "Telechargement des images..." -ForegroundColor Yellow

foreach ($image in $images) {
    $fullImageName = "$accountId.dkr.ecr.$Region.amazonaws.com/${image}:$Tag"
    Write-Host "  Pull: $image..." -ForegroundColor Cyan

    docker pull $fullImageName

    if ($LASTEXITCODE -eq 0) {
        # Re-tag pour usage local
        docker tag $fullImageName "${image}:latest"
        Write-Host "  $image recuperee et taguee" -ForegroundColor Green
    } else {
        Write-Host "  Erreur pour $image" -ForegroundColor Red
    }
}

Write-Host "`nImages recuperees avec succes!" -ForegroundColor Green
Write-Host "Vous pouvez maintenant lancer: docker-compose up -d" -ForegroundColor Yellow

# Afficher les images disponibles
Write-Host "`nImages Docker disponibles:" -ForegroundColor Magenta
docker images | Select-String "sap-kb|latest" | ForEach-Object { Write-Host "  $_" -ForegroundColor White }