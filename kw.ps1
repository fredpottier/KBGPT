# KnowWhere/OSMOSE - Script de gestion Docker unifie
# Usage: ./kw.ps1 [commande] [options]

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(Position=1)]
    [string]$Service = "all",

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

$INFRA_FILE = "docker-compose.infra.yml"
$APP_FILE = "docker-compose.yml"
$MONITORING_FILE = "docker-compose.monitoring.yml"
$COMPOSE_CMD = "docker-compose -f $INFRA_FILE -f $APP_FILE -f $MONITORING_FILE"

# Mot de passe Grafana (synchronisé avec .env)
$GRAFANA_PASSWORD = "Rn1lm@tr"

# Repertoire backups
$BACKUPS_DIR = "data/backups/snapshots"

# Neo4j image (synchronisé avec docker-compose.infra.yml)
$NEO4J_IMAGE = "neo4j:5.26.0"
$NEO4J_VOLUME = "knowbase_neo4j_data"

# Collections Qdrant a sauvegarder
$QDRANT_COLLECTIONS = @("knowbase_chunks_v2", "rfp_qa")

function Show-Help {
    Write-Host ""
    Write-Host "KnowWhere/OSMOSE - Gestionnaire Docker" -ForegroundColor Cyan
    Write-Host "=======================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Commandes:" -ForegroundColor Yellow
    Write-Host "  start [infra|app|monitoring|all]    Demarrer les services (defaut: all)" -ForegroundColor White
    Write-Host "  stop [infra|app|monitoring|all]     Arreter les services (defaut: all)" -ForegroundColor White
    Write-Host "  restart [infra|app|monitoring|all]  Redemarrer les services (defaut: all)" -ForegroundColor White
    Write-Host "  status                   Afficher statut des services" -ForegroundColor White
    Write-Host "  logs <service>           Voir logs (ex: app, worker, neo4j)" -ForegroundColor White
    Write-Host "  info                     Afficher URLs et credentials" -ForegroundColor White
    Write-Host "  clean                    Purger volumes et containers (DANGER!)" -ForegroundColor White
    Write-Host "  ps                       Lister containers actifs" -ForegroundColor White
    Write-Host "  backup <name> [--no-cache]          Creer un backup complet" -ForegroundColor White
    Write-Host "  restore <name> [--force] [--auto-backup]  Restaurer un backup" -ForegroundColor White
    Write-Host "  backup-list              Lister les backups disponibles" -ForegroundColor White
    Write-Host "  backup-delete <name>     Supprimer un backup" -ForegroundColor White
    Write-Host "  help                     Afficher cette aide" -ForegroundColor White
    Write-Host ""
    Write-Host "Exemples:" -ForegroundColor Yellow
    Write-Host "  ./kw.ps1 start               # Demarre infra + app + monitoring" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 backup SAP_20260218  # Cree un backup complet" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 restore SAP_20260218 # Restaure un backup" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 backup-list          # Liste les backups" -ForegroundColor Gray
    Write-Host ""
}

function Show-Info {
    Write-Host ""
    Write-Host "URLs d'Acces" -ForegroundColor Cyan
    Write-Host "============" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Application:" -ForegroundColor Yellow
    Write-Host "  Frontend Next.js  : http://localhost:3000" -ForegroundColor Green
    Write-Host "  API Backend       : http://localhost:8000" -ForegroundColor Green
    Write-Host "  API Documentation : http://localhost:8000/docs" -ForegroundColor Green
    Write-Host "  Streamlit UI      : http://localhost:8501" -ForegroundColor Green
    Write-Host ""
    Write-Host "Infrastructure:" -ForegroundColor Yellow
    Write-Host "  Neo4j Browser     : http://localhost:7474" -ForegroundColor Green
    Write-Host "    Login           : neo4j" -ForegroundColor Magenta
    Write-Host "    Password        : graphiti_neo4j_pass" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  Qdrant Dashboard  : http://localhost:6333/dashboard" -ForegroundColor Green
    Write-Host "    (pas d'auth)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Redis             : localhost:6379" -ForegroundColor Green
    Write-Host "    (pas d'auth)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Monitoring:" -ForegroundColor Yellow
    Write-Host "  Grafana           : http://localhost:3001" -ForegroundColor Green
    Write-Host "    Login           : admin" -ForegroundColor Magenta
    Write-Host "    Password        : Rn1lm@tr" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  Loki API          : http://localhost:3101" -ForegroundColor Green
    Write-Host "    (agregation logs)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Configuration" -ForegroundColor Cyan
    Write-Host "=============" -ForegroundColor Cyan
    Write-Host "  MAX_WORKERS       : 30 (parallelisation vision GPT-4o)" -ForegroundColor Magenta
    Write-Host ""
}

