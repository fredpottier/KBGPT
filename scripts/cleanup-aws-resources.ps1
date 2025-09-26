# Script PowerShell pour nettoyer toutes les ressources AWS créées
# Usage: .\scripts\cleanup-aws-resources.ps1

param(
    [string]$ResourcesFile = "aws-resources-created.json",
    [switch]$DryRun = $false,
    [switch]$Force = $false
)

Write-Host "🧹 Nettoyage des ressources AWS SAP KB..." -ForegroundColor Red

if (-not (Test-Path $ResourcesFile)) {
    Write-Host "❌ Fichier de ressources non trouvé: $ResourcesFile" -ForegroundColor Red
    Write-Host "💡 Tentative de nettoyage par convention de nommage..." -ForegroundColor Yellow

    # Nettoyage par convention si pas de fichier de tracking
    $defaultResources = @(
        @{type="CodeBuild Project"; name="sap-kb-docker-build"; region="eu-west-1"},
        @{type="IAM Role"; name="CodeBuildServiceRole-SAP-KB"; region="global"},
        @{type="ECR Repository"; name="sap-kb-app"; region="eu-west-1"},
        @{type="ECR Repository"; name="sap-kb-frontend"; region="eu-west-1"},
        @{type="ECR Repository"; name="sap-kb-worker"; region="eu-west-1"}
    )

    foreach ($resource in $defaultResources) {
        Write-Host "🔍 Vérification: $($resource.type) - $($resource.name)" -ForegroundColor Cyan

        switch ($resource.type) {
            "CodeBuild Project" {
                $exists = aws codebuild batch-get-projects --names $resource.name --region $resource.region 2>$null
                if ($exists -and $exists -notlike "*not found*") {
                    Write-Host "  ✅ Trouvé: $($resource.name)" -ForegroundColor Yellow
                    if (-not $DryRun) {
                        Write-Host "  🗑️  Suppression..." -ForegroundColor Red
                        aws codebuild delete-project --name $resource.name --region $resource.region
                    }
                }
            }
            "IAM Role" {
                $exists = aws iam get-role --role-name $resource.name 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✅ Trouvé: $($resource.name)" -ForegroundColor Yellow
                    if (-not $DryRun) {
                        Write-Host "  🗑️  Détachement des policies..." -ForegroundColor Red
                        aws iam detach-role-policy --role-name $resource.name --policy-arn "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess" 2>$null
                        aws iam detach-role-policy --role-name $resource.name --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess" 2>$null
                        aws iam delete-role-policy --role-name $resource.name --policy-name "ECRBuildAccess" 2>$null
                        aws iam delete-role --role-name $resource.name
                    }
                }
            }
            "ECR Repository" {
                $exists = aws ecr describe-repositories --repository-names $resource.name --region $resource.region 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✅ Trouvé: $($resource.name)" -ForegroundColor Yellow
                    if (-not $DryRun) {
                        Write-Host "  🗑️  Suppression (avec --force)..." -ForegroundColor Red
                        aws ecr delete-repository --repository-name $resource.name --region $resource.region --force
                    }
                }
            }
        }
    }

    if ($DryRun) {
        Write-Host ""
        Write-Host "🔍 DRY RUN - Aucune ressource supprimée" -ForegroundColor Yellow
        Write-Host "Pour supprimer réellement: .\scripts\cleanup-aws-resources.ps1" -ForegroundColor Cyan
    }

    return
}

# Charger le fichier de ressources
try {
    $resourcesData = Get-Content $ResourcesFile | ConvertFrom-Json
    Write-Host "📋 Ressources trouvées dans $ResourcesFile (créées le $($resourcesData.timestamp))" -ForegroundColor Cyan
} catch {
    Write-Host "❌ Erreur lecture fichier: $_" -ForegroundColor Red
    exit 1
}

