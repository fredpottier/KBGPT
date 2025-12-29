# Stream Deck - Show Status of All Services (opens new window)
$command = @"
Set-Location 'C:\Projects\SAP_KB'
Write-Host '============================================' -ForegroundColor Cyan
Write-Host '  KNOWWHERE - STATUS DES SERVICES' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''
./kw.ps1 status
Write-Host ''
Write-Host 'Appuyez sur une touche pour fermer...' -ForegroundColor Yellow
`$null = `$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $command
