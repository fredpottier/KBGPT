#Requires -Version 5.1
<#
.SYNOPSIS
    Déploie l'infrastructure KnowWhere OSMOSE sur AWS via CloudFormation (1 commande)

.DESCRIPTION
    Ce script:
    1. Crée le stack CloudFormation (EC2, Security Group, Elastic IP, IAM Role)
    2. Attend que l'instance soit ready (~5-10 min)
    3. Transfère docker-compose.ecr.yml + .env.production
    4. Démarre les conteneurs Docker
    5. Retourne l'IP publique pour accès

.PARAMETER StackName
    Nom du stack CloudFormation (ex: "knowbase-test-perf")

.PARAMETER InstanceType
    Type instance EC2 (default: t3.2xlarge pour tests perf)

.PARAMETER KeyPairName
    Nom de la clé SSH EC2 (doit exister dans votre compte AWS)

.PARAMETER KeyPath
    Chemin local vers le fichier .pem de la clé SSH

.PARAMETER YourPublicIP
    Votre IP publique pour SSH (format: X.X.X.X/32)
    Si non fourni, détecté automatiquement

.PARAMETER Region
    Région AWS (default: eu-west-1)

.PARAMETER AutoDestroyAfterHours
    Auto-destruction du stack après X heures (default: 4, 0 = désactivé)
    ⚠️ IMPORTANT: Permet d'éviter les coûts imprévus si vous oubliez de détruire le stack

