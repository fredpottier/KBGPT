<#
.SYNOPSIS
    Arrêter l'instance EC2 (économise les coûts compute)

.DESCRIPTION
    Arrête l'instance EC2 KnowWhere OSMOSE pour économiser les coûts compute.
    L'instance en état "stopped" ne coûte que le stockage EBS (~$10/mois).
    Les données sont conservées et l'instance peut être redémarrée.

.PARAMETER InstanceId
    ID de l'instance EC2 (ex: i-0123456789abcdef)

.PARAMETER InstanceName
    Nom de l'instance EC2 (recherche par tag Name)

.PARAMETER Region
    AWS region (défaut: eu-west-1)

.PARAMETER Profile
    AWS profile à utiliser (défaut: default)

.EXAMPLE
    .\scripts\aws-stop-instance.ps1 -InstanceId "i-0123456789abcdef"
    Arrêter par ID

.EXAMPLE
    .\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"
    Arrêter par nom

.EXAMPLE
    .\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod" -Region "us-east-1"
    Arrêter dans une autre région
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
Write-Header "Arrêt Instance EC2 KnowWhere OSMOSE"

if (-not $InstanceId -and -not $InstanceName) {
    Write-ErrorMessage "Vous devez spécifier soit -InstanceId soit -InstanceName"
    Write-Host "Exemples:" -ForegroundColor Yellow
    Write-Host "  .\scripts\aws-stop-instance.ps1 -InstanceId 'i-0123456789abcdef'"
    Write-Host "  .\scripts\aws-stop-instance.ps1 -InstanceName 'knowbase-osmose-prod'"
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

    Write-Host "Instance trouvée:"
    Write-Host "  - ID: $InstanceId" -ForegroundColor Green
    Write-Host "  - Name: $instanceNameTag"
    Write-Host "  - Type: $instanceType"
    Write-Host "  - État: $instanceState"
    Write-Host "  - IP: $publicIp"
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

    Write-Host "Instance trouvée:"
    Write-Host "  - ID: $InstanceId" -ForegroundColor Green
    Write-Host "  - Name: $instanceNameTag"
    Write-Host "  - Type: $instanceType"
    Write-Host "  - État: $instanceState"
    Write-Host "  - IP: $publicIp"
}

# =====================================================
# VÉRIFICATION ÉTAT
# =====================================================
if ($instanceState -eq "stopped") {
    Write-Warning "L'instance est déjà arrêtée"
    Write-Host "Pour la redémarrer, utilisez:" -ForegroundColor Cyan
    Write-Host "  .\scripts\aws-start-instance.ps1 -InstanceId $InstanceId"
    exit 0
}

if ($instanceState -eq "stopping") {
    Write-Warning "L'instance est déjà en cours d'arrêt"
    Write-Host "Attendez quelques instants..."
    exit 0
}

if ($instanceState -ne "running") {
    Write-ErrorMessage "L'instance est dans un état inattendu: $instanceState"
    Write-Host "États valides: running, stopped"
    exit 1
}

# =====================================================
# ARRÊT GRACIEUX DES CONTENEURS (optionnel)
# =====================================================
if ($publicIp) {
    Write-Step "Voulez-vous arrêter gracieusement les conteneurs Docker avant d'arrêter l'instance ?"
    Write-Host "Cela permet de sauvegarder proprement les données (recommandé)" -ForegroundColor Yellow
    Write-Host ""
    $response = Read-Host "Arrêter les conteneurs Docker ? (o/N)"

    if ($response -eq "o" -or $response -eq "O") {
        Write-Host "Pour arrêter les conteneurs, vous devez avoir la clé SSH de l'instance" -ForegroundColor Yellow
        $keyPath = Read-Host "Chemin vers la clé SSH (.pem) [Entrée pour skip]"

        if ($keyPath -and (Test-Path $keyPath)) {
            try {
                Write-Step "Arrêt gracieux des conteneurs Docker"
                $sshCommand = "ssh -i `"$keyPath`" -o StrictHostKeyChecking=no ubuntu@$publicIp `"cd /home/ubuntu/knowbase && docker-compose down`""
                Invoke-Expression $sshCommand
                Write-SuccessMessage "Conteneurs Docker arrêtés"
                Start-Sleep -Seconds 5
            }
            catch {
                Write-Warning "Impossible d'arrêter les conteneurs Docker: $_"
                Write-Host "L'instance sera quand même arrêtée"
            }
        }
    }
}

