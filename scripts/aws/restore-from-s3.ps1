<#
.SYNOPSIS
    Restaure un backup KnowBase depuis S3 vers une nouvelle instance EC2

.DESCRIPTION
    Ce script :
    1. Récupère l'IP de l'EC2 depuis le nom de la stack CloudFormation
    2. Télécharge le backup depuis S3
    3. Restaure Qdrant, Redis, Neo4j et Data sur la nouvelle instance
    4. Redémarre les services si nécessaire

.PARAMETER StackName
    Nom de la stack CloudFormation (ex: "Osmos")

.PARAMETER BackupTimestamp
    Timestamp du backup à restaurer (format: yyyyMMdd_HHmmss)
    Ex: 20251026_123045

.PARAMETER S3BucketName
    Nom du bucket S3 contenant les backups

.PARAMETER KeyPath
    Chemin vers la clé SSH PEM (défaut: .\Osmose_KeyPair.pem)

.PARAMETER RestartServices
    Redémarrer les services après restauration (défaut: $true)

.EXAMPLE
    .\restore-from-s3.ps1 -StackName "Osmos" -BackupTimestamp "20251026_123045" -S3BucketName "knowbase-backups-715927975014"

.EXAMPLE
    # Restaurer sans redémarrer les services
    .\restore-from-s3.ps1 -StackName "Osmos" -BackupTimestamp "20251026_123045" -S3BucketName "knowbase-backups-715927975014" -RestartServices $false
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$true)]
    [string]$BackupTimestamp,

    [Parameter(Mandatory=$true)]
    [string]$S3BucketName,

    [Parameter(Mandatory=$false)]
    [string]$KeyPath = ".\Osmose_KeyPair.pem",

    [Parameter(Mandatory=$false)]
    [bool]$RestartServices = $true
)

$ErrorActionPreference = "Stop"

# Configuration
$S3Prefix = "backups/$BackupTimestamp"
$LocalBackupDir = ".\backups\$BackupTimestamp"
$RemoteRestoreDir = "/tmp/knowbase_restore_$BackupTimestamp"
$Neo4jPassword = "graphiti_neo4j_pass"

Write-Host "🔄 Restauration KnowBase depuis S3" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# 1. Récupérer l'IP de l'EC2 depuis CloudFormation
Write-Host "`n🔍 Récupération de l'IP EC2 depuis la stack '$StackName'..." -ForegroundColor Cyan
$EC2InstanceId = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" `
    --output text

if ([string]::IsNullOrEmpty($EC2InstanceId)) {
    Write-Host "   ❌ Stack '$StackName' introuvable ou pas d'InstanceId" -ForegroundColor Red
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

Write-Host "   ✅ EC2 trouvé: $EC2PublicIP (Instance: $EC2InstanceId)" -ForegroundColor Green

# 2. Vérifier que le backup existe sur S3
Write-Host "`n🔍 Vérification du backup sur S3..." -ForegroundColor Cyan
$S3BackupPath = "s3://$S3BucketName/$S3Prefix/"
$BackupExists = aws s3 ls $S3BackupPath 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ❌ Backup introuvable: $S3BackupPath" -ForegroundColor Red
    exit 1
}
Write-Host "   ✅ Backup trouvé: $S3BackupPath" -ForegroundColor Green

# 3. Télécharger le backup depuis S3
Write-Host "`n⬇️  Téléchargement du backup depuis S3..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $LocalBackupDir | Out-Null
aws s3 sync $S3BackupPath $LocalBackupDir\ --only-show-errors

if ($LASTEXITCODE -ne 0) {
    Write-Host "   ❌ Erreur téléchargement S3" -ForegroundColor Red
    exit 1
}

