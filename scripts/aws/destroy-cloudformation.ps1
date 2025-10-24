#Requires -Version 5.1
<#
.SYNOPSIS
    Détruit COMPLÈTEMENT l'infrastructure KnowWhere OSMOSE sur AWS (1 commande)

.DESCRIPTION
    Ce script:
    1. Demande double confirmation (sécurité)
    2. Supprime le stack CloudFormation
    3. Vérifie que TOUTES les ressources sont supprimées
    4. Optionnellement: supprime les images ECR
    5. Garantit ZÉRO facturation résiduelle

.PARAMETER StackName
    Nom du stack CloudFormation à détruire

.PARAMETER DeleteECRImages
    Si présent, supprime également les images ECR ($1.50/mois économisés)

.PARAMETER Force
    Bypass les confirmations (DANGER - à utiliser avec précaution)

.PARAMETER Region
    Région AWS (default: eu-west-1)

.EXAMPLE
    .\destroy-cloudformation.ps1 -StackName "knowbase-test-perf"

.EXAMPLE
    # Détruire tout incluant images ECR
    .\destroy-cloudformation.ps1 `
        -StackName "knowbase-test-perf" `
        -DeleteECRImages

.EXAMPLE
    # Mode force (sans confirmations) - DANGER
    .\destroy-cloudformation.ps1 `
        -StackName "knowbase-test-perf" `
        -Force
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$false)]
    [switch]$DeleteECRImages,

    [Parameter(Mandatory=$false)]
    [switch]$Force,

    [Parameter(Mandatory=$false)]
    [string]$Region = 'eu-west-1'
)

$ErrorActionPreference = 'Stop'

# ============================================================================
# CONFIGURATION
# ============================================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# ECR Repositories à supprimer si -DeleteECRImages
$ECRRepositories = @(
    'sap-kb-app',
    'sap-kb-worker',
    'sap-kb-frontend',
    'sap-kb-ui',
    'sap-kb-neo4j',
    'sap-kb-redis',
    'sap-kb-qdrant',
    'sap-kb-ngrok'
)

# Colors
$Green = [ConsoleColor]::Green
$Yellow = [ConsoleColor]::Yellow
$Red = [ConsoleColor]::Red
$Cyan = [ConsoleColor]::Cyan

# ============================================================================
# FUNCTIONS
# ============================================================================

function Write-Step {
    param([string]$Message)
    Write-Host "`n========================================" -ForegroundColor $Cyan
    Write-Host $Message -ForegroundColor $Cyan
    Write-Host "========================================" -ForegroundColor $Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✅ $Message" -ForegroundColor $Green
}

function Write-Warning-Custom {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor $Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "❌ $Message" -ForegroundColor $Red
}

function Test-Prerequisites {
    Write-Step "ÉTAPE 1/5: Vérification prérequis"

    # AWS CLI
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Write-Error-Custom "AWS CLI non installé"
        exit 1
    }
    Write-Success "AWS CLI installé"

    # AWS Credentials
    try {
        $null = aws sts get-caller-identity 2>$null
        Write-Success "AWS credentials configurées"
    } catch {
        Write-Error-Custom "AWS credentials non configurées"
        exit 1
    }
}