if (-not $Force) {
    Write-Host ""
    Write-Host "⚠️  ATTENTION: Cette opération va supprimer TOUTES les ressources suivantes:" -ForegroundColor Red
    foreach ($resource in $resourcesData.resources) {
        Write-Host "  - $($resource.type): $($resource.name) (région: $($resource.region))" -ForegroundColor Yellow
    }
    Write-Host ""

    if ($DryRun) {
        Write-Host "🔍 Mode DRY RUN - simulation seulement" -ForegroundColor Green
    } else {
        Write-Host "❓ Êtes-vous sûr de vouloir continuer? [y/N]" -ForegroundColor Red -NoNewline
        $confirmation = Read-Host " "
        if ($confirmation -ne "y" -and $confirmation -ne "Y") {
            Write-Host "❌ Opération annulée" -ForegroundColor Yellow
            exit 0
        }
    }
}

Write-Host ""
Write-Host "🗑️  Début du nettoyage..." -ForegroundColor Red

$deletedCount = 0
$errorCount = 0

foreach ($resource in $resourcesData.resources) {
    Write-Host "🧹 Traitement: $($resource.type) - $($resource.name)" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "  🔍 [DRY RUN] Serait supprimé" -ForegroundColor Yellow
        $deletedCount++
        continue
    }

    try {
        switch ($resource.type) {
            "CodeBuild Project" {
                Write-Host "  🗑️  Suppression projet CodeBuild..." -ForegroundColor Red
                aws codebuild delete-project --name $resource.name --region $resource.region
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✅ Supprimé avec succès" -ForegroundColor Green
                    $deletedCount++
                } else {
                    Write-Host "  ⚠️  Erreur ou déjà supprimé" -ForegroundColor Yellow
                }
            }

            "IAM Role" {
                Write-Host "  🗑️  Suppression rôle IAM..." -ForegroundColor Red

                # Détacher policies managées
                aws iam detach-role-policy --role-name $resource.name --policy-arn "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess" 2>$null
                aws iam detach-role-policy --role-name $resource.name --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess" 2>$null

                # Supprimer policies inline
                aws iam delete-role-policy --role-name $resource.name --policy-name "ECRBuildAccess" 2>$null

                # Supprimer le rôle
                aws iam delete-role --role-name $resource.name

                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✅ Supprimé avec succès" -ForegroundColor Green
                    $deletedCount++
                } else {
                    Write-Host "  ⚠️  Erreur ou déjà supprimé" -ForegroundColor Yellow
                }
            }

            "ECR Repository" {
                Write-Host "  🗑️  Suppression repository ECR..." -ForegroundColor Red
                aws ecr delete-repository --repository-name $resource.name --region $resource.region --force
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✅ Supprimé avec succès" -ForegroundColor Green
                    $deletedCount++
                } else {
                    Write-Host "  ⚠️  Erreur ou déjà supprimé" -ForegroundColor Yellow
                }
            }

            default {
                Write-Host "  ⚠️  Type de ressource non supporté: $($resource.type)" -ForegroundColor Yellow
                $errorCount++
            }
        }
    } catch {
        Write-Host "  ❌ Erreur: $_" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host ""
if ($DryRun) {
    Write-Host "🔍 DRY RUN Terminé - $deletedCount ressources seraient supprimées" -ForegroundColor Green
    Write-Host "Pour supprimer réellement: .\scripts\cleanup-aws-resources.ps1" -ForegroundColor Cyan
} else {
    Write-Host "✅ Nettoyage terminé!" -ForegroundColor Green
    Write-Host "📊 Résultats:" -ForegroundColor Cyan
    Write-Host "  - Ressources supprimées: $deletedCount" -ForegroundColor Green
    Write-Host "  - Erreurs: $errorCount" -ForegroundColor Red

    # Supprimer le fichier de tracking après nettoyage réussi
    if ($errorCount -eq 0) {
        Remove-Item $ResourcesFile -ErrorAction SilentlyContinue
        Write-Host "🗑️  Fichier de tracking supprimé" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "💡 Commandes utiles pour vérifier le nettoyage:" -ForegroundColor Yellow
Write-Host "  - aws codebuild list-projects --region eu-west-1" -ForegroundColor White
Write-Host "  - aws iam list-roles | grep CodeBuild" -ForegroundColor White
Write-Host "  - aws ecr describe-repositories --region eu-west-1" -ForegroundColor White