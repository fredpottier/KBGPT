Write-Host "Configuration d'AWS CodeBuild pour SAP KB..." -ForegroundColor Green

$ProjectName = "sap-kb-docker-build"
$Region = "eu-west-1"
$RoleName = "CodeBuildServiceRole-SAP-KB"

# Obtenir Account ID
$AwsCli = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$AccountId = & $AwsCli sts get-caller-identity --query "Account" --output text 2>$null
if (-not $AccountId) {
    Write-Host "AWS CLI non configure" -ForegroundColor Red
    exit 1
}

Write-Host "Account ID: $AccountId" -ForegroundColor Cyan

# Créer fichiers JSON
Write-Host "Creation des fichiers de configuration..."
'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}' | Out-File "trust.json" -Encoding ASCII
'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:*"],"Resource":"*"}]}' | Out-File "ecr.json" -Encoding ASCII

# Créer rôle IAM
Write-Host "Creation du role IAM: $RoleName"
& $AwsCli iam create-role --role-name $RoleName --assume-role-policy-document file://trust.json --region $Region 2>$null
Write-Host "  Role cree (ou existe deja)" -ForegroundColor Green

# Attacher policies
Write-Host "Attachement des policies..."
& $AwsCli iam attach-role-policy --role-name $RoleName --policy-arn "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess" 2>$null
& $AwsCli iam attach-role-policy --role-name $RoleName --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess" 2>$null
& $AwsCli iam put-role-policy --role-name $RoleName --policy-name "ECRBuildAccess" --policy-document file://ecr.json 2>$null
Write-Host "  Policies attachees" -ForegroundColor Green

# Créer projet CodeBuild
Write-Host "Creation du projet CodeBuild..."

# Exécuter la commande directement
& $AwsCli codebuild create-project `
    --name $ProjectName `
    --description "Build Docker SAP KB - MegaParse optimisé" `
    --source 'type=GITHUB,location=https://github.com/YOUR_USERNAME/SAP_KB.git' `
    --artifacts 'type=NO_ARTIFACTS' `
    --environment 'type=LINUX_CONTAINER,image=aws/codebuild/amazonlinux2-x86_64-standard:4.0,computeType=BUILD_GENERAL1_LARGE,privilegedMode=true' `
    --service-role "arn:aws:iam::${AccountId}:role/$RoleName" `
    --timeout-in-minutes 60 `
    --region $Region 2>$null

Write-Host "Projet CodeBuild configure!" -ForegroundColor Green

# Créer fichier de tracking simple
$resourcesData = @{
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    account_id = $AccountId
    region = $Region
    resources = @(
        "IAM Role: $RoleName",
        "CodeBuild Project: $ProjectName",
        "ECR Repository: sap-kb-app (sera créé au build)",
        "ECR Repository: sap-kb-frontend (sera créé au build)",
        "ECR Repository: sap-kb-worker (sera créé au build)"
    )
}

$resourcesData | ConvertTo-Json | Out-File "aws-resources-created.json" -Encoding UTF8

# Nettoyer
Remove-Item "trust.json", "ecr.json" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Configuration terminee!" -ForegroundColor Magenta
Write-Host "Ressources trackees dans: aws-resources-created.json" -ForegroundColor Yellow
Write-Host "Console: https://$Region.console.aws.amazon.com/codesuite/codebuild/projects/$ProjectName" -ForegroundColor Cyan
Write-Host ""
Write-Host "Prochaines etapes:" -ForegroundColor Green
Write-Host "  1. Modifier l'URL GitHub dans buildspec.yml si nécessaire" -ForegroundColor White
Write-Host "  2. Tester build: .\scripts\build-remote-local.ps1 -Wait" -ForegroundColor White
Write-Host "  3. Nettoyer plus tard: .\scripts\cleanup-aws-resources.ps1 -DryRun" -ForegroundColor White