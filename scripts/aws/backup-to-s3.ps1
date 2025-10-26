<#
.SYNOPSIS
    Sauvegarde complète de KnowBase (Qdrant, Redis, Neo4j, Data) vers S3

.DESCRIPTION
    Ce script crée des backups horodatés de :
    - Qdrant : Snapshot via API + volumes
    - Redis : Dump RDB
    - Neo4j : Export cypher-shell
    - Data : Dossier complet (/data)

    Puis upload tout sur S3 dans un bucket dédié.

.PARAMETER EC2Host
    IP ou hostname de l'instance EC2 KnowBase (ex: 63.32.164.133)

.PARAMETER KeyPath
    Chemin vers la clé SSH PEM (défaut: .\Osmose_KeyPair.pem)

.PARAMETER S3BucketName
    Nom du bucket S3 (sera créé s'il n'existe pas)
    Défaut: knowbase-backups-{AWS_ACCOUNT_ID}

.EXAMPLE
    .\backup-to-s3.ps1 -EC2Host 63.32.164.133

.EXAMPLE
    .\backup-to-s3.ps1 -EC2Host 63.32.164.133 -S3BucketName "mon-bucket-backups"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$EC2Host,

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = ".\Osmose_KeyPair.pem",

    [Parameter(Mandatory=$false)]
    [string]$S3BucketName = ""
)

$ErrorActionPreference = "Stop"

# Configuration
$BackupTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RemoteBackupDir = "/tmp/knowbase_backup_$BackupTimestamp"
$LocalBackupDir = ".\backups\$BackupTimestamp"
$Neo4jPassword = "graphiti_neo4j_pass"  # Depuis .env.production

Write-Host "🔄 Backup KnowBase vers S3" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# 1. Déterminer le bucket S3
if ([string]::IsNullOrEmpty($S3BucketName)) {
    $AccountId = (aws sts get-caller-identity --query Account --output text)
    $S3BucketName = "knowbase-backups-$AccountId"
    Write-Host "📦 Bucket S3 auto: $S3BucketName" -ForegroundColor Yellow
} else {
    Write-Host "📦 Bucket S3 fourni: $S3BucketName" -ForegroundColor Green
}

# 2. Créer le bucket S3 s'il n'existe pas
Write-Host "`n🪣 Vérification du bucket S3..." -ForegroundColor Cyan
$BucketExists = aws s3api head-bucket --bucket $S3BucketName 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ➜ Création du bucket $S3BucketName..." -ForegroundColor Yellow
    aws s3api create-bucket `
        --bucket $S3BucketName `
        --region eu-west-1 `
        --create-bucket-configuration LocationConstraint=eu-west-1

    # Activer le versioning (recommandé pour backups)
    aws s3api put-bucket-versioning `
        --bucket $S3BucketName `
        --versioning-configuration Status=Enabled

    Write-Host "   ✅ Bucket créé avec versioning activé" -ForegroundColor Green
} else {
    Write-Host "   ✅ Bucket existe déjà" -ForegroundColor Green
}

# 3. Créer répertoire de backup sur EC2
Write-Host "`n📁 Création du répertoire de backup sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host "mkdir -p $RemoteBackupDir"

# 4. Backup Qdrant
Write-Host "`n🔹 Backup Qdrant..." -ForegroundColor Cyan
Write-Host "   ➜ Création snapshot API..." -ForegroundColor Yellow
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Créer snapshot via API Qdrant
    curl -X POST 'http://localhost:6333/collections/knowbase/snapshots' > /dev/null 2>&1
    curl -X POST 'http://localhost:6333/collections/rfp_qa/snapshots' > /dev/null 2>&1
    sleep 2

    # Copier snapshots depuis le volume Docker
    docker run --rm \
        -v knowbase_qdrant_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine sh -c 'cp -r /source/snapshots /backup/qdrant_snapshots 2>/dev/null || echo "No snapshots"'

    # Backup complet du volume Qdrant (au cas où)
    docker run --rm \
        -v knowbase_qdrant_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/qdrant_volume.tar.gz -C /source .
"@
Write-Host "   ✅ Qdrant backupé" -ForegroundColor Green

# 5. Backup Redis
Write-Host "`n🔹 Backup Redis..." -ForegroundColor Cyan
Write-Host "   ➜ Déclenchement BGSAVE..." -ForegroundColor Yellow
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Déclencher BGSAVE
    docker exec knowbase-redis redis-cli BGSAVE
    sleep 5

    # Copier dump.rdb depuis le volume
    docker run --rm \
        -v knowbase_redis_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine sh -c 'cp /source/dump.rdb /backup/redis_dump.rdb || echo "No dump.rdb"'
"@
Write-Host "   ✅ Redis backupé" -ForegroundColor Green