.EXAMPLE
    .\deploy-cloudformation.ps1 `
        -StackName "knowbase-test-perf" `
        -KeyPairName "my-ec2-key" `
        -KeyPath "C:\path\to\my-ec2-key.pem"

.EXAMPLE
    # Avec instance type custom
    .\deploy-cloudformation.ps1 `
        -StackName "knowbase-prod" `
        -InstanceType "m5.2xlarge" `
        -KeyPairName "prod-key" `
        -KeyPath ".\prod-key.pem"

.EXAMPLE
    # Avec auto-destruction dans 8 heures
    .\deploy-cloudformation.ps1 `
        -StackName "knowbase-test" `
        -KeyPairName "my-key" `
        -KeyPath ".\my-key.pem" `
        -AutoDestroyAfterHours 8

.EXAMPLE
    # Sans auto-destruction (doit être détruit manuellement)
    .\deploy-cloudformation.ps1 `
        -StackName "knowbase-longterm" `
        -KeyPairName "my-key" `
        -KeyPath ".\my-key.pem" `
        -AutoDestroyAfterHours 0
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$false)]
    [ValidateSet('t3.xlarge', 't3.2xlarge', 'm5.2xlarge', 'c5.4xlarge')]
    [string]$InstanceType = 't3.2xlarge',

    [Parameter(Mandatory=$true)]
    [string]$KeyPairName,

    [Parameter(Mandatory=$true)]
    [string]$KeyPath,

    [Parameter(Mandatory=$false)]
    [string]$YourPublicIP,

    [Parameter(Mandatory=$false)]
    [string]$Region = 'eu-west-1',

    [Parameter(Mandatory=$false)]
    [int]$RootVolumeSize = 30,

    [Parameter(Mandatory=$false)]
    [int]$DataVolumeSize = 100,

    [Parameter(Mandatory=$false)]
    [int]$AutoDestroyAfterHours = 4
)

$ErrorActionPreference = 'Stop'

# ============================================================================
# CONFIGURATION
# ============================================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$CloudFormationTemplate = Join-Path $ProjectRoot "cloudformation\knowbase-stack.yaml"
$DockerComposeFile = Join-Path $ProjectRoot "docker-compose.ecr.yml"
$MonitoringDir = Join-Path $ProjectRoot "monitoring"
$EnvFile = Join-Path $ProjectRoot ".env.production"

# Variables globales pour nettoyage S3
$script:s3Bucket = $null
$script:s3Key = $null

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
    Write-Step "ÉTAPE 1/7: Vérification prérequis"

    # AWS CLI
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Write-Error-Custom "AWS CLI non installé. Installez-le depuis https://aws.amazon.com/cli/"
        exit 1
    }
    Write-Success "AWS CLI installé"

    # AWS Credentials
    try {
        $null = aws sts get-caller-identity 2>$null
        Write-Success "AWS credentials configurées"
    } catch {
        Write-Error-Custom "AWS credentials non configurées. Exécutez 'aws configure'"
        exit 1
    }

    # CloudFormation template
    if (-not (Test-Path $CloudFormationTemplate)) {
        Write-Error-Custom "Template CloudFormation non trouvé: $CloudFormationTemplate"
        exit 1
    }
    Write-Success "Template CloudFormation trouvé"

    # docker-compose.ecr.yml
    if (-not (Test-Path $DockerComposeFile)) {
        Write-Error-Custom "docker-compose.ecr.yml non trouvé: $DockerComposeFile"
        exit 1
    }
    Write-Success "docker-compose.ecr.yml trouvé"

    # monitoring/
    if (-not (Test-Path $MonitoringDir)) {
        Write-Error-Custom "Répertoire monitoring/ non trouvé: $MonitoringDir"
        exit 1
    }
    Write-Success "Répertoire monitoring/ trouvé"

    # .env.production
    if (-not (Test-Path $EnvFile)) {
        Write-Error-Custom ".env.production non trouvé: $EnvFile"
        Write-Warning-Custom "Créez-le en copiant .env.ecr.example et en configurant vos API keys"
        exit 1
    }
    Write-Success ".env.production trouvé"

    # SSH Key
    if (-not (Test-Path $KeyPath)) {
        Write-Error-Custom "Clé SSH non trouvée: $KeyPath"
        exit 1
    }
    Write-Success "Clé SSH trouvée: $KeyPath"
}

function Get-MyPublicIP {
    Write-Step "ÉTAPE 2/7: Détection IP publique"

    if ($YourPublicIP) {
        Write-Success "IP fournie: $YourPublicIP"
        return $YourPublicIP
    }

    try {
        $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content.Trim()
        $ipCidr = "$ip/32"
        Write-Success "IP détectée: $ipCidr"
        return $ipCidr
    } catch {
        Write-Error-Custom "Impossible de détecter votre IP publique automatiquement"
        Write-Warning-Custom "Fournissez-la via -YourPublicIP 'X.X.X.X/32'"
        exit 1
    }
}

function Get-ECRAccountID {
    # Lire depuis .env.production
    if (Test-Path $EnvFile) {
        $content = Get-Content $EnvFile | Where-Object { $_ -match '^AWS_ACCOUNT_ID=' }
        if ($content) {
            $accountId = $content -replace 'AWS_ACCOUNT_ID=', ''
            return $accountId
        }
    }

    # Fallback: détecter depuis AWS CLI
    try {
        $accountId = (aws sts get-caller-identity --query Account --output text 2>$null)
        return $accountId
    } catch {
        return "715927975014"  # Default from doc
    }
}

function Deploy-CloudFormationStack {
    param(
        [string]$IPCidr
    )

    Write-Step "ÉTAPE 3/7: Création stack CloudFormation"

    $AccountID = Get-ECRAccountID
    Write-Host "Account ID ECR: $AccountID"

    $params = @(
        "ParameterKey=InstanceType,ParameterValue=$InstanceType",
        "ParameterKey=KeyPairName,ParameterValue=$KeyPairName",
        "ParameterKey=YourPublicIP,ParameterValue=$IPCidr",
        "ParameterKey=RootVolumeSize,ParameterValue=$RootVolumeSize",
        "ParameterKey=DataVolumeSize,ParameterValue=$DataVolumeSize",
        "ParameterKey=ECRAccountID,ParameterValue=$AccountID",
        "ParameterKey=ECRRegion,ParameterValue=$Region",
        "ParameterKey=AutoDestroyAfterHours,ParameterValue=$AutoDestroyAfterHours"
    )

    Write-Host "Création du stack '$StackName'..."
    Write-Host "Instance Type: $InstanceType"
    Write-Host "Région: $Region"
    if ($AutoDestroyAfterHours -gt 0) {
        Write-Host "⚠️  Auto-destruction: ACTIVÉE dans $AutoDestroyAfterHours heures" -ForegroundColor Yellow
    } else {
        Write-Host "Auto-destruction: DÉSACTIVÉE (pensez à détruire manuellement)" -ForegroundColor Cyan
    }

    try {
        # AWS CLI v2 sur Windows a des problèmes critiques avec file:// et UTF-8
        # Solution : Sauvegarder le template dans S3 temporairement

        Write-Host "Préparation upload template vers S3..."

        # Nom unique pour le bucket temporaire
        $script:s3Bucket = "knowbase-cloudformation-templates-temp"
        $script:s3Key = "$StackName-$(Get-Date -Format 'yyyyMMddHHmmss').yaml"

        # Vérifier si le bucket existe
        Write-Host "Vérification bucket S3: $s3Bucket..."

        # Désactiver temporairement ErrorActionPreference pour cette commande
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'

        $bucketCheckError = $null
        aws s3api head-bucket --bucket $s3Bucket --region $Region 2>&1 | Out-Null
        $bucketExists = ($LASTEXITCODE -eq 0)

        $ErrorActionPreference = $previousErrorAction

        if (-not $bucketExists) {
            Write-Host "Bucket n'existe pas, création..."

            $ErrorActionPreference = 'Continue'
            $createResult = aws s3 mb "s3://$s3Bucket" --region $Region 2>&1
            $createSuccess = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = $previousErrorAction

            if (-not $createSuccess) {
                Write-Error-Custom "Échec création bucket S3"
                Write-Host "Erreur: $createResult"
                throw "Impossible de créer le bucket S3"
            }

            Write-Success "Bucket créé: $s3Bucket"

            # Ajouter policy pour permettre à CloudFormation de lire
            Write-Host "Configuration permissions bucket pour CloudFormation..."
            $bucketPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "cloudformation.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::$s3Bucket/*"
        }
    ]
}
"@
            $bucketPolicy | Out-File -FilePath "$env:TEMP\bucket-policy.json" -Encoding UTF8 -NoNewline
            aws s3api put-bucket-policy --bucket $s3Bucket --policy "file://$env:TEMP\bucket-policy.json" --region $Region 2>&1 | Out-Null
            Remove-Item "$env:TEMP\bucket-policy.json" -ErrorAction SilentlyContinue

            # Attendre que le bucket soit prêt
            Start-Sleep -Seconds 3
        } else {
            Write-Success "Bucket existe déjà: $s3Bucket"
        }

        # Upload template vers S3 (sans ACL, permissions via bucket policy)
        Write-Host "Upload template vers s3://$s3Bucket/$s3Key..."

        $ErrorActionPreference = 'Continue'
        $uploadResult = aws s3 cp $CloudFormationTemplate "s3://$s3Bucket/$s3Key" --region $Region 2>&1
        $uploadSuccess = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $previousErrorAction

        if (-not $uploadSuccess) {
            Write-Error-Custom "Échec upload template vers S3"
            Write-Host "Erreur: $uploadResult"
            throw "Impossible d'uploader le template vers S3"
        }

        Write-Success "Template uploadé avec succès"

        # URL S3 du template
        $templateUrl = "https://$s3Bucket.s3.$Region.amazonaws.com/$s3Key"

        Write-Host "Template disponible sur: $templateUrl"

        # Créer le stack avec template-url
        Write-Host "`nCréation du stack CloudFormation..."

        $ErrorActionPreference = 'Continue'
        $stackResult = aws cloudformation create-stack `
            --stack-name $StackName `
            --template-url $templateUrl `
            --parameters $params `
            --capabilities CAPABILITY_NAMED_IAM `
            --region $Region `
            --tags "Key=Project,Value=KnowWhere" "Key=ManagedBy,Value=CloudFormation" 2>&1
        $stackSuccess = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $previousErrorAction

        if (-not $stackSuccess) {
            Write-Error-Custom "Échec création stack CloudFormation"
            Write-Host "Erreur détaillée:"
            Write-Host $stackResult
            throw "Impossible de créer le stack CloudFormation"
        }

        Write-Host "Stack ID: $stackResult"

        Write-Success "Stack créé, attente de CREATE_COMPLETE..."

        # Wait for stack creation
        Write-Host "Attente création stack (5-10 min)..." -NoNewline
        $startTime = Get-Date

        while ($true) {
            Start-Sleep -Seconds 15
            Write-Host "." -NoNewline

            $status = (aws cloudformation describe-stacks `
                --stack-name $StackName `
                --region $Region `
                --query "Stacks[0].StackStatus" `
                --output text 2>$null)

            if ($status -eq "CREATE_COMPLETE") {
                $elapsed = ((Get-Date) - $startTime).TotalMinutes
                Write-Host ""
                Write-Success "Stack créé avec succès en $([math]::Round($elapsed, 1)) minutes"
                return $true
            }

            if ($status -like "*FAILED*" -or $status -like "*ROLLBACK*") {
                Write-Host ""
                Write-Error-Custom "Échec création stack: $status"

                # Afficher les événements d'erreur
                Write-Host "`nÉvénements récents:"
                aws cloudformation describe-stack-events `
                    --stack-name $StackName `
                    --region $Region `
                    --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" `
                    --output table

                exit 1
            }

            # Timeout après 20 minutes
            if (((Get-Date) - $startTime).TotalMinutes -gt 20) {
                Write-Host ""
                Write-Error-Custom "Timeout création stack (>20 min)"
                exit 1
            }
        }

    } catch {
        Write-Error-Custom "Erreur création stack: $_"
        exit 1
    }
}

