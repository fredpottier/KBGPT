# Stream Deck - Build All Services (without starting)
Set-Location "C:\Projects\SAP_KB"
Write-Host "Building all Docker images..." -ForegroundColor Cyan
docker-compose -f docker-compose.infra.yml -f docker-compose.yml build
Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Read-Host "Appuyez sur Entree pour fermer"
