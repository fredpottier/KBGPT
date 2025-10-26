<#
.SYNOPSIS
    Restaure un backup KnowBase depuis archive .tar.gz (locale ou S3)

.DESCRIPTION
    Restaure une archive complète sur une instance EC2.
    Source : Local (fichier .tar.gz) ou S3 (bucket)

.PARAMETER StackName
    Nom de la stack CloudFormation (pour récupérer l'IP EC2)

.PARAMETER BackupSource
    Source du backup : "Local" ou "S3"

.PARAMETER LocalArchivePath
    Chemin vers l'archive locale .tar.gz (requis si BackupSource="Local")

.PARAMETER BackupTimestamp
    Timestamp du backup S3 (requis si BackupSource="S3")

.PARAMETER S3BucketName
    Nom du bucket S3 (requis si BackupSource="S3")

.PARAMETER KeyPath
    Chemin vers la clé SSH PEM (défaut: .\Osmose_KeyPair.pem)

.PARAMETER RestartServices
    Redémarrer les services après restauration (défaut: $true)

.EXAMPLE
    # Restauration depuis archive locale
    .\restore-knowbase.ps1 `
        -StackName "Osmos" `
        -BackupSource Local `
        -LocalArchivePath ".\backups\knowbase_backup_20251026_143052.tar.gz"

.EXAMPLE
    # Restauration depuis S3
    .\restore-knowbase.ps1 `
        -StackName "Osmos" `
        -BackupSource S3 `
        -BackupTimestamp "20251026_143052" `
        -S3BucketName "knowbase-backups-715927975014"

.EXAMPLE
    # Restauration sans redémarrer les services
    .\restore-knowbase.ps1 `
        -StackName "Osmos" `
        -BackupSource Local `
        -LocalArchivePath ".\backups\knowbase_backup_20251026_143052.tar.gz" `
        -RestartServices $false
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$true)]
    [ValidateSet("Local", "S3")]
    [string]$BackupSource,

    [Parameter(Mandatory=$false)]
    [string]$LocalArchivePath = "",

    [Parameter(Mandatory=$false)]
    [string]$BackupTimestamp = "",

    [Parameter(Mandatory=$false)]
    [string]$S3BucketName = "",

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = ".\Osmose_KeyPair.pem",

    [Parameter(Mandatory=$false)]
    [bool]$RestartServices = $true
)

$ErrorActionPreference = "Stop"

# Validation
if ($BackupSource -eq "Local" -and [string]::IsNullOrEmpty($LocalArchivePath)) {
    Write-Host "❌ Erreur: -LocalArchivePath requis quand -BackupSource Local" -ForegroundColor Red
    exit 1
}

if ($BackupSource -eq "S3" -and ([string]::IsNullOrEmpty($BackupTimestamp) -or [string]::IsNullOrEmpty($S3BucketName))) {
    Write-Host "❌ Erreur: -BackupTimestamp et -S3BucketName requis quand -BackupSource S3" -ForegroundColor Red
    exit 1
}

if ($BackupSource -eq "Local" -and !(Test-Path $LocalArchivePath)) {
    Write-Host "❌ Erreur: Archive introuvable: $LocalArchivePath" -ForegroundColor Red
    exit 1
}

# Configuration
$RemoteRestoreDir = "/tmp/knowbase_restore_$(Get-Date -Format 'yyyyMMddHHmmss')"
$Neo4jPassword = "graphiti_neo4j_pass"

if ($BackupSource -eq "S3") {
    $ArchiveName = "knowbase_backup_$BackupTimestamp.tar.gz"
} else {
    $ArchiveName = Split-Path $LocalArchivePath -Leaf
}

Write-Host "🔄 Restauration KnowBase" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "📦 Archive : $ArchiveName" -ForegroundColor Cyan
Write-Host "🎯 Source  : $BackupSource" -ForegroundColor Cyan
if ($BackupSource -eq "S3") {
    Write-Host "☁️  Bucket S3: $S3BucketName" -ForegroundColor Cyan
} else {
    Write-Host "💾 Local   : $LocalArchivePath" -ForegroundColor Cyan
}
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# 1. Récupérer l'IP EC2 depuis CloudFormation
Write-Host "`n🔍 Récupération de l'IP EC2 depuis '$StackName'..." -ForegroundColor Cyan
$EC2InstanceId = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" `
    --output text

if ([string]::IsNullOrEmpty($EC2InstanceId)) {
    Write-Host "   ❌ Stack introuvable ou pas d'InstanceId" -ForegroundColor Red
    exit 1
}

$EC2PublicIP = aws ec2 describe-instances `
    --instance-ids $EC2InstanceId `
    --query "Reservations[0].Instances[0].PublicIpAddress" `
    --output text

if ([string]::IsNullOrEmpty($EC2PublicIP)) {
    Write-Host "   ❌ Impossible de récupérer l'IP publique" -ForegroundColor Red
    exit 1
}

Write-Host "   ✅ EC2: $EC2PublicIP ($EC2InstanceId)" -ForegroundColor Green

# 2. Obtenir l'archive (S3 ou Local)
$LocalTempArchive = ""

if ($BackupSource -eq "S3") {
    Write-Host "`n⬇️  Téléchargement depuis S3..." -ForegroundColor Cyan
    $S3Key = "backups/$ArchiveName"
    $LocalTempArchive = Join-Path $env:TEMP $ArchiveName

    aws s3 cp "s3://$S3BucketName/$S3Key" $LocalTempArchive --only-show-errors

    if ($LASTEXITCODE -ne 0 -or !(Test-Path $LocalTempArchive)) {
        Write-Host "   ❌ Erreur téléchargement S3" -ForegroundColor Red
        exit 1
    }

    $ArchiveSize = (Get-Item $LocalTempArchive).Length / 1MB
    Write-Host "   ✅ Archive téléchargée: $([math]::Round($ArchiveSize, 2)) MB" -ForegroundColor Green
} else {
    $LocalTempArchive = $LocalArchivePath
    $ArchiveSize = (Get-Item $LocalTempArchive).Length / 1MB
    Write-Host "`n📦 Archive locale: $([math]::Round($ArchiveSize, 2)) MB" -ForegroundColor Cyan
}

