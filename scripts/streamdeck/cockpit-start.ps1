# Stream Deck - Start OSMOSIS Cockpit
$ProjectDir = "C:\Projects\SAP_KB"
$CockpitVenv = "$ProjectDir\cockpit\.venv\Scripts\python.exe"
$CockpitPort = 9090
$StateUrl = "http://127.0.0.1:${CockpitPort}/cockpit/state"
$CockpitUrl = "http://127.0.0.1:${CockpitPort}/cockpit"
$ChromeProfile = "$ProjectDir\cockpit\.chrome-profile"
$ChromeExe = "C:\Program Files\Google\Chrome\Application\chrome.exe"

# -- Backend : demarrer si pas deja actif --
$backendOk = $false
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $StateUrl -TimeoutSec 2 -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $backendOk = $true }
} catch {}

if (-not $backendOk) {
    # Nettoyer zombie sur le port
    Get-NetTCPConnection -LocalPort $CockpitPort -ErrorAction SilentlyContinue |
        ForEach-Object {
            $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
            if ($p) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
    Start-Sleep -Milliseconds 500

    $proc = Start-Process -FilePath $CockpitVenv `
        -ArgumentList "-m", "cockpit" `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -PassThru
    $proc.Id | Out-File "$ProjectDir\cockpit\.cockpit.pid" -Force

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $StateUrl -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $backendOk = $true; break }
        } catch {}
    }
}

if (-not $backendOk) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("Backend non demarre", "OSMOSIS Erreur") | Out-Null
    exit 1
}

# -- Frontend : fermer ancien + ouvrir nouveau --
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$ChromeProfile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Milliseconds 500

Start-Process -FilePath $ChromeExe -ArgumentList `
    "--kiosk", `
    "--window-position=-307,1080", `
    "--disable-infobars", `
    "--no-first-run", `
    "--noerrdialogs", `
    "--disable-session-crashed-bubble", `
    "--user-data-dir=$ChromeProfile", `
    $CockpitUrl