function Get-StackOutputs {
    Write-Step "ÉTAPE 4/7: Récupération informations stack"

    try {
        $outputs = aws cloudformation describe-stacks `
            --stack-name $StackName `
            --region $Region `
            --query "Stacks[0].Outputs" `
            --output json | ConvertFrom-Json

        $result = @{}
        foreach ($output in $outputs) {
            $result[$output.OutputKey] = $output.OutputValue
        }

        Write-Success "Informations stack récupérées:"
        Write-Host "  Instance ID: $($result.InstanceId)"
        Write-Host "  Public IP (Elastic): $($result.PublicIP)"
        Write-Host "  Security Group: $($result.SecurityGroupId)"

        return $result

    } catch {
        Write-Error-Custom "Erreur récupération outputs: $_"
        exit 1
    }
}

function Wait-ForInstanceReady {
    param([string]$InstanceId)

    Write-Step "ÉTAPE 5/7: Attente instance EC2 ready"

    Write-Host "Attente status checks 2/2..." -NoNewline

    $maxWait = 300  # 5 minutes max
    $waited = 0

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 10
        Write-Host "." -NoNewline
        $waited += 10

        $status = (aws ec2 describe-instance-status `
            --instance-ids $InstanceId `
            --region $Region `
            --query "InstanceStatuses[0].InstanceStatus.Status" `
            --output text 2>$null)

        if ($status -eq "ok") {
            Write-Host ""
            Write-Success "Instance ready"
            Start-Sleep -Seconds 30  # Attendre 30s pour User Data
            return $true
        }
    }

    Write-Host ""
    Write-Warning-Custom "Instance status non 'ok' après 5 min, continue quand même..."
    return $true
}

