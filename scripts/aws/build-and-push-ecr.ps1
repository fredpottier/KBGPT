<#
.SYNOPSIS
    Script de build local et push vers AWS ECR (Windows PowerShell)

.DESCRIPTION
    Build les images Docker localement et les push vers AWS ECR.
    Supporte le build incrémental et complet avec options flexibles.

.PARAMETER NoCache
    Build sans cache Docker (from scratch)

.PARAMETER SkipThirdParty
    Ne pas rebuilder les images third-party (neo4j, redis, qdrant, ngrok)

.PARAMETER Tag
    Tag custom pour les images (défaut: git commit hash ou 'latest')

.PARAMETER Profile
    AWS profile à utiliser (défaut: default)

.PARAMETER Region
    AWS region (défaut: eu-west-1)

.EXAMPLE
    .\scripts\build-and-push-ecr.ps1
    Build et push toutes les images avec tag automatique

.EXAMPLE
    .\scripts\build-and-push-ecr.ps1 -NoCache
    Build from scratch sans cache Docker

.EXAMPLE
    .\scripts\build-and-push-ecr.ps1 -SkipThirdParty -Tag "v1.0.0"
    Build seulement les images custom avec tag v1.0.0

.EXAMPLE
    .\scripts\build-and-push-ecr.ps1 -Profile "my-aws-profile" -Region "us-east-1"
    Utiliser un profil AWS et région spécifiques
#>

[CmdletBinding()]
param(
    [switch]$NoCache,
    [switch]$SkipThirdParty,
    [string]$Tag = "",
    [string]$Profile = "default",
    [string]$Region = "eu-west-1"
)

$ErrorActionPreference = "Stop"

# =====================================================
# DETECTION ET POSITIONNEMENT A LA RACINE DU PROJET
# =====================================================
# Le script doit etre execute depuis la racine du projet (ou se trouvent app/, src/, frontend/)
$scriptPath = $PSScriptRoot
$currentDir = Get-Location

# Verifier si nous sommes a la racine du projet (presence de app/, src/, frontend/)
$isAtRoot = (Test-Path "app") -and (Test-Path "src") -and (Test-Path "frontend")

if (-not $isAtRoot) {
    Write-Host "Repositionnement automatique a la racine du projet..." -ForegroundColor Yellow

    # Remonter jusqu'a trouver la racine (max 3 niveaux)
    $foundRoot = $false
    $testDir = $currentDir

    for ($i = 0; $i -lt 3; $i++) {
        $testDir = Split-Path $testDir -Parent
        Push-Location $testDir

        if ((Test-Path "app") -and (Test-Path "src") -and (Test-Path "frontend")) {
            $foundRoot = $true
            Write-Host "Racine du projet trouvee: $testDir" -ForegroundColor Green
            break
        }

        Pop-Location
    }

    if (-not $foundRoot) {
        Write-Host ""
        Write-Host "ERROR: Impossible de trouver la racine du projet" -ForegroundColor Red
        Write-Host ""
        Write-Host "Le script doit etre execute depuis la racine du projet (ou un sous-repertoire proche)." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Structure attendue:" -ForegroundColor Yellow
        Write-Host "  C:\Project\SAP_KB\"
        Write-Host "  - app/            (Dossier requis)"
        Write-Host "  - src/            (Dossier requis)"
        Write-Host "  - frontend/       (Dossier requis)"
        Write-Host "  - scripts/aws/    (Ce script)"
        Write-Host ""
        Write-Host "Positionnez-vous a la racine du projet:" -ForegroundColor Cyan
        Write-Host "  cd C:\Project\SAP_KB"
        Write-Host "  .\scripts\aws\build-and-push-ecr.ps1"
        Write-Host ""
        exit 1
    }
}

Write-Host "Repertoire de travail: $(Get-Location)" -ForegroundColor Gray
Write-Host ""

# =====================================================
# CONFIGURATION PAR DEFAUT
# =====================================================
$AWS_DEFAULT_REGION = $Region
$AWS_ACCOUNT_ID = $env:AWS_ACCOUNT_ID
if (-not $AWS_ACCOUNT_ID) {
    $AWS_ACCOUNT_ID = "715927975014"
}

# Repositories ECR
$IMAGE_REPO_NAME_APP = "sap-kb-app"
$IMAGE_REPO_NAME_WORKER = "sap-kb-worker"
$IMAGE_REPO_NAME_FRONTEND = "sap-kb-frontend"
$IMAGE_REPO_NAME_UI = "sap-kb-ui"
$IMAGE_REPO_NAME_NEO4J = "sap-kb-neo4j"
$IMAGE_REPO_NAME_REDIS = "sap-kb-redis"
$IMAGE_REPO_NAME_QDRANT = "sap-kb-qdrant"
$IMAGE_REPO_NAME_NGROK = "sap-kb-ngrok"
$IMAGE_REPO_NAME_LOKI = "sap-kb-loki"
$IMAGE_REPO_NAME_PROMTAIL = "sap-kb-promtail"
$IMAGE_REPO_NAME_GRAFANA = "sap-kb-grafana"

