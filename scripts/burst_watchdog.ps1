# burst_watchdog.ps1 — Sentinelle burst pour run de nuit.
# Toutes les ~90s : vérifie la santé du vLLM burst. Si down (interruption spot), trouve
# l'instance g6 de remplacement (le spot fleet en relance une), attend son vLLM, et
# re-pointe l'état burst Redis (via le helper projet, avec auth) → le router récupère.
# S'arrête à HH:mm cible. Loggue chaque action.
param(
  [string]$Region = "eu-central-1",
  [string]$StopAt = "09:30"   # heure locale d'arrêt de la sentinelle
)
$ErrorActionPreference = "Continue"
Set-Location "C:\Projects\SAP_KB"
$stop = [datetime]::ParseExact($StopAt, "HH:mm", $null)
if ($stop -lt (Get-Date)) { $stop = $stop.AddDays(1) }
Write-Host "[WATCHDOG] démarrage, arrêt prévu à $StopAt"

function Get-BurstIp {
  $s = docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis as g; d=g() or {}; print((d.get('vllm_url') or '').replace('http://','').replace(':8000',''))" 2>$null
  return ($s | Select-Object -Last 1).Trim()
}
function Test-Vllm($ip) {
  if (-not $ip) { return $false }
  try { $r = Invoke-WebRequest -Uri "http://${ip}:8000/health" -TimeoutSec 6 -UseBasicParsing; return ($r.StatusCode -eq 200) } catch { return $false }
}

while ((Get-Date) -lt $stop) {
  Start-Sleep -Seconds 90
  $curIp = Get-BurstIp
  if (Test-Vllm $curIp) { continue }   # burst sain → rien à faire
  Write-Host "[WATCHDOG] $(Get-Date -Format HH:mm:ss) vLLM down sur '$curIp' — recherche remplacement..."
  # Trouver l'instance g6 running
  $newIp = aws ec2 describe-instances --region $Region --filters "Name=instance-state-name,Values=running" "Name=instance-type,Values=g6.2xlarge,g6.xlarge" --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>$null
  if (-not $newIp -or $newIp -eq "None") { Write-Host "[WATCHDOG] pas d'instance g6 running (fleet en cours de relance ?)"; continue }
  # Attendre son vLLM (max ~7 min)
  $ok = $false
  for ($i=1; $i -le 28; $i++) { if (Test-Vllm $newIp) { $ok = $true; break }; Start-Sleep -Seconds 15 }
  if ($ok) {
    docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis as s; s('http://${newIp}:8000','Qwen/Qwen2.5-14B-Instruct-AWQ','http://${newIp}:8001')" 2>$null | Out-Null
    Write-Host "[WATCHDOG] $(Get-Date -Format HH:mm:ss) RE-POINTÉ sur $newIp"
  } else {
    Write-Host "[WATCHDOG] nouvelle instance $newIp pas prête (vLLM)"
  }
}
Write-Host "[WATCHDOG] arrêt ($StopAt atteint)"
