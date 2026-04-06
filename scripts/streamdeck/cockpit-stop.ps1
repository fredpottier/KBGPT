# Stream Deck - Stop OSMOSIS Cockpit
$ProjectDir = "C:\Projects\SAP_KB"
$PidFile = "$ProjectDir\cockpit\.cockpit.pid"
$CockpitPort = 9090
$ChromeProfile = "$ProjectDir\cockpit\.chrome-profile"

# -- Fermer Chrome cockpit --
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$ChromeProfile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# -- Tuer backend via PID --
if (Test-Path $PidFile) {
    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($savedPid) {
        Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# -- Tuer tout process restant sur le port --
Get-NetTCPConnection -LocalPort $CockpitPort -ErrorAction SilentlyContinue |
    ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like "*python*") {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }

# -- Notification Windows --
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    "Cockpit arrete",
    "OSMOSIS",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
