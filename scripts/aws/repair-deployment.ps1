#Requires -Version 5.1
<#
.SYNOPSIS
    Répare un déploiement CloudFormation KnowWhere si l'application n'est pas accessible

.DESCRIPTION
    Ce script diagnostique et répare les problèmes courants:
    - Répertoires manquants
    - Fichiers de configuration non transférés
    - Conteneurs Docker non démarrés
    - Logs UserData pour diagnostic

.PARAMETER StackName
    Nom du stack CloudFormation déployé

.PARAMETER KeyPath
    Chemin vers le fichier .pem de la clé SSH

.PARAMETER Region
    Région AWS (default: eu-west-1)

.EXAMPLE
    .\repair-deployment.ps1 -StackName "Osmos" -KeyPath ".\ma-cle.pem"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$true)]
    [string]$KeyPath,

    [Parameter(Mandatory=$false)]
    [string]$Region = 'eu-west-1'
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$DockerComposeFile = Join-Path $ProjectRoot "docker-compose.ecr.yml"
$EnvFile = Join-Path $ProjectRoot ".env.production"
$ConfigDir = Join-Path $ProjectRoot "config"

# Colors
$Green = [ConsoleColor]::Green
$Yellow = [ConsoleColor]::Yellow
$Red = [ConsoleColor]::Red
$Cyan = [ConsoleColor]::Cyan

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

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Cyan
Write-Host "║   KnowWhere OSMOSE - Réparation Déploiement              ║" -ForegroundColor $Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Cyan
Write-Host ""

# 1. Get Stack Public IP
Write-Step "ÉTAPE 1/5: Récupération IP du stack"

try {
    $publicIP = aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region `
        --query "Stacks[0].Outputs[?OutputKey=='PublicIP'].OutputValue" `
        --output text

    if (-not $publicIP) {
        Write-Error-Custom "Impossible de trouver l'IP publique du stack '$StackName'"
        exit 1
    }

    Write-Success "IP publique: $publicIP"
} catch {
    Write-Error-Custom "Stack '$StackName' non trouvé dans la région $Region"
    exit 1
}

$KeyPathUnix = $KeyPath -replace '\\', '/'

# 2. Test SSH Connection
Write-Step "ÉTAPE 2/5: Test connexion SSH"

try {
    $null = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@$publicIP "echo 'connected'" 2>$null
    Write-Success "Connexion SSH OK"
} catch {
    Write-Error-Custom "Impossible de se connecter en SSH à $publicIP"
    Write-Warning-Custom "Vérifiez que le Security Group autorise votre IP"
    exit 1
}

# 3. Check UserData Logs
Write-Step "ÉTAPE 3/5: Diagnostic UserData"

Write-Host "Récupération logs UserData..."
$userDataLog = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo cat /var/log/user-data.log 2>/dev/null || echo 'NO_LOG'"

if ($userDataLog -eq "NO_LOG") {
    Write-Warning-Custom "Logs UserData non trouvés (UserData peut ne pas avoir démarré)"
} else {
    $lastLines = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo tail -10 /var/log/user-data.log"
    Write-Host "`nDernières lignes UserData:"
    Write-Host $lastLines -ForegroundColor $Yellow

    if ($userDataLog -like "*User Data Script Completed Successfully*") {
        Write-Success "UserData exécuté avec succès"
    } else {
        Write-Warning-Custom "UserData incomplet ou en erreur"
    }
}

# 4. Check and Create Directories + Fix Permissions
Write-Step "ÉTAPE 4/5: Vérification/Création répertoires et permissions"

$dirCheck = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "test -d /home/ubuntu/knowbase && echo 'exists'"

if ($dirCheck -eq "exists") {
    Write-Success "Répertoire /home/ubuntu/knowbase existe"
} else {
    Write-Warning-Custom "Répertoire manquant, création..."
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "mkdir -p /home/ubuntu/knowbase"
    Write-Success "Répertoire knowbase créé"
}

# Create /data directories with sudo
Write-Host "Vérification répertoires /data..."
ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo mkdir -p /data/neo4j /data/qdrant /data/redis"
ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo chown -R ubuntu:ubuntu /home/ubuntu/knowbase /data"
Write-Success "Permissions répertoires configurées"

# Check Docker
Write-Host "`nVérification Docker..."
$dockerVersion = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "docker --version 2>/dev/null || echo 'NOT_INSTALLED'"

if ($dockerVersion -eq "NOT_INSTALLED") {
    Write-Error-Custom "Docker non installé (UserData non terminé)"
    Write-Warning-Custom "Attendez quelques minutes et relancez ce script"
    exit 1
} else {
    Write-Success "Docker installé: $dockerVersion"
}

# Fix Docker permissions (add ubuntu to docker group)
Write-Host "Vérification permissions Docker..."
$dockerGroupCheck = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "groups | grep docker || echo 'NOT_IN_GROUP'"

if ($dockerGroupCheck -like "*NOT_IN_GROUP*") {
    Write-Warning-Custom "Utilisateur ubuntu pas dans le groupe docker, correction..."
    ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo usermod -aG docker ubuntu"
    Write-Success "Utilisateur ajouté au groupe docker"
    Write-Warning-Custom "Une nouvelle session SSH est nécessaire pour appliquer les permissions"
} else {
    Write-Success "Permissions Docker OK"
}

