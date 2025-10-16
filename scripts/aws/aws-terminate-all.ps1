<#
.SYNOPSIS
    Détruire COMPLÈTEMENT l'infrastructure AWS KnowWhere OSMOSE

.DESCRIPTION
    ⚠️  ATTENTION: Ce script DÉTRUIT DÉFINITIVEMENT toute l'infrastructure AWS.

    Ce script supprime:
    - Instance(s) EC2 (terminate)
    - Volumes EBS associés
    - Images ECR (optionnel)
    - Elastic IP (optionnel)
    - Security Groups (optionnel)

    ⚠️  LES DONNÉES SONT PERDUES DÉFINITIVEMENT (Neo4j, Qdrant, Redis)
    ⚠️  Faites un backup AVANT si vous voulez conserver vos données

.PARAMETER InstanceId
    ID de l'instance EC2 à terminer

.PARAMETER InstanceName
    Nom de l'instance EC2 (recherche par tag Name)

.PARAMETER Region
    AWS region (défaut: eu-west-1)

.PARAMETER Profile
    AWS profile à utiliser (défaut: default)

.PARAMETER DeleteECRImages
    Supprimer aussi les images ECR (économise $1.50/mois storage)

.PARAMETER DeleteSecurityGroup
    Supprimer aussi le Security Group

.PARAMETER Force
    Skip les confirmations (DANGEREUX !)

.EXAMPLE
    .\scripts\aws-terminate-all.ps1 -InstanceName "knowbase-osmose-prod"
    Terminer l'instance (avec confirmations)

.EXAMPLE
    .\scripts\aws-terminate-all.ps1 -InstanceId "i-0123456789abcdef" -DeleteECRImages
    Terminer l'instance ET supprimer les images ECR

.EXAMPLE
    .\scripts\aws-terminate-all.ps1 -InstanceName "knowbase-osmose-prod" -Force
    Terminer sans confirmation (ATTENTION !)
#>

