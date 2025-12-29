$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$token = $login.access_token
$headers = @{ 'Authorization' = "Bearer $token"; 'Content-Type' = 'application/json' }

Write-Host "=== Re-activating Burst Providers ===" -ForegroundColor Cyan

# Try to call start with force
try {
    $body = '{"force": true}'
    $result = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/start' -Method Post -Headers $headers -Body $body
    Write-Host "Start result:"
    $result | ConvertTo-Json
} catch {
    Write-Host "Start failed: $($_.Exception.Message)" -ForegroundColor Yellow

    # Try process directly
    Write-Host "Trying /process..." -ForegroundColor Cyan
    try {
        $result = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/process' -Method Post -Headers $headers
        Write-Host "Process result:"
        $result | ConvertTo-Json
    } catch {
        Write-Host "Process failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Show final status
Write-Host "`n=== Final Status ===" -ForegroundColor Cyan
$status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
$status | ConvertTo-Json -Depth 3
