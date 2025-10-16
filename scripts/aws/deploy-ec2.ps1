<#
.SYNOPSIS
    Script de deploiement sur EC2 via SSH (Windows PowerShell)

.DESCRIPTION
    Deploie KnowWhere OSMOSE sur une instance EC2 en utilisant les images ECR.
    Se connecte via SSH, configure l'environnement et lance les conteneurs.

.PARAMETER InstanceIP
    Adresse IP publique de l'instance EC2 (obligatoire)

.PARAMETER KeyPath
    Chemin vers la cle SSH privee (.pem) pour se connecter a l'instance

.PARAMETER Username
    Nom d'utilisateur SSH (defaut: ubuntu pour Ubuntu, ec2-user pour Amazon Linux)

.PARAMETER Profile
    AWS profile a utiliser (defaut: default)

.PARAMETER Region
    AWS region (defaut: eu-west-1)

.PARAMETER SkipSetup
    Skip la configuration initiale (Docker, Docker Compose, AWS CLI deja installes)

.EXAMPLE
    .\scripts\aws\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\keys\my-ec2-key.pem"
    Deploiement complet avec setup initial

.EXAMPLE
    .\scripts\aws\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\keys\my-ec2-key.pem" -SkipSetup
    Deploiement sans refaire le setup (update des conteneurs seulement)

.EXAMPLE
    .\scripts\aws\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\keys\my-ec2-key.pem" -Username "ec2-user"
    Deploiement sur Amazon Linux 2 (au lieu d'Ubuntu)
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceIP,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ })]
    [string]$KeyPath,

    [string]$Username = "ubuntu",
    [string]$Profile = "default",
    [string]$Region = "eu-west-1",
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"

# =====================================================
# DETECTION ET POSITIONNEMENT A LA RACINE DU PROJET
# =====================================================
$currentDir = Get-Location
$isAtRoot = (Test-Path "docker-compose.ecr.yml") -and (Test-Path "config")

if (-not $isAtRoot) {
    Write-Host "Repositionnement automatique a la racine du projet..." -ForegroundColor Yellow

    $foundRoot = $false
    $testDir = $currentDir

    for ($i = 0; $i -lt 3; $i++) {
        $testDir = Split-Path $testDir -Parent
        Push-Location $testDir

        if ((Test-Path "docker-compose.ecr.yml") -and (Test-Path "config")) {
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
        Write-Host "Positionnez-vous a la racine du projet:" -ForegroundColor Cyan
        Write-Host "  cd C:\Project\SAP_KB"
        Write-Host "  .\scripts\aws\deploy-ec2.ps1 -InstanceIP 1.2.3.4 -KeyPath C:\keys\my-key.pem"
        Write-Host ""
        exit 1
    }
}

Write-Host "Repertoire de travail: $(Get-Location)" -ForegroundColor Gray
Write-Host ""

# =====================================================
# CONFIGURATION
# =====================================================
$AWS_ACCOUNT_ID = $env:AWS_ACCOUNT_ID
if (-not $AWS_ACCOUNT_ID) {
    $AWS_ACCOUNT_ID = "715927975014"
}

$ECR_REGISTRY = "$AWS_ACCOUNT_ID.dkr.ecr.$Region.amazonaws.com"
$PROJECT_NAME = "knowbase-osmose"
$DEPLOY_DIR = "/home/$Username/knowbase"

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
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host ""
}

function Write-SuccessMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "OK: $Message" -ForegroundColor Green
    Write-Host ""
}

