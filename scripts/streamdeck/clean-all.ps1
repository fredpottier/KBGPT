# Stream Deck - Clean All (DANGER - demande confirmation)
$command = @"
Set-Location 'C:\Projects\SAP_KB'

Write-Host ''
Write-Host '============================================' -ForegroundColor Red
Write-Host '  ⚠️  ATTENTION: NETTOYAGE COMPLET  ⚠️' -ForegroundColor Red
Write-Host '============================================' -ForegroundColor Red
Write-Host ''
Write-Host 'Cette action va:' -ForegroundColor Yellow
Write-Host '  - Arreter TOUS les containers' -ForegroundColor Yellow
Write-Host '  - Supprimer les volumes Docker' -ForegroundColor Yellow
Write-Host '  - Purger les donnees (SAUF extraction_cache)' -ForegroundColor Yellow
Write-Host ''
Write-Host '============================================' -ForegroundColor Red
`$confirm = Read-Host \"Tapez 'CONFIRMER' pour continuer (ou Entree pour annuler)\"
if (`$confirm -eq 'CONFIRMER') {
    Write-Host ''
    Write-Host 'Nettoyage en cours...' -ForegroundColor Cyan
    ./kw.ps1 clean
    Write-Host ''
    Write-Host 'Nettoyage termine!' -ForegroundColor Green
} else {
    Write-Host ''
    Write-Host 'Annule.' -ForegroundColor Green
}
Write-Host ''
Read-Host 'Appuyez sur Entree pour fermer'
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $command
