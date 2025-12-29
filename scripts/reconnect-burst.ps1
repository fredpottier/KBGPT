$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$token = $login.access_token
$headers = @{ 'Authorization' = "Bearer $token" }

Write-Host "=== ACTIVE STACKS ===" -ForegroundColor Cyan
$stacks = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/active-stacks' -Headers $headers
$stacks | ConvertTo-Json -Depth 5

if ($stacks.count -gt 0) {
    $stackName = $stacks.stacks[0].stack_name
    Write-Host "`n=== RECONNECTING TO $stackName ===" -ForegroundColor Yellow

    $body = @{ stack_name = $stackName } | ConvertTo-Json
    $reconnect = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/reconnect' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
    $reconnect | ConvertTo-Json -Depth 5
}
