$ErrorActionPreference = "Stop"

$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$headers = @{ 'Authorization' = "Bearer $($login.access_token)"; 'Content-Type' = 'application/json' }

# Prepare batch with the test document (correct path: /data/docs_in/)
Write-Host "=== 1. Preparing Batch ===" -ForegroundColor Cyan
$body = '{"document_paths": ["/data/docs_in/nist_ai_rmf_playbook.pdf"]}'
$prepare = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/prepare' -Method Post -Headers $headers -Body $body
Write-Host "Batch ID: $($prepare.batch_id)"
Write-Host "Documents: $($prepare.documents_count)"
$prepare.documents | ForEach-Object { Write-Host "  - $($_.name)" }

# Start infrastructure (should reconnect)
Write-Host "`n=== 2. Starting/Reconnecting Infrastructure ===" -ForegroundColor Cyan
$startBody = '{"force": true}'
$start = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/start' -Method Post -Headers $headers -Body $startBody
Write-Host "Status: $($start.status)"
Write-Host "Instance IP: $($start.instance_ip)"
Write-Host "vLLM URL: $($start.vllm_url)"
Write-Host "Embeddings URL: $($start.embeddings_url)"

# Process batch
Write-Host "`n=== 3. Processing Batch (this will take a while) ===" -ForegroundColor Cyan
$startTime = Get-Date
Write-Host "Started at: $($startTime.ToString('HH:mm:ss'))"
$process = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/process' -Method Post -Headers $headers -TimeoutSec 900
$endTime = Get-Date
$duration = $endTime - $startTime
Write-Host "Completed at: $($endTime.ToString('HH:mm:ss'))"
Write-Host "Duration: $($duration.TotalMinutes.ToString('F1')) minutes"
Write-Host "Result:"
$process | ConvertTo-Json

Write-Host "`n=== 4. Final Status ===" -ForegroundColor Cyan
Start-Sleep -Seconds 2
$status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
$status | ConvertTo-Json -Depth 3