# Images third-party de base
$NEO4J_BASE_IMAGE = "neo4j:5.26.0"
$REDIS_BASE_IMAGE = "redis:7.2"
$QDRANT_BASE_IMAGE = "qdrant/qdrant:v1.15.1"
$NGROK_BASE_IMAGE = "ngrok/ngrok:latest"
$LOKI_BASE_IMAGE = "grafana/loki:2.9.3"
$PROMTAIL_BASE_IMAGE = "grafana/promtail:2.9.3"
$GRAFANA_BASE_IMAGE = "grafana/grafana:10.2.3"

$PUSH_LATEST = $true

# =====================================================
# FONCTIONS UTILITAIRES
# =====================================================
function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  $Message"
    Write-Host "=============================================="
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">>> $Message" -ForegroundColor Cyan
    Write-Host ""
}

function Write-ErrorMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "❌ ERROR: $Message" -ForegroundColor Red
    Write-Host ""
}

function Write-SuccessMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "✅ $Message" -ForegroundColor Green
    Write-Host ""
}

# =====================================================
# VALIDATION ENVIRONNEMENT
# =====================================================
Write-Header "Validation de l'environnement"

# Vérifier Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-ErrorMessage "Docker n'est pas installé ou n'est pas dans le PATH"
    exit 1
}
$dockerVersion = docker --version
Write-SuccessMessage "Docker trouvé: $dockerVersion"

# Vérifier AWS CLI
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrorMessage "AWS CLI n'est pas installé ou n'est pas dans le PATH"
    Write-Host "Installation: https://aws.amazon.com/cli/" -ForegroundColor Yellow
    exit 1
}
$awsVersion = aws --version
Write-SuccessMessage "AWS CLI trouvé: $awsVersion"

# Vérifier les credentials AWS
try {
    $null = aws sts get-caller-identity --profile $Profile 2>$null
    Write-SuccessMessage "Credentials AWS valides pour le profil '$Profile'"
}
catch {
    Write-ErrorMessage "Credentials AWS invalides pour le profil '$Profile'"
    Write-Host "Configurez vos credentials avec: aws configure --profile $Profile" -ForegroundColor Yellow
    exit 1
}

# Définir le tag d'image
if ($Tag) {
    $IMAGE_TAG = $Tag
}
else {
    # Essayer d'obtenir le commit hash git
    try {
        $gitHash = git rev-parse --short HEAD 2>$null
        if ($gitHash) {
            $IMAGE_TAG = $gitHash
            Write-Step "Tag automatique depuis git: $IMAGE_TAG"
        }
        else {
            $IMAGE_TAG = "latest"
            Write-Step "Pas de git détecté, utilisation du tag: $IMAGE_TAG"
        }
    }
    catch {
        $IMAGE_TAG = "latest"
        Write-Step "Pas de git détecté, utilisation du tag: $IMAGE_TAG"
    }
}

$ECR_REGISTRY = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com"

Write-Header "Configuration"
Write-Host "AWS Account ID:    $AWS_ACCOUNT_ID"
Write-Host "AWS Region:        $AWS_DEFAULT_REGION"
Write-Host "AWS Profile:       $Profile"
Write-Host "ECR Registry:      $ECR_REGISTRY"
Write-Host "Image Tag:         $IMAGE_TAG"
Write-Host "No Cache:          $NoCache"
Write-Host "Skip Third Party:  $SkipThirdParty"
Write-Host "Push Latest:       $PUSH_LATEST"

# =====================================================
# LOGIN AWS ECR
# =====================================================
Write-Header "Login AWS ECR"
try {
    $loginPassword = aws ecr get-login-password --region $AWS_DEFAULT_REGION --profile $Profile
    $loginPassword | docker login --username AWS --password-stdin $ECR_REGISTRY
    Write-SuccessMessage "Login ECR réussi"
}
catch {
    Write-ErrorMessage "Échec du login ECR: $_"
    exit 1
}

# =====================================================
# CRÉATION DES REPOSITORIES ECR
# =====================================================
Write-Header "Vérification des repositories ECR"

