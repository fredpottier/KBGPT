$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$headers = @{ 'Authorization' = "Bearer $($login.access_token)"; 'Content-Type' = 'application/json' }

Write-Host "=== Stopping Burst Infrastructure ===" -ForegroundColor Yellow
try {
    $result = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/stop' -Method Post -Headers $headers
    Write-Host "Stop result:"
    $result | ConvertTo-Json -Depth 3
} catch {
    Write-Host "Stop failed: $($_.Exception.Message)" -ForegroundColor Red

    # Try cancel instead
    Write-Host "`nTrying /cancel..." -ForegroundColor Cyan
    try {
        $result = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/cancel' -Method Post -Headers $headers
        Write-Host "Cancel result:"
        $result | ConvertTo-Json -Depth 3
    } catch {
        Write-Host "Cancel failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Show final status
Write-Host "`n=== Final Status ===" -ForegroundColor Cyan
$status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
$status | ConvertTo-Json -Depth 3
