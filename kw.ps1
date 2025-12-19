# KnowWhere/OSMOSE - Script de gestion Docker unifie
# Usage: ./kw.ps1 [commande] [options]

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(Position=1)]
    [string]$Service = "all"
)

$INFRA_FILE = "docker-compose.infra.yml"
$APP_FILE = "docker-compose.yml"
$MONITORING_FILE = "docker-compose.monitoring.yml"
$COMPOSE_CMD = "docker-compose -f $INFRA_FILE -f $APP_FILE -f $MONITORING_FILE"

# Mot de passe Grafana (synchronisé avec .env)
$GRAFANA_PASSWORD = "Rn1lm@tr"

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
    Write-Host "  help                     Afficher cette aide" -ForegroundColor White
    Write-Host ""
    Write-Host "Exemples:" -ForegroundColor Yellow
    Write-Host "  ./kw.ps1 start               # Demarre infra + app + monitoring" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 start infra         # Demarre uniquement infrastructure" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 start monitoring    # Demarre uniquement Grafana/Loki" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 restart app         # Redemarre uniquement application" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 logs app            # Voir logs du backend" -ForegroundColor Gray
    Write-Host "  ./kw.ps1 info                # Afficher toutes les URLs/credentials" -ForegroundColor Gray
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
            $response = Invoke-WebRequest -Uri "http://localhost:3001/api/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
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
