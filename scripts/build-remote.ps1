# Script PowerShell pour build distant via AWS CodeBuild
# Usage: .\scripts\build-remote.ps1

param(
    [string]$ProjectName = "sap-kb-docker-build",
    [string]$Region = "us-east-1",
    [switch]$Wait = $false
)

Write-Host "🚀 Démarrage du build distant SAP KB via CodeBuild..." -ForegroundColor Green

# Vérifier les credentials AWS
$awsIdentity = aws sts get-caller-identity 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur: AWS CLI non configuré ou credentials invalides" -ForegroundColor Red
    Write-Host "Configurez avec: aws configure" -ForegroundColor Yellow
    exit 1
}

$identity = $awsIdentity | ConvertFrom-Json
Write-Host "✅ AWS Account: $($identity.Account) - User: $($identity.Arn)" -ForegroundColor Green

# Vérifier si le projet CodeBuild existe
Write-Host "🔍 Vérification du projet CodeBuild: $ProjectName"
$project = aws codebuild batch-get-projects --names $ProjectName --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Projet CodeBuild '$ProjectName' non trouvé" -ForegroundColor Red
    Write-Host "Créez-le d'abord avec: .\scripts\setup-codebuild.ps1" -ForegroundColor Yellow
    exit 1
}

# Démarrer le build
Write-Host "🔨 Démarrage du build distant..."
$buildResult = aws codebuild start-build --project-name $ProjectName --region $Region | ConvertFrom-Json

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur lors du démarrage du build" -ForegroundColor Red
    exit 1
}

$buildId = $buildResult.build.id
Write-Host "✅ Build démarré avec ID: $buildId" -ForegroundColor Green
Write-Host "🔗 Console: https://$Region.console.aws.amazon.com/codesuite/codebuild/projects/$ProjectName/build/$($buildId)?region=$Region" -ForegroundColor Cyan

if ($Wait) {
    Write-Host "⏱️  Attente de la fin du build..." -ForegroundColor Yellow

    do {
        Start-Sleep -Seconds 30
        $buildStatus = aws codebuild batch-get-builds --ids $buildId --region $Region | ConvertFrom-Json
        $status = $buildStatus.builds[0].buildStatus
        $phase = $buildStatus.builds[0].currentPhase

        Write-Host "📊 Statut: $status - Phase: $phase" -ForegroundColor Cyan

    } while ($status -eq "IN_PROGRESS")

    if ($status -eq "SUCCEEDED") {
        Write-Host "🎉 Build terminé avec succès!" -ForegroundColor Green
        Write-Host "📦 Récupération des images avec: .\scripts\pull-images.ps1" -ForegroundColor Yellow
    } else {
        Write-Host "❌ Build échoué: $status" -ForegroundColor Red
        Write-Host "🔍 Vérifiez les logs dans la console AWS" -ForegroundColor Yellow
    }
}

Write-Host "`n✨ Commandes suivantes:" -ForegroundColor Magenta
Write-Host "  - Suivre le build: .\scripts\watch-build.ps1 -BuildId $buildId" -ForegroundColor White
Write-Host "  - Récupérer les images: .\scripts\pull-images.ps1" -ForegroundColor White