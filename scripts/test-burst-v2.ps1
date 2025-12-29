# Test Burst Spot v2 - Fixed JSON handling
$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   OSMOSE Burst - Test Instance Spot v2" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Configuration
$AMI_ID = "ami-0f1273572a6a564a1"  # Deep Learning PyTorch 2.7 Ubuntu 22.04
$INSTANCE_TYPE = "g6.2xlarge"
$SPOT_PRICE = "1.20"

Write-Host "AMI: $AMI_ID"
Write-Host "Instance: $INSTANCE_TYPE"
Write-Host "Region: $REGION"
Write-Host ""

# Get network info
Write-Host "[1/6] Getting network info..." -ForegroundColor Yellow
$VPC_ID = & $AWS ec2 describe-vpcs --region $REGION --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text
$SUBNET_ID = & $AWS ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[0].SubnetId" --output text
Write-Host "VPC: $VPC_ID, Subnet: $SUBNET_ID"

# Create Security Group
Write-Host "[2/6] Creating security group..." -ForegroundColor Yellow
$SG_NAME = "burst-test-$(Get-Date -Format 'HHmmss')"
$SG_ID = & $AWS ec2 create-security-group --region $REGION --group-name $SG_NAME --description "OSMOSE Burst Test" --vpc-id $VPC_ID --query "GroupId" --output text

& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null
Write-Host "Security Group: $SG_ID"

# Create user data file
$userData = @'
#!/bin/bash
set -ex
exec > /var/log/burst-init.log 2>&1

echo "=== OSMOSE Burst Init ==="
date

VLLM_MODEL="Qwen/Qwen2.5-14B-Instruct-AWQ"
EMBEDDINGS_MODEL="intfloat/multilingual-e5-large"

systemctl start docker
systemctl enable docker

echo "Pulling images..."
docker pull vllm/vllm-openai:latest &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait

echo "Starting vLLM..."
docker run -d --gpus all -p 8000:8000 --name vllm --restart unless-stopped \
  vllm/vllm-openai:latest \
  --model $VLLM_MODEL --quantization awq --dtype half \
  --gpu-memory-utilization 0.85 --max-model-len 8192 --max-num-seqs 32 --trust-remote-code

echo "Starting TEI..."
docker run -d --gpus all -p 8001:80 --name embeddings --restart unless-stopped \
  ghcr.io/huggingface/text-embeddings-inference:1.5 --model-id $EMBEDDINGS_MODEL

cat > /opt/health.py << 'PYEOF'
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, json

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        v, e = False, False
        try:
            with urllib.request.urlopen("http://localhost:8000/health", timeout=5) as r: v = r.status == 200
        except: pass
        try:
            with urllib.request.urlopen("http://localhost:8001/health", timeout=5) as r: e = r.status == 200
        except: pass
        self.send_response(200 if v and e else 503)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"vllm": v, "embeddings": e, "ready": v and e}).encode())
    def log_message(self, *a): pass

HTTPServer(("", 8080), H).serve_forever()
PYEOF

nohup python3 /opt/health.py > /var/log/health.log 2>&1 &
echo "=== Init done ===" && date
'@

$userDataB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))

# Create launch spec JSON file
$launchSpec = @{
    ImageId = $AMI_ID
    InstanceType = $INSTANCE_TYPE
    SecurityGroupIds = @($SG_ID)
    SubnetId = $SUBNET_ID
    UserData = $userDataB64
    BlockDeviceMappings = @(
        @{
            DeviceName = "/dev/sda1"
            Ebs = @{
                VolumeSize = 100
                VolumeType = "gp3"
            }
        }
    )
} | ConvertTo-Json -Depth 5 -Compress

$launchSpecFile = "$env:TEMP\burst-launch-spec.json"
$launchSpec | Out-File -FilePath $launchSpecFile -Encoding utf8