$REPOS = @(
    $IMAGE_REPO_NAME_APP,
    $IMAGE_REPO_NAME_WORKER,
    $IMAGE_REPO_NAME_FRONTEND,
    $IMAGE_REPO_NAME_UI,
    $IMAGE_REPO_NAME_NEO4J,
    $IMAGE_REPO_NAME_REDIS,
    $IMAGE_REPO_NAME_QDRANT,
    $IMAGE_REPO_NAME_NGROK,
    $IMAGE_REPO_NAME_LOKI,
    $IMAGE_REPO_NAME_PROMTAIL,
    $IMAGE_REPO_NAME_GRAFANA
)

foreach ($repo in $REPOS) {
    try {
        $null = aws ecr describe-repositories --repository-names $repo --region $AWS_DEFAULT_REGION --profile $Profile 2>$null
        Write-Step "Repository $repo existe déjà"
    }
    catch {
        Write-Step "Création du repository $repo"
        aws ecr create-repository `
            --repository-name $repo `
            --image-scanning-configuration scanOnPush=true `
            --region $AWS_DEFAULT_REGION `
            --profile $Profile
    }
}

Write-SuccessMessage "Tous les repositories ECR sont prêts"

# =====================================================
# BUILD DES IMAGES FIRST-PARTY
# =====================================================
Write-Header "Build des images first-party"

$noCacheFlag = if ($NoCache) { "--no-cache" } else { "" }

# Backend API (réutilisé pour worker)
Write-Step "Build de l'image backend/worker (app)"
$APP_LOCAL_TAG = "sap-kb-app:build"

if ($NoCache) {
    docker build --no-cache --file app/Dockerfile --tag $APP_LOCAL_TAG .
}
else {
    docker build --file app/Dockerfile --tag $APP_LOCAL_TAG .
}

docker tag $APP_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_APP`:$IMAGE_TAG"
docker tag $APP_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_WORKER`:$IMAGE_TAG"

if ($PUSH_LATEST) {
    docker tag $APP_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_APP`:latest"
    docker tag $APP_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_WORKER`:latest"
}

Write-SuccessMessage "Image backend/worker buildée"

# Streamlit UI
Write-Step "Build de l'image Streamlit UI"
$UI_LOCAL_TAG = "sap-kb-ui:build"

if ($NoCache) {
    docker build --no-cache --file ui/Dockerfile --tag $UI_LOCAL_TAG ui
}
else {
    docker build --file ui/Dockerfile --tag $UI_LOCAL_TAG ui
}

docker tag $UI_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_UI`:$IMAGE_TAG"

if ($PUSH_LATEST) {
    docker tag $UI_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_UI`:latest"
}

Write-SuccessMessage "Image Streamlit UI buildée"

# Next.js frontend
Write-Step "Build de l'image Next.js frontend"
$FRONTEND_LOCAL_TAG = "sap-kb-frontend:build"

if ($NoCache) {
    docker build --no-cache --file frontend/Dockerfile --tag $FRONTEND_LOCAL_TAG frontend
}
else {
    docker build --file frontend/Dockerfile --tag $FRONTEND_LOCAL_TAG frontend
}

# Tag local latest
docker tag $FRONTEND_LOCAL_TAG "sap-kb-frontend:latest"

# Tag pour ECR
docker tag $FRONTEND_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_FRONTEND`:$IMAGE_TAG"

if ($PUSH_LATEST) {
    docker tag $FRONTEND_LOCAL_TAG "$ECR_REGISTRY/$IMAGE_REPO_NAME_FRONTEND`:latest"
}

Write-SuccessMessage "Image Next.js frontend buildée"

# =====================================================
# MIRROR DES IMAGES THIRD-PARTY
# =====================================================
if (-not $SkipThirdParty) {
    Write-Header "Mirror des images third-party vers ECR"

    function Mirror-ExternalImage {
        param(
            [string]$SourceImage,
            [string]$TargetRepo
        )

        $versionTag = $SourceImage.Split(':')[-1]
        Write-Step "Mirror de $SourceImage -> $TargetRepo`:$versionTag"

        docker pull $SourceImage
        docker tag $SourceImage "$ECR_REGISTRY/$TargetRepo`:$versionTag"

        if ($PUSH_LATEST) {
            docker tag $SourceImage "$ECR_REGISTRY/$TargetRepo`:latest"
        }
    }

    Mirror-ExternalImage -SourceImage $NEO4J_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_NEO4J
    Mirror-ExternalImage -SourceImage $REDIS_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_REDIS
    Mirror-ExternalImage -SourceImage $QDRANT_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_QDRANT
    Mirror-ExternalImage -SourceImage $NGROK_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_NGROK
    Mirror-ExternalImage -SourceImage $LOKI_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_LOKI
    Mirror-ExternalImage -SourceImage $PROMTAIL_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_PROMTAIL
    Mirror-ExternalImage -SourceImage $GRAFANA_BASE_IMAGE -TargetRepo $IMAGE_REPO_NAME_GRAFANA

    Write-SuccessMessage "Toutes les images third-party sont prêtes"
}
else {
    Write-Step "Skip du mirror des images third-party (-SkipThirdParty)"
}

