$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$key = & $AWS ec2 create-key-pair --region eu-central-1 --key-name osmose-burst-key2 --query 'KeyMaterial' --output text
[System.IO.File]::WriteAllText("C:\Projects\SAP_KB\config\osmose-burst-key2.pem", $key)
Write-Host "Key saved to config/osmose-burst-key2.pem"
