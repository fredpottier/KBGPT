# Stream Deck - Show All URLs and Info (opens new window)
$command = @"
Set-Location 'C:\Projects\SAP_KB'
Write-Host '============================================' -ForegroundColor Cyan
Write-Host '  KNOWWHERE - INFOS & URLs' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''
./kw.ps1 info
Write-Host ''
Write-Host 'Appuyez sur une touche pour fermer...' -ForegroundColor Yellow
`$null = `$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $command
