# Test Burst Spot - Simple Direct Instance
# Usage: .\scripts\test-burst-simple.ps1

$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   OSMOSE Burst - Test Instance Spot" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$INSTANCE_TYPE = "g6.2xlarge"  # L4 GPU 24GB
$SPOT_PRICE = "1.20"
$KEY_NAME = ""  # Laisser vide si pas de SSH nécessaire

# Get Deep Learning AMI ID via SSM
Write-Host "[1/6] Getting Deep Learning AMI ID..." -ForegroundColor Yellow
$AMI_ID = & $AWS ssm get-parameter `
    --region $REGION `
    --name "/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.5-ubuntu-22.04/latest/ami-id" `
    --query "Parameter.Value" `
    --output text

Write-Host "AMI: $AMI_ID" -ForegroundColor Cyan

# Get default VPC and Subnet
Write-Host "[2/6] Getting network configuration..." -ForegroundColor Yellow
$VPC_ID = & $AWS ec2 describe-vpcs `
    --region $REGION `
    --filters "Name=is-default,Values=true" `
    --query "Vpcs[0].VpcId" `
    --output text

$SUBNET_ID = & $AWS ec2 describe-subnets `
    --region $REGION `
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=availability-zone,Values=eu-central-1a" `
    --query "Subnets[0].SubnetId" `
    --output text

Write-Host "VPC: $VPC_ID, Subnet: $SUBNET_ID" -ForegroundColor Cyan

# Create Security Group
Write-Host "[3/6] Creating security group..." -ForegroundColor Yellow
$SG_NAME = "burst-test-$(Get-Date -Format 'HHmmss')"

try {
    $SG_ID = & $AWS ec2 create-security-group `
        --region $REGION `
        --group-name $SG_NAME `
        --description "OSMOSE Burst Test - Temporary" `
        --vpc-id $VPC_ID `
        --query "GroupId" `
        --output text

    # Allow ports 8000, 8001, 8080
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID `
        --protocol tcp --port 8000 --cidr 0.0.0.0/0 | Out-Null
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID `
        --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID `
        --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID `
        --protocol tcp --port 22 --cidr 0.0.0.0/0 | Out-Null

    Write-Host "Security Group: $SG_ID" -ForegroundColor Cyan
} catch {
    Write-Host "Error creating security group: $_" -ForegroundColor Red
    exit 1
}

# User Data script
$USER_DATA = @'
#!/bin/bash
set -ex
exec > /var/log/burst-init.log 2>&1

echo "=== OSMOSE Burst Init ==="
date

# Variables
VLLM_MODEL="Qwen/Qwen2.5-14B-Instruct-AWQ"
EMBEDDINGS_MODEL="intfloat/multilingual-e5-large"

# Start Docker (DLAMI has it pre-installed)
systemctl start docker
systemctl enable docker

# Pull images in parallel
echo "Pulling Docker images..."
docker pull vllm/vllm-openai:latest &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait
echo "Images pulled."

# Start vLLM with AWQ
echo "Starting vLLM..."
docker run -d --gpus all \
  -p 8000:8000 \
  --name vllm \
  --restart unless-stopped \
  vllm/vllm-openai:latest \
  --model $VLLM_MODEL \
  --quantization awq \
  --dtype half \
  --gpu-memory-utilization 0.85 \
  --max-model-len 8192 \
  --max-num-seqs 32 \
  --trust-remote-code

# Start Embeddings
echo "Starting TEI..."
docker run -d --gpus all \
  -p 8001:80 \
  --name embeddings \
  --restart unless-stopped \
  ghcr.io/huggingface/text-embeddings-inference:1.5 \
  --model-id $EMBEDDINGS_MODEL

# Health check endpoint
echo "Starting health server..."
cat > /opt/health.py << 'HEALTHEOF'
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import json

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            vllm_ok = False
            emb_ok = False
            try:
                with urllib.request.urlopen("http://localhost:8000/health", timeout=5) as r:
                    vllm_ok = r.status == 200
            except: pass
            try:
                with urllib.request.urlopen("http://localhost:8001/health", timeout=5) as r:
                    emb_ok = r.status == 200
            except: pass

            status = {"vllm": vllm_ok, "embeddings": emb_ok, "ready": vllm_ok and emb_ok}

            if status["ready"]:
                self.send_response(200)
            else:
                self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        pass  # Silence logs

print("Health server starting on :8080")
HTTPServer(("", 8080), HealthHandler).serve_forever()
HEALTHEOF

nohup python3 /opt/health.py > /var/log/health.log 2>&1 &

echo "=== Init complete ==="
date
'@

$USER_DATA_B64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($USER_DATA))

# Request Spot Instance
Write-Host "[4/6] Requesting Spot Instance ($INSTANCE_TYPE)..." -ForegroundColor Yellow
Write-Host "       This may take 1-5 minutes depending on capacity..." -ForegroundColor Gray

$SPOT_REQUEST = & $AWS ec2 request-spot-instances `
    --region $REGION `
    --spot-price $SPOT_PRICE `
    --instance-count 1 `
    --type "one-time" `
    --launch-specification "{
        \"ImageId\": \"$AMI_ID\",
        \"InstanceType\": \"$INSTANCE_TYPE\",
        \"SecurityGroupIds\": [\"$SG_ID\"],
        \"SubnetId\": \"$SUBNET_ID\",
        \"UserData\": \"$USER_DATA_B64\",
        \"BlockDeviceMappings\": [{
            \"DeviceName\": \"/dev/sda1\",
            \"Ebs\": {\"VolumeSize\": 100, \"VolumeType\": \"gp3\"}
        }]
    }" `
    --query "SpotInstanceRequests[0].SpotInstanceRequestId" `
    --output text

Write-Host "Spot Request: $SPOT_REQUEST" -ForegroundColor Cyan

# Wait for spot request to be fulfilled
Write-Host "Waiting for Spot fulfillment..." -ForegroundColor Gray
$maxWait = 30
$waited = 0
$INSTANCE_ID = $null

while ($waited -lt $maxWait -and -not $INSTANCE_ID) {
    Start-Sleep -Seconds 10
    $waited++

    $status = & $AWS ec2 describe-spot-instance-requests `
        --region $REGION `
        --spot-instance-request-ids $SPOT_REQUEST `
        --query "SpotInstanceRequests[0].[State,Status.Code,InstanceId]" `
        --output text

    $parts = $status -split "\s+"
    $state = $parts[0]
    $code = $parts[1]
    $INSTANCE_ID = if ($parts[2] -ne "None") { $parts[2] } else { $null }

    Write-Host "  Status: $state ($code)" -NoNewline
    if ($INSTANCE_ID) {
        Write-Host " -> Instance: $INSTANCE_ID" -ForegroundColor Green
    } else {
        Write-Host ""
    }

    if ($state -eq "failed" -or $state -eq "cancelled") {
        Write-Host "Spot request failed!" -ForegroundColor Red
        & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID 2>$null
        exit 1
    }
}

if (-not $INSTANCE_ID) {
    Write-Host "Timeout waiting for Spot instance" -ForegroundColor Red
    & $AWS ec2 cancel-spot-instance-requests --region $REGION --spot-instance-request-ids $SPOT_REQUEST
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID 2>$null
    exit 1
}

# Wait for instance running
Write-Host "[5/6] Waiting for instance to be running..." -ForegroundColor Yellow
& $AWS ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID

# Get public IP
$INSTANCE_IP = & $AWS ec2 describe-instances `
    --region $REGION `
    --instance-ids $INSTANCE_ID `
    --query "Reservations[0].Instances[0].PublicIpAddress" `
    --output text

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   Instance Running!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Instance ID:   $INSTANCE_ID" -ForegroundColor Cyan
Write-Host "Instance Type: $INSTANCE_TYPE" -ForegroundColor Cyan
Write-Host "Public IP:     $INSTANCE_IP" -ForegroundColor Cyan
Write-Host ""

# Wait for services
Write-Host "[6/6] Waiting for vLLM + Embeddings (8-15 min for 14B model)..." -ForegroundColor Yellow
Write-Host "       Model loading: Qwen/Qwen2.5-14B-Instruct-AWQ" -ForegroundColor Gray

$HEALTH_URL = "http://${INSTANCE_IP}:8080/health"
$VLLM_URL = "http://${INSTANCE_IP}:8000"

$maxAttempts = 60  # 15 minutes
$attempt = 0
$ready = $false

while (-not $ready -and $attempt -lt $maxAttempts) {
    $attempt++
    $elapsed = $attempt * 15
    $mins = [math]::Floor($elapsed / 60)
    $secs = $elapsed % 60
    Write-Host "  [$mins`:$($secs.ToString('00'))] Checking..." -NoNewline

    try {
        $response = Invoke-RestMethod -Uri $HEALTH_URL -TimeoutSec 10 -ErrorAction SilentlyContinue
        if ($response.ready -eq $true) {
            $ready = $true
            Write-Host " READY!" -ForegroundColor Green
        } else {
            $v = if ($response.vllm) { "OK" } else { "..." }
            $e = if ($response.embeddings) { "OK" } else { "..." }
            Write-Host " vLLM:$v Emb:$e"
        }
    } catch {
        Write-Host " connecting..."
    }

    if (-not $ready) {
        Start-Sleep -Seconds 15
    }
}

