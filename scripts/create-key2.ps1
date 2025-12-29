# Create key and save with correct format
$AWS = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

# Get key as JSON
$json = & $AWS ec2 create-key-pair --region eu-central-1 --key-name osmose-burst-key3 --output json | ConvertFrom-Json

# Extract key material and write to file
$key = $json.KeyMaterial
Set-Content -Path "C:\Projects\SAP_KB\config\osmose-burst-key3.pem" -Value $key -NoNewline

Write-Host "Key created and saved"
Write-Host "First lines:"
Get-Content "C:\Projects\SAP_KB\config\osmose-burst-key3.pem" | Select-Object -First 3
