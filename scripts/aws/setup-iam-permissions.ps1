#Requires -Version 5.1
<#
.SYNOPSIS
    Ajoute les permissions CloudFormation à l'utilisateur IAM

.DESCRIPTION
    Crée et attache une policy IAM pour permettre la gestion CloudFormation

.EXAMPLE
    .\setup-iam-permissions.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$UserName = "sap-kb-codebuild-user",

    [Parameter(Mandatory=$false)]
    [string]$PolicyName = "KnowWhereCloudFormationPolicy"
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$PolicyFile = Join-Path $ProjectRoot "cloudformation\iam-policy-cloudformation.json"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Configuration IAM pour CloudFormation" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Vérifier que le fichier de policy existe
if (-not (Test-Path $PolicyFile)) {
    Write-Host "❌ Fichier de policy non trouvé: $PolicyFile" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Utilisateur IAM: $UserName" -ForegroundColor Yellow
Write-Host "📋 Policy: $PolicyName`n" -ForegroundColor Yellow

# Obtenir l'Account ID
try {
    $accountId = (aws sts get-caller-identity --query Account --output text)
    Write-Host "✅ Account ID: $accountId`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Impossible d'obtenir l'Account ID" -ForegroundColor Red
    exit 1
}

# Vérifier si la policy existe déjà
$policyArn = "arn:aws:iam::${accountId}:policy/${PolicyName}"
try {
    $existingPolicy = aws iam get-policy --policy-arn $policyArn 2>$null
    if ($existingPolicy) {
        Write-Host "⚠️  Policy '$PolicyName' existe déjà" -ForegroundColor Yellow
        $response = Read-Host "Voulez-vous la recréer ? (y/N)"
        if ($response -eq 'y' -or $response -eq 'Y') {
            Write-Host "Détachement de la policy..."
            aws iam detach-user-policy --user-name $UserName --policy-arn $policyArn 2>$null

            Write-Host "Suppression de l'ancienne policy..."
            aws iam delete-policy --policy-arn $policyArn
            Write-Host "✅ Ancienne policy supprimée`n" -ForegroundColor Green
        } else {
            Write-Host "ℹ️  Tentative d'attachement de la policy existante..." -ForegroundColor Cyan
            aws iam attach-user-policy --user-name $UserName --policy-arn $policyArn
            Write-Host "`n✅ Policy attachée avec succès !`n" -ForegroundColor Green
            exit 0
        }
    }
} catch {
    # Policy n'existe pas, on continue
}

# Créer la policy
Write-Host "Création de la policy IAM..."
try {
    $policyDocument = Get-Content $PolicyFile -Raw
    $createResult = aws iam create-policy `
        --policy-name $PolicyName `
        --policy-document $policyDocument `
        --description "Permissions CloudFormation pour KnowWhere OSMOSE deployment"

    Write-Host "✅ Policy créée: $policyArn`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Erreur lors de la création de la policy: $_" -ForegroundColor Red
    exit 1
}

# Attacher la policy à l'utilisateur
Write-Host "Attachement de la policy à l'utilisateur '$UserName'..."
try {
    aws iam attach-user-policy `
        --user-name $UserName `
        --policy-arn $policyArn

    Write-Host "✅ Policy attachée avec succès !`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Erreur lors de l'attachement de la policy: $_" -ForegroundColor Red
    Write-Host "ℹ️  La policy a été créée mais pas attachée." -ForegroundColor Yellow
    Write-Host "   Vous pouvez l'attacher manuellement depuis la console AWS." -ForegroundColor Yellow
    exit 1
}

# Afficher les policies actuelles de l'utilisateur
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Policies attachées à '$UserName'" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

aws iam list-attached-user-policies --user-name $UserName --output table

Write-Host "`n✅ Configuration terminée !`n" -ForegroundColor Green
Write-Host "Vous pouvez maintenant exécuter le script de déploiement CloudFormation.`n" -ForegroundColor Yellow
