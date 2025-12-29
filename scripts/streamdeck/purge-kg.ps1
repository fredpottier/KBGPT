# Stream Deck - Purge Knowledge Graph Only (preserve caches)
$command = @'
Set-Location 'C:\Projects\SAP_KB'

Write-Host ''
Write-Host '============================================' -ForegroundColor Yellow
Write-Host '  PURGE KNOWLEDGE GRAPH' -ForegroundColor Yellow
Write-Host '============================================' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Cette action va purger:' -ForegroundColor Yellow
Write-Host '  - Neo4j (tous les noeuds du tenant default)' -ForegroundColor Yellow
Write-Host '  - Qdrant collections' -ForegroundColor Yellow
Write-Host '  - Redis queue' -ForegroundColor Yellow
Write-Host ''
Write-Host 'PRESERVE: extraction_cache (*.knowcache.json)' -ForegroundColor Green
Write-Host ''
Write-Host '============================================' -ForegroundColor Yellow
$confirm = Read-Host "Tapez 'OUI' pour continuer (ou Entree pour annuler)"
if ($confirm -eq 'OUI') {
    Write-Host ''
    Write-Host 'Purge Redis...' -ForegroundColor Cyan
    docker exec knowbase-redis redis-cli FLUSHDB

    Write-Host 'Purge Qdrant...' -ForegroundColor Cyan
    Invoke-RestMethod -Method Delete -Uri 'http://localhost:6333/collections/knowbase' -ErrorAction SilentlyContinue
    Invoke-RestMethod -Method Delete -Uri 'http://localhost:6333/collections/rfp_qa' -ErrorAction SilentlyContinue
    Invoke-RestMethod -Method Delete -Uri 'http://localhost:6333/collections/knowwhere_proto' -ErrorAction SilentlyContinue

    Write-Host 'Purge Neo4j tenant default...' -ForegroundColor Cyan
    docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "MATCH (n) WHERE n.tenant_id = 'default' DETACH DELETE n"

    Write-Host 'Purge fichiers status...' -ForegroundColor Cyan
    Remove-Item -Path 'C:\Projects\SAP_KB\data\docs_in\*' -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path 'C:\Projects\SAP_KB\data\docs_done\*' -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path 'C:\Projects\SAP_KB\data\status\*.status' -Force -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host 'Purge terminee! extraction_cache preserve.' -ForegroundColor Green
} else {
    Write-Host ''
    Write-Host 'Annule.' -ForegroundColor Green
}
Write-Host ''
Read-Host 'Appuyez sur Entree pour fermer'
'@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $command