# =====================================================
# ARRÊT DE L'INSTANCE
# =====================================================
Write-Header "Arrêt de l'instance EC2"

Write-Warning "L'instance va être arrêtée"
Write-Host "Après arrêt:"
Write-Host "  - État: stopped"
Write-Host "  - Coût compute: $0/mois (économisé !)"
Write-Host "  - Coût storage: ~$10/mois (EBS volumes conservés)"
Write-Host "  - Données: CONSERVÉES (Neo4j, Qdrant, Redis, etc.)"
Write-Host "  - IP publique: PERDUE (sauf si Elastic IP associée)"
Write-Host ""
Write-Host "Pour redémarrer: .\scripts\aws-start-instance.ps1 -InstanceId $InstanceId"
Write-Host ""
$confirm = Read-Host "Confirmer l'arrêt de l'instance ? (o/N)"

if ($confirm -ne "o" -and $confirm -ne "O") {
    Write-Host "Arrêt annulé" -ForegroundColor Yellow
    exit 0
}

Write-Step "Arrêt de l'instance $InstanceId en cours..."

try {
    aws ec2 stop-instances `
        --instance-ids $InstanceId `
        --region $Region `
        --profile $Profile | Out-Null

    Write-SuccessMessage "Commande d'arrêt envoyée avec succès"

    # Attendre que l'instance soit arrêtée
    Write-Step "Attente de l'arrêt complet (peut prendre 1-2 minutes)..."

    $maxWait = 120  # 2 minutes
    $waited = 0
    $checkInterval = 5

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds $checkInterval
        $waited += $checkInterval

        $currentState = aws ec2 describe-instances `
            --instance-ids $InstanceId `
            --query "Reservations[0].Instances[0].State.Name" `
            --output text `
            --region $Region `
            --profile $Profile

        Write-Host "  État actuel: $currentState (${waited}s)" -ForegroundColor Gray

        if ($currentState -eq "stopped") {
            break
        }
    }

    if ($currentState -eq "stopped") {
        Write-SuccessMessage "Instance arrêtée avec succès !"
    }
    else {
        Write-Warning "L'instance est en cours d'arrêt mais pas encore complètement arrêtée"
        Write-Host "Vérifiez l'état dans quelques minutes avec:"
        Write-Host "  aws ec2 describe-instances --instance-ids $InstanceId --query 'Reservations[0].Instances[0].State.Name'"
    }
}
catch {
    Write-ErrorMessage "Échec de l'arrêt de l'instance: $_"
    exit 1
}

# =====================================================
# RÉSUMÉ
# =====================================================
Write-Header "✅ Instance EC2 arrêtée"

Write-Host "Résumé:"
Write-Host "  - Instance ID: $InstanceId" -ForegroundColor Green
Write-Host "  - État: stopped"
Write-Host "  - Économies: ~$50-110/mois (compute arrêté)"
Write-Host "  - Données: CONSERVÉES"
Write-Host ""
Write-Host "Pour redémarrer l'instance:" -ForegroundColor Cyan
Write-Host "  .\scripts\aws-start-instance.ps1 -InstanceId $InstanceId"
Write-Host ""
Write-Host "Pour détruire complètement l'instance (ATTENTION: perte de données):" -ForegroundColor Yellow
Write-Host "  .\scripts\aws-terminate-instance.ps1 -InstanceId $InstanceId"
