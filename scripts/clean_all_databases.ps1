# Script de nettoyage complet de toutes les bases de données
# Usage: .\scripts\clean_all_databases.ps1 [-Confirm]

param(
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"

# Fonction pour afficher des logs colorés
function Log-Info($message) {
    Write-Host "ℹ️  $message" -ForegroundColor Blue
}

function Log-Success($message) {
    Write-Host "✅ $message" -ForegroundColor Green
}

function Log-Warning($message) {
    Write-Host "⚠️  $message" -ForegroundColor Yellow
}

function Log-Error($message) {
    Write-Host "❌ $message" -ForegroundColor Red
}

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  🧹 NETTOYAGE COMPLET DES BASES DE DONNÉES SAP KB" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Log-Warning "Ce script va supprimer TOUTES les données de :"
Write-Host "  • Qdrant (collections knowbase et rfp_qa)"
Write-Host "  • Redis (DB 0 et DB 1)"
Write-Host "  • Neo4j (tous les nodes et relations)"
Write-Host "  • Postgres/Graphiti (cache episodes)"
Write-Host "  • Historique imports (data/status/)"
Write-Host ""

if (-not $Confirm) {
    $response = Read-Host "Êtes-vous sûr de vouloir continuer ? (tapez 'oui' pour confirmer)"
    if ($response -ne "oui") {
        Log-Error "Annulation du nettoyage."
        exit 1
    }
}

Write-Host ""
Log-Info "Démarrage du nettoyage..."
Write-Host ""

# ═══════════════════════════════════════════════════════════════════
# 1. QDRANT - Supprimer toutes les collections
# ═══════════════════════════════════════════════════════════════════
Log-Info "[1/5] Nettoyage Qdrant..."

try {
    $qdrantResponse = Invoke-RestMethod -Uri "http://localhost:6333/collections" -Method Get
    $collections = $qdrantResponse.result.collections

    if ($collections.Count -eq 0) {
        Log-Warning "Aucune collection Qdrant trouvée"
    } else {
        foreach ($collection in $collections) {
            $collectionName = $collection.name
            Log-Info "  Suppression collection: $collectionName"
            Invoke-RestMethod -Uri "http://localhost:6333/collections/$collectionName" -Method Delete | Out-Null
            Log-Success "  Collection $collectionName supprimée"
        }
    }
} catch {
    Log-Warning "Erreur lors du nettoyage Qdrant: $_"
}

# ═══════════════════════════════════════════════════════════════════
# 2. REDIS - Purger toutes les bases
# ═══════════════════════════════════════════════════════════════════
Log-Info "[2/5] Nettoyage Redis..."

# DB 0 (imports metadata)
try {
    $db0Size = docker exec knowbase-redis redis-cli -n 0 DBSIZE
    $db0SizeNum = [int]($db0Size -replace '\D','')
    if ($db0SizeNum -gt 0) {
        Log-Info "  Purge Redis DB 0 ($db0SizeNum cles)"
        docker exec knowbase-redis redis-cli -n 0 FLUSHDB | Out-Null
        Log-Success "  Redis DB 0 purgee"
    } else {
        Log-Warning "  Redis DB 0 deja vide"
    }
} catch {
    Log-Warning "Erreur Redis DB 0: $_"
}

# DB 1 (jobs queue)
try {
    $db1Size = docker exec knowbase-redis redis-cli -n 1 DBSIZE
    $db1SizeNum = [int]($db1Size -replace '\D','')
    if ($db1SizeNum -gt 0) {
        Log-Info "  Purge Redis DB 1 ($db1SizeNum cles)"
        docker exec knowbase-redis redis-cli -n 1 FLUSHDB | Out-Null
        Log-Success "  Redis DB 1 purgee"
    } else {
        Log-Warning "  Redis DB 1 deja vide"
    }
} catch {
    Log-Warning "Erreur Redis DB 1: $_"
}

# ═══════════════════════════════════════════════════════════════════
# 3. NEO4J - Supprimer tous les nodes et relations
# ═══════════════════════════════════════════════════════════════════
Log-Info "[3/5] Nettoyage Neo4j..."

try {
    $neo4jContainer = docker ps --format "{{.Names}}" | Select-String "graphiti-neo4j"
    if ($neo4jContainer) {
        $neo4jUser = if ($env:NEO4J_USER) { $env:NEO4J_USER } else { "neo4j" }
        $neo4jPassword = if ($env:NEO4J_PASSWORD) { $env:NEO4J_PASSWORD } else { "graphiti_password" }

        $nodeCountOutput = docker exec graphiti-neo4j cypher-shell -u $neo4jUser -p $neo4jPassword "MATCH (n) RETURN count(n) as count" 2>&1
        $nodeCount = ($nodeCountOutput | Select-String "\d+" | Select-Object -Last 1).Matches.Value

        if ([int]$nodeCount -gt 0) {
            Log-Info "  Suppression de $nodeCount nodes Neo4j"
            docker exec graphiti-neo4j cypher-shell -u $neo4jUser -p $neo4jPassword "MATCH (n) DETACH DELETE n" | Out-Null
            Log-Success "  Neo4j purge ($nodeCount nodes supprimes)"
        } else {
            Log-Warning "  Neo4j deja vide"
        }
    } else {
        Log-Warning "  Conteneur Neo4j non trouvé (OK si non utilisé)"
    }
} catch {
    Log-Warning "Erreur Neo4j: $_"
}

# ═══════════════════════════════════════════════════════════════════
# 4. POSTGRES/GRAPHITI - Supprimer cache episodes
# ═══════════════════════════════════════════════════════════════════
Log-Info "[4/5] Nettoyage Postgres (Graphiti cache)..."

try {
    $postgresContainer = docker ps --format "{{.Names}}" | Select-String "graphiti-postgres"
    if ($postgresContainer) {
        $postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "postgres" }
        $postgresDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "postgres" }

        $tables = docker exec graphiti-postgres psql -U $postgresUser -d $postgresDb -t -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE '%episode%' OR tablename LIKE '%graphiti%');" 2>&1

        $tableList = $tables -split "`n" | Where-Object { $_.Trim() -ne "" }

        if ($tableList.Count -gt 0) {
            foreach ($table in $tableList) {
                $tableName = $table.Trim()
                Log-Info "  Suppression table: $tableName"
                docker exec graphiti-postgres psql -U $postgresUser -d $postgresDb -c "DROP TABLE IF EXISTS $tableName CASCADE;" | Out-Null
            }
            Log-Success "  Tables Graphiti supprimees"
        } else {
            Log-Warning "  Aucune table Graphiti trouvee"
        }
    } else {
        Log-Warning "  Conteneur Postgres non trouvé (OK si non utilisé)"
    }
} catch {
    Log-Warning "Erreur Postgres: $_"
}