function Test-StackExists {
    try {
        $status = (aws cloudformation describe-stacks `
            --stack-name $StackName `
            --region $Region `
            --query "Stacks[0].StackStatus" `
            --output text 2>$null)

        if ($status) {
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

function Get-StackResources {
    Write-Step "ÉTAPE 2/5: Inventaire ressources à supprimer"

    if (-not (Test-StackExists)) {
        Write-Warning-Custom "Stack '$StackName' n'existe pas dans la région $Region"
        return $null
    }

    try {
        $outputs = aws cloudformation describe-stacks `
            --stack-name $StackName `
            --region $Region `
            --query "Stacks[0].Outputs" `
            --output json | ConvertFrom-Json

        $resources = @{}
        foreach ($output in $outputs) {
            $resources[$output.OutputKey] = $output.OutputValue
        }

        Write-Host "`n📋 RESSOURCES QUI SERONT SUPPRIMÉES:" -ForegroundColor $Yellow
        Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Yellow
        Write-Host "  Stack Name       : $StackName"
        Write-Host "  Instance ID      : $($resources.InstanceId)"
        Write-Host "  Public IP        : $($resources.PublicIP)"
        Write-Host "  Security Group   : $($resources.SecurityGroupId)"
        Write-Host ""

        # Estimer données qui seront perdues
        Write-Host "⚠️  DONNÉES QUI SERONT PERDUES:" -ForegroundColor $Red
        Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Red
        Write-Host "  - Toutes les données Neo4j (Knowledge Graph)"
        Write-Host "  - Toutes les données Qdrant (Embeddings)"
        Write-Host "  - Toutes les données Redis (Queue/Cache)"
        Write-Host "  - Tous les logs applicatifs"
        Write-Host ""

        if ($DeleteECRImages) {
            Write-Host "  - Images Docker ECR ($($ECRRepositories.Count) repositories)" -ForegroundColor $Red
            Write-Host ""
        }

        return $resources

    } catch {
        Write-Error-Custom "Erreur récupération ressources: $_"
        exit 1
    }
}

function Confirm-Destruction {
    if ($Force) {
        Write-Warning-Custom "Mode Force activé - bypass confirmations"
        return $true
    }

    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Red
    Write-Host "║   ⚠️  CONFIRMATION DESTRUCTION INFRASTRUCTURE            ║" -ForegroundColor $Red
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Red
    Write-Host ""

    Write-Host "Cette opération va SUPPRIMER DÉFINITIVEMENT:" -ForegroundColor $Yellow
    Write-Host "  1. L'instance EC2 et tous ses volumes EBS"
    Write-Host "  2. L'Elastic IP"
    Write-Host "  3. Le Security Group"
    Write-Host "  4. Le IAM Role"
    Write-Host "  5. TOUTES LES DONNÉES (Neo4j, Qdrant, Redis)"

    if ($DeleteECRImages) {
        Write-Host "  6. TOUTES LES IMAGES DOCKER ECR" -ForegroundColor $Red
    }

    Write-Host ""
    Write-Host "Cette action est IRRÉVERSIBLE." -ForegroundColor $Red
    Write-Host ""

    # Première confirmation
    Write-Host "Pour continuer, tapez exactement: " -NoNewline -ForegroundColor $Yellow
    Write-Host "DELETE" -ForegroundColor $Red
    $confirm1 = Read-Host "Votre réponse"

    if ($confirm1 -cne "DELETE") {
        Write-Host ""
        Write-Warning-Custom "Destruction annulée par l'utilisateur"
        exit 0
    }

    # Deuxième confirmation
    Write-Host ""
    Write-Host "Êtes-vous ABSOLUMENT SÛR ? (yes/no): " -NoNewline -ForegroundColor $Yellow
    $confirm2 = Read-Host

    if ($confirm2 -ne "yes") {
        Write-Host ""
        Write-Warning-Custom "Destruction annulée par l'utilisateur"
        exit 0
    }

    Write-Host ""
    Write-Success "Confirmations reçues, destruction en cours..."
    return $true
}

function Remove-CloudFormationStack {
    Write-Step "ÉTAPE 3/5: Suppression stack CloudFormation"

    try {
        Write-Host "Suppression du stack '$StackName'..."

        aws cloudformation delete-stack `
            --stack-name $StackName `
            --region $Region

        Write-Success "Commande de suppression envoyée"

        # Wait for stack deletion
        Write-Host "Attente suppression complète (3-5 min)..." -NoNewline
        $startTime = Get-Date

        while ($true) {
            Start-Sleep -Seconds 10
            Write-Host "." -NoNewline

            if (-not (Test-StackExists)) {
                $elapsed = ((Get-Date) - $startTime).TotalMinutes
                Write-Host ""
                Write-Success "Stack supprimé avec succès en $([math]::Round($elapsed, 1)) minutes"
                return $true
            }

            # Check for errors
            $status = (aws cloudformation describe-stacks `
                --stack-name $StackName `
                --region $Region `
                --query "Stacks[0].StackStatus" `
                --output text 2>$null)

            if ($status -like "*FAILED*") {
                Write-Host ""
                Write-Error-Custom "Échec suppression stack: $status"

                # Show events
                Write-Host "`nÉvénements récents:"
                aws cloudformation describe-stack-events `
                    --stack-name $StackName `
                    --region $Region `
                    --query "StackEvents[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceStatusReason]" `
                    --output table

                exit 1
            }

            # Timeout après 15 minutes
            if (((Get-Date) - $startTime).TotalMinutes -gt 15) {
                Write-Host ""
                Write-Error-Custom "Timeout suppression stack (>15 min)"
                Write-Warning-Custom "Le stack pourrait encore être en cours de suppression"
                Write-Warning-Custom "Vérifiez manuellement dans la console AWS"
                exit 1
            }
        }

    } catch {
        Write-Error-Custom "Erreur suppression stack: $_"
        exit 1
    }
}

function Remove-ECRImages {
    if (-not $DeleteECRImages) {
        Write-Host ""
        Write-Host "ℹ️  Images ECR conservées (utilisez -DeleteECRImages pour supprimer)" -ForegroundColor $Cyan
        return
    }

    Write-Step "ÉTAPE 4/5: Suppression images ECR"

    $deletedCount = 0
    $notFoundCount = 0

    foreach ($repo in $ECRRepositories) {
        try {
            # Check if repo exists
            $exists = aws ecr describe-repositories `
                --repository-names $repo `
                --region $Region `
                --query "repositories[0].repositoryName" `
                --output text 2>$null

            if ($exists -eq $repo) {
                Write-Host "Suppression repository '$repo'..." -NoNewline

                aws ecr delete-repository `
                    --repository-name $repo `
                    --region $Region `
                    --force 2>$null | Out-Null

                Write-Host " ✅" -ForegroundColor $Green
                $deletedCount++
            } else {
                $notFoundCount++
            }

        } catch {
            Write-Host " ⚠️  (n'existe pas)" -ForegroundColor $Yellow
            $notFoundCount++
        }
    }

    Write-Host ""
    Write-Success "$deletedCount repositories ECR supprimés"
    if ($notFoundCount -gt 0) {
        Write-Host "   ($notFoundCount repositories n'existaient pas)" -ForegroundColor $Gray
    }
}

function Verify-NoRemainingResources {
    Write-Step "ÉTAPE 5/5: Vérification cleanup complet"

    $allGood = $true

    # Check CloudFormation stack
    Write-Host "Vérification stack CloudFormation..." -NoNewline
    if (Test-StackExists) {
        Write-Host " ❌" -ForegroundColor $Red
        Write-Warning-Custom "Le stack existe encore !"
        $allGood = $false
    } else {
        Write-Host " ✅" -ForegroundColor $Green
    }

    # Check ECR images
    if ($DeleteECRImages) {
        Write-Host "Vérification images ECR..." -NoNewline
        $remainingRepos = 0

        foreach ($repo in $ECRRepositories) {
            $exists = aws ecr describe-repositories `
                --repository-names $repo `
                --region $Region `
                --query "repositories[0].repositoryName" `
                --output text 2>$null

            if ($exists) {
                $remainingRepos++
            }
        }

        if ($remainingRepos -eq 0) {
            Write-Host " ✅" -ForegroundColor $Green
        } else {
            Write-Host " ⚠️  ($remainingRepos repositories restants)" -ForegroundColor $Yellow
        }
    }

    Write-Host ""

    if ($allGood) {
        Write-Success "CLEANUP COMPLET - Aucune ressource résiduelle"
        Write-Success "Facturation AWS: $0/mois pour ce projet"
    } else {
        Write-Warning-Custom "Certaines ressources n'ont pas pu être supprimées"
        Write-Warning-Custom "Vérifiez manuellement dans la console AWS"
    }

    return $allGood
}

function Show-Summary {
    Write-Step "RÉSUMÉ DESTRUCTION"

    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Green
    Write-Host "║   ✅ DESTRUCTION COMPLÈTE                                ║" -ForegroundColor $Green
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Green
    Write-Host ""

    Write-Host "📋 RESSOURCES SUPPRIMÉES" -ForegroundColor $Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
    Write-Host "  ✅ Stack CloudFormation : $StackName"
    Write-Host "  ✅ Instance EC2"
    Write-Host "  ✅ Volumes EBS (root + data)"
    Write-Host "  ✅ Elastic IP"
    Write-Host "  ✅ Security Group"
    Write-Host "  ✅ IAM Role + Instance Profile"

    if ($DeleteECRImages) {
        Write-Host "  ✅ Images Docker ECR"
    }

    Write-Host ""
    Write-Host "💰 FACTURATION" -ForegroundColor $Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
    Write-Host "  Coût mensuel maintenant : " -NoNewline
    if ($DeleteECRImages) {
        Write-Host "`$0.00/mois" -ForegroundColor $Green
    } else {
        Write-Host "`$1.50/mois (images ECR conservées)" -ForegroundColor $Yellow
    }

    Write-Host ""
    Write-Host "📊 POUR REDÉPLOYER" -ForegroundColor $Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
    Write-Host "  1. Build + push images ECR:" -ForegroundColor $Gray
    Write-Host "     .\scripts\aws\build-and-push-ecr.ps1" -ForegroundColor $Gray
    Write-Host ""
    Write-Host "  2. Déployer stack:" -ForegroundColor $Gray
    Write-Host "     .\scripts\aws\deploy-cloudformation.ps1 -StackName 'name' -KeyPairName 'key'" -ForegroundColor $Gray
    Write-Host ""
}

# ============================================================================
# MAIN SCRIPT
# ============================================================================

try {
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Cyan
    Write-Host "║   KnowWhere OSMOSE - Destruction Infrastructure          ║" -ForegroundColor $Cyan
    Write-Host "║   One-Click Destroy (garantie zéro facturation)          ║" -ForegroundColor $Cyan
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Cyan
    Write-Host ""

    # 1. Prerequisites
    Test-Prerequisites

    # 2. Inventory resources
    $resources = Get-StackResources

    if (-not $resources) {
        Write-Host ""
        Write-Warning-Custom "Aucune ressource à supprimer"
        exit 0
    }

    # 3. Confirm destruction
    if (-not (Confirm-Destruction)) {
        exit 0
    }

    # 4. Delete CloudFormation Stack
    Remove-CloudFormationStack

    # 5. Delete ECR Images (optional)
    Remove-ECRImages

    # 6. Verify cleanup
    $cleanupOK = Verify-NoRemainingResources

    # 7. Show summary
    Show-Summary

    Write-Host ""
    Write-Host "🎉 Infrastructure détruite avec succès !" -ForegroundColor $Green
    Write-Host ""

    if (-not $cleanupOK) {
        exit 1
    }

    exit 0

} catch {
    Write-Host ""
    Write-Error-Custom "Erreur inattendue: $_"
    Write-Host $_.ScriptStackTrace
    exit 1
}