function Reset-GrafanaPassword {
    Write-Host ""
    Write-Host "Configuration mot de passe Grafana..." -ForegroundColor Cyan

    # Attendre que Grafana soit pret (max 60 secondes)
    $maxAttempts = 30
    $attempt = 0
    $grafanaReady = $false

    Write-Host "   Attente demarrage Grafana..." -ForegroundColor Gray -NoNewline
    while ($attempt -lt $maxAttempts -and -not $grafanaReady) {
        $attempt++
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:3001/api/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $grafanaReady = $true
            }
        } catch {
            Write-Host "." -ForegroundColor Gray -NoNewline
            Start-Sleep -Seconds 2
        }
    }
    Write-Host ""

    if ($grafanaReady) {
        # Reset le mot de passe via grafana-cli (silencieux)
        $result = docker exec knowbase-grafana grafana cli admin reset-admin-password $GRAFANA_PASSWORD 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   Mot de passe Grafana configure: admin / $GRAFANA_PASSWORD" -ForegroundColor Green
        } else {
            Write-Host "   Avertissement: Impossible de configurer le mot de passe Grafana" -ForegroundColor Yellow
            Write-Host "   Essayez: docker exec knowbase-grafana grafana cli admin reset-admin-password $GRAFANA_PASSWORD" -ForegroundColor Gray
        }
    } else {
        Write-Host "   Grafana pas encore pret - mot de passe non configure" -ForegroundColor Yellow
        Write-Host "   Executez apres demarrage: docker exec knowbase-grafana grafana cli admin reset-admin-password $GRAFANA_PASSWORD" -ForegroundColor Gray
    }
}

function Start-Services {
    param([string]$Target)

    Write-Host ""
    Write-Host "Demarrage des services..." -ForegroundColor Cyan

    switch ($Target) {
        "infra" {
            Write-Host "   Infrastructure uniquement (Qdrant, Redis, Neo4j)" -ForegroundColor Gray
            docker-compose -f $INFRA_FILE up -d
        }
        "app" {
            Write-Host "   Application uniquement (App, Worker, Frontend, UI)" -ForegroundColor Gray
            docker-compose -f $APP_FILE up -d
        }
        "monitoring" {
            Write-Host "   Monitoring uniquement (Grafana, Loki, Promtail)" -ForegroundColor Gray
            docker-compose -f $MONITORING_FILE up -d
        }
        default {
            Write-Host "   Infrastructure + Application + Monitoring" -ForegroundColor Gray
            Invoke-Expression "$COMPOSE_CMD up -d"
        }
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Services demarres avec succes!" -ForegroundColor Green

        # Reset mot de passe Grafana si monitoring est demarre
        if ($Target -eq "monitoring" -or $Target -eq "all" -or $Target -eq "") {
            Reset-GrafanaPassword
        }

        Start-Sleep -Seconds 2
        Get-Status
        Show-Info
    } else {
        Write-Host ""
        Write-Host "Erreur lors du demarrage" -ForegroundColor Red
    }
}

function Stop-Services {
    param([string]$Target)

    Write-Host ""
    Write-Host "Arret des services..." -ForegroundColor Cyan

    switch ($Target) {
        "infra" {
            Write-Host "   Infrastructure uniquement" -ForegroundColor Gray
            docker-compose -f $INFRA_FILE down
        }
        "app" {
            Write-Host "   Application uniquement" -ForegroundColor Gray
            docker-compose -f $APP_FILE down
        }
        "monitoring" {
            Write-Host "   Monitoring uniquement" -ForegroundColor Gray
            docker-compose -f $MONITORING_FILE down
        }
        default {
            Write-Host "   Tous les services" -ForegroundColor Gray
            Invoke-Expression "$COMPOSE_CMD down"
        }
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Services arretes avec succes!" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Erreur lors de l'arret" -ForegroundColor Red
    }
}

function Restart-Services {
    param([string]$Target)

    Write-Host ""
    Write-Host "Redemarrage des services..." -ForegroundColor Cyan

    Stop-Services -Target $Target
    Start-Sleep -Seconds 2
    Start-Services -Target $Target
}

