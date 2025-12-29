$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$token = $login.access_token
$headers = @{ 'Authorization' = "Bearer $token" }

Write-Host "=== BURST STATUS ===" -ForegroundColor Cyan
$status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
$status | ConvertTo-Json -Depth 5

Write-Host "`n=== DOCUMENTS ===" -ForegroundColor Cyan
$docs = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/documents' -Headers $headers
$docs | ConvertTo-Json -Depth 5
