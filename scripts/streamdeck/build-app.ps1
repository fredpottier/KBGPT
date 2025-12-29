# Stream Deck - Build App Services Only
Set-Location "C:\Projects\SAP_KB"
Write-Host "Building app Docker images..." -ForegroundColor Cyan
docker-compose -f docker-compose.yml build app ingestion-worker frontend streamlit-ui
Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Read-Host "Appuyez sur Entree pour fermer"
