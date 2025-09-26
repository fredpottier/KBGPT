# Script PowerShell pour build distant avec sources locales
# Upload sources vers S3 temporaire puis build sur CodeBuild
# Usage: .\scripts\build-remote-local-fixed.ps1

param(
    [string]$ProjectName = "sap-kb-docker-build",
    [string]$Region = "eu-west-1",
    [string]$BucketName = "sap-kb-build-sources-$(Get-Random)",
    [switch]$Wait = $false
)

$AwsCli = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

Write-Host "Build distant avec sources locales..." -ForegroundColor Green

# Vérifier les credentials AWS
try {
    $identity = & $AwsCli sts get-caller-identity --output json | ConvertFrom-Json
    $accountId = $identity.Account
    Write-Host "Account: $accountId" -ForegroundColor Cyan
}
catch {
    Write-Host "AWS CLI non configure" -ForegroundColor Red
    exit 1
}

# Créer bucket S3 temporaire
Write-Host "Creation bucket temporaire: $BucketName"
& $AwsCli s3 mb "s3://$BucketName" --region $Region

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur creation bucket" -ForegroundColor Red
    exit 1
}

# Compresser et uploader sources locales
Write-Host "Upload sources locales vers S3..."
$zipFile = "sap-kb-sources.zip"

# Créer archive ZIP des sources (exclut les gros dossiers)
Add-Type -AssemblyName System.IO.Compression.FileSystem

$compressionLevel = [System.IO.Compression.CompressionLevel]::Optimal
$includeBaseDirectory = $false

# Liste des dossiers/fichiers à inclure (exclusion data, scripts, doc, tests)
$sourcePaths = @(
    "src", "app", "frontend", "config",
    "buildspec.yml", "docker-compose.yml", "docker-compose.build.yml",
    "requirements.txt"
)

# Ajouter package.json s'il existe dans frontend
if (Test-Path "frontend/package.json") {
    $sourcePaths += "frontend/package.json"
}

# Copie directe des fichiers importants à la racine du projet
Write-Host "Copie directe des fichiers et dossiers requis..."

# Copier fichiers de configuration à la racine
$filesToCopy = @("buildspec.yml", "docker-compose.yml", "docker-compose.build.yml", "requirements.txt")
foreach ($file in $filesToCopy) {
    if (Test-Path $file) {
        Write-Host "Copie fichier: $file"
    }
}

# Créer une archive directement depuis le répertoire courant avec tar
# Exclure les dossiers non nécessaires
Write-Host "Creation archive directement depuis le repertoire projet..."

$excludeParams = @(
    "--exclude=data/*",
    "--exclude=scripts/*",
    "--exclude=doc/*",
    "--exclude=tests/*",
    "--exclude=frontend/.next/*",
    "--exclude=frontend/node_modules/*",
    "--exclude=src/knowbase/**/public_files/*",
    "--exclude=**/__pycache__/*",
    "--exclude=**/.pytest_cache/*",
    "--exclude=**/*.pyc",
    "--exclude=**/*.pyo",
    "--exclude=**/*.log"
)

