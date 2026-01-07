# Liste les documents du cache d'extraction avec le nombre de pages
$cacheDir = "C:\Projects\SAP_KB\data\extraction_cache"
$corpusDir = "C:\Projects\SAP_KB\data\corpus"

Add-Type -AssemblyName System.IO.Compression.FileSystem

$results = @()

Get-ChildItem "$cacheDir\*.knowcache.json" | ForEach-Object {
    $json = Get-Content $_.FullName | ConvertFrom-Json
    $sourceName = $json.metadata.source_file

    if ($sourceName) {
        # Chercher le fichier source dans corpus
        $sourceFile = Get-ChildItem -Path $corpusDir -Recurse -Filter $sourceName -ErrorAction SilentlyContinue | Select-Object -First 1

        $pages = 0
        if ($sourceFile) {
            if ($sourceFile.Extension -eq '.pdf') {
                try {
                    $content = [System.IO.File]::ReadAllBytes($sourceFile.FullName)
                    $text = [System.Text.Encoding]::GetEncoding('iso-8859-1').GetString($content)
                    $matches = [regex]::Matches($text, '/Type\s*/Page[^s]')
                    $pages = $matches.Count
                } catch { $pages = -1 }
            }
            elseif ($sourceFile.Extension -eq '.pptx') {
                try {
                    $zip = [System.IO.Compression.ZipFile]::OpenRead($sourceFile.FullName)
                    $slides = $zip.Entries | Where-Object { $_.FullName -match '^ppt/slides/slide[0-9]+\.xml$' }
                    $pages = $slides.Count
                    $zip.Dispose()
                } catch { $pages = -1 }
            }
        }

        $results += [PSCustomObject]@{
            Pages = $pages
            Name = $sourceName
            Found = [bool]$sourceFile
        }
    }
}

Write-Host "`n=== Documents du cache (tries par pages) ===`n"
$results | Sort-Object Pages | ForEach-Object {
    $status = if ($_.Found) { "" } else { " [non trouve]" }
    Write-Host ("{0,4} pages | {1}{2}" -f $_.Pages, $_.Name, $status)
}
Write-Host ""
