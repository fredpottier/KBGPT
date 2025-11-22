$headers = @{'Content-Type'='application/json'}
$dashboard = Get-Content -Raw -Path 'monitoring/dashboards/phase_1_8_metrics.json' | ConvertFrom-Json
$payload = @{
    dashboard = $dashboard
    overwrite = $true
} | ConvertTo-Json -Depth 50 -Compress

$cred = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:Rn1lm@tr"))
$headers['Authorization'] = "Basic $cred"
$response = Invoke-RestMethod -Uri 'http://localhost:3001/api/dashboards/db' -Method Post -Headers $headers -Body $payload
Write-Output "Dashboard uploaded successfully!"
Write-Output "URL: $($response.url)"
Write-Output "Version: $($response.version)"
