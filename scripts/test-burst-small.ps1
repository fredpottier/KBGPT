$ErrorActionPreference = "Continue"

$login = Invoke-RestMethod -Uri 'http://localhost:8000/api/auth/login' -Method Post -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"admin123"}'
$headers = @{ 'Authorization' = "Bearer $($login.access_token)"; 'Content-Type' = 'application/json' }

# Use the smaller test PDF
Write-Host "=== 1. Preparing Batch (small PDF) ===" -ForegroundColor Cyan
$body = '{"document_paths": ["/data/docs_in/test_burst_small.pdf"]}'
$prepare = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/prepare' -Method Post -Headers $headers -Body $body
Write-Host "Batch ID: $($prepare.batch_id)"
Write-Host "Documents: $($prepare.documents_count)"

# Start infrastructure
Write-Host "`n=== 2. Starting Infrastructure ===" -ForegroundColor Cyan
$startBody = '{"force": true}'
$start = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/start' -Method Post -Headers $headers -Body $startBody
Write-Host "Status: $($start.status)"
Write-Host "Instance IP: $($start.instance_ip)"
Write-Host "vLLM URL: $($start.vllm_url)"

# Process batch
Write-Host "`n=== 3. Processing Batch ===" -ForegroundColor Cyan
$startTime = Get-Date
Write-Host "Started at: $($startTime.ToString('HH:mm:ss'))"
$process = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/process' -Method Post -Headers $headers -TimeoutSec 600
Write-Host "Processing started"

# Monitor progress
Write-Host "`n=== 4. Monitoring Progress ===" -ForegroundColor Cyan
for ($i = 1; $i -le 20; $i++) {
    Start-Sleep -Seconds 15
    try {
        $status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
        $elapsed = (Get-Date) - $startTime
        Write-Host "[$($elapsed.ToString('mm\:ss'))] Status: $($status.status), Done: $($status.documents_done)/$($status.total_documents)"

        if ($status.status -eq "completed" -or $status.status -eq "failed") {
            break
        }
    } catch {
        Write-Host "[$($elapsed.ToString('mm\:ss'))] API unreachable - checking container..."
        docker ps --format "{{.Names}} {{.Status}}" | Select-String "knowbase-app"
    }
}

# Final status
Write-Host "`n=== 5. Final Status ===" -ForegroundColor Cyan
$endTime = Get-Date
$duration = $endTime - $startTime
Write-Host "Duration: $($duration.TotalMinutes.ToString('F1')) minutes"

try {
    $status = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/status' -Headers $headers
    $status | ConvertTo-Json -Depth 3

    Write-Host "`n=== Documents ===" -ForegroundColor Cyan
    $docs = Invoke-RestMethod -Uri 'http://localhost:8000/api/burst/documents' -Headers $headers
    $docs.documents | ForEach-Object {
        Write-Host "  $($_.name): $($_.status) - $($_.chunks_count) chunks"
    }
} catch {
    Write-Host "Could not get final status: $($_.Exception.Message)" -ForegroundColor Red
}
