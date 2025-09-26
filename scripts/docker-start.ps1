#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Demarre tous les containers Docker Compose
.DESCRIPTION
    Script qui demarre Docker Compose en mode detache pour eviter les blocages
#>

param(
    [switch]$Build = $false,
    [switch]$Logs = $false
)

Write-Host "Demarrage des containers Docker Compose..." -ForegroundColor Green

# Obtenir le répertoire du script et le répertoire du projet
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir

# Vérifier l'existence du fichier docker-compose.yml
if (!(Test-Path "$projectDir\docker-compose.yml")) {
    Write-Host "Erreur: docker-compose.yml non trouve dans $projectDir" -ForegroundColor Red
    return
}

# Aller dans le répertoire du projet
Set-Location $projectDir

try {
    if ($Build) {
        Write-Host "Build des images..." -ForegroundColor Yellow
        docker-compose up -d --build
    } else {
        docker-compose up -d
    }

    Write-Host "Containers demarres" -ForegroundColor Green

    # Afficher le statut
    Write-Host ""
    Write-Host "Statut des services:" -ForegroundColor Cyan
    docker-compose ps

    if ($Logs) {
        Write-Host ""
        Write-Host "Affichage des logs en temps reel..." -ForegroundColor Yellow
        Write-Host "   (Ctrl+C pour arreter l'affichage des logs)" -ForegroundColor Gray
        docker-compose logs -f
    } else {
        Write-Host ""
        Write-Host "Pour voir les logs: docker-compose logs -f" -ForegroundColor Gray
        Write-Host "Pour arreter: .\scripts\docker-stop.ps1" -ForegroundColor Gray
    }
} catch {
    Write-Host "Erreur: $($_.Exception.Message)" -ForegroundColor Red
}