# ═══════════════════════════════════════════════════════════════════
# 5. HISTORIQUE IMPORTS - Supprimer fichiers status
# ═══════════════════════════════════════════════════════════════════
Log-Info "[5/5] Nettoyage historique imports..."

try {
    $statusDir = ".\data\status"
    if (Test-Path $statusDir) {
        $statusFiles = Get-ChildItem -Path $statusDir -Filter "*.json"
        if ($statusFiles.Count -gt 0) {
            Log-Info "  Suppression de $($statusFiles.Count) fichiers status"
            Remove-Item -Path "$statusDir\*.json" -Force
            Log-Success "  Historique imports nettoye"
        } else {
            Log-Warning "  Aucun fichier status trouve"
        }
    } else {
        Log-Warning "  Repertoire status non trouve"
    }
} catch {
    Log-Warning "Erreur nettoyage historique: $_"
}

# ═══════════════════════════════════════════════════════════════════
# RÉSUMÉ FINAL
# ═══════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Log-Success "NETTOYAGE TERMINE AVEC SUCCES"
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Log-Info "Resume des operations :"
Write-Host "  • Qdrant : toutes les collections supprimees"
Write-Host "  • Redis : DB 0 et DB 1 purgees"
Write-Host "  • Neo4j : tous les nodes supprimes"
Write-Host "  • Postgres : cache Graphiti nettoye"
Write-Host "  • Historique : fichiers status supprimes"
Write-Host ""
Log-Info "Vous pouvez maintenant importer un nouveau PPTX avec une base propre."
Write-Host ""
