Add-Type -AssemblyName System.IO.Compression.FileSystem

$docs = Get-ChildItem 'C:\Projects\SAP_KB\data\docs_done' | Where-Object {
    $_.Name -notmatch 'Joule_L0_(debug|clean|bridge|final|test|phase0)'
}

$results = @()

foreach ($f in $docs) {
    $pages = 0

    if ($f.Extension -eq '.pdf') {
        try {
            $content = [System.IO.File]::ReadAllBytes($f.FullName)
            $text = [System.Text.Encoding]::GetEncoding('iso-8859-1').GetString($content)
            $matches = [regex]::Matches($text, '/Type\s*/Page[^s]')
            $pages = $matches.Count
        } catch {
            $pages = -1
        }
    }
    elseif ($f.Extension -eq '.pptx') {
        try {
            $zip = [System.IO.Compression.ZipFile]::OpenRead($f.FullName)
            $slides = $zip.Entries | Where-Object { $_.FullName -match '^ppt/slides/slide[0-9]+\.xml$' }
            $pages = $slides.Count
            $zip.Dispose()
        } catch {
            $pages = -1
        }
    }

    if ($pages -gt 0) {
        $results += [PSCustomObject]@{
            Pages = $pages
            Name = $f.Name
        }
    }
}

Write-Host "`n=== Documents triés par nombre de pages/slides ===`n"
$results | Sort-Object Pages | ForEach-Object {
    Write-Host ("{0,4} pages | {1}" -f $_.Pages, $_.Name)
}
Write-Host ""
