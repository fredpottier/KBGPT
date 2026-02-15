# Test Burst Spot v3 - Fixed encoding
$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   OSMOSE Burst - Test Spot v3" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$AMI_ID = "ami-0f1273572a6a564a1"
$INSTANCE_TYPE = "g6.2xlarge"
$SPOT_PRICE = "1.20"

Write-Host "AMI: $AMI_ID | Instance: $INSTANCE_TYPE | Region: $REGION"
Write-Host ""

# Network
Write-Host "[1/6] Network info..." -ForegroundColor Yellow
$VPC_ID = & $AWS ec2 describe-vpcs --region $REGION --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text
$SUBNET_ID = & $AWS ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[0].SubnetId" --output text
Write-Host "VPC: $VPC_ID, Subnet: $SUBNET_ID"

# Security Group
Write-Host "[2/6] Security group..." -ForegroundColor Yellow
$SG_NAME = "burst-$(Get-Date -Format 'HHmmss')"
$SG_ID = & $AWS ec2 create-security-group --region $REGION --group-name $SG_NAME --description "Burst" --vpc-id $VPC_ID --query "GroupId" --output text
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null
Write-Host "SG: $SG_ID"

# User data
$userData = @'
#!/bin/bash
exec > /var/log/burst.log 2>&1
set -ex
echo "=== BURST INIT ===" && date
systemctl start docker && systemctl enable docker
docker pull vllm/vllm-openai:v0.9.2 &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait
# Patch AWQ Marlin (bug vLLM v0.9.2)
mkdir -p /opt/burst/patches
docker create --name vllm-temp vllm/vllm-openai:v0.9.2
docker cp vllm-temp:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py /opt/burst/patches/awq_marlin.py
docker rm vllm-temp
python3 -c "
p='/opt/burst/patches/awq_marlin.py'
c=open(p).read()
old='or user_quant == \"awq_marlin\")'
new='or user_quant == \"awq_marlin\"\n                            or user_quant == \"awq\")'
if old in c and 'or user_quant == \"awq\")' not in c:
    open(p,'w').write(c.replace(old,new))
"
docker run -d --gpus all -p 8000:8000 --name vllm \
  -v /opt/burst/patches/awq_marlin.py:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py:ro \
  vllm/vllm-openai:v0.9.2 --model Qwen/Qwen3-14B-AWQ --quantization awq_marlin --dtype half --gpu-memory-utilization 0.85 --max-model-len 32768 --reasoning-parser qwen3 --max-num-seqs 32 --trust-remote-code
docker run -d --gpus all -p 8001:80 --name emb ghcr.io/huggingface/text-embeddings-inference:1.5 --model-id intfloat/multilingual-e5-large
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, json
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        v=e=False
        try:
            with urllib.request.urlopen('http://localhost:8000/health',timeout=5) as r: v=r.status==200
        except: pass
        try:
            with urllib.request.urlopen('http://localhost:8001/health',timeout=5) as r: e=r.status==200
        except: pass
        self.send_response(200 if v and e else 503)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'vllm':v,'emb':e,'ready':v and e}).encode())
    def log_message(self,*a): pass
HTTPServer(('',8080),H).serve_forever()
" &
echo "=== DONE ===" && date
'@
$userDataB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))

# Launch spec JSON - write without BOM
$launchSpec = @"
{"ImageId":"$AMI_ID","InstanceType":"$INSTANCE_TYPE","SecurityGroupIds":["$SG_ID"],"SubnetId":"$SUBNET_ID","UserData":"$userDataB64","BlockDeviceMappings":[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]}
"@
$specFile = "$env:TEMP\burst-spec.json"
[System.IO.File]::WriteAllText($specFile, $launchSpec)

# Request Spot
Write-Host "[3/6] Requesting Spot..." -ForegroundColor Yellow
$SPOT_REQ = & $AWS ec2 request-spot-instances --region $REGION --spot-price $SPOT_PRICE --instance-count 1 --type one-time --launch-specification "file://$specFile" --query "SpotInstanceRequests[0].SpotInstanceRequestId" --output text 2>&1

if ($SPOT_REQ -match "^sir-") {
    Write-Host "Spot Request: $SPOT_REQ" -ForegroundColor Cyan
} else {
    Write-Host "Error: $SPOT_REQ" -ForegroundColor Red
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID | Out-Null
    exit 1
}

# Wait fulfillment
Write-Host "[4/6] Waiting fulfillment..." -ForegroundColor Yellow
$INSTANCE_ID = $null
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 10
    $r = & $AWS ec2 describe-spot-instance-requests --region $REGION --spot-instance-request-ids $SPOT_REQ --query "SpotInstanceRequests[0].[State,Status.Code,InstanceId]" --output text
    $p = $r -split "`t"
    Write-Host "  [$i] $($p[0]) ($($p[1]))" -NoNewline
    if ($p[2] -and $p[2] -ne "None") {
        $INSTANCE_ID = $p[2]
        Write-Host " -> $INSTANCE_ID" -ForegroundColor Green
        break
    }
    Write-Host ""
    if ($p[0] -eq "failed") {
        Write-Host "Failed!" -ForegroundColor Red
        & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID | Out-Null
        exit 1
    }
}

if (-not $INSTANCE_ID) { Write-Host "Timeout!" -ForegroundColor Red; exit 1 }

& $AWS ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID
$IP = & $AWS ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID --query "Reservations[0].Instances[0].PublicIpAddress" --output text

Write-Host ""
Write-Host "INSTANCE: $INSTANCE_ID @ $IP" -ForegroundColor Green
Write-Host ""

# Wait services
Write-Host "[5/6] Waiting services (8-15min)..." -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    $m = [math]::Floor($i*15/60); $s = ($i*15)%60
    Write-Host "  [$m`:$($s.ToString('00'))]" -NoNewline
    try {
        $h = Invoke-RestMethod -Uri "http://${IP}:8080/health" -TimeoutSec 10 -ErrorAction SilentlyContinue
        if ($h.ready) { Write-Host " READY!" -ForegroundColor Green; $ready=$true; break }
        Write-Host " vLLM:$(if($h.vllm){'OK'}else{'..'}) Emb:$(if($h.emb){'OK'}else{'..'})"
    } catch { Write-Host " ..." }
    Start-Sleep -Seconds 15
}

if ($ready) {
    Write-Host ""
    Write-Host "=== SERVICES UP ===" -ForegroundColor Green
    Write-Host "vLLM: http://${IP}:8000/v1/chat/completions"
    Write-Host "Emb:  http://${IP}:8001/embed"
    Write-Host ""

    Write-Host "[6/6] Testing..." -ForegroundColor Yellow
    try {
        $b = '{"model":"Qwen/Qwen3-14B-AWQ","messages":[{"role":"user","content":"Say hello OSMOSE"}],"max_tokens":20}'
        $r = Invoke-RestMethod -Uri "http://${IP}:8000/v1/chat/completions" -Method POST -ContentType "application/json" -Body $b -TimeoutSec 60
        Write-Host "Response: $($r.choices[0].message.content)" -ForegroundColor Green
    } catch { Write-Host "Test error: $_" -ForegroundColor Red }
}

Write-Host ""
Write-Host "=== CLEANUP ===" -ForegroundColor Yellow
Write-Host "Terminate: & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
Write-Host "Delete SG: & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG_ID"
Write-Host ""
$c = Read-Host "Terminate now? (y/N)"
if ($c -eq "y") {
    & $AWS ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID | Out-Null
    & $AWS ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG_ID
    Write-Host "Cleaned!" -ForegroundColor Green
}