function Get-Status {
    Write-Host ""
    Write-Host "Statut des services" -ForegroundColor Cyan
    Write-Host "===================" -ForegroundColor Cyan
    Write-Host ""
    Invoke-Expression "$COMPOSE_CMD ps"
}

function Get-Logs {
    param([string]$ServiceName)

    # Alias mapping pour noms de services
    $serviceAliases = @{
        "worker" = "ingestion-worker"
    }

    # Resoudre l'alias si presente
    if ($serviceAliases.ContainsKey($ServiceName)) {
        $ServiceName = $serviceAliases[$ServiceName]
    }

    if ($ServiceName -eq "all") {
        Write-Host ""
        Write-Host "Logs de tous les services (Ctrl+C pour quitter)" -ForegroundColor Cyan
        Invoke-Expression "$COMPOSE_CMD logs -f"
    } else {
        Write-Host ""
        Write-Host "Logs du service: $ServiceName (Ctrl+C pour quitter)" -ForegroundColor Cyan
        Invoke-Expression "$COMPOSE_CMD logs -f $ServiceName"
    }
}

function Clean-All {
    Write-Host ""
    Write-Host "ATTENTION: Nettoyage complet" -ForegroundColor Red
    Write-Host "Cela va supprimer:" -ForegroundColor Yellow
    Write-Host "  - Tous les containers KnowWhere" -ForegroundColor Gray
    Write-Host "  - Tous les volumes Docker (donnees Neo4j, Qdrant, Redis)" -ForegroundColor Gray
    Write-Host "  - Le reseau knowbase_network" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Les caches d'extraction dans data/extraction_cache/ seront PRESERVES" -ForegroundColor Green
    Write-Host ""

    $confirm = Read-Host "Etes-vous sur? (tapez OUI pour confirmer)"

    if ($confirm -eq "OUI") {
        Write-Host ""
        Write-Host "Nettoyage en cours..." -ForegroundColor Cyan

        # Arreter tous les services
        Invoke-Expression "$COMPOSE_CMD down -v"

        # Supprimer containers orphelins
        docker ps -a | Select-String "knowbase" | ForEach-Object {
            $containerId = ($_ -split "\s+")[0]
            docker rm -f $containerId 2>$null
        }

        Write-Host ""
        Write-Host "Nettoyage termine!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Pour redemarrer: ./kw.ps1 start" -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "Nettoyage annule" -ForegroundColor Yellow
    }
}

# ============================================================================
# BACKUP & RESTORE
# ============================================================================

function Format-FileSize {
    param([long]$Size)
    if ($Size -lt 1KB) { return "$Size B" }
    elseif ($Size -lt 1MB) { return "{0:N1} KB" -f ($Size / 1KB) }
    elseif ($Size -lt 1GB) { return "{0:N1} MB" -f ($Size / 1MB) }
    else { return "{0:N2} GB" -f ($Size / 1GB) }
}

