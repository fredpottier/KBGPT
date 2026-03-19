# Stream Deck - Burst Mode Start (Autonome)
# Demarre l'infrastructure EC2 Spot via CloudFormation directement (sans API OSMOSE)

$ErrorActionPreference = "Stop"
Set-Location "C:\Projects\SAP_KB"

# === Configuration (memes valeurs que BurstConfig dans le code) ===
$REGION = "eu-central-1"
$STACK_PREFIX = "knowwhere-burst"
$TEMPLATE_PATH = "src\knowbase\ingestion\burst\cloudformation\burst-spot.yaml"
$VLLM_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"
$EMBEDDINGS_MODEL = "intfloat/multilingual-e5-large"
$SPOT_MAX_PRICE = "1.50"
$VLLM_PORT = "8000"
$EMBEDDINGS_PORT = "8001"
$GPU_MEMORY_UTIL = "0.85"
$QUANTIZATION = "awq_marlin"
$DTYPE = "half"
$MAX_MODEL_LEN = "16384"
$MAX_NUM_SEQS = "64"
$ENABLE_PREFIX_CACHING = "true"
$ENABLE_CHUNKED_PREFILL = "true"
$MAX_BATCHED_TOKENS = "8192"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  OSMOSE BURST MODE - DEMARRAGE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# [1/5] Verifier credentials AWS
Write-Host "[1/5] Verification credentials AWS..." -ForegroundColor Yellow
try {
    $identity = aws sts get-caller-identity --region $REGION --output json 2>$null | ConvertFrom-Json
    Write-Host "  Account: $($identity.Account)" -ForegroundColor Green
} catch {
    Write-Host "  ERREUR: Credentials AWS non configures!" -ForegroundColor Red
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# [2/5] Verifier qu'il n'y a pas deja une stack active
Write-Host ""
Write-Host "[2/5] Verification stacks existantes..." -ForegroundColor Yellow
$existingStacks = aws cloudformation list-stacks `
    --region $REGION `
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE CREATE_IN_PROGRESS `
    --query "StackSummaries[?contains(StackName,'burst')].[StackName,StackStatus]" `
    --output text 2>$null

if ($existingStacks -and $existingStacks.Trim()) {
    Write-Host "  Stack Burst deja active:" -ForegroundColor Red
    Write-Host "  $existingStacks" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Supprimez d'abord avec burst-stop.ps1" -ForegroundColor Yellow
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}
Write-Host "  Aucune stack active" -ForegroundColor Green

# [3/5] Verifier que le template existe
Write-Host ""
Write-Host "[3/5] Verification template CloudFormation..." -ForegroundColor Yellow
if (-not (Test-Path $TEMPLATE_PATH)) {
    Write-Host "  ERREUR: Template non trouve: $TEMPLATE_PATH" -ForegroundColor Red
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}
Write-Host "  Template: $TEMPLATE_PATH" -ForegroundColor Green

# [4/5] Creer la stack CloudFormation
$batchId = "sd-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$stackName = "$STACK_PREFIX-$batchId"

Write-Host ""
Write-Host "[4/5] Creation stack CloudFormation..." -ForegroundColor Yellow
Write-Host "  Stack: $stackName" -ForegroundColor Cyan
Write-Host "  Modele: $VLLM_MODEL" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Cela peut prendre 5-10 minutes..." -ForegroundColor Gray

try {
    # Charger le template et nettoyer les caractères non-ASCII (accents dans commentaires)
    $templateAbsPath = (Resolve-Path $TEMPLATE_PATH).Path
    $tempTemplate = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "burst-spot-clean.yaml")
    $content = [System.IO.File]::ReadAllText($templateAbsPath, [System.Text.Encoding]::UTF8)
    $content = $content -replace '[^\x00-\x7F]', '?'
    [System.IO.File]::WriteAllText($tempTemplate, $content, (New-Object System.Text.UTF8Encoding $false))

    # Construire la commande comme un seul string (evite les problemes de backtick PowerShell)
    $params = @(
        "ParameterKey=BatchId,ParameterValue=$batchId"
        "ParameterKey=VllmModel,ParameterValue=$VLLM_MODEL"
        "ParameterKey=EmbeddingsModel,ParameterValue=$EMBEDDINGS_MODEL"
        "ParameterKey=SpotMaxPrice,ParameterValue=$SPOT_MAX_PRICE"
        "ParameterKey=VllmPort,ParameterValue=$VLLM_PORT"
        "ParameterKey=EmbeddingsPort,ParameterValue=$EMBEDDINGS_PORT"
        "ParameterKey=VllmGpuMemoryUtilization,ParameterValue=$GPU_MEMORY_UTIL"
        "ParameterKey=VllmQuantization,ParameterValue=$QUANTIZATION"
        "ParameterKey=VllmDtype,ParameterValue=$DTYPE"
        "ParameterKey=VllmMaxModelLen,ParameterValue=$MAX_MODEL_LEN"
        "ParameterKey=VllmMaxNumSeqs,ParameterValue=$MAX_NUM_SEQS"
        "ParameterKey=VllmEnablePrefixCaching,ParameterValue=$ENABLE_PREFIX_CACHING"
        "ParameterKey=VllmEnableChunkedPrefill,ParameterValue=$ENABLE_CHUNKED_PREFILL"
        "ParameterKey=VllmMaxNumBatchedTokens,ParameterValue=$MAX_BATCHED_TOKENS"
    )

    $createOutput = & aws cloudformation create-stack --region $REGION --stack-name $stackName --template-body "file://$tempTemplate" --capabilities CAPABILITY_NAMED_IAM --parameters $params --tags "Key=Project,Value=KnowWhere" "Key=Component,Value=Burst" "Key=BatchId,Value=$batchId" --output text 2>&1

    Remove-Item $tempTemplate -ErrorAction SilentlyContinue

    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI error (exit $LASTEXITCODE): $createOutput"
    }

    Write-Host "  Stack soumise, en attente de creation..." -ForegroundColor Yellow
    Write-Host "  Stack ID: $createOutput" -ForegroundColor Gray
} catch {
    Write-Host "  ERREUR creation stack: $($_.Exception.Message)" -ForegroundColor Red
    if ($createOutput) { Write-Host "  Details: $createOutput" -ForegroundColor Red }
    Remove-Item $tempTemplate -ErrorAction SilentlyContinue
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# [5/5] Attendre que la stack soit creee et recuperer l'IP
Write-Host ""
Write-Host "[5/5] Attente creation stack (polling toutes les 15s)..." -ForegroundColor Yellow

$maxAttempts = 60  # 15 minutes max
$attempt = 0
$instanceIp = $null

while ($attempt -lt $maxAttempts) {
    $attempt++
    Start-Sleep -Seconds 15

    $stackStatus = aws cloudformation describe-stacks `
        --region $REGION `
        --stack-name $stackName `
        --query "Stacks[0].StackStatus" `
        --output text 2>$null

    if ($stackStatus -eq "CREATE_COMPLETE") {
        Write-Host "  Stack creee!" -ForegroundColor Green
        break
    } elseif ($stackStatus -match "FAILED|ROLLBACK") {
        Write-Host "  ERREUR: Stack en echec ($stackStatus)" -ForegroundColor Red
        # Afficher la raison
        $events = aws cloudformation describe-stack-events `
            --region $REGION `
            --stack-name $stackName `
            --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].ResourceStatusReason" `
            --output text 2>$null
        if ($events) {
            Write-Host "  Raison: $events" -ForegroundColor Red
        }
        Read-Host "Appuyez sur Entree pour fermer"
        exit 1
    } else {
        $elapsed = $attempt * 15
        Write-Host "  [$elapsed s] Status: $stackStatus..." -ForegroundColor Gray
    }
}

if ($attempt -ge $maxAttempts) {
    Write-Host "  TIMEOUT: Stack non creee apres 15 minutes" -ForegroundColor Red
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}

# Recuperer l'IP de l'instance
$instanceIp = aws cloudformation describe-stacks `
    --region $REGION `
    --stack-name $stackName `
    --query "Stacks[0].Outputs[?OutputKey=='InstancePublicIp'].OutputValue" `
    --output text 2>$null

if (-not $instanceIp -or $instanceIp -eq "None") {
    # Fallback : chercher l'instance via les tags
    $instanceIp = aws ec2 describe-instances `
        --region $REGION `
        --filters "Name=tag:BatchId,Values=$batchId" "Name=instance-state-name,Values=running" `
        --query "Reservations[0].Instances[0].PublicIpAddress" `
        --output text 2>$null
}

if (-not $instanceIp -or $instanceIp -eq "None") {
    Write-Host "  ATTENTION: IP non trouvee, l'instance demarre peut-etre encore" -ForegroundColor Yellow
    Write-Host "  Verifiez dans la console AWS EC2" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BURST MODE DEMARRE!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Instance IP: $instanceIp" -ForegroundColor Cyan
    Write-Host "  vLLM:        http://${instanceIp}:${VLLM_PORT}" -ForegroundColor Cyan
    Write-Host "  Embeddings:  http://${instanceIp}:${EMBEDDINGS_PORT}" -ForegroundColor Cyan
    Write-Host "  Stack:       $stackName" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Le modele vLLM peut mettre 3-5 min a charger." -ForegroundColor Yellow
    Write-Host "  Verifiez avec:" -ForegroundColor Yellow
    Write-Host "    curl http://${instanceIp}:${VLLM_PORT}/health" -ForegroundColor Gray
    Write-Host ""

    $vllmUrl = "http://${instanceIp}:${VLLM_PORT}"
    $embUrl = "http://${instanceIp}:${EMBEDDINGS_PORT}"

    # Sauvegarder l'IP pour d'autres scripts
    $burstInfo = @{
        instance_ip = $instanceIp
        stack_name = $stackName
        batch_id = $batchId
        vllm_url = $vllmUrl
        embeddings_url = $embUrl
        started_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    }
    $burstInfo | ConvertTo-Json | Out-File -FilePath "data\.burst_info.json" -Encoding UTF8
    Write-Host "  Info sauvegardee dans data\.burst_info.json" -ForegroundColor Gray

    # Enregistrer dans Redis pour que le frontend + worker detectent le burst
    Write-Host ""
    Write-Host "  Enregistrement dans Redis..." -ForegroundColor Yellow
    $redisState = "{`"active`":true,`"vllm_url`":`"$vllmUrl`",`"vllm_model`":`"$VLLM_MODEL`",`"embeddings_url`":`"$embUrl`"}"
    try {
        docker exec knowbase-redis redis-cli SET "osmose:burst:state" $redisState 2>$null | Out-Null
        Write-Host "  Redis: OK (osmose:burst:state)" -ForegroundColor Green
    } catch {
        Write-Host "  Redis non accessible, ecriture fichier seulement" -ForegroundColor Yellow
    }

    # Ecrire aussi le fichier /data/.burst_state.json dans le volume Docker
    try {
        $burstStateJson = @{
            active = $true
            vllm_url = $vllmUrl
            vllm_model = $VLLM_MODEL
            embeddings_url = $embUrl
        } | ConvertTo-Json -Compress
        $burstStateJson | Out-File -FilePath "data\.burst_state.json" -Encoding UTF8 -NoNewline
        Write-Host "  Fichier: OK (data/.burst_state.json)" -ForegroundColor Green
    } catch {
        Write-Host "  Ecriture fichier state echouee" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  Le frontend et le worker detecteront le burst" -ForegroundColor Green
    Write-Host "  automatiquement au prochain health check." -ForegroundColor Green
}

Write-Host ""
Read-Host "Appuyez sur Entree pour fermer"