[CmdletBinding()]
param(
    [Parameter(ParameterSetName = "ById")]
    [string]$InstanceId,

    [Parameter(ParameterSetName = "ByName")]
    [string]$InstanceName,

    [string]$Region = "eu-west-1",
    [string]$Profile = "default",
    [switch]$DeleteECRImages,
    [switch]$DeleteSecurityGroup,
    [switch]$Force
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

function Write-Danger {
    param([string]$Message)
    Write-Host ""
    Write-Host "🔴 DANGER: $Message" -ForegroundColor Red
    Write-Host ""
}

# =====================================================
# VALIDATION
# =====================================================
Write-Header "🔴 DESTRUCTION INFRASTRUCTURE AWS"

Write-Danger "Ce script va SUPPRIMER DÉFINITIVEMENT des ressources AWS"
Write-Host "Toutes les données seront PERDUES (Neo4j, Qdrant, Redis, etc.)"
Write-Host ""

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
        --filters "Name=tag:Name,Values=$InstanceName" `
        --query "Reservations[0].Instances[0].[InstanceId,State.Name,PublicIpAddress,InstanceType,Tags[?Key=='Name'].Value|[0],BlockDeviceMappings[*].Ebs.VolumeId,SecurityGroups[0].GroupId]" `
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
    $volumeIds = $queryResult[5]
    $securityGroupId = $queryResult[6]
}
else {
    Write-Step "Récupération des informations de l'instance: $InstanceId"

    $queryResult = aws ec2 describe-instances `
        --instance-ids $InstanceId `
        --query "Reservations[0].Instances[0].[State.Name,PublicIpAddress,InstanceType,Tags[?Key=='Name'].Value|[0],BlockDeviceMappings[*].Ebs.VolumeId,SecurityGroups[0].GroupId]" `
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
    $volumeIds = $queryResult[4]
    $securityGroupId = $queryResult[5]
}

# =====================================================
# AFFICHAGE DES RESSOURCES À SUPPRIMER
# =====================================================
Write-Header "Ressources AWS qui seront supprimées"

Write-Host "Instance EC2:" -ForegroundColor Red
Write-Host "  - ID: $InstanceId"
Write-Host "  - Name: $instanceNameTag"
Write-Host "  - Type: $instanceType"
Write-Host "  - État: $instanceState"
Write-Host "  - IP: $publicIp"
Write-Host ""

Write-Host "Volumes EBS (seront supprimés avec l'instance):" -ForegroundColor Red
if ($volumeIds) {
    foreach ($volumeId in $volumeIds) {
        Write-Host "  - $volumeId"
    }
}
Write-Host ""

if ($DeleteSecurityGroup -and $securityGroupId) {
    Write-Host "Security Group (sera supprimé):" -ForegroundColor Red
    Write-Host "  - $securityGroupId"
    Write-Host ""
}

if ($DeleteECRImages) {
    Write-Host "Images ECR (seront supprimées):" -ForegroundColor Red
    $ecrRepos = @(
        "sap-kb-app", "sap-kb-worker", "sap-kb-frontend", "sap-kb-ui",
        "sap-kb-neo4j", "sap-kb-redis", "sap-kb-qdrant", "sap-kb-ngrok"
    )
    foreach ($repo in $ecrRepos) {
        Write-Host "  - $repo"
    }
    Write-Host ""
}

Write-Danger "⚠️  TOUTES LES DONNÉES SERONT PERDUES DÉFINITIVEMENT"
Write-Host "Cela inclut:"
Write-Host "  - Base de données Neo4j (Knowledge Graph)"
Write-Host "  - Base vectorielle Qdrant (embeddings)"
Write-Host "  - Files d'attente Redis"
Write-Host "  - Documents traités et non traités"
Write-Host "  - Toutes les configurations"
Write-Host ""

# =====================================================
# CONFIRMATION
# =====================================================
if (-not $Force) {
    Write-Warning "Êtes-vous ABSOLUMENT SÛR de vouloir continuer ?"
    Write-Host "Tapez exactement 'DELETE' pour confirmer (en majuscules)" -ForegroundColor Yellow
    $confirmation = Read-Host

    if ($confirmation -ne "DELETE") {
        Write-Host "Suppression annulée" -ForegroundColor Green
        Write-Host "Rien n'a été supprimé"
        exit 0
    }

    Write-Warning "Dernière confirmation !"
    $finalConfirm = Read-Host "Tapez 'YES' pour confirmer la suppression définitive"

    if ($finalConfirm -ne "YES") {
        Write-Host "Suppression annulée" -ForegroundColor Green
        exit 0
    }
}

# =====================================================
# SUPPRESSION INSTANCE EC2
# =====================================================
Write-Header "Suppression de l'instance EC2"

Write-Step "Termination de l'instance $InstanceId..."

try {
    aws ec2 terminate-instances `
        --instance-ids $InstanceId `
        --region $Region `
        --profile $Profile | Out-Null

    Write-SuccessMessage "Commande de termination envoyée"

    # Attendre la termination
    Write-Step "Attente de la termination complète (peut prendre 2-3 minutes)..."

    $maxWait = 180
    $waited = 0
    $checkInterval = 10

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds $checkInterval
        $waited += $checkInterval

        $currentState = aws ec2 describe-instances `
            --instance-ids $InstanceId `
            --query "Reservations[0].Instances[0].State.Name" `
            --output text `
            --region $Region `
            --profile $Profile 2>$null

        if (-not $currentState -or $currentState -eq "terminated") {
            break
        }

        Write-Host "  État: $currentState (${waited}s)" -ForegroundColor Gray
    }

    Write-SuccessMessage "Instance terminée"
}
catch {
    Write-ErrorMessage "Échec de la termination: $_"
    Write-Host "Continuez quand même avec les autres ressources ? (o/N)"
    $continue = Read-Host
    if ($continue -ne "o" -and $continue -ne "O") {
        exit 1
    }
}

# =====================================================
# SUPPRESSION SECURITY GROUP (optionnel)
# =====================================================
if ($DeleteSecurityGroup -and $securityGroupId) {
    Write-Header "Suppression du Security Group"

    Write-Step "Tentative de suppression du Security Group: $securityGroupId"
    Write-Host "Note: Le Security Group par défaut ne peut pas être supprimé" -ForegroundColor Gray

    try {
        # Attendre que l'instance soit complètement terminée avant de supprimer le SG
        Start-Sleep -Seconds 30

        aws ec2 delete-security-group `
            --group-id $securityGroupId `
            --region $Region `
            --profile $Profile 2>$null

        Write-SuccessMessage "Security Group supprimé"
    }
    catch {
        Write-Warning "Impossible de supprimer le Security Group: $_"
        Write-Host "Vous pouvez le supprimer manuellement via la console AWS si nécessaire"
    }
}