# Request Spot
Write-Host "[3/6] Requesting Spot Instance..." -ForegroundColor Yellow
$SPOT_REQUEST = & $AWS ec2 request-spot-instances `
    --region $REGION `
    --spot-price $SPOT_PRICE `
    --instance-count 1 `
    --type one-time `
    --launch-specification "file://$launchSpecFile" `
    --query "SpotInstanceRequests[0].SpotInstanceRequestId" `
    --output text

Write-Host "Spot Request: $SPOT_REQUEST" -ForegroundColor Cyan

# Wait for fulfillment
Write-Host "[4/6] Waiting for Spot fulfillment..." -ForegroundColor Yellow
$maxWait = 30
$INSTANCE_ID = $null

for ($i = 1; $i -le $maxWait; $i++) {
    Start-Sleep -Seconds 10
    $result = & $AWS ec2 describe-spot-instance-requests --region $REGION --spot-instance-request-ids $SPOT_REQUEST --query "SpotInstanceRequests[0].[State,Status.Code,InstanceId]" --output text
    $parts = $result -split "`t"
    $state = $parts[0]
    $code = $parts[1]
    $instId = $parts[2]

    Write-Host "  [$i/$maxWait] State: $state, Code: $code" -NoNewline

    if ($instId -and $instId -ne "None") {
        $INSTANCE_ID = $instId
        Write-Host " -> Instance: $INSTANCE_ID" -ForegroundColor Green
        break
    }
    Write-Host ""

    if ($state -eq "failed" -or $state -eq "cancelled") {
        Write-Host "Spot request failed: $code" -ForegroundColor Red
        & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID 2>$null
        exit 1
    }
}

if (-not $INSTANCE_ID) {
    Write-Host "Timeout!" -ForegroundColor Red
    exit 1
}

# Wait running
& $AWS ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID
$INSTANCE_IP = & $AWS ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID --query "Reservations[0].Instances[0].PublicIpAddress" --output text

Write-Host ""
Write-Host "Instance: $INSTANCE_ID @ $INSTANCE_IP" -ForegroundColor Green
Write-Host ""

# Wait for services
Write-Host "[5/6] Waiting for vLLM + TEI (8-15 min)..." -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    $mins = [math]::Floor($i * 15 / 60)
    $secs = ($i * 15) % 60
    Write-Host "  [$mins`:$($secs.ToString('00'))] Checking..." -NoNewline

    try {
        $resp = Invoke-RestMethod -Uri "http://${INSTANCE_IP}:8080/health" -TimeoutSec 10 -ErrorAction SilentlyContinue
        if ($resp.ready) {
            Write-Host " READY!" -ForegroundColor Green
            $ready = $true
            break
        }
        $v = if ($resp.vllm) { "OK" } else { ".." }
        $e = if ($resp.embeddings) { "OK" } else { ".." }
        Write-Host " vLLM:$v Emb:$e"
    } catch {
        Write-Host " connecting..."
    }
    Start-Sleep -Seconds 15
}

if ($ready) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "   SERVICES READY!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "vLLM: http://${INSTANCE_IP}:8000/v1/chat/completions"
    Write-Host "Emb:  http://${INSTANCE_IP}:8001/embed"
    Write-Host ""

    # Test
    Write-Host "[6/6] Testing vLLM..." -ForegroundColor Yellow
    $body = '{"model":"Qwen/Qwen2.5-14B-Instruct-AWQ","messages":[{"role":"user","content":"Dis Bonjour OSMOSE"}],"max_tokens":30}'
    try {
        $r = Invoke-RestMethod -Uri "http://${INSTANCE_IP}:8000/v1/chat/completions" -Method POST -ContentType "application/json" -Body $body -TimeoutSec 60
        Write-Host "Response: $($r.choices[0].message.content)" -ForegroundColor Green
    } catch {
        Write-Host "Test failed: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== CLEANUP ===" -ForegroundColor Yellow
Write-Host "Instance: $INSTANCE_ID"
Write-Host "SG: $SG_ID"
Write-Host ""
Write-Host "To terminate:"
Write-Host "  & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "  & '$AWS' ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "  & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG_ID"
Write-Host ""

$c = Read-Host "Terminate now? (y/N)"
if ($c -eq "y") {
    & $AWS ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID | Out-Null
    Write-Host "Terminating..."
    & $AWS ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID
    Write-Host "Done!" -ForegroundColor Green
}
