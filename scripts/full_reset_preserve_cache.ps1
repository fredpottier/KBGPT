# Script de purge complete Neo4j + Redis + Qdrant
# PRESERVE les caches d'extraction (data/extraction_cache/)

Write-Host ""
Write-Host "PURGE COMPLETE SYSTEME OSMOSE" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "ATTENTION : Cette operation va supprimer :" -ForegroundColor Yellow
Write-Host "   - Tous les graphes Neo4j"
Write-Host "   - Toutes les queues Redis"
Write-Host "   - Toutes les collections Qdrant"
Write-Host "   - Tous les fichiers de statut"
Write-Host ""
Write-Host "PRESERVE :" -ForegroundColor Green
Write-Host "   - Caches d'extraction (data/extraction_cache/)"
Write-Host "   - Contexte metier Neo4j (DomainContextProfile)"
Write-Host ""

$confirmation = Read-Host "Continuer ? (y/N)"
if ($confirmation -ne 'y' -and $confirmation -ne 'Y') {
    Write-Host "Operation annulee" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "1. Purge Redis..." -ForegroundColor Cyan
docker exec knowbase-redis redis-cli FLUSHDB | Out-Null
Write-Host "   OK Redis purge" -ForegroundColor Green

Write-Host ""
Write-Host "2. Purge Qdrant (collections)..." -ForegroundColor Cyan
try { Invoke-RestMethod -Method Delete -Uri "http://localhost:6333/collections/knowbase" -ErrorAction SilentlyContinue } catch { Write-Host "   Collection knowbase n'existait pas" -ForegroundColor Yellow }
try { Invoke-RestMethod -Method Delete -Uri "http://localhost:6333/collections/rfp_qa" -ErrorAction SilentlyContinue } catch { Write-Host "   Collection rfp_qa n'existait pas" -ForegroundColor Yellow }
try { Invoke-RestMethod -Method Delete -Uri "http://localhost:6333/collections/knowwhere_proto" -ErrorAction SilentlyContinue } catch { Write-Host "   Collection knowwhere_proto n'existait pas" -ForegroundColor Yellow }
Write-Host "   OK Qdrant purge" -ForegroundColor Green

Write-Host ""
Write-Host "3. Purge Neo4j (SAUF DomainContextProfile)..." -ForegroundColor Cyan
$cypher = @"
MATCH (n)
WHERE NOT n:DomainContextProfile
DETACH DELETE n
"@
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain $cypher 2>$null | Out-Null
Write-Host "   OK Neo4j purge (contexte metier preserve)" -ForegroundColor Green

Write-Host ""
Write-Host "4. Purge fichiers traites..." -ForegroundColor Cyan
if (Test-Path "data/docs_done") { Remove-Item -Path "data/docs_done/*" -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path "data/status") { Remove-Item -Path "data/status/*.status" -Force -ErrorAction SilentlyContinue }
Write-Host "   OK Fichiers de statut purges" -ForegroundColor Green

Write-Host ""
Write-Host "5. Verification caches preserves..." -ForegroundColor Cyan
if (Test-Path "data/extraction_cache") {
    $cacheCount = (Get-ChildItem -Path "data/extraction_cache" -Filter "*.knowcache.json" -Recurse -ErrorAction SilentlyContinue).Count
    Write-Host "   OK $cacheCount fichiers cache preserves" -ForegroundColor Green
} else {
    Write-Host "   Dossier extraction_cache introuvable" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "6. Verification contexte metier..." -ForegroundColor Cyan
$cypherCheck = "MATCH (dcp:DomainContextProfile {tenant_id: 'default'}) RETURN dcp.tenant_id AS tenant, dcp.industry AS industry"
$contextCheck = docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain $cypherCheck 2>$null

if ($contextCheck -like "*default*") {
    Write-Host "   OK Contexte metier 'default' preserve" -ForegroundColor Green
} else {
    Write-Host "   Contexte metier 'default' non trouve (peut-etre pas encore cree)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==============================" -ForegroundColor Cyan
Write-Host "PURGE TERMINEE" -ForegroundColor Green
Write-Host ""
Write-Host "Etat du systeme :"
Write-Host "   - Neo4j : Vide (sauf DomainContextProfile)"
Write-Host "   - Redis : Vide"
Write-Host "   - Qdrant : Vide"
Write-Host "   - Caches extraction : Preserves"
Write-Host "   - Contexte metier : Preserve"
Write-Host ""
Write-Host "Pret pour un nouvel import !" -ForegroundColor Green
Write-Host ""
