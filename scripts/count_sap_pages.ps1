# Compte les pages des fichiers SAP
Add-Type -AssemblyName System.IO.Compression.FileSystem

$sourceDir = "C:\Users\fredp\Downloads\sap_docs"

$sapFiles = @(
    "Joule_L0.pdf",
    "L2_GROW_with_SAP_Overview Oct 2024.pptx",
    "RISE_with_SAP_Cloud_ERP_Private.pptx",
    "SAP-012_Conversion_Guide_for_SAP_S_4HANA_Cloud_Private_Edition_2025.pdf",
    "SAP-017_SAP_Sales_Cloud_Version_2_Integration_Guide_for_SAP_S_4HANA_Cloud_Public_Edition_(Set_Up_and_Managed_by_SAP).pdf",
    "SAP_S4HANA_Cloud,_public_edition-Security_and_Compliance.pptx"
)

$results = @()

foreach ($name in $sapFiles) {
    $f = Get-ChildItem -Path $sourceDir -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1

    if (-not $f) {
        # Essayer avec des variations de nom
        $baseName = $name -replace '_+\d{8}_\d{6}', ''
        $f = Get-ChildItem -Path $sourceDir -Filter $baseName -ErrorAction SilentlyContinue | Select-Object -First 1
    }

    $pages = 0
    if ($f) {
        if ($f.Extension -eq '.pdf') {
            try {
                $content = [System.IO.File]::ReadAllBytes($f.FullName)
                $text = [System.Text.Encoding]::GetEncoding('iso-8859-1').GetString($content)
                $matches = [regex]::Matches($text, '/Type\s*/Page[^s]')
                $pages = $matches.Count
            } catch { $pages = -1 }
        }
        elseif ($f.Extension -eq '.pptx') {
            try {
                $zip = [System.IO.Compression.ZipFile]::OpenRead($f.FullName)
                $slides = $zip.Entries | Where-Object { $_.FullName -match '^ppt/slides/slide[0-9]+\.xml$' }
                $pages = $slides.Count
                $zip.Dispose()
            } catch { $pages = -1 }
        }
        $results += [PSCustomObject]@{ Pages = $pages; Name = $name }
    } else {
        $results += [PSCustomObject]@{ Pages = 0; Name = "$name [non trouve]" }
    }
}

Write-Host "`n=== Fichiers SAP tries par pages (croissant) ===`n"
$results | Sort-Object Pages | ForEach-Object {
    Write-Host ("{0,4} pages | {1}" -f $_.Pages, $_.Name)
}
Write-Host ""
