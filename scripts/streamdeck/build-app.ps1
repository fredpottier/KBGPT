# Stream Deck - Build App Services Only
Set-Location "C:\Projects\SAP_KB"

$startTime = Get-Date
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KNOWWHERE - BUILD APP SERVICES" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Demarrage du build..." -ForegroundColor Yellow

# Services a builder
$services = @("app", "ingestion-worker", "folder-watcher")

foreach ($service in $services) {
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Building $service..." -ForegroundColor Cyan

    $buildStart = Get-Date

    # Note: 2>&1 redirige stderr vers stdout pour eviter les faux positifs PowerShell
    $output = docker-compose -f docker-compose.infra.yml -f docker-compose.yml build --no-cache $service 2>&1
    $exitCode = $LASTEXITCODE

    # Afficher les lignes importantes
    $output | ForEach-Object {
        $line = $_.ToString()
        if ($line -match "Step \d+/\d+") {
            Write-Host "  $line" -ForegroundColor DarkGray
        } elseif ($line -match "Successfully|Built") {
            Write-Host "  $line" -ForegroundColor Green
        } elseif ($line -match "error|Error|ERROR" -and $line -notmatch "ErrorAction") {
            Write-Host "  $line" -ForegroundColor Red
        }
    }

    if ($exitCode -eq 0) {
        $buildDuration = ((Get-Date) - $buildStart).TotalSeconds
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] OK $service ($([math]::Round($buildDuration))s)" -ForegroundColor Green
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ECHEC $service (code: $exitCode)" -ForegroundColor Red
        Read-Host "Appuyez sur Entree pour fermer"
        exit 1
    }
}

# Redemarrer les services
Write-Host ""
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Redemarrage des services..." -ForegroundColor Yellow
docker-compose -f docker-compose.infra.yml -f docker-compose.yml up -d app ingestion-worker folder-watcher

$totalDuration = ((Get-Date) - $startTime).TotalSeconds
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  BUILD TERMINE en $([math]::Round($totalDuration))s" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Notification sonore Windows
[Console]::Beep(800, 200)
[Console]::Beep(1000, 200)

Read-Host "Appuyez sur Entree pour fermer"