function Invoke-SSHCommand {
    param(
        [string]$Command,
        [string]$Description = ""
    )

    if ($Description) {
        Write-Step $Description
    }

    # Afficher un apercu de la commande (premiere ligne seulement pour les scripts multi-lignes)
    $firstLine = ($Command -split "`n")[0].Trim()
    Write-Host "Execution: $firstLine..." -ForegroundColor DarkGray

    # Normaliser les sauts de ligne Windows -> Unix
    $Command = $Command -replace "`r`n", "`n"
    $Command = $Command -replace "`r", "`n"

    # Creer un fichier temporaire local avec encodage UTF-8 Unix (LF)
    $tempFileLocal = [System.IO.Path]::GetTempFileName()
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($tempFileLocal, $Command, $utf8NoBom)

    # Nom de fichier temporaire sur EC2
    $tempFileRemote = "/tmp/ssh-script-$(Get-Random).sh"

    try {
        # Transferer le script sur EC2
        scp -i "$KeyPath" -o StrictHostKeyChecking=no "$tempFileLocal" "${Username}@${InstanceIP}:${tempFileRemote}" | Out-Null

        # Executer le script sur EC2
        ssh -i "$KeyPath" -o StrictHostKeyChecking=no "$Username@$InstanceIP" "bash $tempFileRemote && rm -f $tempFileRemote"

        if ($LASTEXITCODE -ne 0) {
            Write-ErrorMessage "Echec de la commande SSH"
            throw "SSH command failed"
        }
    }
    finally {
        # Nettoyer le fichier temporaire local
        Remove-Item $tempFileLocal -ErrorAction SilentlyContinue
    }
}

