# Convert file to UTF-8 with BOM
param(
    [string]$FilePath
)

$content = Get-Content $FilePath -Raw -Encoding UTF8
$utf8WithBom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($FilePath, $content, $utf8WithBom)
Write-Host "File converted to UTF-8 with BOM: $FilePath"