if ($ready) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "   ALL SERVICES READY!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "vLLM API:       $VLLM_URL/v1/chat/completions" -ForegroundColor Cyan
    Write-Host "Embeddings:     http://${INSTANCE_IP}:8001/embed" -ForegroundColor Cyan
    Write-Host "Health:         $HEALTH_URL" -ForegroundColor Cyan
    Write-Host ""

    # Test vLLM
    Write-Host "Testing vLLM API..." -ForegroundColor Yellow
    $testBody = @{
        model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
        messages = @(
            @{ role = "user"; content = "Dis 'Bonjour OSMOSE' en une phrase." }
        )
        max_tokens = 50
    } | ConvertTo-Json -Depth 3

    try {
        $response = Invoke-RestMethod -Uri "$VLLM_URL/v1/chat/completions" `
            -Method POST -ContentType "application/json" -Body $testBody -TimeoutSec 60

        Write-Host ""
        Write-Host "Response: $($response.choices[0].message.content)" -ForegroundColor Green
        Write-Host ""
        Write-Host "SUCCESS! Qwen 14B AWQ is working!" -ForegroundColor Green
    } catch {
        Write-Host "Test failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "Services did not become ready in 15 minutes." -ForegroundColor Red
    Write-Host "Check instance logs via SSH or console." -ForegroundColor Yellow
}

# Cleanup prompt
Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "   CLEANUP INFO" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Instance: $INSTANCE_ID" -ForegroundColor Cyan
Write-Host "Security Group: $SG_ID" -ForegroundColor Cyan
Write-Host "Spot Request: $SPOT_REQUEST" -ForegroundColor Cyan
Write-Host ""
Write-Host "Estimated cost: ~`$0.50-0.80/hour (Spot g6.2xlarge)" -ForegroundColor Yellow
Write-Host ""
Write-Host "To terminate and cleanup:"
Write-Host "  & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "  & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG_ID"
Write-Host ""

$cleanup = Read-Host "Terminate instance now? (y/N)"
if ($cleanup -eq "y" -or $cleanup -eq "Y") {
    Write-Host "Terminating instance..." -ForegroundColor Yellow
    & $AWS ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID | Out-Null
    Write-Host "Waiting for termination..." -ForegroundColor Gray
    & $AWS ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID
    Write-Host "Deleting security group..." -ForegroundColor Yellow
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID
    Write-Host "Cleanup complete!" -ForegroundColor Green
}
