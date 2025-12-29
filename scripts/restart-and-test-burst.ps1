$ErrorActionPreference = "Continue"

$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$headers = @{ 'Authorization' = "Bearer $($login.access_token)"; 'Content-Type' = 'application/json' }

# Cancel current batch
Write-Host "=== Cancelling current batch ===" -ForegroundColor Yellow
try {
    $cancel = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/cancel' -Method Post -Headers $headers
    Write-Host "Cancel result: $($cancel.message)"
} catch {
    Write-Host "Cancel failed (may be already completed): $($_.Exception.Message)"
}

Write-Host "`n=== Waiting for app restart... ===" -ForegroundColor Cyan
Start-Sleep -Seconds 5

# Prepare batch
Write-Host "`n=== Preparing new batch ===" -ForegroundColor Cyan
$body = '{"document_paths": ["/data/docs_in/nist_ai_rmf_playbook.pdf"]}'
$prepare = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/prepare' -Method Post -Headers $headers -Body $body
Write-Host "Batch ID: $($prepare.batch_id)"
Write-Host "Documents: $($prepare.documents_count)"

# Start infrastructure
Write-Host "`n=== Starting Infrastructure ===" -ForegroundColor Cyan
$startBody = '{"force": true}'
$start = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/start' -Method Post -Headers $headers -Body $startBody
Write-Host "Status: $($start.status)"
Write-Host "Instance IP: $($start.instance_ip)"
Write-Host "vLLM URL: $($start.vllm_url)"
Write-Host "Message: $($start.message)"

# Check that model name is correct
Write-Host "`n=== Checking vLLM model ===" -ForegroundColor Cyan
$models = Invoke-RestMethod -Uri "http://$($start.instance_ip):8000/v1/models"
Write-Host "Available model: $($models.data[0].id)"

# Process batch
Write-Host "`n=== Processing Batch ===" -ForegroundColor Cyan
$startTime = Get-Date
Write-Host "Started at: $($startTime.ToString('HH:mm:ss'))"
$process = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/process' -Method Post -Headers $headers -TimeoutSec 900
Write-Host "Processing started (background)"

# Monitor progress
Write-Host "`n=== Monitoring Progress ===" -ForegroundColor Cyan
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 30
    $status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
    $elapsed = (Get-Date) - $startTime
    Write-Host "[$($elapsed.ToString('mm\:ss'))] Status: $($status.status), Done: $($status.documents_done)/$($status.total_documents)"

    if ($status.status -eq "completed" -or $status.status -eq "failed") {
        break
    }
}

# Final status
Write-Host "`n=== Final Status ===" -ForegroundColor Cyan
$endTime = Get-Date
$duration = $endTime - $startTime
Write-Host "Duration: $($duration.TotalMinutes.ToString('F1')) minutes"
$status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
$status | ConvertTo-Json -Depth 3