# 3. Upload vers EC2
Write-Host "`n⬆️  Upload de l'archive vers EC2..." -ForegroundColor Cyan
scp -i $KeyPath -o StrictHostKeyChecking=no $LocalTempArchive "ubuntu@$($EC2PublicIP):/tmp/$ArchiveName"

if ($LASTEXITCODE -ne 0) {
    Write-Host "   ❌ Erreur upload vers EC2" -ForegroundColor Red
    exit 1
}
Write-Host "   ✅ Upload terminé" -ForegroundColor Green

# 4. Extraire l'archive sur EC2
Write-Host "`n📂 Extraction de l'archive sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    mkdir -p $RemoteRestoreDir
    cd $RemoteRestoreDir
    tar xzf /tmp/$ArchiveName
    rm /tmp/$ArchiveName
"@
Write-Host "   ✅ Archive extraite" -ForegroundColor Green

# 5. Arrêter les services si demandé
if ($RestartServices) {
    Write-Host "`n⏸️  Arrêt des services..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml stop app ingestion-worker qdrant redis neo4j
"@
    Write-Host "   ✅ Services arrêtés" -ForegroundColor Green
}

# 6. Restaurer Qdrant
Write-Host "`n🔹 Restauration Qdrant..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    docker run --rm \
        -v knowbase_qdrant_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/qdrant.tar.gz'
"@
Write-Host "   ✅ Qdrant restauré" -ForegroundColor Green

# 7. Restaurer Redis
Write-Host "`n🔹 Restauration Redis..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    docker run --rm \
        -v knowbase_redis_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/redis.tar.gz'
"@
Write-Host "   ✅ Redis restauré" -ForegroundColor Green

# 8. Restaurer Neo4j
Write-Host "`n🔹 Restauration Neo4j..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    docker run --rm \
        -v knowbase_neo4j_data:/target_data \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target_data && tar xzf /backup/neo4j_data.tar.gz'

    docker run --rm \
        -v knowbase_neo4j_logs:/target_logs \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target_logs && tar xzf /backup/neo4j_logs.tar.gz'
"@
Write-Host "   ✅ Neo4j restauré" -ForegroundColor Green

# 9. Restaurer Data
Write-Host "`n🔹 Restauration Data..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    docker run --rm \
        -v knowbase_app_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/app_data.tar.gz'

    docker run --rm \
        -v knowbase_app_logs:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/app_logs.tar.gz'

    # app_models optionnel
    if [ -f "$RemoteRestoreDir/app_models.tar.gz" ]; then
        docker run --rm \
            -v knowbase_app_models:/target \
            -v $RemoteRestoreDir:/backup:ro \
            alpine sh -c 'cd /target && tar xzf /backup/app_models.tar.gz'
    fi
"@
Write-Host "   ✅ Data restauré" -ForegroundColor Green

# 10. Redémarrer les services si demandé
if ($RestartServices) {
    Write-Host "`n▶️  Redémarrage des services..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d neo4j qdrant redis
        sleep 10
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d app ingestion-worker
"@
    Write-Host "   ✅ Services redémarrés" -ForegroundColor Green

    Write-Host "`n⏳ Attente stabilisation (30s)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30

    Write-Host "`n🔍 Vérification des services..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml ps
"@
}

# 11. Nettoyer
Write-Host "`n🧹 Nettoyage..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP "rm -rf $RemoteRestoreDir"

# Nettoyer archive S3 téléchargée
if ($BackupSource -eq "S3" -and (Test-Path $LocalTempArchive)) {
    Remove-Item $LocalTempArchive -Force
}

Write-Host "   ✅ Nettoyage terminé" -ForegroundColor Green

# 12. Résumé final
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Restauration terminée avec succès !" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "🖥️  EC2 Instance : $EC2PublicIP ($EC2InstanceId)" -ForegroundColor Cyan
Write-Host "📦 Archive      : $ArchiveName" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Cyan
Write-Host "🌐 Accès KnowBase :" -ForegroundColor Yellow
Write-Host "   Frontend      : http://$EC2PublicIP:3000" -ForegroundColor White
Write-Host "   API           : http://$EC2PublicIP:8000/docs" -ForegroundColor White
Write-Host "   Grafana       : http://$EC2PublicIP:3001 (admin / Rn1lm@tr)" -ForegroundColor White
Write-Host "   Neo4j Browser : http://$EC2PublicIP:7474 (neo4j / graphiti_neo4j_pass)" -ForegroundColor White
Write-Host "" -ForegroundColor Cyan

if ($RestartServices) {
    Write-Host "⚠️  Services redémarrés. Vérifiez les logs :" -ForegroundColor Yellow
    Write-Host "   ssh -i $KeyPath ubuntu@$EC2PublicIP 'cd ~/knowbase && docker-compose -f docker-compose.ecr.yml logs -f'" -ForegroundColor White
} else {
    Write-Host "⚠️  Services NON redémarrés. Pour démarrer :" -ForegroundColor Yellow
    Write-Host "   ssh -i $KeyPath ubuntu@$EC2PublicIP 'cd ~/knowbase && docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d'" -ForegroundColor White
}

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