function Get-DirSize {
    param([string]$Path)
    if (Test-Path $Path) {
        return (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    }
    return 0
}

function New-Backup {
    param(
        [string]$Name,
        [bool]$IncludeCache = $true
    )

    $startTime = Get-Date

    # Valider le nom
    if ($Name -notmatch '^[a-zA-Z0-9_\-]+$') {
        Write-Host "ERREUR: Le nom du backup ne peut contenir que des lettres, chiffres, _ et -" -ForegroundColor Red
        exit 1
    }

    $backupDir = Join-Path $BACKUPS_DIR $Name

    # Verifier qu'il n'existe pas deja
    if (Test-Path $backupDir) {
        Write-Host "ERREUR: Un backup '$Name' existe deja dans $backupDir" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " OSMOSE BACKUP : $Name" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Creer les repertoires
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $backupDir "qdrant_snapshots") -Force | Out-Null

    # Initialiser le manifest
    $manifest = @{
        backup_id = [guid]::NewGuid().ToString().Substring(0, 8)
        name = $Name
        created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
        duration_seconds = 0
        size_bytes = 0
        tenant_id = "default"
        osmose_version = "1.0"
        domain_context = @{ industry = ""; domain_summary = "" }
        components = @{}
        imported_documents = @()
    }

    # --- Collecter stats via API (si disponible) ---
    Write-Host "[1/6] Collecte des statistiques..." -ForegroundColor Yellow
    try {
        $token = ""
        # Essayer sans auth d'abord
        $statsResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/backup/current-stats" -Method GET -Headers @{ Authorization = "Bearer admin" } -ErrorAction SilentlyContinue -TimeoutSec 5
        if ($statsResponse) {
            if ($statsResponse.domain_context) {
                $manifest.domain_context = @{
                    industry = if ($statsResponse.domain_context.industry) { $statsResponse.domain_context.industry } else { "" }
                    domain_summary = if ($statsResponse.domain_context.domain_summary) { $statsResponse.domain_context.domain_summary } else { "" }
                }
            }
            if ($statsResponse.imported_documents) {
                $manifest.imported_documents = $statsResponse.imported_documents
            }
            Write-Host "   Stats collectees via API" -ForegroundColor Green
        }
    } catch {
        Write-Host "   API non disponible, stats seront partielles" -ForegroundColor Yellow
    }

    # --- PostgreSQL ---
    Write-Host "[2/6] Backup PostgreSQL..." -ForegroundColor Yellow
    try {
        $pgDumpPath = Join-Path $backupDir "postgres_dump.sql"
        docker exec knowbase-postgres pg_dump -U knowbase --clean --if-exists knowbase > $pgDumpPath 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path $pgDumpPath)) {
            $pgSize = (Get-Item $pgDumpPath).Length
            $manifest.components.postgresql = @{
                status = "success"
                size_bytes = $pgSize
            }
            Write-Host "   PostgreSQL: $(Format-FileSize $pgSize)" -ForegroundColor Green
        } else {
            $manifest.components.postgresql = @{ status = "error"; error = "pg_dump failed" }
            Write-Host "   PostgreSQL: ERREUR pg_dump" -ForegroundColor Red
        }
    } catch {
        $manifest.components.postgresql = @{ status = "error"; error = $_.Exception.Message }
        Write-Host "   PostgreSQL: ERREUR - $_" -ForegroundColor Red
    }

    # --- Qdrant ---
    Write-Host "[3/6] Backup Qdrant..." -ForegroundColor Yellow
    $qdrantOk = $true
    $qdrantSize = 0
    $qdrantCollections = @{}
    foreach ($coll in $QDRANT_COLLECTIONS) {
        try {
            # Creer snapshot
            $snapResponse = Invoke-RestMethod -Uri "http://localhost:6333/collections/$coll/snapshots" -Method POST -TimeoutSec 60 -ErrorAction Stop
            $snapName = $snapResponse.result.name

            if ($snapName) {
                # Telecharger snapshot
                $snapPath = Join-Path $backupDir "qdrant_snapshots" "$coll.snapshot"
                Invoke-WebRequest -Uri "http://localhost:6333/collections/$coll/snapshots/$snapName" -OutFile $snapPath -TimeoutSec 300
                $snapSize = (Get-Item $snapPath).Length
                $qdrantSize += $snapSize

                # Info collection
                $collInfo = Invoke-RestMethod -Uri "http://localhost:6333/collections/$coll" -Method GET -TimeoutSec 10
                $qdrantCollections[$coll] = @{
                    point_count = $collInfo.result.points_count
                    vector_size = if ($collInfo.result.config.params.vectors.size) { $collInfo.result.config.params.vectors.size } else { 0 }
                }

                Write-Host "   $coll : $($collInfo.result.points_count) points ($(Format-FileSize $snapSize))" -ForegroundColor Green

                # Supprimer le snapshot du serveur (nettoyage)
                try {
                    Invoke-RestMethod -Uri "http://localhost:6333/collections/$coll/snapshots/$snapName" -Method DELETE -TimeoutSec 10 -ErrorAction SilentlyContinue | Out-Null
                } catch {}
            }
        } catch {
            Write-Host "   $coll : ERREUR - $_" -ForegroundColor Red
            $qdrantOk = $false
        }
    }
    $manifest.components.qdrant = @{
        status = if ($qdrantOk) { "success" } else { "error" }
        size_bytes = $qdrantSize
        collections = $qdrantCollections
    }

    # --- Redis ---
    Write-Host "[4/6] Backup Redis..." -ForegroundColor Yellow
    try {
        docker exec knowbase-redis redis-cli BGSAVE | Out-Null
        Start-Sleep -Seconds 2

        # Attendre que BGSAVE termine
        $maxWait = 30
        $waited = 0
        while ($waited -lt $maxWait) {
            $lastSave = docker exec knowbase-redis redis-cli LASTSAVE 2>$null
            $bgInProgress = docker exec knowbase-redis redis-cli INFO persistence 2>$null | Select-String "rdb_bgsave_in_progress:1"
            if (-not $bgInProgress) { break }
            Start-Sleep -Seconds 1
            $waited++
        }

        $redisDumpPath = Join-Path $backupDir "redis_dump.rdb"
        docker cp knowbase-redis:/data/dump.rdb $redisDumpPath 2>$null
        if (Test-Path $redisDumpPath) {
            $redisSize = (Get-Item $redisDumpPath).Length
            $manifest.components.redis = @{ status = "success"; size_bytes = $redisSize }
            Write-Host "   Redis: $(Format-FileSize $redisSize)" -ForegroundColor Green
        } else {
            $manifest.components.redis = @{ status = "error"; error = "dump.rdb not found" }
            Write-Host "   Redis: ERREUR - dump.rdb introuvable" -ForegroundColor Red
        }
    } catch {
        $manifest.components.redis = @{ status = "error"; error = $_.Exception.Message }
        Write-Host "   Redis: ERREUR - $_" -ForegroundColor Red
    }

    # --- Extraction Cache ---
    Write-Host "[5/6] Backup Extraction Cache..." -ForegroundColor Yellow
    if ($IncludeCache) {
        $cacheDir = "data/extraction_cache"
        if (Test-Path $cacheDir) {
            $cacheFiles = Get-ChildItem -Path $cacheDir -Filter "*.knowcache.json" -ErrorAction SilentlyContinue
            $cacheCount = ($cacheFiles | Measure-Object).Count
            if ($cacheCount -gt 0) {
                $tarPath = Join-Path $backupDir "extraction_cache.tar.gz"
                # Utiliser tar via docker ou directement si disponible
                try {
                    tar -czf $tarPath -C data extraction_cache 2>$null
                    if (Test-Path $tarPath) {
                        $cacheSize = (Get-Item $tarPath).Length
                        $manifest.components.extraction_cache = @{
                            status = "success"
                            file_count = $cacheCount
                            size_bytes = $cacheSize
                        }
                        Write-Host "   Cache: $cacheCount fichiers ($(Format-FileSize $cacheSize))" -ForegroundColor Green
                    } else {
                        $manifest.components.extraction_cache = @{ status = "error"; error = "tar failed" }
                        Write-Host "   Cache: ERREUR compression" -ForegroundColor Red
                    }
                } catch {
                    $manifest.components.extraction_cache = @{ status = "error"; error = $_.Exception.Message }
                    Write-Host "   Cache: ERREUR - $_" -ForegroundColor Red
                }
            } else {
                $manifest.components.extraction_cache = @{ status = "success"; file_count = 0; size_bytes = 0 }
                Write-Host "   Cache: Aucun fichier" -ForegroundColor Gray
            }
        } else {
            $manifest.components.extraction_cache = @{ status = "skipped"; file_count = 0; size_bytes = 0 }
            Write-Host "   Cache: Repertoire inexistant" -ForegroundColor Gray
        }
    } else {
        $manifest.components.extraction_cache = @{ status = "skipped"; file_count = 0; size_bytes = 0 }
        Write-Host "   Cache: Ignore (--no-cache)" -ForegroundColor Gray
    }

    # --- Neo4j ---
    Write-Host "[6/6] Backup Neo4j..." -ForegroundColor Yellow
    Write-Host "   Arret du container Neo4j..." -ForegroundColor Gray
    try {
        docker stop knowbase-neo4j | Out-Null
        Start-Sleep -Seconds 3

        # Utiliser docker run avec le meme volume pour executer neo4j-admin dump
        Write-Host "   Dump de la base..." -ForegroundColor Gray
        docker run --rm `
            -v "${NEO4J_VOLUME}:/data" `
            -v "${PWD}/${backupDir}:/backup" `
            $NEO4J_IMAGE `
            neo4j-admin database dump neo4j --to-path=/backup 2>&1 | ForEach-Object {
                Write-Host "   $_" -ForegroundColor Gray
            }

        # Verifier que le dump existe
        $neo4jDumpPath = Join-Path $backupDir "neo4j.dump"
        if (Test-Path $neo4jDumpPath) {
            $neo4jSize = (Get-Item $neo4jDumpPath).Length
            $manifest.components.neo4j = @{
                status = "success"
                size_bytes = $neo4jSize
                total_nodes = 0
                total_relationships = 0
            }
            Write-Host "   Neo4j: $(Format-FileSize $neo4jSize)" -ForegroundColor Green
        } else {
            $manifest.components.neo4j = @{ status = "error"; error = "dump file not found" }
            Write-Host "   Neo4j: ERREUR - fichier dump introuvable" -ForegroundColor Red
        }
    } catch {
        $manifest.components.neo4j = @{ status = "error"; error = $_.Exception.Message }
        Write-Host "   Neo4j: ERREUR - $_" -ForegroundColor Red
    } finally {
        # Toujours redemarrer Neo4j
        Write-Host "   Redemarrage Neo4j..." -ForegroundColor Gray
        docker start knowbase-neo4j | Out-Null
    }

    # --- Finaliser manifest ---
    $endTime = Get-Date
    $duration = ($endTime - $startTime).TotalSeconds
    $totalSize = Get-DirSize $backupDir
    $manifest.duration_seconds = [math]::Round($duration, 1)
    $manifest.size_bytes = $totalSize

    # Ecrire manifest
    $manifestPath = Join-Path $backupDir "manifest.json"
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $manifestPath -Encoding UTF8

    # Resume
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " BACKUP COMPLET : $Name" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Repertoire : $backupDir" -ForegroundColor White
    Write-Host "  Taille     : $(Format-FileSize $totalSize)" -ForegroundColor White
    Write-Host "  Duree      : $([math]::Round($duration, 1))s" -ForegroundColor White
    Write-Host ""

    $components = $manifest.components
    foreach ($comp in @("neo4j", "qdrant", "postgresql", "redis", "extraction_cache")) {
        $status = $components[$comp].status
        $color = if ($status -eq "success") { "Green" } elseif ($status -eq "skipped") { "Gray" } else { "Red" }
        $icon = if ($status -eq "success") { "[OK]" } elseif ($status -eq "skipped") { "[--]" } else { "[!!]" }
        Write-Host "  $icon $comp" -ForegroundColor $color
    }
    Write-Host ""
    Write-Host "Backup termine avec succes!" -ForegroundColor Green
}

