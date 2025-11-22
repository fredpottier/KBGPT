$dashboardPath = "C:\Projects\SAP_KB\monitoring\dashboards\phase_1_8_metrics.json"
$grafanaUrl = "http://localhost:3001"
$auth = "admin:admin"
$base64Auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($auth))

Write-Host "Upload Dashboard vers Grafana..." -ForegroundColor Cyan

# Load dashboard JSON
$dashboardContent = Get-Content $dashboardPath -Raw | ConvertFrom-Json

# Wrap in Grafana API format
$payload = @{
    dashboard = $dashboardContent
    overwrite = $true
    message = "Updated via script - metrics implementation"
} | ConvertTo-Json -Depth 50

# Upload to Grafana
$headers = @{
    "Authorization" = "Basic $base64Auth"
    "Content-Type" = "application/json"
}

try {
    $response = Invoke-RestMethod -Uri "$grafanaUrl/api/dashboards/db" -Method Post -Headers $headers -Body $payload
    Write-Host "Dashboard uploade avec succes!" -ForegroundColor Green
    Write-Host "   URL: $grafanaUrl$($response.url)" -ForegroundColor Gray
    Write-Host "   UID: $($response.uid)" -ForegroundColor Gray
    Write-Host "   Version: $($response.version)" -ForegroundColor Gray
} catch {
    Write-Host "Erreur upload: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
