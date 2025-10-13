<#
.SYNOPSIS
    Redémarrer l'instance EC2 arrêtée

.DESCRIPTION
    Redémarre une instance EC2 KnowWhere OSMOSE précédemment arrêtée.
    Les conteneurs Docker redémarrent automatiquement (restart: unless-stopped).

.PARAMETER InstanceId
    ID de l'instance EC2 (ex: i-0123456789abcdef)

.PARAMETER InstanceName
    Nom de l'instance EC2 (recherche par tag Name)

.PARAMETER Region
    AWS region (défaut: eu-west-1)

.PARAMETER Profile
    AWS profile à utiliser (défaut: default)

.EXAMPLE
    .\scripts\aws-start-instance.ps1 -InstanceId "i-0123456789abcdef"
    Démarrer par ID

.EXAMPLE
    .\scripts\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"
    Démarrer par nom
#>

[CmdletBinding()]
param(
    [Parameter(ParameterSetName = "ById")]
    [string]$InstanceId,

    [Parameter(ParameterSetName = "ByName")]
    [string]$InstanceName,

    [string]$Region = "eu-west-1",
    [string]$Profile = "default"
)

$ErrorActionPreference = "Stop"

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

function Write-Warning {
    param([string]$Message)
    Write-Host ""
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
    Write-Host ""
}

# =====================================================
# VALIDATION
# =====================================================
Write-Header "Démarrage Instance EC2 KnowWhere OSMOSE"

if (-not $InstanceId -and -not $InstanceName) {
    Write-ErrorMessage "Vous devez spécifier soit -InstanceId soit -InstanceName"
    exit 1
}

# Vérifier AWS CLI
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrorMessage "AWS CLI n'est pas installé"
    exit 1
}

# Vérifier credentials
try {
    $null = aws sts get-caller-identity --profile $Profile 2>$null
    Write-SuccessMessage "Credentials AWS valides"
}
catch {
    Write-ErrorMessage "Credentials AWS invalides pour le profil '$Profile'"
    exit 1
}

# =====================================================
# RECHERCHE DE L'INSTANCE
# =====================================================
if ($InstanceName) {
    Write-Step "Recherche de l'instance par nom: $InstanceName"

    $queryResult = aws ec2 describe-instances `
        --filters "Name=tag:Name,Values=$InstanceName" "Name=instance-state-name,Values=pending,running,stopping,stopped" `
        --query "Reservations[0].Instances[0].[InstanceId,State.Name,PublicIpAddress,InstanceType,Tags[?Key=='Name'].Value|[0]]" `
        --output json `
        --region $Region `
        --profile $Profile | ConvertFrom-Json

    if (-not $queryResult -or $queryResult.Count -eq 0) {
        Write-ErrorMessage "Aucune instance trouvée avec le nom '$InstanceName'"
        exit 1
    }

    $InstanceId = $queryResult[0]
    $instanceState = $queryResult[1]
    $publicIp = $queryResult[2]
    $instanceType = $queryResult[3]
    $instanceNameTag = $queryResult[4]
}
else {
    Write-Step "Récupération des informations de l'instance: $InstanceId"

    $queryResult = aws ec2 describe-instances `
        --instance-ids $InstanceId `
        --query "Reservations[0].Instances[0].[State.Name,PublicIpAddress,InstanceType,Tags[?Key=='Name'].Value|[0]]" `
        --output json `
        --region $Region `
        --profile $Profile | ConvertFrom-Json

    if (-not $queryResult) {
        Write-ErrorMessage "Instance '$InstanceId' non trouvée"
        exit 1
    }

    $instanceState = $queryResult[0]
    $publicIp = $queryResult[1]
    $instanceType = $queryResult[2]
    $instanceNameTag = $queryResult[3]
}

Write-Host "Instance trouvée:"
Write-Host "  - ID: $InstanceId" -ForegroundColor Green
Write-Host "  - Name: $instanceNameTag"
Write-Host "  - Type: $instanceType"
Write-Host "  - État: $instanceState"
Write-Host "  - IP actuelle: $publicIp"

# =====================================================
# VÉRIFICATION ÉTAT
# =====================================================
if ($instanceState -eq "running") {
    Write-Warning "L'instance est déjà en cours d'exécution"
    Write-Host "IP publique: $publicIp"
    Write-Host ""
    Write-Host "Services accessibles:"
    Write-Host "  - Frontend: http://$publicIp:3000"
    Write-Host "  - API: http://$publicIp:8000/docs"
    exit 0
}

if ($instanceState -eq "pending") {
    Write-Warning "L'instance est déjà en cours de démarrage"
    Write-Host "Attendez quelques instants..."
    exit 0
}

