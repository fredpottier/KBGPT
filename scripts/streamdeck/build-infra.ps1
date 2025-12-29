# Stream Deck - Build Infrastructure Services Only
Set-Location "C:\Projects\SAP_KB"
Write-Host "Building infrastructure Docker images..." -ForegroundColor Cyan
docker-compose -f docker-compose.infra.yml build
Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Read-Host "Appuyez sur Entree pour fermer"
