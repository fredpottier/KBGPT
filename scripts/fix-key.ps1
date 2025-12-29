$content = Get-Content "C:\Projects\SAP_KB\config\osmose-burst-key2.pem" -Raw
$fixed = $content -replace " ", "`n"
[System.IO.File]::WriteAllText("C:\Projects\SAP_KB\config\osmose-burst-key2.pem", $fixed)
Write-Host "Key fixed"
Get-Content "C:\Projects\SAP_KB\config\osmose-burst-key2.pem" | Select-Object -First 3