# Supprimer le fichier ZIP s'il existe déjà
if (Test-Path $zipFile) {
    Write-Host "Suppression de l'ancien ZIP: $zipFile"
    Remove-Item $zipFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# Créer l'archive ZIP avec chemins Unix compatibles CodeBuild
Write-Host "Creation archive ZIP avec chemins Unix..."

try {
    # Méthode alternative : utiliser Python pour créer un ZIP avec chemins Unix
    $pythonScript = @"
import zipfile
import os
import sys

zip_file = '$zipFile'
exclude_patterns = [
    'data/', 'scripts/', 'doc/', 'tests/',
    'frontend/.next/', 'frontend/node_modules/',
    'public_files/', 'presentations/', 'thumbnails/',
    '__pycache__/', '.pytest_cache/',
    '.pyc', '.pyo', '.log'
]

def should_exclude(path):
    for pattern in exclude_patterns:
        if pattern in path.replace(os.sep, '/'):
            return True
    return False

print('Creating ZIP with Unix paths...')
with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
    # Add files at root
    for file in ['buildspec.yml', 'docker-compose.yml', 'docker-compose.build.yml', 'requirements.txt']:
        if os.path.exists(file):
            print(f'Adding file: {file}')
            zf.write(file, file)

    # Add directories
    for root_dir in ['src', 'app', 'frontend', 'config', 'ui']:
        if os.path.exists(root_dir):
            print(f'Adding directory: {root_dir}/')
            for root, dirs, files in os.walk(root_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Convert to Unix path and check exclusions
                    unix_path = file_path.replace(os.sep, '/')
                    if not should_exclude(unix_path):
                        print(f'Adding: {unix_path}')
                        zf.write(file_path, unix_path)

if os.path.exists(zip_file):
    print(f'ZIP created successfully: {zip_file}')
    print(f'Size: {os.path.getsize(zip_file)} bytes')
else:
    print('ERROR: ZIP not created')
    sys.exit(1)
"@

    # Écrire le script Python temporaire
    $tempPyScript = "create_zip.py"
    $pythonScript | Out-File -FilePath $tempPyScript -Encoding UTF8

    Write-Host "Execution script Python pour créer ZIP avec chemins Unix..."

    # Exécuter le script Python
    python $tempPyScript

    # Supprimer le script temporaire
    Remove-Item $tempPyScript -Force -ErrorAction SilentlyContinue

    if (Test-Path $zipFile) {
        Write-Host "Archive ZIP creee avec succes: $zipFile" -ForegroundColor Green
        Write-Host "Taille archive: $((Get-Item $zipFile).Length) bytes"
    } else {
        throw "ZIP non créé par Python"
    }
}
catch {
    Write-Host "Erreur creation archive: $($_.Exception.Message)" -ForegroundColor Red

    # Fallback vers tar si Python échoue, mais avec extension correcte
    Write-Host "Tentative fallback avec tar..." -ForegroundColor Yellow
    try {
        $tarFile = $zipFile.Replace(".zip", ".tar.gz")

        # Construire les arguments tar
        $tarArgs = @(
            "-czf", $tarFile,
            "--exclude=data/*",
            "--exclude=scripts/*",
            "--exclude=doc/*",
            "--exclude=tests/*",
            "--exclude=frontend/.next/*",
            "--exclude=frontend/node_modules/*",
            "--exclude=**/public_files/*",
            "--exclude=**/presentations/*",
            "--exclude=**/thumbnails/*",
            "--exclude=**/__pycache__/*",
            "--exclude=**/.pytest_cache/*",
            "--exclude=**/*.pyc",
            "--exclude=**/*.pyo",
            "--exclude=**/*.log"
        )

        # Ajouter les éléments à inclure
        @("src", "app", "frontend", "config", "ui", "buildspec.yml", "docker-compose.yml", "docker-compose.build.yml", "requirements.txt") | ForEach-Object {
            if (Test-Path $_) {
                $tarArgs += $_
            }
        }

        & tar $tarArgs

        if (Test-Path $tarFile) {
            Write-Host "Archive tar creee: $tarFile" -ForegroundColor Yellow
            Write-Host "ATTENTION: CodeBuild ne peut pas lire les fichiers .tar.gz avec source S3" -ForegroundColor Red
            exit 1
        }
    }
    catch {
        Write-Host "Toutes les methodes ont echoue" -ForegroundColor Red
        exit 1
    }
}

# Upload vers S3
& $AwsCli s3 cp $zipFile "s3://$BucketName/source.zip"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur upload S3" -ForegroundColor Red
    Remove-Item $zipFile -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Sources uploadees" -ForegroundColor Green

# Déclencher build
Write-Host "Demarrage build distant..."
$buildResult = & $AwsCli codebuild start-build --project-name $ProjectName --source-type-override S3 --source-location-override "$BucketName/source.zip" --region $Region | ConvertFrom-Json

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur demarrage build" -ForegroundColor Red
    exit 1
}

$buildId = $buildResult.build.id
Write-Host "Build demarre: $buildId" -ForegroundColor Green
Write-Host "Console: https://$Region.console.aws.amazon.com/codesuite/codebuild/builds/$buildId" -ForegroundColor Cyan

# Attendre si demandé
if ($Wait) {
    Write-Host "Attente fin du build..." -ForegroundColor Yellow

    do {
        Start-Sleep -Seconds 30
        $buildStatus = & $AwsCli codebuild batch-get-builds --ids $buildId --region $Region | ConvertFrom-Json
        $status = $buildStatus.builds[0].buildStatus
        $phase = $buildStatus.builds[0].currentPhase

        Write-Host "Status: $status - Phase: $phase" -ForegroundColor Cyan

    } while ($status -eq "IN_PROGRESS")

    if ($status -eq "SUCCEEDED") {
        Write-Host "Build reussi!" -ForegroundColor Green
    } else {
        Write-Host "Build echoue: $status" -ForegroundColor Red
    }
}

# Nettoyage
Write-Host "Nettoyage..."
& $AwsCli s3 rm "s3://$BucketName" --recursive --quiet
& $AwsCli s3 rb "s3://$BucketName" --region $Region

# Nettoyage des fichiers temporaires
if (Test-Path $zipFile) {
    Remove-Item $zipFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Termine!" -ForegroundColor Magenta
if (-not $Wait) {
    Write-Host "Suivre le build: https://$Region.console.aws.amazon.com/codesuite/codebuild/builds/$buildId" -ForegroundColor Cyan
}