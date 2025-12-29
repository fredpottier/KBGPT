$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$REGION = "eu-central-1"

Write-Host "Creating SG..."
$SG = & $AWS ec2 create-security-group --region $REGION --group-name "burst-quick-test" --description "Quick Test" --query GroupId --output text
Write-Host "SG: $SG"

& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG --protocol tcp --port 8000-8001 --cidr 0.0.0.0/0 | Out-Null
& $AWS ec2 authorize-security-group-ingress --region $REGION --group-id $SG --protocol tcp --port 8080 --cidr 0.0.0.0/0 | Out-Null

Write-Host "Launching Spot instance (g6e.xlarge - L4 24GB)..."
$INST = & $AWS ec2 run-instances --region $REGION --image-id ami-0f1273572a6a564a1 --instance-type g6e.xlarge --security-group-ids $SG --instance-market-options MarketType=spot --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3}" --query "Instances[0].InstanceId" --output text 2>&1

Write-Host "Result: $INST"

if ($INST -match "^i-") {
    Write-Host "SUCCESS: Instance $INST created" -ForegroundColor Green
    Write-Host "Cleanup: & '$AWS' ec2 terminate-instances --region $REGION --instance-ids $INST"
    Write-Host "         & '$AWS' ec2 delete-security-group --region $REGION --group-id $SG"
} else {
    Write-Host "FAILED: $INST" -ForegroundColor Red
    & $AWS ec2 delete-security-group --region $REGION --group-id $SG | Out-Null
    Write-Host "SG deleted"
}
