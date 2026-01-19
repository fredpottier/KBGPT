Add-Type -AssemblyName System.IO.Compression.FileSystem
$dir = 'C:\Projects\SAP_KB\data\burst\waiting'
$results = @()

Get-ChildItem $dir -File | ForEach-Object {
    $pages = 0
    if ($_.Extension -eq '.pdf') {
        try {
            $content = [System.IO.File]::ReadAllBytes($_.FullName)
            $text = [System.Text.Encoding]::GetEncoding('iso-8859-1').GetString($content)
            $m = [regex]::Matches($text, '/Type\s*/Page[^s]')
            $pages = $m.Count
        } catch { $pages = -1 }
    }
    elseif ($_.Extension -eq '.pptx') {
        try {
            $zip = [System.IO.Compression.ZipFile]::OpenRead($_.FullName)
            $slides = $zip.Entries | Where-Object { $_.FullName -match '^ppt/slides/slide[0-9]+\.xml$' }
            $pages = $slides.Count
            $zip.Dispose()
        } catch { $pages = -1 }
    }
    $results += [PSCustomObject]@{ Pages = $pages; Name = $_.Name }
}

Write-Host ""
$results | Sort-Object Pages | ForEach-Object {
    Write-Host ('{0,4} pages | {1}' -f $_.Pages, $_.Name)
}