$BackupSize = (Get-ChildItem $LocalBackupDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "   ✅ Backup téléchargé: $([math]::Round($BackupSize, 2)) MB" -ForegroundColor Green

# 4. Créer répertoire de restauration sur EC2
Write-Host "`n📁 Préparation de l'EC2 pour la restauration..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP "mkdir -p $RemoteRestoreDir"

# 5. Upload du backup vers EC2
Write-Host "`n⬆️  Upload du backup vers EC2..." -ForegroundColor Cyan
scp -i $KeyPath -o StrictHostKeyChecking=no -r "$LocalBackupDir\*" "ubuntu@$($EC2PublicIP):$RemoteRestoreDir\"
Write-Host "   ✅ Upload terminé" -ForegroundColor Green

# 6. Arrêter les services si demandé
if ($RestartServices) {
    Write-Host "`n⏸️  Arrêt des services pour restauration..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml stop app ingestion-worker qdrant redis neo4j
"@
    Write-Host "   ✅ Services arrêtés" -ForegroundColor Green
}

# 7. Restaurer Qdrant
Write-Host "`n🔹 Restauration Qdrant..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    # Restaurer volume complet Qdrant
    docker run --rm \
        -v knowbase_qdrant_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/qdrant_volume.tar.gz'

    echo "   ✅ Volume Qdrant restauré"

    # Restaurer snapshots si présents
    if [ -d "$RemoteRestoreDir/qdrant_snapshots" ]; then
        docker run --rm \
            -v knowbase_qdrant_data:/target \
            -v $RemoteRestoreDir:/backup:ro \
            alpine sh -c 'cp -r /backup/qdrant_snapshots /target/snapshots'
        echo "   ✅ Snapshots Qdrant restaurés"
    fi
"@
Write-Host "   ✅ Qdrant restauré" -ForegroundColor Green

# 8. Restaurer Redis
Write-Host "`n🔹 Restauration Redis..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    # Restaurer dump.rdb Redis
    docker run --rm \
        -v knowbase_redis_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cp /backup/redis_dump.rdb /target/dump.rdb'

    echo "   ✅ Redis dump.rdb restauré"
"@
Write-Host "   ✅ Redis restauré" -ForegroundColor Green

# 9. Restaurer Neo4j
Write-Host "`n🔹 Restauration Neo4j..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    # Restaurer volumes Neo4j (data + logs)
    docker run --rm \
        -v knowbase_neo4j_data:/target_data \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target_data && tar xzf /backup/neo4j_data.tar.gz'

    docker run --rm \
        -v knowbase_neo4j_logs:/target_logs \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target_logs && tar xzf /backup/neo4j_logs.tar.gz'

    echo "   ✅ Volumes Neo4j restaurés"
"@
Write-Host "   ✅ Neo4j restauré" -ForegroundColor Green

# 10. Restaurer Data
Write-Host "`n🔹 Restauration dossier Data..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
    # Restaurer app_data (docs, uploads)
    docker run --rm \
        -v knowbase_app_data:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/app_data.tar.gz'

    echo "   ✅ app_data restauré"

    # Restaurer app_logs
    docker run --rm \
        -v knowbase_app_logs:/target \
        -v $RemoteRestoreDir:/backup:ro \
        alpine sh -c 'cd /target && tar xzf /backup/app_logs.tar.gz'

    echo "   ✅ app_logs restauré"

    # Restaurer app_models si présent
    if [ -f "$RemoteRestoreDir/app_models.tar.gz" ]; then
        docker run --rm \
            -v knowbase_app_models:/target \
            -v $RemoteRestoreDir:/backup:ro \
            alpine sh -c 'cd /target && tar xzf /backup/app_models.tar.gz'
        echo "   ✅ app_models restauré"
    fi
"@
Write-Host "   ✅ Data restauré" -ForegroundColor Green

# 11. Redémarrer les services si demandé
if ($RestartServices) {
    Write-Host "`n▶️  Redémarrage des services..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d neo4j qdrant redis
        sleep 10
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d app ingestion-worker
"@
    Write-Host "   ✅ Services redémarrés" -ForegroundColor Green

    # Attendre que les services soient prêts
    Write-Host "`n⏳ Attente de la disponibilité des services (30s)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30

    # Vérifier les services
    Write-Host "`n🔍 Vérification des services..." -ForegroundColor Cyan
    ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP @"
        cd ~/knowbase
        echo "Services en cours d'exécution :"
        docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml ps
"@
}

# 12. Nettoyer backup temporaire sur EC2
Write-Host "`n🧹 Nettoyage du backup temporaire sur EC2..." -ForegroundColor Cyan
ssh -i $KeyPath -o StrictHostKeyChecking=no ubuntu@$EC2PublicIP "rm -rf $RemoteRestoreDir"
Write-Host "   ✅ Nettoyage terminé" -ForegroundColor Green

# 13. Résumé final
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Restauration terminée avec succès !" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "🖥️  EC2 Instance : $EC2PublicIP ($EC2InstanceId)" -ForegroundColor Cyan
Write-Host "📦 Backup Source : s3://$S3BucketName/$S3Prefix/" -ForegroundColor Cyan
Write-Host "🕐 Timestamp     : $BackupTimestamp" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Cyan
Write-Host "🌐 Accès KnowBase :" -ForegroundColor Yellow
Write-Host "   Frontend      : http://$EC2PublicIP:3000" -ForegroundColor White
Write-Host "   API           : http://$EC2PublicIP:8000/docs" -ForegroundColor White
Write-Host "   Grafana       : http://$EC2PublicIP:3001 (admin / Rn1lm@tr)" -ForegroundColor White
Write-Host "   Neo4j Browser : http://$EC2PublicIP:7474 (neo4j / graphiti_neo4j_pass)" -ForegroundColor White
Write-Host "" -ForegroundColor Cyan

if ($RestartServices) {
    Write-Host "⚠️  Les services ont été redémarrés. Vérifiez les logs :" -ForegroundColor Yellow
    Write-Host "   ssh -i $KeyPath ubuntu@$EC2PublicIP 'docker-compose -f docker-compose.ecr.yml logs -f'" -ForegroundColor White
} else {
    Write-Host "⚠️  Services NON redémarrés. Pour démarrer :" -ForegroundColor Yellow
    Write-Host "   ssh -i $KeyPath ubuntu@$EC2PublicIP 'cd ~/knowbase && docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml up -d'" -ForegroundColor White
}

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
