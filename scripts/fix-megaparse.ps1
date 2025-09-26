#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Corrige MegaParse en installant les dependances OpenGL dans les containers actifs
.DESCRIPTION
    Script rapide pour installer libGL.so.1 et dependencies dans les containers
    app et worker sans rebuild complet
#>

Write-Host "Correction rapide MegaParse - Installation dependances OpenGL..." -ForegroundColor Yellow

try {
    # Installer les dependances dans le container app
    Write-Host "Installation dans container app..." -ForegroundColor Green
    docker-compose exec -T app bash -c "
        apt-get update > /dev/null 2>&1 &&
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            libgl1 \
            libgl1-mesa-dri \
            libgbm1 \
            xvfb > /dev/null 2>&1 &&
        apt-get clean > /dev/null 2>&1 &&
        rm -rf /var/lib/apt/lists/* > /dev/null 2>&1
    "

    # Installer les dependances dans le container worker
    Write-Host "Installation dans container worker..." -ForegroundColor Green
    docker-compose exec -T ingestion-worker bash -c "
        apt-get update > /dev/null 2>&1 &&
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            libgl1 \
            libgl1-mesa-dri \
            libgbm1 \
            xvfb > /dev/null 2>&1 &&
        apt-get clean > /dev/null 2>&1 &&
        rm -rf /var/lib/apt/lists/* > /dev/null 2>&1
    "

    Write-Host "Redemarrage des containers pour prendre en compte les changements..." -ForegroundColor Cyan
    docker-compose restart app ingestion-worker

    Write-Host "MegaParse corrige avec succes !" -ForegroundColor Green
    Write-Host "Verification dans 10 secondes..." -ForegroundColor Gray

    Start-Sleep 10
    Write-Host "Logs worker (verification MegaParse):" -ForegroundColor Cyan
    docker-compose logs ingestion-worker --tail 5

} catch {
    Write-Host "Erreur lors de la correction: $($_.Exception.Message)" -ForegroundColor Red
}