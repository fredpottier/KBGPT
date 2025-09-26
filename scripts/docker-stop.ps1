#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Arrete proprement tous les containers avec timeout
.DESCRIPTION
    Script qui arrete Docker Compose avec un timeout de 15 secondes maximum,
    evitant le blocage du terminal PowerShell
#>

param(
    [int]$Timeout = 20
)

Write-Host "Arret des containers Docker Compose..." -ForegroundColor Yellow
Write-Host "Timeout configure: ${Timeout}s" -ForegroundColor Gray

try {
    # Obtenir le répertoire du script
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectDir = Split-Path -Parent $scriptDir

    # Vérifier l'existence du fichier docker-compose.yml
    if (!(Test-Path "$projectDir\docker-compose.yml")) {
        Write-Host "Erreur: docker-compose.yml non trouve dans $projectDir" -ForegroundColor Red
        return
    }

    # Arret avec timeout
    $job = Start-Job -ScriptBlock {
        param($timeout, $projectPath)
        Set-Location $projectPath
        docker-compose down --timeout $timeout
    } -ArgumentList $Timeout, $projectDir

    # Attendre le job avec timeout
    if (Wait-Job $job -Timeout ($Timeout + 5)) {
        $result = Receive-Job $job
        Write-Host $result
        Write-Host "Containers arretes proprement" -ForegroundColor Green
    } else {
        Write-Host "Timeout atteint - Arret force" -ForegroundColor Red
        docker-compose kill
        docker-compose down
        Write-Host "Containers forces a s'arreter" -ForegroundColor Red
    }
} catch {
    Write-Host "Erreur: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    Write-Host "Arret termine - Terminal pret" -ForegroundColor Green
}