# Login to ECR
Write-Host "`nConnexion à ECR..."
$ecrLogin = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "aws ecr get-login-password --region eu-west-1 | sudo docker login --username AWS --password-stdin 715927975014.dkr.ecr.eu-west-1.amazonaws.com 2>&1"
if ($ecrLogin -like "*Login Succeeded*") {
    Write-Success "Connecté à ECR"
} else {
    Write-Warning-Custom "Login ECR avec sudo (permissions docker en attente)"
}

# 5. Transfer Files
Write-Step "ÉTAPE 5/5: Transfert fichiers et démarrage"

Write-Host "Transfert docker-compose.yml..."
scp -i $KeyPathUnix -o StrictHostKeyChecking=no $DockerComposeFile ubuntu@${publicIP}:/home/ubuntu/knowbase/docker-compose.yml

Write-Host "Transfert .env..."
scp -i $KeyPathUnix -o StrictHostKeyChecking=no $EnvFile ubuntu@${publicIP}:/home/ubuntu/knowbase/.env

Write-Host "Transfert config/..."
if (Test-Path $ConfigDir) {
    scp -i $KeyPathUnix -o StrictHostKeyChecking=no -r $ConfigDir ubuntu@${publicIP}:/home/ubuntu/knowbase/
}

Write-Success "Fichiers transférés"

# Update .env with correct IP (configure CORS_ORIGINS for both frontend ports)
Write-Host "`nConfiguration .env avec IP EC2..."
$corsOrigins = "http://${publicIP}:3000,http://${publicIP}:8501"
$updateEnvCmd = "cd /home/ubuntu/knowbase && sed -i 's|CORS_ORIGINS=.*|CORS_ORIGINS=$corsOrigins|g' .env"
ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP $updateEnvCmd
Write-Success ".env configuré (CORS_ORIGINS=$corsOrigins)"

# Check if containers are running
Write-Host "`nVérification conteneurs Docker..."
$runningContainers = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "sudo docker ps --format '{{.Names}}' 2>/dev/null || echo ''"

if ($runningContainers) {
    Write-Host "Conteneurs actuels:"
    Write-Host $runningContainers -ForegroundColor $Yellow

    $response = Read-Host "`nRedémarrer les conteneurs? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Write-Host "Arrêt conteneurs existants..."
        ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "cd /home/ubuntu/knowbase && sudo docker-compose down"
    }
}

# Start containers (with sudo because docker group may not be active yet)
Write-Host "`nDémarrage conteneurs Docker..."
Write-Warning-Custom "Utilisation de sudo (permissions docker en cours d'activation)"

Write-Host "Pull des images ECR (peut prendre 2-3 min)..." -NoNewline
$pullCmd = "cd /home/ubuntu/knowbase && sudo docker-compose pull > /tmp/docker-pull.log 2>&1 && echo 'PULL_OK' || echo 'PULL_FAILED'"
$pullResult = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP $pullCmd

if ($pullResult -like "*PULL_OK*") {
    Write-Host ""
    Write-Success "Images téléchargées"
} else {
    Write-Host ""
    Write-Warning-Custom "Erreur pull images (vérifier /tmp/docker-pull.log sur l'instance)"
}

Write-Host "Démarrage des conteneurs..." -NoNewline
$startCmd = "cd /home/ubuntu/knowbase && sudo docker-compose up -d > /tmp/docker-start.log 2>&1 && echo 'START_OK' || echo 'START_FAILED'"
$startResult = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP $startCmd

if ($startResult -like "*START_OK*") {
    Write-Host ""
    Write-Success "Conteneurs démarrés"
} else {
    Write-Host ""
    Write-Error-Custom "Erreur démarrage conteneurs"

    # Récupérer les logs d'erreur
    $errorLogs = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "cat /tmp/docker-start.log"
    Write-Host "`nLogs d'erreur:" -ForegroundColor $Red
    Write-Host $errorLogs -ForegroundColor $Red
    Write-Warning-Custom "Vérifiez aussi: ssh ubuntu@$publicIP 'cd /home/ubuntu/knowbase && sudo docker-compose logs'"
}

Write-Host "`nAttente démarrage services (60s)..."
Start-Sleep -Seconds 60

# Check container status
Write-Host "`nStatut final des conteneurs:"
$containerStatus = ssh -i $KeyPathUnix -o StrictHostKeyChecking=no ubuntu@$publicIP "cd /home/ubuntu/knowbase && sudo docker-compose ps"
Write-Host $containerStatus -ForegroundColor $Yellow

# Summary
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor $Green
Write-Host "║   ✅ RÉPARATION TERMINÉE                                  ║" -ForegroundColor $Green
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor $Green
Write-Host ""
Write-Host "📋 URLs D'ACCÈS" -ForegroundColor $Cyan
Write-Host "Frontend: http://${publicIP}:3000" -ForegroundColor $Yellow
Write-Host "Backend:  http://${publicIP}:8000/docs" -ForegroundColor $Yellow
Write-Host ""
Write-Host "🔍 DIAGNOSTIC SUPPLÉMENTAIRE" -ForegroundColor $Cyan
Write-Host "Logs conteneurs: ssh -i $KeyPath ubuntu@$publicIP 'cd /home/ubuntu/knowbase && docker-compose logs'" -ForegroundColor $Yellow
Write-Host "UserData logs:   ssh -i $KeyPath ubuntu@$publicIP 'sudo cat /var/log/user-data.log'" -ForegroundColor $Yellow
Write-Host ""