function Copy-FileToEC2 {
    param(
        [string]$LocalPath,
        [string]$RemotePath,
        [string]$Description = ""
    )

    if ($Description) {
        Write-Step $Description
    }

    $scpCommand = "scp -i `"$KeyPath`" -o StrictHostKeyChecking=no `"$LocalPath`" $Username@$InstanceIP`:$RemotePath"
    Write-Host "Copy: $LocalPath -> $RemotePath" -ForegroundColor DarkGray

    Invoke-Expression $scpCommand

    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMessage "Echec du transfert SCP: $LocalPath"
        throw "SCP transfer failed"
    }
}

# =====================================================
# VALIDATION ENVIRONNEMENT LOCAL
# =====================================================
Write-Header "Validation de l'environnement local"

# Verifier SSH (OpenSSH sur Windows)
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-ErrorMessage "SSH n'est pas disponible"
    Write-Host "Installation OpenSSH sur Windows:" -ForegroundColor Yellow
    Write-Host "  Settings > Apps > Optional Features > Add a feature > OpenSSH Client"
    exit 1
}
Write-SuccessMessage "SSH trouve"

# Verifier AWS CLI
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrorMessage "AWS CLI n'est pas installe"
    exit 1
}
Write-SuccessMessage "AWS CLI trouve"

# Verifier credentials AWS
try {
    $null = aws sts get-caller-identity --profile $Profile 2>$null
    Write-SuccessMessage "Credentials AWS valides"
}
catch {
    Write-ErrorMessage "Credentials AWS invalides pour le profil '$Profile'"
    exit 1
}

# Verifier la cle SSH
if (-not (Test-Path $KeyPath)) {
    Write-ErrorMessage "Cle SSH non trouvee: $KeyPath"
    exit 1
}
Write-SuccessMessage "Cle SSH trouvee: $KeyPath"

Write-Header "Configuration du deploiement"
Write-Host "Instance IP:      $InstanceIP"
Write-Host "Username:         $Username"
Write-Host "Key Path:         $KeyPath"
Write-Host "AWS Account ID:   $AWS_ACCOUNT_ID"
Write-Host "AWS Region:       $Region"
Write-Host "ECR Registry:     $ECR_REGISTRY"
Write-Host "Deploy Directory: $DEPLOY_DIR"
Write-Host "Skip Setup:       $SkipSetup"

# =====================================================
# TEST CONNEXION EC2
# =====================================================
Write-Header "Test de connexion EC2"

try {
    Invoke-SSHCommand -Command "echo 'Connexion reussie'" -Description "Test de connexion SSH"
    Write-SuccessMessage "Connexion EC2 etablie"
}
catch {
    Write-ErrorMessage "Impossible de se connecter a l'instance EC2"
    Write-Host "Verifiez:" -ForegroundColor Yellow
    Write-Host "  - L'adresse IP est correcte"
    Write-Host "  - Le Security Group autorise SSH (port 22) depuis votre IP"
    Write-Host "  - La cle SSH correspond bien a l'instance"
    exit 1
}

# =====================================================
# SETUP INITIAL DE L'INSTANCE (si necessaire)
# =====================================================
if (-not $SkipSetup) {
    Write-Header "Setup initial de l'instance EC2"

    # Mise a jour du systeme
    Invoke-SSHCommand -Command "sudo apt-get update -qq" -Description "Mise a jour des paquets"

    # Installation Docker
    Write-Step "Installation de Docker"
    $dockerInstallScript = @"
if ! command -v docker &> /dev/null; then
    echo 'Installation de Docker...'
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $Username
    rm get-docker.sh
    echo 'Docker installe'
else
    echo 'Docker deja installe'
fi
"@
    Invoke-SSHCommand -Command $dockerInstallScript

    # Installation Docker Compose
    Write-Step "Installation de Docker Compose"
    $composeInstallScript = @"
if ! command -v docker-compose &> /dev/null; then
    echo 'Installation de Docker Compose...'
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-`$(uname -s)-`$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo 'Docker Compose installe'
else
    echo 'Docker Compose deja installe'
fi
"@
    Invoke-SSHCommand -Command $composeInstallScript

    # Installation AWS CLI
    Write-Step "Installation de AWS CLI"
    $awsInstallScript = @"
if ! command -v aws &> /dev/null; then
    echo 'Installation AWS CLI...'
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    sudo apt-get install -y unzip
    unzip -q awscliv2.zip
    sudo ./aws/install
    rm -rf aws awscliv2.zip
    echo 'AWS CLI installe'
else
    echo 'AWS CLI deja installe'
fi
"@
    Invoke-SSHCommand -Command $awsInstallScript

    Write-SuccessMessage "Setup initial termine"

    # Redemarrage de la session SSH pour appliquer les groupes Docker
    Write-Host "Redemarrage de la session SSH necessaire pour appliquer les permissions Docker" -ForegroundColor Yellow
    Write-Host "Attendez 5 secondes..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
else {
    Write-Step "Skip du setup initial (-SkipSetup active)"
}

# =====================================================
# CONFIGURATION AWS CREDENTIALS SUR EC2
# =====================================================
Write-Header "Configuration AWS sur l'instance EC2"

Write-Step "Recuperation des credentials AWS du profil local"

# Recuperer les credentials du profil AWS
$awsAccessKeyId = aws configure get aws_access_key_id --profile $Profile
$awsSecretAccessKey = aws configure get aws_secret_access_key --profile $Profile
$awsSessionToken = aws configure get aws_session_token --profile $Profile

# Verifier que les credentials sont recuperees
if (-not $awsAccessKeyId -or -not $awsSecretAccessKey) {
    Write-ErrorMessage "Impossible de recuperer les credentials AWS du profil '$Profile'"
    Write-Host "Verifiez votre configuration AWS avec: aws configure list --profile $Profile" -ForegroundColor Yellow
    exit 1
}

# Construire le script de configuration (avec ou sans session token)
if ($awsSessionToken) {
    # Credentials temporaires avec session token
    $awsConfigScript = @"
mkdir -p ~/.aws
cat > ~/.aws/credentials <<'EOF'
[default]
aws_access_key_id = $awsAccessKeyId
aws_secret_access_key = $awsSecretAccessKey
aws_session_token = $awsSessionToken
EOF

cat > ~/.aws/config <<'EOF'
[default]
region = $Region
output = json
EOF

chmod 600 ~/.aws/credentials
chmod 600 ~/.aws/config
echo 'AWS credentials configurees (avec session token)'
"@
}
else {
    # Credentials permanentes (IAM user)
    $awsConfigScript = @"
mkdir -p ~/.aws
cat > ~/.aws/credentials <<'EOF'
[default]
aws_access_key_id = $awsAccessKeyId
aws_secret_access_key = $awsSecretAccessKey
EOF

cat > ~/.aws/config <<'EOF'
[default]
region = $Region
output = json
EOF

chmod 600 ~/.aws/credentials
chmod 600 ~/.aws/config
echo 'AWS credentials configurees (IAM user)'
"@
}

Invoke-SSHCommand -Command $awsConfigScript -Description "Configuration des credentials AWS"

# =====================================================
# CREATION DU REPERTOIRE DE DEPLOIEMENT
# =====================================================
Write-Header "Preparation du repertoire de deploiement"

Invoke-SSHCommand -Command "mkdir -p $DEPLOY_DIR/config" -Description "Creation des repertoires"

# =====================================================
# TRANSFERT DES FICHIERS DE CONFIGURATION
# =====================================================
Write-Header "Transfert des fichiers de configuration"

# Transfert docker-compose.ecr.yml
Copy-FileToEC2 -LocalPath "docker-compose.ecr.yml" -RemotePath "$DEPLOY_DIR/docker-compose.yml" -Description "Transfert de docker-compose.ecr.yml"

# Transfert du fichier .env avec mise a jour automatique de l'IP EC2
Write-Step "Preparation du fichier .env avec l'IP EC2"

$envSourceFile = $null
if (Test-Path ".env.production") {
    $envSourceFile = ".env.production"
    Write-Host "Utilisation de .env.production" -ForegroundColor Green
}
elseif (Test-Path ".env") {
    $envSourceFile = ".env"
    Write-Host "Attention: Utilisation du .env local (creez .env.production pour la production)" -ForegroundColor Yellow
}
else {
    Write-ErrorMessage "Aucun fichier .env trouve"
    Write-Host "Creez un fichier .env.production avec vos variables d'environnement" -ForegroundColor Yellow
    exit 1
}

# Lire le contenu du .env et mettre a jour automatiquement l'IP EC2
Write-Host "  -> Mise a jour automatique de FRONTEND_API_BASE_URL avec l'IP EC2: $InstanceIP" -ForegroundColor Cyan
$envContent = Get-Content $envSourceFile -Raw

# Remplacer localhost ou toute autre IP par l'IP EC2 fournie
$envContent = $envContent -replace 'FRONTEND_API_BASE_URL=http://[^:]+:8000', "FRONTEND_API_BASE_URL=http://$InstanceIP:8000"

# Creer un fichier temporaire avec le contenu mis a jour
$tempEnvFile = ".env.deploy.tmp"
Set-Content -Path $tempEnvFile -Value $envContent -NoNewline

# Transferer le fichier temporaire
Copy-FileToEC2 -LocalPath $tempEnvFile -RemotePath "$DEPLOY_DIR/.env" -Description "Transfert de .env (avec IP EC2 mise a jour)"

# Nettoyer le fichier temporaire
Remove-Item $tempEnvFile

Write-SuccessMessage "Fichier .env configure avec l'IP EC2: $InstanceIP"

# Transfert du repertoire config (YAML configs)
if (Test-Path "config") {
    Write-Step "Transfert du repertoire config"
    Get-ChildItem -Path "config" -Filter "*.yaml" | ForEach-Object {
        Copy-FileToEC2 -LocalPath $_.FullName -RemotePath "$DEPLOY_DIR/config/$($_.Name)"
    }
}

Write-SuccessMessage "Fichiers de configuration transferes"

# =====================================================
# MISE A JOUR DU FICHIER .ENV POUR ECR
# =====================================================
Write-Header "Configuration des variables ECR"

$envUpdateScript = @"
cd $DEPLOY_DIR

# Ajout des variables AWS si absentes
if ! grep -q 'AWS_ACCOUNT_ID' .env; then
    echo '' >> .env
    echo '# AWS ECR Configuration' >> .env
    echo 'AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID' >> .env
    echo 'AWS_REGION=$Region' >> .env
fi

# Mise a jour des valeurs
sed -i 's/^AWS_ACCOUNT_ID=.*/AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID/' .env
sed -i 's/^AWS_REGION=.*/AWS_REGION=$Region/' .env

echo 'Variables ECR configurees'
"@

Invoke-SSHCommand -Command $envUpdateScript

# =====================================================
# LOGIN ECR SUR L'INSTANCE EC2
# =====================================================
Write-Header "Login ECR sur l'instance EC2"

$ecrLoginScript = "aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $ECR_REGISTRY"
Invoke-SSHCommand -Command $ecrLoginScript -Description "Authentification a ECR"

Write-SuccessMessage "Login ECR reussi"

# =====================================================
# PULL DES IMAGES DEPUIS ECR
# =====================================================
Write-Header "Pull des images depuis ECR"

Invoke-SSHCommand -Command "cd $DEPLOY_DIR && docker-compose pull" -Description "Pull de toutes les images"

Write-SuccessMessage "Images telechargees"

# =====================================================
# ARRET DES CONTENEURS EXISTANTS (si deja deployes)
# =====================================================
Write-Header "Gestion des conteneurs existants"

$stopScript = @"
cd $DEPLOY_DIR
if [ -f docker-compose.yml ]; then
    echo 'Arret des conteneurs existants...'
    docker-compose down --remove-orphans || true
    echo 'Conteneurs arretes'
else
    echo 'Pas de conteneurs existants'
fi
"@

Invoke-SSHCommand -Command $stopScript

# =====================================================
# DEMARRAGE DES CONTENEURS
# =====================================================
Write-Header "Demarrage des conteneurs"

Invoke-SSHCommand -Command "cd $DEPLOY_DIR && docker-compose up -d" -Description "Lancement de tous les services"

# Attendre le demarrage
Write-Step "Attente du demarrage des services (60s)"
Start-Sleep -Seconds 60

# Verifier les services
Invoke-SSHCommand -Command "cd $DEPLOY_DIR && docker-compose ps" -Description "Statut des services"

Write-SuccessMessage "Conteneurs demarres"

# =====================================================
# VERIFICATION SANTE DES SERVICES
# =====================================================
Write-Header "Verification sante des services"

$healthCheckScript = @"
cd $DEPLOY_DIR

echo '=== Healthcheck des services ==='

# API Backend
echo -n 'Backend API: '
curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/status || echo 'FAIL'

# Frontend
echo -n 'Frontend: '
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/health || echo 'FAIL'

# Neo4j
echo -n 'Neo4j: '
curl -s -o /dev/null -w '%{http_code}' http://localhost:7474 || echo 'FAIL'

# Qdrant
echo -n 'Qdrant: '
curl -s -o /dev/null -w '%{http_code}' http://localhost:6333/health || echo 'FAIL'

# Redis
echo -n 'Redis: '
docker exec knowbase-redis redis-cli ping || echo 'FAIL'

echo ''
echo '=== Logs recents ==='
docker-compose logs --tail=20
"@

Invoke-SSHCommand -Command $healthCheckScript

# =====================================================
# RESUME FINAL
# =====================================================
Write-Header "Deploiement termine avec succes"

Write-Host ""
Write-Host "Services accessibles sur l'instance EC2:" -ForegroundColor Green
Write-Host "  - API Backend:    http://$InstanceIP:8000/docs"
Write-Host "  - Frontend:       http://$InstanceIP:3000"
Write-Host "  - Streamlit UI:   http://$InstanceIP:8501"
Write-Host "  - Neo4j Browser:  http://$InstanceIP:7474"
Write-Host "  - Qdrant UI:      http://$InstanceIP:6333/dashboard"
Write-Host ""
Write-Host "IMPORTANT: Configurez votre Security Group pour autoriser ces ports depuis votre IP" -ForegroundColor Yellow
Write-Host ""
Write-Host "Commandes utiles:" -ForegroundColor Cyan
Write-Host "  ssh -i `"$KeyPath`" $Username@$InstanceIP"
Write-Host "  cd $DEPLOY_DIR && docker-compose logs -f"
Write-Host "  cd $DEPLOY_DIR && docker-compose restart app"
Write-Host ""
Write-Host "Pour mettre a jour le deploiement:" -ForegroundColor Cyan
Write-Host "  .\scripts\aws\deploy-ec2.ps1 -InstanceIP $InstanceIP -KeyPath `"$KeyPath`" -SkipSetup"

Write-SuccessMessage "Deploiement termine a $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
