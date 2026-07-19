# test-launch.ps1
$env:N8N_PORT = "5678"
$env:N8N_HOST = "localhost"
$env:N8N_SECURE_COOKIE = "false"
$env:N8N_USER_FOLDER = "$env:LOCALAPPDATA\AIJobAgent\n8n"
$env:N8N_LOG_LEVEL = "info"

$n8nDir = "$env:LOCALAPPDATA\AIJobAgent\n8n\node_modules\n8n"

Write-Host "Starting n8n from: $n8nDir"
Write-Host "URL: http://localhost:5678"
Write-Host ""

Push-Location $n8nDir
node bin/n8n
Pop-Location