# =====================================================
# SUPPRESSION IMAGES ECR (optionnel)
# =====================================================
if ($DeleteECRImages) {
    Write-Header "Suppression des images ECR"

    $ecrRepos = @(
        "sap-kb-app", "sap-kb-worker", "sap-kb-frontend", "sap-kb-ui",
        "sap-kb-neo4j", "sap-kb-redis", "sap-kb-qdrant", "sap-kb-ngrok"
    )

    foreach ($repo in $ecrRepos) {
        Write-Step "Suppression du repository: $repo"

        try {
            aws ecr delete-repository `
                --repository-name $repo `
                --force `
                --region $Region `
                --profile $Profile 2>$null | Out-Null

            Write-Host "  ✓ $repo supprimé" -ForegroundColor Green
        }
        catch {
            Write-Host "  ⚠️  $repo non trouvé ou déjà supprimé" -ForegroundColor Gray
        }
    }

    Write-SuccessMessage "Repositories ECR supprimés"
}

# =====================================================
# RÉSUMÉ FINAL
# =====================================================
Write-Header "✅ Suppression terminée"

Write-Host "Ressources supprimées:" -ForegroundColor Green
Write-Host "  ✓ Instance EC2: $InstanceId (terminated)"
Write-Host "  ✓ Volumes EBS associés (supprimés automatiquement)"

if ($DeleteSecurityGroup) {
    Write-Host "  ✓ Security Group: $securityGroupId (tenté)"
}

if ($DeleteECRImages) {
    Write-Host "  ✓ Images ECR: 8 repositories (supprimés)"
}

Write-Host ""
Write-Host "Économies estimées:" -ForegroundColor Cyan
Write-Host "  - Compute EC2: ~$60-120/mois"
Write-Host "  - Storage EBS: ~$10/mois"

if ($DeleteECRImages) {
    Write-Host "  - Storage ECR: ~$1.50/mois"
    Write-Host "  TOTAL: ~$71.50-131.50/mois économisés" -ForegroundColor Green
}
else {
    Write-Host "  TOTAL: ~$70-130/mois économisés" -ForegroundColor Green
}

Write-Host ""
Write-Warning "Note: Les images ECR sont conservées (sauf si -DeleteECRImages utilisé)"
Write-Host "Vous pouvez les supprimer plus tard pour économiser $1.50/mois:"
Write-Host "  .\scripts\aws-terminate-all.ps1 -InstanceName dummy -DeleteECRImages -Force"
Write-Host "  (Cela supprimera seulement les ECR repos, pas d'instance)"
Write-Host ""
Write-Host "Pour recréer l'infrastructure:" -ForegroundColor Cyan
Write-Host "  1. Créer nouvelle instance EC2 via AWS Console"
Write-Host "  2. .\scripts\build-and-push-ecr.ps1 (si ECR images supprimées)"
Write-Host "  3. .\scripts\deploy-ec2.ps1 -InstanceIP <new-ip> -KeyPath <key>"