# =====================================================
# AFFICHAGE DES IMAGES BUILDÉES
# =====================================================
Write-Header "Images buildées localement"
docker images | Select-String -Pattern "sap-kb|neo4j|redis|qdrant|ngrok" | Select-String -Pattern "build|latest|$IMAGE_TAG"

# =====================================================
# PUSH VERS ECR
# =====================================================
Write-Header "Push des images vers ECR"

function Push-WithTags {
    param(
        [string]$Repo,
        [string]$Tag
    )

    Write-Step "Push de $Repo`:$Tag"
    docker push "$ECR_REGISTRY/$Repo`:$Tag"

    if ($PUSH_LATEST -and $Tag -ne "latest") {
        Write-Step "Push de $Repo`:latest"
        docker push "$ECR_REGISTRY/$Repo`:latest"
    }
}

# Push des images first-party
Push-WithTags -Repo $IMAGE_REPO_NAME_APP -Tag $IMAGE_TAG
Push-WithTags -Repo $IMAGE_REPO_NAME_WORKER -Tag $IMAGE_TAG
Push-WithTags -Repo $IMAGE_REPO_NAME_FRONTEND -Tag $IMAGE_TAG
Push-WithTags -Repo $IMAGE_REPO_NAME_UI -Tag $IMAGE_TAG

# Push des images third-party
if (-not $SkipThirdParty) {
    $neo4jTag = $NEO4J_BASE_IMAGE.Split(':')[-1]
    $redisTag = $REDIS_BASE_IMAGE.Split(':')[-1]
    $qdrantTag = $QDRANT_BASE_IMAGE.Split(':')[-1]
    $ngrokTag = $NGROK_BASE_IMAGE.Split(':')[-1]

    Push-WithTags -Repo $IMAGE_REPO_NAME_NEO4J -Tag $neo4jTag
    Push-WithTags -Repo $IMAGE_REPO_NAME_REDIS -Tag $redisTag
    Push-WithTags -Repo $IMAGE_REPO_NAME_QDRANT -Tag $qdrantTag
    Push-WithTags -Repo $IMAGE_REPO_NAME_NGROK -Tag $ngrokTag
    Push-WithTags -Repo $IMAGE_REPO_NAME_LOKI -Tag "2.9.3"
    Push-WithTags -Repo $IMAGE_REPO_NAME_PROMTAIL -Tag "2.9.3"
    Push-WithTags -Repo $IMAGE_REPO_NAME_GRAFANA -Tag "10.2.3"
}

# =====================================================
# RÉSUMÉ FINAL
# =====================================================
Write-Header "✅ Build et push terminés avec succès !"

Write-Host ""
Write-Host "Images disponibles dans ECR:"
Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_APP`:$IMAGE_TAG"
Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_WORKER`:$IMAGE_TAG"
Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_FRONTEND`:$IMAGE_TAG"
Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_UI`:$IMAGE_TAG"

if (-not $SkipThirdParty) {
    $neo4jTag = $NEO4J_BASE_IMAGE.Split(':')[-1]
    $redisTag = $REDIS_BASE_IMAGE.Split(':')[-1]
    $qdrantTag = $QDRANT_BASE_IMAGE.Split(':')[-1]
    $ngrokTag = $NGROK_BASE_IMAGE.Split(':')[-1]

    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_NEO4J`:$neo4jTag"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_REDIS`:$redisTag"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_QDRANT`:$qdrantTag"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_NGROK`:$ngrokTag"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_LOKI`:2.9.3"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_PROMTAIL`:2.9.3"
    Write-Host "  - $ECR_REGISTRY/$IMAGE_REPO_NAME_GRAFANA`:10.2.3"
}

Write-Host ""
Write-Host "Prochaines etapes:" -ForegroundColor Yellow
Write-Host "  1. Creer une instance EC2 (t3.xlarge ou plus recommande)"
Write-Host "  2. Utiliser le script .\scripts\aws\deploy-ec2.ps1 pour deployer"
Write-Host ""
Write-Host "Documentation: doc\AWS_DEPLOYMENT_GUIDE.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "Exemple de deploiement:" -ForegroundColor Cyan
Write-Host "  .\scripts\aws\deploy-ec2.ps1 -InstanceIP 54.123.45.67 -KeyPath C:\aws\ma-cle.pem"

Write-SuccessMessage "Terminé à $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
