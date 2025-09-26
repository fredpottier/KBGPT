@echo off
echo 🛠️  Configuration d'AWS CodeBuild pour SAP KB...

REM Vérifier les credentials AWS
aws sts get-caller-identity >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ Erreur: AWS CLI non configuré
    echo Configurez avec: aws configure
    pause
    exit /b 1
)

echo ✅ AWS CLI configuré

REM Variables
set PROJECT_NAME=sap-kb-docker-build
set REGION=eu-west-1
set ROLE_NAME=CodeBuildServiceRole-SAP-KB
set GITHUB_REPO=https://github.com/YOUR_USERNAME/SAP_KB.git

echo 🔐 Création du rôle IAM: %ROLE_NAME%

REM Créer trust policy
echo {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]} > trust-policy.json

REM Créer le rôle IAM
aws iam create-role --role-name %ROLE_NAME% --assume-role-policy-document file://trust-policy.json --region %REGION% >nul 2>&1

REM Attacher les policies
echo   🔗 Attachement des policies...
aws iam attach-role-policy --role-name %ROLE_NAME% --policy-arn "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess" >nul 2>&1
aws iam attach-role-policy --role-name %ROLE_NAME% --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess" >nul 2>&1

REM Policy ECR
echo {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:*"],"Resource":"*"}]} > ecr-policy.json
aws iam put-role-policy --role-name %ROLE_NAME% --policy-name "ECRBuildAccess" --policy-document file://ecr-policy.json >nul 2>&1

echo ✅ Rôle IAM configuré

REM Récupérer Account ID
for /f "tokens=*" %%i in ('aws sts get-caller-identity --query "Account" --output text') do set ACCOUNT_ID=%%i

REM Configuration CodeBuild
echo 🔨 Création du projet CodeBuild...

aws codebuild create-project ^
    --name %PROJECT_NAME% ^
    --description "Build Docker SAP KB" ^
    --source type=GITHUB,location=%GITHUB_REPO% ^
    --artifacts type=NO_ARTIFACTS ^
    --environment type=LINUX_CONTAINER,image=aws/codebuild/amazonlinux2-x86_64-standard:4.0,computeType=BUILD_GENERAL1_LARGE,privilegedMode=true ^
    --service-role arn:aws:iam::%ACCOUNT_ID%:role/%ROLE_NAME% ^
    --timeout-in-minutes 60 ^
    --region %REGION% >nul 2>&1

if %ERRORLEVEL% equ 0 (
    echo ✅ Projet créé avec succès!
    echo 🔗 Console: https://%REGION%.console.aws.amazon.com/codesuite/codebuild/projects/%PROJECT_NAME%
) else (
    echo ❌ Erreur ou projet déjà existant
)

REM Nettoyer
del trust-policy.json ecr-policy.json >nul 2>&1

echo.
echo 🎯 Configuration terminée!
echo 📝 Prochaines étapes:
echo   1. Account ID configuré: %ACCOUNT_ID%
echo   2. Tester: .\scripts\build-remote.ps1
pause