# 6. Backup Neo4j
Write-Host "`n🔹 Backup Neo4j..." -ForegroundColor Cyan
Write-Host "   ➜ Export base Neo4j via cypher-shell..." -ForegroundColor Yellow
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Export complet via cypher-shell
    docker exec knowbase-neo4j cypher-shell -u neo4j -p $Neo4jPassword \
        --format plain \
        'MATCH (n) OPTIONAL MATCH (n)-[r]->() RETURN n, r' \
        > $RemoteBackupDir/neo4j_export.cypher 2>/dev/null || echo 'Export cypher failed'

    # Backup volumes Neo4j (data + logs)
    docker run --rm \
        -v knowbase_neo4j_data:/source_data:ro \
        -v knowbase_neo4j_logs:/source_logs:ro \
        -v $RemoteBackupDir:/backup \
        alpine sh -c 'tar czf /backup/neo4j_data.tar.gz -C /source_data . && tar czf /backup/neo4j_logs.tar.gz -C /source_logs .'
"@
Write-Host "   ✅ Neo4j backupé" -ForegroundColor Green

# 7. Backup dossier Data
Write-Host "`n🔹 Backup dossier Data..." -ForegroundColor Cyan
Write-Host "   ➜ Compression du volume app_data..." -ForegroundColor Yellow
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    # Backup volume app_data (docs, uploads, etc.)
    docker run --rm \
        -v knowbase_app_data:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_data.tar.gz -C /source .

    # Backup volume app_logs (logs fichiers)
    docker run --rm \
        -v knowbase_app_logs:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_logs.tar.gz -C /source .

    # Backup volume app_models (modèles ML si présents)
    docker run --rm \
        -v knowbase_app_models:/source:ro \
        -v $RemoteBackupDir:/backup \
        alpine tar czf /backup/app_models.tar.gz -C /source . 2>/dev/null || echo 'No models'
"@
Write-Host "   ✅ Data backupé" -ForegroundColor Green

# 8. Créer manifeste de backup
Write-Host "`n📋 Création du manifeste..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host @"
    cat > $RemoteBackupDir/backup_manifest.json <<EOF
{
  "backup_timestamp": "$BackupTimestamp",
  "backup_date": "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  "source_ec2": "$EC2Host",
  "components": {
    "qdrant": ["qdrant_snapshots/", "qdrant_volume.tar.gz"],
    "redis": ["redis_dump.rdb"],
    "neo4j": ["neo4j_export.cypher", "neo4j_data.tar.gz", "neo4j_logs.tar.gz"],
    "data": ["app_data.tar.gz", "app_logs.tar.gz", "app_models.tar.gz"]
  },
  "sizes": {}
}
EOF

    # Ajouter tailles des fichiers
    du -sh $RemoteBackupDir/* >> $RemoteBackupDir/backup_manifest.txt
"@
Write-Host "   ✅ Manifeste créé" -ForegroundColor Green

# 9. Télécharger backup en local
Write-Host "`n⬇️  Téléchargement du backup en local..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $LocalBackupDir | Out-Null
scp -i $KeyPath -o StrictHostKeyChecking=no -r "ubuntu@$($EC2Host):$RemoteBackupDir/*" $LocalBackupDir\
Write-Host "   ✅ Backup téléchargé: $LocalBackupDir" -ForegroundColor Green

# 10. Upload vers S3
Write-Host "`n☁️  Upload vers S3..." -ForegroundColor Cyan
$S3Prefix = "backups/$BackupTimestamp"
Write-Host "   ➜ Destination: s3://$S3BucketName/$S3Prefix/" -ForegroundColor Yellow
aws s3 sync $LocalBackupDir "s3://$S3BucketName/$S3Prefix/" --only-show-errors

if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Upload S3 terminé" -ForegroundColor Green
} else {
    Write-Host "   ❌ Erreur upload S3" -ForegroundColor Red
    exit 1
}

# 11. Nettoyer backup temporaire sur EC2
Write-Host "`n🧹 Nettoyage du backup temporaire sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2Host "rm -rf $RemoteBackupDir"
Write-Host "   ✅ Nettoyage terminé" -ForegroundColor Green

# 12. Résumé final
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Backup terminé avec succès !" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "📦 Bucket S3    : $S3BucketName" -ForegroundColor Cyan
Write-Host "📂 Chemin S3    : s3://$S3BucketName/$S3Prefix/" -ForegroundColor Cyan
Write-Host "🕐 Timestamp    : $BackupTimestamp" -ForegroundColor Cyan
Write-Host "💾 Local        : $LocalBackupDir" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Cyan
Write-Host "Pour restaurer ce backup :" -ForegroundColor Yellow
Write-Host ".\restore-from-s3.ps1 -StackName 'Osmos' -BackupTimestamp '$BackupTimestamp' -S3BucketName '$S3BucketName'" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
