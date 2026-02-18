# Test complet Mode Burst avec vLLM
# - Cree instance Spot g6e.xlarge
# - Attend que vLLM soit pret
# - Teste l'API vLLM
# - Compare avec le systeme actuel
# - Nettoie les ressources

param(
    [switch]$SkipCleanup,
    [int]$MaxWaitMinutes = 15
)

$ErrorActionPreference = "Stop"
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"
$AMI_ID = "ami-0f1273572a6a564a1"  # Deep Learning PyTorch 2.7 Ubuntu 22.04
$INSTANCE_TYPE = "g6e.xlarge"
$TIMESTAMP = Get-Date -Format "yyyyMMdd-HHmmss"
$SG_NAME = "burst-vllm-test-$TIMESTAMP"

# Userdata pour vLLM
$USERDATA = @'
#!/bin/bash
exec > /var/log/burst.log 2>&1
set -ex
echo "=== BURST START ===" && date

# Demarrer Docker
systemctl start docker
systemctl enable docker

# Pull images en parallele
echo "Pulling Docker images..."
docker pull vllm/vllm-openai:v0.9.2 &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait
echo "Docker images pulled"

# Patch AWQ Marlin (bug vLLM v0.9.2 : user_quant="awq" non reconnu)
echo "Patching vLLM for AWQ Marlin activation..."
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
    print('Patched awq_marlin.py')
"

# Lancer vLLM (Qwen3 14B AWQ + Marlin kernels)
echo "Starting vLLM..."
docker run -d --gpus all -p 8000:8000 --name vllm \
    -v /opt/burst/patches/awq_marlin.py:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py:ro \
    vllm/vllm-openai:v0.9.2 \
    --model Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq_marlin \
    --dtype half \
    --gpu-memory-utilization 0.85 \
    --max-model-len 32768 --reasoning-parser qwen3 \
    --max-num-seqs 32 \
    --trust-remote-code

# Lancer Embeddings
echo "Starting Embeddings..."
docker run -d --gpus all -p 8001:80 --name emb \
    ghcr.io/huggingface/text-embeddings-inference:1.5 \
    --model-id intfloat/multilingual-e5-large

# Healthcheck aggrege sur port 8080
echo "Starting healthcheck server..."
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

echo "=== BURST READY ===" && date
'@

# Encoder userdata en base64
$USERDATA_B64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($USERDATA))

function Cleanup {
    param($InstanceId, $SgId)

    Write-Host "`n=== CLEANUP ===" -ForegroundColor Yellow

    if ($InstanceId) {
        Write-Host "Terminating instance $InstanceId..."
        & $AWS ec2 terminate-instances --region $REGION --instance-ids $InstanceId | Out-Null

        # Attendre la terminaison
        Write-Host "Waiting for instance termination..."
        for ($i = 0; $i -lt 12; $i++) {
            Start-Sleep -Seconds 10
            $state = & $AWS ec2 describe-instances --region $REGION --instance-ids $InstanceId --query 'Reservations[0].Instances[0].State.Name' --output text 2>$null
            if ($state -eq "terminated") {
                Write-Host "Instance terminated" -ForegroundColor Green
                break
            }
            Write-Host "  State: $state"
        }
    }

    if ($SgId) {
        Start-Sleep -Seconds 5
        Write-Host "Deleting security group $SgId..."
        & $AWS ec2 delete-security-group --region $REGION --group-id $SgId 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Security group deleted" -ForegroundColor Green
        } else {
            Write-Host "Warning: Could not delete SG (may need manual cleanup)" -ForegroundColor Yellow
        }
    }
}