function Restore-Backup {
    param(
        [string]$Name,
        [bool]$Force = $false,
        [bool]$AutoBackup = $false
    )

    $backupDir = Join-Path $BACKUPS_DIR $Name
    $manifestPath = Join-Path $backupDir "manifest.json"

    # Verifier que le backup existe
    if (-not (Test-Path $manifestPath)) {
        Write-Host "ERREUR: Backup '$Name' non trouve dans $backupDir" -ForegroundColor Red
        exit 1
    }

    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " OSMOSE RESTORE : $Name" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Date backup  : $($manifest.created_at)" -ForegroundColor White
    Write-Host "  Industrie    : $($manifest.domain_context.industry)" -ForegroundColor White
    Write-Host "  Documents    : $($manifest.imported_documents.Count)" -ForegroundColor White
    Write-Host ""

    # Confirmation
    if (-not $Force) {
        Write-Host "ATTENTION: Cette operation va REMPLACER toutes les donnees actuelles!" -ForegroundColor Red
        $confirm = Read-Host "Continuer? (tapez OUI pour confirmer)"
        if ($confirm -ne "OUI") {
            Write-Host "Restauration annulee" -ForegroundColor Yellow
            exit 0
        }
    }

    # Auto-backup si demande
    if ($AutoBackup) {
        $autoName = "auto_before_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Write-Host ""
        Write-Host "Sauvegarde automatique en cours: $autoName" -ForegroundColor Yellow
        New-Backup -Name $autoName -IncludeCache $false
        Write-Host ""
    }

    $startTime = Get-Date

    # --- Neo4j ---
    Write-Host "[1/5] Restore Neo4j..." -ForegroundColor Yellow
    $neo4jDumpPath = Join-Path $backupDir "neo4j.dump"
    if (Test-Path $neo4jDumpPath) {
        try {
            Write-Host "   Arret Neo4j..." -ForegroundColor Gray
            docker stop knowbase-neo4j | Out-Null
            Start-Sleep -Seconds 3

            Write-Host "   Chargement du dump..." -ForegroundColor Gray
            docker run --rm `
                -v "${NEO4J_VOLUME}:/data" `
                -v "${PWD}/${backupDir}:/backup" `
                $NEO4J_IMAGE `
                neo4j-admin database load neo4j --from-path=/backup --overwrite-destination=true 2>&1 | ForEach-Object {
                    Write-Host "   $_" -ForegroundColor Gray
                }

            Write-Host "   Redemarrage Neo4j..." -ForegroundColor Gray
            docker start knowbase-neo4j | Out-Null
            Start-Sleep -Seconds 5
            Write-Host "   Neo4j: OK" -ForegroundColor Green
        } catch {
            Write-Host "   Neo4j: ERREUR - $_" -ForegroundColor Red
            # S'assurer que Neo4j est redemarre
            docker start knowbase-neo4j 2>$null | Out-Null
        }
    } else {
        Write-Host "   Neo4j: Pas de dump, ignore" -ForegroundColor Gray
    }

    # --- PostgreSQL ---
    Write-Host "[2/5] Restore PostgreSQL..." -ForegroundColor Yellow
    $pgDumpPath = Join-Path $backupDir "postgres_dump.sql"
    if (Test-Path $pgDumpPath) {
        try {
            Get-Content $pgDumpPath | docker exec -i knowbase-postgres psql -U knowbase knowbase 2>$null | Out-Null
            Write-Host "   PostgreSQL: OK" -ForegroundColor Green
        } catch {
            Write-Host "   PostgreSQL: ERREUR - $_" -ForegroundColor Red
        }
    } else {
        Write-Host "   PostgreSQL: Pas de dump, ignore" -ForegroundColor Gray
    }

    # --- Qdrant ---
    Write-Host "[3/5] Restore Qdrant..." -ForegroundColor Yellow
    foreach ($coll in $QDRANT_COLLECTIONS) {
        $snapPath = Join-Path $backupDir "qdrant_snapshots" "$coll.snapshot"
        if (Test-Path $snapPath) {
            try {
                # Supprimer la collection existante
                try {
                    Invoke-RestMethod -Uri "http://localhost:6333/collections/$coll" -Method DELETE -TimeoutSec 30 -ErrorAction SilentlyContinue | Out-Null
                } catch {}
                Start-Sleep -Seconds 1

                # Restaurer depuis le snapshot
                # Utiliser curl car Invoke-RestMethod ne gere pas bien le multipart upload de gros fichiers
                curl.exe -s -X POST "http://localhost:6333/collections/$coll/snapshots/upload" `
                    -H "Content-Type: multipart/form-data" `
                    -F "snapshot=@$snapPath" `
                    --max-time 600 | Out-Null

                if ($LASTEXITCODE -eq 0) {
                    Write-Host "   $coll : OK" -ForegroundColor Green
                } else {
                    Write-Host "   $coll : ERREUR upload snapshot" -ForegroundColor Red
                }
            } catch {
                Write-Host "   $coll : ERREUR - $_" -ForegroundColor Red
            }
        } else {
            Write-Host "   $coll : Pas de snapshot, ignore" -ForegroundColor Gray
        }
    }

    # --- Redis ---
    Write-Host "[4/5] Restore Redis..." -ForegroundColor Yellow
    $redisDumpPath = Join-Path $backupDir "redis_dump.rdb"
    if (Test-Path $redisDumpPath) {
        try {
            docker stop knowbase-redis | Out-Null
            Start-Sleep -Seconds 2
            docker cp $redisDumpPath knowbase-redis:/data/dump.rdb 2>$null
            docker start knowbase-redis | Out-Null
            Start-Sleep -Seconds 2
            Write-Host "   Redis: OK" -ForegroundColor Green
        } catch {
            Write-Host "   Redis: ERREUR - $_" -ForegroundColor Red
            docker start knowbase-redis 2>$null | Out-Null
        }
    } else {
        Write-Host "   Redis: Pas de dump, ignore" -ForegroundColor Gray
    }

    # --- Extraction Cache ---
    Write-Host "[5/5] Restore Extraction Cache..." -ForegroundColor Yellow
    $cacheTarPath = Join-Path $backupDir "extraction_cache.tar.gz"
    if (Test-Path $cacheTarPath) {
        try {
            tar -xzf $cacheTarPath -C data 2>$null
            Write-Host "   Cache: OK" -ForegroundColor Green
        } catch {
            Write-Host "   Cache: ERREUR - $_" -ForegroundColor Red
        }
    } else {
        Write-Host "   Cache: Pas d'archive, ignore" -ForegroundColor Gray
    }

    # Resume
    $endTime = Get-Date
    $duration = ($endTime - $startTime).TotalSeconds

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " RESTORE COMPLET : $Name" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Duree : $([math]::Round($duration, 1))s" -ForegroundColor White
    Write-Host ""
    Write-Host "Restore termine avec succes!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Note: Redemarrez l'application pour prendre en compte les changements:" -ForegroundColor Yellow
    Write-Host "  ./kw.ps1 restart app" -ForegroundColor Gray
}

function List-Backups {
    Write-Host ""
    Write-Host "Backups disponibles" -ForegroundColor Cyan
    Write-Host "===================" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path $BACKUPS_DIR)) {
        Write-Host "  Aucun backup trouve" -ForegroundColor Gray
        Write-Host ""
        return
    }

    $backups = Get-ChildItem -Path $BACKUPS_DIR -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending

    if ($backups.Count -eq 0) {
        Write-Host "  Aucun backup trouve" -ForegroundColor Gray
        Write-Host ""
        return
    }

    Write-Host ("{0,-30} {1,-22} {2,-12} {3,-20}" -f "NOM", "DATE", "TAILLE", "INDUSTRIE") -ForegroundColor Yellow
    Write-Host ("{0,-30} {1,-22} {2,-12} {3,-20}" -f "---", "----", "------", "---------") -ForegroundColor Gray

    foreach ($dir in $backups) {
        $manifestPath = Join-Path $dir.FullName "manifest.json"
        if (Test-Path $manifestPath) {
            try {
                $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
                $size = Get-DirSize $dir.FullName
                $sizeStr = Format-FileSize $size
                $dateStr = if ($manifest.created_at) {
                    try { (Get-Date $manifest.created_at -Format "yyyy-MM-dd HH:mm") } catch { $manifest.created_at.Substring(0, 19) }
                } else { "?" }
                $industry = if ($manifest.domain_context.industry) { $manifest.domain_context.industry } else { "-" }

                Write-Host ("{0,-30} {1,-22} {2,-12} {3,-20}" -f $dir.Name, $dateStr, $sizeStr, $industry) -ForegroundColor White
            } catch {
                Write-Host ("{0,-30} {1,-22}" -f $dir.Name, "(manifest invalide)") -ForegroundColor Red
            }
        } else {
            Write-Host ("{0,-30} {1,-22}" -f $dir.Name, "(pas de manifest)") -ForegroundColor Red
        }
    }
    Write-Host ""
    Write-Host "  Total: $($backups.Count) backup(s)" -ForegroundColor Gray
    Write-Host ""
}

function Delete-Backup {
    param([string]$Name)

    $backupDir = Join-Path $BACKUPS_DIR $Name

    if (-not (Test-Path $backupDir)) {
        Write-Host "ERREUR: Backup '$Name' non trouve" -ForegroundColor Red
        exit 1
    }

    $size = Get-DirSize $backupDir
    Write-Host ""
    Write-Host "Suppression du backup '$Name' ($(Format-FileSize $size))" -ForegroundColor Yellow
    $confirm = Read-Host "Confirmer? (tapez OUI)"
    if ($confirm -eq "OUI") {
        Remove-Item -Path $backupDir -Recurse -Force
        Write-Host "Backup '$Name' supprime" -ForegroundColor Green
    } else {
        Write-Host "Suppression annulee" -ForegroundColor Yellow
    }
}

# Main
switch ($Command.ToLower()) {
    "start" {
        Start-Services -Target $Service
    }
    "stop" {
        Stop-Services -Target $Service
    }
    "restart" {
        Restart-Services -Target $Service
    }
    "status" {
        Get-Status
    }
    "logs" {
        Get-Logs -ServiceName $Service
    }
    "info" {
        Show-Info
    }
    "clean" {
        Clean-All
    }
    "ps" {
        Get-Status
    }
    "backup" {
        $noCache = $ExtraArgs -contains "--no-cache"
        New-Backup -Name $Service -IncludeCache (-not $noCache)
    }
    "restore" {
        $force = $ExtraArgs -contains "--force"
        $autoBackup = $ExtraArgs -contains "--auto-backup"
        Restore-Backup -Name $Service -Force $force -AutoBackup $autoBackup
    }
    "backup-list" {
        List-Backups
    }
    "backup-delete" {
        Delete-Backup -Name $Service
    }
    "help" {
        Show-Help
    }
    default {
        Write-Host ""
        Write-Host "Commande inconnue: $Command" -ForegroundColor Red
        Show-Help
        exit 1
    }
}