if ($instanceState -ne "stopped") {
    Write-ErrorMessage "L'instance est dans un état inattendu: $instanceState"
    Write-Host "États valides: stopped, running"
    exit 1
}

# =====================================================
# DÉMARRAGE DE L'INSTANCE
# =====================================================
Write-Header "Démarrage de l'instance EC2"

Write-Warning "⚠️  IMPORTANT: L'IP publique va probablement changer"
Write-Host "Après démarrage:"
Write-Host "  - État: running"
Write-Host "  - Coût compute: ~$60-120/mois (selon type instance)"
Write-Host "  - IP publique: NOUVELLE (sauf si Elastic IP associée)"
Write-Host "  - Conteneurs Docker: Redémarrent automatiquement"
Write-Host ""

$confirm = Read-Host "Confirmer le démarrage de l'instance ? (o/N)"

if ($confirm -ne "o" -and $confirm -ne "O") {
    Write-Host "Démarrage annulé" -ForegroundColor Yellow
    exit 0
}

Write-Step "Démarrage de l'instance $InstanceId en cours..."

try {
    aws ec2 start-instances `
        --instance-ids $InstanceId `
        --region $Region `
        --profile $Profile | Out-Null

    Write-SuccessMessage "Commande de démarrage envoyée avec succès"

    # Attendre que l'instance soit démarrée
    Write-Step "Attente du démarrage complet (peut prendre 2-3 minutes)..."

    $maxWait = 180  # 3 minutes
    $waited = 0
    $checkInterval = 10

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds $checkInterval
        $waited += $checkInterval

        $statusResult = aws ec2 describe-instances `
            --instance-ids $InstanceId `
            --query "Reservations[0].Instances[0].[State.Name,PublicIpAddress]" `
            --output json `
            --region $Region `
            --profile $Profile | ConvertFrom-Json

        $currentState = $statusResult[0]
        $newPublicIp = $statusResult[1]

        Write-Host "  État: $currentState | IP: $newPublicIp (${waited}s)" -ForegroundColor Gray

        if ($currentState -eq "running" -and $newPublicIp) {
            break
        }
    }

    if ($currentState -eq "running") {
        Write-SuccessMessage "Instance démarrée avec succès !"

        # Récupérer la nouvelle IP publique
        $newPublicIp = aws ec2 describe-instances `
            --instance-ids $InstanceId `
            --query "Reservations[0].Instances[0].PublicIpAddress" `
            --output text `
            --region $Region `
            --profile $Profile

        Write-Host ""
        Write-Host "Nouvelle IP publique: $newPublicIp" -ForegroundColor Green
        Write-Host ""

        # Attendre que les conteneurs Docker démarrent
        Write-Step "Attente du démarrage des conteneurs Docker (2 minutes)..."
        Write-Host "Les conteneurs redémarrent automatiquement (restart: unless-stopped)"

        Start-Sleep -Seconds 120

        Write-SuccessMessage "Conteneurs Docker devraient être opérationnels"
    }
    else {
        Write-Warning "L'instance est en cours de démarrage mais pas encore complètement démarrée"
        Write-Host "Vérifiez l'état dans quelques minutes"
    }
}
catch {
    Write-ErrorMessage "Échec du démarrage de l'instance: $_"
    exit 1
}

# =====================================================
# RÉSUMÉ
# =====================================================
Write-Header "✅ Instance EC2 démarrée"

Write-Host "Résumé:"
Write-Host "  - Instance ID: $InstanceId" -ForegroundColor Green
Write-Host "  - État: running"
Write-Host "  - IP publique: $newPublicIp" -ForegroundColor Yellow
Write-Host ""
Write-Host "⚠️  IMPORTANT: L'IP a changé !" -ForegroundColor Yellow
Write-Host ""
Write-Host "Services accessibles (après 2-3 minutes de démarrage):"
Write-Host "  - Frontend:       http://$newPublicIp:3000" -ForegroundColor Cyan
Write-Host "  - API Backend:    http://$newPublicIp:8000/docs" -ForegroundColor Cyan
Write-Host "  - Neo4j Browser:  http://$newPublicIp:7474" -ForegroundColor Cyan
Write-Host "  - Qdrant UI:      http://$newPublicIp:6333/dashboard" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  Si l'IP a changé, vous devez redéployer pour mettre à jour FRONTEND_API_BASE_URL:" -ForegroundColor Yellow
Write-Host "  .\scripts\deploy-ec2.ps1 -InstanceIP $newPublicIp -KeyPath <path> -SkipSetup"
Write-Host ""
Write-Host "Pour arrêter l'instance:" -ForegroundColor Cyan
Write-Host "  .\scripts\aws-stop-instance.ps1 -InstanceId $InstanceId"