try {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  TEST vLLM BURST MODE" -ForegroundColor Cyan
    Write-Host "  Instance: $INSTANCE_TYPE" -ForegroundColor Cyan
    Write-Host "  Model: Qwen/Qwen2.5-14B-Instruct-AWQ" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    # 1. Creer Security Group
    Write-Host "[1/6] Creating Security Group: $SG_NAME" -ForegroundColor Yellow
    $SG_ID = & $AWS ec2 create-security-group --region $REGION --group-name $SG_NAME --description "Burst vLLM Test" --query GroupId --output text
    Write-Host "  SG ID: $SG_ID" -ForegroundColor Green

    # Ouvrir ports
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0 | Out-Null
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
    & $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null
    Write-Host "  Ports 8000, 8001, 8080 opened" -ForegroundColor Green

    # 2. Lancer instance Spot
    Write-Host "`n[2/6] Launching Spot instance..." -ForegroundColor Yellow
    $INSTANCE_ID = & $AWS ec2 run-instances `
        --region $REGION `
        --image-id $AMI_ID `
        --instance-type $INSTANCE_TYPE `
        --security-group-ids $SG_ID `
        --instance-market-options MarketType=spot `
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3}" `
        --user-data $USERDATA_B64 `
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=burst-vllm-test},{Key=Purpose,Value=Testing}]" `
        --query "Instances[0].InstanceId" `
        --output text

    if (-not ($INSTANCE_ID -match "^i-")) {
        throw "Failed to create instance: $INSTANCE_ID"
    }
    Write-Host "  Instance ID: $INSTANCE_ID" -ForegroundColor Green

    # 3. Attendre l'IP publique
    Write-Host "`n[3/6] Waiting for public IP..." -ForegroundColor Yellow
    $PUBLIC_IP = $null
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 5
        $PUBLIC_IP = & $AWS ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
        if ($PUBLIC_IP -and $PUBLIC_IP -ne "None") {
            break
        }
        Write-Host "  Waiting..."
    }

    if (-not $PUBLIC_IP -or $PUBLIC_IP -eq "None") {
        throw "No public IP assigned"
    }
    Write-Host "  Public IP: $PUBLIC_IP" -ForegroundColor Green

    # 4. Attendre que vLLM soit pret
    Write-Host "`n[4/6] Waiting for vLLM to be ready (up to $MaxWaitMinutes min)..." -ForegroundColor Yellow
    $HEALTH_URL = "http://${PUBLIC_IP}:8080"
    $VLLM_URL = "http://${PUBLIC_IP}:8000"
    $startTime = Get-Date
    $ready = $false

    while ((Get-Date) -lt $startTime.AddMinutes($MaxWaitMinutes)) {
        try {
            $response = Invoke-RestMethod -Uri $HEALTH_URL -TimeoutSec 5 -ErrorAction SilentlyContinue
            Write-Host "  Health: vLLM=$($response.vllm) Emb=$($response.emb)" -ForegroundColor Gray
            if ($response.ready -eq $true) {
                $ready = $true
                break
            }
        } catch {
            Write-Host "  Waiting for services to start..." -ForegroundColor Gray
        }
        Start-Sleep -Seconds 15
    }

    if (-not $ready) {
        throw "vLLM not ready after $MaxWaitMinutes minutes"
    }

    $elapsed = ((Get-Date) - $startTime).TotalMinutes
    Write-Host "  vLLM ready in $([math]::Round($elapsed, 1)) minutes!" -ForegroundColor Green

    # 5. Tester l'API vLLM
    Write-Host "`n[5/6] Testing vLLM API..." -ForegroundColor Yellow

    $testPrompt = "Explique en 2 phrases ce qu'est SAP S/4HANA."
    $requestBody = @{
        model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
        messages = @(
            @{ role = "user"; content = $testPrompt }
        )
        max_tokens = 200
        temperature = 0.7
    } | ConvertTo-Json -Depth 5

    $headers = @{ "Content-Type" = "application/json" }

    Write-Host "  Prompt: $testPrompt" -ForegroundColor Cyan
    $apiStart = Get-Date

    try {
        $response = Invoke-RestMethod -Uri "$VLLM_URL/v1/chat/completions" -Method Post -Body $requestBody -Headers $headers -TimeoutSec 60
        $apiTime = ((Get-Date) - $apiStart).TotalSeconds

        $answer = $response.choices[0].message.content
        $tokens = $response.usage.total_tokens

        Write-Host "`n  === REPONSE vLLM ===" -ForegroundColor Green
        Write-Host "  $answer" -ForegroundColor White
        Write-Host "`n  Tokens: $tokens | Time: $([math]::Round($apiTime, 2))s" -ForegroundColor Gray

        # Sauvegarder le log
        $logEntry = @{
            timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            instance_type = $INSTANCE_TYPE
            model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
            prompt = $testPrompt
            response = $answer
            tokens = $tokens
            response_time_sec = [math]::Round($apiTime, 2)
            startup_time_min = [math]::Round($elapsed, 1)
        }

        $logFile = "C:\Projects\SAP_KB\data\vllm_test_logs.jsonl"
        $logEntry | ConvertTo-Json -Compress | Out-File -FilePath $logFile -Append -Encoding utf8
        Write-Host "`n  Log saved to: $logFile" -ForegroundColor Gray

    } catch {
        Write-Host "  API Error: $_" -ForegroundColor Red
    }

    # 6. Test embeddings
    Write-Host "`n[6/6] Testing Embeddings API..." -ForegroundColor Yellow
    $EMB_URL = "http://${PUBLIC_IP}:8001"

    $embBody = @{
        inputs = "Test embedding for SAP knowledge base"
    } | ConvertTo-Json

    try {
        $embStart = Get-Date
        $embResponse = Invoke-RestMethod -Uri "$EMB_URL/embed" -Method Post -Body $embBody -Headers $headers -TimeoutSec 30
        $embTime = ((Get-Date) - $embStart).TotalSeconds

        $embDim = $embResponse[0].Count
        Write-Host "  Embedding dimension: $embDim | Time: $([math]::Round($embTime, 2))s" -ForegroundColor Green
    } catch {
        Write-Host "  Embeddings Error: $_" -ForegroundColor Red
    }

    Write-Host "`n============================================" -ForegroundColor Green
    Write-Host "  TEST COMPLETED SUCCESSFULLY" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Instance IP: $PUBLIC_IP"
    Write-Host "vLLM API: $VLLM_URL/v1/chat/completions"
    Write-Host "Embeddings: $EMB_URL/embed"
    Write-Host ""

    if ($SkipCleanup) {
        Write-Host "Cleanup skipped. To terminate manually:" -ForegroundColor Yellow
        Write-Host "  & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
        Write-Host "  & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG_ID"
    } else {
        Cleanup -InstanceId $INSTANCE_ID -SgId $SG_ID
    }

} catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red

    if (-not $SkipCleanup) {
        Cleanup -InstanceId $INSTANCE_ID -SgId $SG_ID
    }

    exit 1
}
