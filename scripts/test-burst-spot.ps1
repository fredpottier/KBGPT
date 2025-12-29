# Test Burst Spot Infrastructure
# Usage: .\scripts\test-burst-spot.ps1

$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"
$STACK_NAME = "burst-test-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$TEMPLATE = "C:\Projects\SAP_KB\src\knowbase\ingestion\burst\cloudformation\burst-spot.yaml"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   OSMOSE Burst Spot - Test Infrastructure" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stack: $STACK_NAME"
Write-Host "Region: $REGION"
Write-Host ""

# 1. Deploy stack
Write-Host "[1/5] Deploying CloudFormation stack..." -ForegroundColor Yellow
& $AWS cloudformation create-stack `
    --region $REGION `
    --stack-name $STACK_NAME `
    --template-body "file://$TEMPLATE" `
    --parameters "ParameterKey=BatchId,ParameterValue=test-$(Get-Date -Format 'HHmmss')" `
    --capabilities CAPABILITY_NAMED_IAM `
    --output json

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to create stack" -ForegroundColor Red
    exit 1
}

Write-Host "Stack creation initiated. Waiting..." -ForegroundColor Green

# 2. Wait for stack
Write-Host "[2/5] Waiting for stack creation (5-10 min)..." -ForegroundColor Yellow
& $AWS cloudformation wait stack-create-complete --region $REGION --stack-name $STACK_NAME

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Stack creation failed" -ForegroundColor Red
    Write-Host "Check events with: aws cloudformation describe-stack-events --stack-name $STACK_NAME"
    exit 1
}

Write-Host "Stack created successfully!" -ForegroundColor Green

# 3. Get instance info
Write-Host "[3/5] Getting instance information..." -ForegroundColor Yellow

$INSTANCE_ID = & $AWS cloudformation describe-stacks `
    --region $REGION `
    --stack-name $STACK_NAME `
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" `
    --output text

$INSTANCE_IP = & $AWS cloudformation describe-stacks `
    --region $REGION `
    --stack-name $STACK_NAME `
    --query "Stacks[0].Outputs[?OutputKey=='InstancePublicIp'].OutputValue" `
    --output text

$INSTANCE_TYPE = & $AWS cloudformation describe-stacks `
    --region $REGION `
    --stack-name $STACK_NAME `
    --query "Stacks[0].Outputs[?OutputKey=='InstanceType'].OutputValue" `
    --output text

Write-Host ""
Write-Host "Instance ID:   $INSTANCE_ID" -ForegroundColor Cyan
Write-Host "Instance Type: $INSTANCE_TYPE" -ForegroundColor Cyan
Write-Host "Public IP:     $INSTANCE_IP" -ForegroundColor Cyan
Write-Host ""

# 4. Wait for services
Write-Host "[4/5] Waiting for vLLM + Embeddings to start (8-15 min)..." -ForegroundColor Yellow
Write-Host "       Model: Qwen/Qwen2.5-14B-Instruct-AWQ (needs ~5min to load)"

$HEALTH_URL = "http://${INSTANCE_IP}:8080/health"
$VLLM_URL = "http://${INSTANCE_IP}:8000"
$EMB_URL = "http://${INSTANCE_IP}:8001"

$maxAttempts = 60  # 15 minutes (60 x 15s)
$attempt = 0
$ready = $false

while (-not $ready -and $attempt -lt $maxAttempts) {
    $attempt++
    Write-Host "  Attempt $attempt/$maxAttempts - checking health..." -NoNewline

    try {
        $response = Invoke-WebRequest -Uri $HEALTH_URL -TimeoutSec 10 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $ready = $true
            Write-Host " READY!" -ForegroundColor Green
        } else {
            Write-Host " not ready (status: $($response.StatusCode))"
        }
    } catch {
        Write-Host " not ready (connecting...)"
    }

    if (-not $ready) {
        Start-Sleep -Seconds 15
    }
}

if (-not $ready) {
    Write-Host "ERROR: Services did not become ready in time" -ForegroundColor Red
    Write-Host "You can check manually: curl $HEALTH_URL"
} else {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "   Services are READY!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "vLLM API:       $VLLM_URL/v1/chat/completions" -ForegroundColor Cyan
    Write-Host "Embeddings API: $EMB_URL/embed" -ForegroundColor Cyan
    Write-Host "Health Check:   $HEALTH_URL" -ForegroundColor Cyan
    Write-Host ""

    # 5. Test vLLM
    Write-Host "[5/5] Testing vLLM API..." -ForegroundColor Yellow

    $testBody = @{
        model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
        messages = @(
            @{ role = "user"; content = "Say 'Hello OSMOSE' in exactly 3 words." }
        )
        max_tokens = 20
    } | ConvertTo-Json -Depth 3

    try {
        $response = Invoke-RestMethod -Uri "$VLLM_URL/v1/chat/completions" `
            -Method POST `
            -ContentType "application/json" `
            -Body $testBody `
            -TimeoutSec 60

        Write-Host "vLLM Response: $($response.choices[0].message.content)" -ForegroundColor Green
        Write-Host ""
        Write-Host "SUCCESS! Infrastructure is working." -ForegroundColor Green
    } catch {
        Write-Host "vLLM test failed: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "   CLEANUP" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "To delete the stack and stop billing:"
Write-Host "  & '$AWS' cloudformation delete-stack --region $REGION --stack-name $STACK_NAME"
Write-Host ""
Write-Host "To keep testing, the instance will continue running."
Write-Host "Estimated cost: ~`$0.70-1.00/hour (Spot)"
Write-Host ""

$cleanup = Read-Host "Delete stack now? (y/N)"
if ($cleanup -eq "y" -or $cleanup -eq "Y") {
    Write-Host "Deleting stack..." -ForegroundColor Yellow
    & $AWS cloudformation delete-stack --region $REGION --stack-name $STACK_NAME
    Write-Host "Stack deletion initiated." -ForegroundColor Green
}
