# Test Burst v4 - Using run-instances with spot market
$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== OSMOSE Burst Test v4 ===" -ForegroundColor Cyan

$AMI_ID = "ami-0f1273572a6a564a1"
$INSTANCE_TYPE = "g6.2xlarge"

# Network
$VPC_ID = & $AWS ec2 describe-vpcs --region $REGION --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text
$SUBNET_ID = & $AWS ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[0].SubnetId" --output text
Write-Host "VPC: $VPC_ID, Subnet: $SUBNET_ID"

# Security Group
$SG_NAME = "burst-$(Get-Date -Format 'HHmmss')"
$SG_ID = & $AWS ec2 create-security-group --region $REGION --group-name $SG_NAME --description "Burst Test" --vpc-id $VPC_ID --query "GroupId" --output text
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null
Write-Host "SG: $SG_ID"

# User data file
$userDataScript = @'
#!/bin/bash
exec > /var/log/burst.log 2>&1
set -ex
echo "=== BURST ===" && date
systemctl start docker && systemctl enable docker
docker pull vllm/vllm-openai:v0.9.2 &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait
docker run -d --gpus all -p 8000:8000 --name vllm vllm/vllm-openai:v0.9.2 --model Qwen/Qwen3-14B-AWQ --quantization awq --dtype half --gpu-memory-utilization 0.85 --max-model-len 32768 --reasoning-parser qwen3 --max-num-seqs 32 --trust-remote-code
docker run -d --gpus all -p 8001:80 --name emb ghcr.io/huggingface/text-embeddings-inference:1.5 --model-id intfloat/multilingual-e5-large
python3 -c "
from http.server import HTTPServer,BaseHTTPRequestHandler
import urllib.request,json
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  v=e=False
  try:
   with urllib.request.urlopen('http://localhost:8000/health',timeout=5) as r:v=r.status==200
  except:pass
  try:
   with urllib.request.urlopen('http://localhost:8001/health',timeout=5) as r:e=r.status==200
  except:pass
  self.send_response(200 if v and e else 503);self.send_header('Content-Type','application/json');self.end_headers()
  self.wfile.write(json.dumps({'vllm':v,'emb':e,'ready':v and e}).encode())
 def log_message(self,*a):pass
HTTPServer(('',8080),H).serve_forever()
" &
echo "=== DONE ===" && date
'@
$userDataFile = "$SCRIPT_DIR\burst-userdata.sh"
[System.IO.File]::WriteAllText($userDataFile, $userDataScript)

# Spot market options file
$spotOptionsFile = "$SCRIPT_DIR\burst-spec.json"

Write-Host "Launching Spot instance..." -ForegroundColor Yellow

try {
    $result = & $AWS ec2 run-instances `
        --region $REGION `
        --image-id $AMI_ID `
        --instance-type $INSTANCE_TYPE `
        --subnet-id $SUBNET_ID `
        --security-group-ids $SG_ID `
        --instance-market-options "file://$spotOptionsFile" `
        --user-data "file://$userDataFile" `
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3}" `
        --query "Instances[0].InstanceId" `
        --output text 2>&1

    if ($result -match "^i-") {
        $INSTANCE_ID = $result
        Write-Host "Instance: $INSTANCE_ID" -ForegroundColor Green
    } else {
        Write-Host "Error: $result" -ForegroundColor Red
        & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID | Out-Null
        exit 1
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID | Out-Null
    exit 1
}

# Wait running
Write-Host "Waiting instance running..." -ForegroundColor Yellow
& $AWS ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID

$IP = & $AWS ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID --query "Reservations[0].Instances[0].PublicIpAddress" --output text
$TYPE = & $AWS ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID --query "Reservations[0].Instances[0].InstanceType" --output text

Write-Host ""
Write-Host "RUNNING: $INSTANCE_ID ($TYPE) @ $IP" -ForegroundColor Green
Write-Host ""

# Wait for services
Write-Host "Waiting for vLLM + TEI (8-15 min for 14B model)..." -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    $mins = [math]::Floor($i * 15 / 60)
    $secs = ($i * 15) % 60
    Write-Host "  [$mins`:$($secs.ToString('00'))]" -NoNewline

    try {
        $health = Invoke-RestMethod -Uri "http://${IP}:8080/health" -TimeoutSec 10 -ErrorAction SilentlyContinue
        if ($health.ready -eq $true) {
            Write-Host " READY!" -ForegroundColor Green
            $ready = $true
            break
        }
        $vStat = if ($health.vllm) { "OK" } else { ".." }
        $eStat = if ($health.emb) { "OK" } else { ".." }
        Write-Host " vLLM:$vStat Emb:$eStat"
    } catch {
        Write-Host " connecting..."
    }

    Start-Sleep -Seconds 15
}

if ($ready) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  SERVICES READY!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "vLLM API:   http://${IP}:8000/v1/chat/completions" -ForegroundColor Cyan
    Write-Host "Embeddings: http://${IP}:8001/embed" -ForegroundColor Cyan
    Write-Host "Health:     http://${IP}:8080/health" -ForegroundColor Cyan
    Write-Host ""

    # Test API
    Write-Host "Testing vLLM API..." -ForegroundColor Yellow
    $testBody = '{"model":"Qwen/Qwen3-14B-AWQ","messages":[{"role":"user","content":"Say: Hello OSMOSE!"}],"max_tokens":20}'

    try {
        $response = Invoke-RestMethod -Uri "http://${IP}:8000/v1/chat/completions" -Method POST -ContentType "application/json" -Body $testBody -TimeoutSec 60
        Write-Host ""
        Write-Host "Response: $($response.choices[0].message.content)" -ForegroundColor Green
        Write-Host ""
        Write-Host "SUCCESS! Qwen 14B AWQ is working!" -ForegroundColor Green
    } catch {
        Write-Host "API test failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "Services did not start in 15 minutes." -ForegroundColor Red
    Write-Host "Check logs: ssh ubuntu@$IP 'cat /var/log/burst.log'" -ForegroundColor Yellow
}

# Cleanup
Write-Host ""
Write-Host "=== CLEANUP ===" -ForegroundColor Yellow
Write-Host "Instance: $INSTANCE_ID" -ForegroundColor Cyan
Write-Host "Security Group: $SG_ID" -ForegroundColor Cyan
Write-Host ""
Write-Host "Estimated cost: ~`$0.50-0.80/hour (Spot g6.2xlarge)"
Write-Host ""
Write-Host "To terminate manually:"
Write-Host "  & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "  & '$AWS' ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "  & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG_ID"
Write-Host ""

$cleanup = Read-Host "Terminate instance now? (y/N)"
if ($cleanup -eq "y" -or $cleanup -eq "Y") {
    Write-Host "Terminating..." -ForegroundColor Yellow
    & $AWS ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID | Out-Null
    Write-Host "Waiting for termination..." -ForegroundColor Gray
    & $AWS ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID
    Write-Host "Deleting security group..." -ForegroundColor Gray
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID
    Write-Host "Cleanup complete!" -ForegroundColor Green
}
