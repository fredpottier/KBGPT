# Stream Deck - Build Infrastructure Services Only
# Note: Les services infra (qdrant, redis, neo4j, postgres) utilisent des images officielles
# donc il n'y a generalement rien a builder. Ce script est la pour coherence.

Set-Location "C:\Projects\SAP_KB"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KNOWWHERE - BUILD INFRA" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Verification des images infrastructure..." -ForegroundColor Yellow

$output = docker-compose -f docker-compose.infra.yml build 2>&1
$exitCode = $LASTEXITCODE

$output | ForEach-Object {
    $line = $_.ToString()
    if ($line -match "Step|Successfully|Built|pull") {
        Write-Host "  $line" -ForegroundColor DarkGray
    }
}

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] OK - Images infra pretes" -ForegroundColor Green
    Write-Host ""
    Write-Host "Note: Les services infra utilisent des images officielles" -ForegroundColor Yellow
    Write-Host "(qdrant, redis, neo4j, postgres, grafana, loki, promtail)" -ForegroundColor Yellow
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ECHEC (code: $exitCode)" -ForegroundColor Red
}

Write-Host ""
[Console]::Beep(800, 200)
Read-Host "Appuyez sur Entree pour fermer"
