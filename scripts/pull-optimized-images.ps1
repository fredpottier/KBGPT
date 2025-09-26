# Script pour pull les images optimisées depuis ECR après build distant
# Usage: .\pull-optimized-images.ps1

param(
    [string]$Region = "eu-west-1",
    [string]$AccountId = "715927975014",
    [string]$Tag = "latest"
)

$AwsCli = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

Write-Host "Pull des images optimisees depuis ECR" -ForegroundColor Green
Write-Host "Region: $Region" -ForegroundColor Cyan
Write-Host "Account: $AccountId" -ForegroundColor Cyan

# Login ECR
Write-Host "`nConnexion a ECR..."
& $AwsCli ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$AccountId.dkr.ecr.$Region.amazonaws.com"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur connexion ECR" -ForegroundColor Red
    exit 1
}

# Images à pull
$images = @(
    "sap-kb-app",
    "sap-kb-worker",
    "sap-kb-ui",
    "sap-kb-frontend"
)

Write-Host "`nPull des images optimisees..."

foreach ($image in $images) {
    $ecrImage = "$AccountId.dkr.ecr.$Region.amazonaws.com/${image}:$Tag"
    $localImage = "${image}:latest"

    Write-Host "`nPull $image..." -ForegroundColor Yellow

    # Pull from ECR
    docker pull $ecrImage

    if ($LASTEXITCODE -eq 0) {
        # Tag pour usage local
        docker tag $ecrImage $localImage
        Write-Host "$image pulle et tague" -ForegroundColor Green

        # Afficher la taille
        $size = docker images --format "{{.Size}}" $localImage
        Write-Host "   Taille: $size" -ForegroundColor Cyan
    } else {
        Write-Host "Erreur pull $image" -ForegroundColor Red
    }
}

Write-Host "`nImages locales apres optimisation:"
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | Select-String -Pattern "sap.*kb"

Write-Host "`nImages optimisees pretes !" -ForegroundColor Green
Write-Host "Pour demarrer: docker-compose up -d" -ForegroundColor Cyan