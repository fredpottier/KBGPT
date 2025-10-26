<#
.SYNOPSIS
    Sauvegarde complète de KnowBase (archive .tar.gz unique)

.DESCRIPTION
    Crée une archive complète horodatée incluant :
    - Qdrant (vectors)
    - Redis (cache/queue)
    - Neo4j (graph)
    - Data (docs/models/logs)

    L'archive peut être sauvegardée en LOCAL ou uploadée sur S3.

.PARAMETER EC2Host
    IP ou hostname de l'instance EC2 KnowBase

.PARAMETER KeyPath
    Chemin vers la clé SSH PEM (défaut: .\Osmose_KeyPair.pem)

.PARAMETER Destination
    Destination du backup : "Local" ou "S3" (défaut: "Local")

.PARAMETER S3BucketName
    Nom du bucket S3 (requis si Destination="S3")

.PARAMETER OutputDir
    Répertoire de sortie local (défaut: .\backups)

.EXAMPLE
    # Backup local (par défaut)
    .\backup-knowbase.ps1 -EC2Host 63.32.164.133

.EXAMPLE
    # Backup vers S3
    .\backup-knowbase.ps1 -EC2Host 63.32.164.133 -Destination S3 -S3BucketName "knowbase-backups-715927975014"

.EXAMPLE
    # Backup local avec répertoire personnalisé
    .\backup-knowbase.ps1 -EC2Host 63.32.164.133 -OutputDir "D:\Backups"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$EC2Host,

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = ".\Osmose_KeyPair.pem",

    [Parameter(Mandatory=$false)]
    [ValidateSet("Local", "S3")]
    [string]$Destination = "Local",

    [Parameter(Mandatory=$false)]
    [string]$S3BucketName = "",

    [Parameter(Mandatory=$false)]
    [string]$OutputDir = ".\backups"
)

$ErrorActionPreference = "Stop"

# Validation
if ($Destination -eq "S3" -and [string]::IsNullOrEmpty($S3BucketName)) {
    Write-Host "❌ Erreur: -S3BucketName requis quand -Destination S3" -ForegroundColor Red
    exit 1
}

# Configuration
$BackupTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupName = "knowbase_backup_$BackupTimestamp"
$RemoteBackupDir = "/tmp/$BackupName"
$LocalBackupDir = Join-Path $OutputDir $BackupTimestamp
$ArchiveName = "$BackupName.tar.gz"
$LocalArchivePath = Join-Path $OutputDir $ArchiveName
$Neo4jPassword = "graphiti_neo4j_pass"