function Deploy-Application {
    param(
        [string]$PublicIP
    )

    Write-Step "ÉTAPE 6/7: Déploiement application sur EC2"

    # Fix Windows path for SSH
    $KeyPathUnix = $KeyPath -replace '\\', '/'

    # Test SSH connection
    Write-Host "Test connexion SSH..." -NoNewline
    $maxRetries = 5
    $retry = 0

    while ($retry -lt $maxRetries) {
        try {
            $null = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@$PublicIP "echo 'connected'" 2>$null
            Write-Host ""
            Write-Success "Connexion SSH établie"
            break
        } catch {
            $retry++
            if ($retry -lt $maxRetries) {
                Write-Host "." -NoNewline
                Start-Sleep -Seconds 10
            } else {
                Write-Host ""
                Write-Error-Custom "Impossible de se connecter en SSH après $maxRetries tentatives"
                Write-Warning-Custom "Vérifiez que le Security Group autorise votre IP"
                exit 1
            }
        }
    }

    # Wait for UserData to complete and create directories
    Write-Host "Vérification UserData (création répertoires)..."
    $maxWaitUserData = 10
    $waitedUserData = 0
    $userDataComplete = $false

    while ($waitedUserData -lt $maxWaitUserData -and -not $userDataComplete) {
        $checkDir = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP "test -d /home/ubuntu/knowbase && echo 'exists'" 2>$null
        if ($checkDir -eq "exists") {
            Write-Success "Répertoires créés par UserData"
            $userDataComplete = $true
        } else {
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 10
            $waitedUserData++
        }
    }

    # Create directory if UserData didn't complete in time
    if (-not $userDataComplete) {
        Write-Host ""
        Write-Warning-Custom "UserData non terminé, création manuelle des répertoires..."
        ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP "mkdir -p /home/ubuntu/knowbase /data/neo4j /data/qdrant /data/redis && sudo chown -R ubuntu:ubuntu /home/ubuntu/knowbase /data"
        Write-Success "Répertoires créés manuellement"
    }

    # Transfer files
    Write-Host "Transfert fichiers..."
    scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
        $DockerComposeFile ubuntu@${PublicIP}:/home/ubuntu/knowbase/docker-compose.yml

    scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
        $EnvFile ubuntu@${PublicIP}:/home/ubuntu/knowbase/.env

    # Transfer monitoring docker-compose
    $MonitoringComposeFile = Join-Path $ProjectRoot "docker-compose.monitoring.yml"
    scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
        $MonitoringComposeFile ubuntu@${PublicIP}:/home/ubuntu/knowbase/docker-compose.monitoring.yml

    # Transfer monitoring config
    Write-Host "Transfert configuration monitoring..."
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP "mkdir -p /home/ubuntu/knowbase/monitoring/dashboards"

    # Transfer monitoring YAML files individually
    Get-ChildItem "$MonitoringDir\*.yml" | ForEach-Object {
        Write-Host "  Transfert: $($_.Name)"
        scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
            "`"$($_.FullName)`"" ubuntu@${PublicIP}:/home/ubuntu/knowbase/monitoring/
    }

    # Transfer dashboards JSON files individually
    Get-ChildItem "$MonitoringDir\dashboards\*.json" | ForEach-Object {
        Write-Host "  Transfert: $($_.Name)"
        scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
            "`"$($_.FullName)`"" ubuntu@${PublicIP}:/home/ubuntu/knowbase/monitoring/dashboards/
    }

    Write-Success "Configuration monitoring transférée"

    # Transfer config directory
    Write-Host "Transfert fichiers configuration..."
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP "mkdir -p /home/ubuntu/knowbase/config"

    $ConfigDir = Join-Path $ProjectRoot "config"
    if (Test-Path $ConfigDir) {
        Get-ChildItem "$ConfigDir\*.yaml" | ForEach-Object {
            $filePath = $_.FullName.Replace('\', '/')
            Write-Host "  Transfert: $($_.Name)"
            scp -i $KeyPathUnix -o StrictHostKeyChecking=no `
                "`"$($_.FullName)`"" ubuntu@${PublicIP}:/home/ubuntu/knowbase/config/
        }
        Write-Success "Fichiers configuration transférés"
    }

    # Configure CORS_ORIGINS avec l'IP EC2 publique
    Write-Host "Configuration CORS_ORIGINS avec IP EC2..."
    $corsOrigins = "http://${PublicIP}:3000,http://${PublicIP}:8501"
    $updateEnvCmd = "cd /home/ubuntu/knowbase && sed -i 's|CORS_ORIGINS=.*|CORS_ORIGINS=$corsOrigins|g' .env"
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP $updateEnvCmd
    Write-Success "CORS_ORIGINS configuré: $corsOrigins"

    # Configure Docker permissions (l'utilisateur ubuntu doit être dans le groupe docker)
    Write-Host "Configuration permissions Docker..."
    $dockerPermsCmd = "sudo usermod -aG docker ubuntu"
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP $dockerPermsCmd
    Write-Success "Permissions Docker configurées"

    # Authenticate Docker to ECR
    Write-Host "Authentification Docker vers ECR..."
    $AccountID = Get-ECRAccountID
    $ecrLoginCmd = "aws ecr get-login-password --region $Region | sudo docker login --username AWS --password-stdin ${AccountID}.dkr.ecr.${Region}.amazonaws.com"
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP $ecrLoginCmd
    Write-Success "Docker authentifié vers ECR"

    # Start containers (utiliser sudo car la session SSH actuelle n'a pas encore les nouvelles permissions)
    Write-Host "Démarrage conteneurs Docker (3-5 min)..."
    $dockerCommand = "cd /home/ubuntu/knowbase && sudo docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml pull && sudo docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d"
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$PublicIP $dockerCommand
    Write-Success "Conteneurs démarrés (avec monitoring stack)"

    # Wait for services
    Write-Host "Attente services ready (2 min)..."
    Start-Sleep -Seconds 120

    Write-Success "Déploiement terminé"
}

function Show-Summary {
    param([hashtable]$Outputs)

    Write-Step "ÉTAPE 7/7: Résumé déploiement"

    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Green
    Write-Host "║   ✅ DÉPLOIEMENT RÉUSSI                                   ║" -ForegroundColor $Green
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Green
    Write-Host ""

    Write-Host "📋 INFORMATIONS ACCÈS" -ForegroundColor $Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
    Write-Host ""
    Write-Host "Frontend (Next.js)    : " -NoNewline
    Write-Host $Outputs.FrontendURL -ForegroundColor $Yellow
    Write-Host "API Backend (Swagger) : " -NoNewline
    Write-Host $Outputs.BackendURL -ForegroundColor $Yellow
    Write-Host "Grafana (Monitoring)  : " -NoNewline
    Write-Host $Outputs.GrafanaURL -ForegroundColor $Yellow
    Write-Host "Neo4j Browser         : " -NoNewline
    Write-Host $Outputs.Neo4jBrowserURL -ForegroundColor $Yellow
    Write-Host "Qdrant Dashboard      : " -NoNewline
    Write-Host $Outputs.QdrantDashboardURL -ForegroundColor $Yellow
    Write-Host ""
    Write-Host "SSH                   : " -NoNewline
    Write-Host $Outputs.SSHCommand -ForegroundColor $Yellow
    Write-Host ""

    Write-Host "💰 COÛTS" -ForegroundColor $Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
    Write-Host ""
    Write-Host "Si running 24/7       : ~`$120-130/mois" -ForegroundColor $Yellow
    Write-Host "Session 3h de tests   : ~`$0.50" -ForegroundColor $Green
    Write-Host ""

    # Afficher info auto-destruction
    if ($Outputs.AutoDestroyStatus) {
        Write-Host "⏰ AUTO-DESTRUCTION" -ForegroundColor $Cyan
        Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Cyan
        Write-Host ""
        Write-Host $Outputs.AutoDestroyStatus -ForegroundColor $Yellow
        Write-Host ""
    }

    Write-Host "⚠️  Pour détruire manuellement le stack :" -ForegroundColor $Yellow
    Write-Host "    .\scripts\aws\destroy-cloudformation.ps1 -StackName '$StackName'" -ForegroundColor $Yellow
    Write-Host ""
}

# ============================================================================
# MAIN SCRIPT
# ============================================================================

try {
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Cyan
    Write-Host "║   KnowWhere OSMOSE - Déploiement CloudFormation          ║" -ForegroundColor $Cyan
    Write-Host "║   One-Click Deploy AWS Infrastructure                     ║" -ForegroundColor $Cyan
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Cyan
    Write-Host ""

    # 1. Prerequisites
    Test-Prerequisites

    # 2. Detect IP
    $IPCidr = Get-MyPublicIP

    # 3. Deploy CloudFormation Stack
    Deploy-CloudFormationStack -IPCidr $IPCidr

    # 4. Get Outputs
    $Outputs = Get-StackOutputs

    # 5. Wait for instance
    Wait-ForInstanceReady -InstanceId $Outputs.InstanceId

    # 6. Deploy Application
    Deploy-Application -PublicIP $Outputs.PublicIP

    # 7. Show Summary
    Show-Summary -Outputs $Outputs

    Write-Host ""
    Write-Host "🎉 Vous pouvez maintenant accéder à votre application !" -ForegroundColor $Green
    Write-Host ""

    # Nettoyage template S3 temporaire
    if ($s3Bucket -and $s3Key) {
        Write-Host "`n🧹 Nettoyage template S3 temporaire..." -NoNewline
        aws s3 rm "s3://$s3Bucket/$s3Key" --region $Region 2>$null
        Write-Host " OK"
    }

    exit 0

} catch {
    Write-Host ''
    $errorMsg = $_.Exception.Message
    Write-Error-Custom ('Erreur inattendue: ' + $errorMsg)
    Write-Host $_.ScriptStackTrace
    exit 1
}
