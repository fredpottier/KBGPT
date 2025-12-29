# Stream Deck - Rebuild All Services (no cache) and Start
Set-Location "C:\Projects\SAP_KB"
Write-Host "Stopping all services..." -ForegroundColor Yellow
./kw.ps1 stop
Write-Host ""
Write-Host "Rebuilding all Docker images (no cache)..." -ForegroundColor Cyan
docker-compose -f docker-compose.infra.yml -f docker-compose.yml build --no-cache
Write-Host ""
Write-Host "Starting all services..." -ForegroundColor Cyan
./kw.ps1 start
Write-Host ""
Write-Host "Rebuild and start complete!" -ForegroundColor Green
Read-Host "Appuyez sur Entree pour fermer"