Write-Host "🔄 Backup KnowBase" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "📍 Source    : $EC2Host" -ForegroundColor Cyan
Write-Host "📦 Archive   : $ArchiveName" -ForegroundColor Cyan
Write-Host "🎯 Destination: $Destination" -ForegroundColor Cyan
if ($Destination -eq "S3") {
    Write-Host "☁️  Bucket S3 : $S3BucketName" -ForegroundColor Cyan
} else {
    Write-Host "💾 Local     : $LocalArchivePath" -ForegroundColor Cyan
}
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# Créer répertoires
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# 1. Vérifier bucket S3 si nécessaire
if ($Destination -eq "S3") {
    Write-Host "`n🪣 Vérification du bucket S3..." -ForegroundColor Cyan
    $BucketExists = aws s3api head-bucket --bucket $S3BucketName 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ➜ Création du bucket $S3BucketName..." -ForegroundColor Yellow
        aws s3api create-bucket `
            --bucket $S3BucketName `
            --region eu-west-1 `
            --create-bucket-configuration LocationConstraint=eu-west-1

        aws s3api put-bucket-versioning `
            --bucket $S3BucketName `
            --versioning-configuration Status=Enabled

        Write-Host "   ✅ Bucket créé avec versioning" -ForegroundColor Green
    } else {
        Write-Host "   ✅ Bucket existe" -ForegroundColor Green
    }
}

# 2. Créer répertoire de backup sur EC2
Write-Host "`n📁 Préparation du backup sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host "mkdir -p $RemoteBackupDir"

# 3. Backup Qdrant
Write-Host "`n🔹 Backup Qdrant..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Créer snapshots via API
    curl -X POST 'http://localhost:6333/collections/knowbase/snapshots' > /dev/null 2>&1
    curl -X POST 'http://localhost:6333/collections/rfp_qa/snapshots' > /dev/null 2>&1
    sleep 2

    # Backup volume Qdrant complet
    docker run --rm \
        -v knowbase_qdrant_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/qdrant.tar.gz -C /source .
"@
Write-Host "   ✅ Qdrant backupé" -ForegroundColor Green

# 4. Backup Redis
Write-Host "`n🔹 Backup Redis..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Déclencher BGSAVE
    docker exec knowbase-redis redis-cli BGSAVE
    sleep 5

    # Backup volume Redis
    docker run --rm \
        -v knowbase_redis_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/redis.tar.gz -C /source .
"@
Write-Host "   ✅ Redis backupé" -ForegroundColor Green

# 5. Backup Neo4j
Write-Host "`n🔹 Backup Neo4j..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Backup volumes Neo4j
    docker run --rm \
        -v knowbase_neo4j_data:/source_data:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/neo4j_data.tar.gz -C /source_data .

    docker run --rm \
        -v knowbase_neo4j_logs:/source_logs:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/neo4j_logs.tar.gz -C /source_logs .
"@
Write-Host "   ✅ Neo4j backupé" -ForegroundColor Green

# 6. Backup Data
Write-Host "`n🔹 Backup Data..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Backup app_data
    docker run --rm \
        -v knowbase_app_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_data.tar.gz -C /source .

    # Backup app_logs
    docker run --rm \
        -v knowbase_app_logs:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_logs.tar.gz -C /source .

    # Backup app_models (si présent)
    docker run --rm \
        -v knowbase_app_models:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_models.tar.gz -C /source . 2>/dev/null || echo 'No models'
"@
Write-Host "   ✅ Data backupé" -ForegroundColor Green

# 7. Créer manifeste
Write-Host "`n📋 Création du manifeste..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    cat > $RemoteBackupDir/manifest.json <<EOF
{
  "backup_name": "$BackupName",
  "backup_timestamp": "$BackupTimestamp",
  "backup_date": "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  "source_ec2": "$EC2Host",
  "components": [
    "qdrant.tar.gz",
    "redis.tar.gz",
    "neo4j_data.tar.gz",
    "neo4j_logs.tar.gz",
    "app_data.tar.gz",
    "app_logs.tar.gz",
    "app_models.tar.gz"
  ]
}
EOF

    # Liste des fichiers avec tailles
    ls -lh $RemoteBackupDir/ > $RemoteBackupDir/files.txt
"@
Write-Host "   ✅ Manifeste créé" -ForegroundColor Green

# 8. Créer archive unique sur EC2
Write-Host "`n📦 Création de l'archive unique..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    cd /tmp
    tar czf $ArchiveName -C $BackupName .
    rm -rf $BackupName
"@
Write-Host "   ✅ Archive créée: $ArchiveName" -ForegroundColor Green

# 9. Télécharger l'archive
Write-Host "`n⬇️  Téléchargement de l'archive..." -ForegroundColor Cyan
scp -i $KeyPath -o StrictHostKeyChecking=no "ubuntu@$($EC2Host):/tmp/$ArchiveName" $LocalArchivePath

if (Test-Path $LocalArchivePath) {
    $ArchiveSize = (Get-Item $LocalArchivePath).Length / 1MB
    Write-Host "   ✅ Archive téléchargée: $([math]::Round($ArchiveSize, 2)) MB" -ForegroundColor Green
} else {
    Write-Host "   ❌ Erreur téléchargement" -ForegroundColor Red
    exit 1
}

# 10. Upload vers S3 si demandé
if ($Destination -eq "S3") {
    Write-Host "`n☁️  Upload vers S3..." -ForegroundColor Cyan
    $S3Key = "backups/$ArchiveName"
    aws s3 cp $LocalArchivePath "s3://$S3BucketName/$S3Key" --only-show-errors

    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Upload S3 terminé: s3://$S3BucketName/$S3Key" -ForegroundColor Green

        # Option : supprimer la copie locale
        Write-Host "`n🗑️  Voulez-vous supprimer la copie locale ? (O/N)" -ForegroundColor Yellow
        $response = Read-Host
        if ($response -eq "O" -or $response -eq "o") {
            Remove-Item $LocalArchivePath -Force
            Write-Host "   ✅ Copie locale supprimée" -ForegroundColor Green
        }
    } else {
        Write-Host "   ❌ Erreur upload S3" -ForegroundColor Red
        exit 1
    }
}

# 11. Nettoyer l'archive sur EC2
Write-Host "`n🧹 Nettoyage sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host "rm -f /tmp/$ArchiveName"
Write-Host "   ✅ Nettoyage terminé" -ForegroundColor Green

# 12. Résumé final
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Backup terminé avec succès !" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "📦 Archive      : $ArchiveName" -ForegroundColor Cyan
Write-Host "🕐 Timestamp    : $BackupTimestamp" -ForegroundColor Cyan

if ($Destination -eq "S3") {
    Write-Host "☁️  Bucket S3    : $S3BucketName" -ForegroundColor Cyan
    Write-Host "📂 Chemin S3    : s3://$S3BucketName/backups/$ArchiveName" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor Cyan
    Write-Host "Pour restaurer ce backup :" -ForegroundColor Yellow
    Write-Host ".\restore-knowbase.ps1 -StackName 'Osmos' -BackupSource S3 -BackupTimestamp '$BackupTimestamp' -S3BucketName '$S3BucketName'" -ForegroundColor White
} else {
    Write-Host "💾 Chemin Local : $LocalArchivePath" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor Cyan
    Write-Host "Pour restaurer ce backup :" -ForegroundColor Yellow
    Write-Host ".\restore-knowbase.ps1 -StackName 'Osmos' -BackupSource Local -LocalArchivePath '$LocalArchivePath'" -ForegroundColor White
}

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
