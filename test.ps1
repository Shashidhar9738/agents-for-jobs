# --------------------------- LAUNCH -----------------------------------------

function Invoke-Launch {
    if (!(Test-Path $N8NBin)) {
        Write-Host ""
        Write-Host "[ERROR] Local n8n installation not found." -ForegroundColor Red
        Write-Host "Expected:" -ForegroundColor Yellow
        Write-Host $N8NBin -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Run setup first:" -ForegroundColor Yellow
        Write-Host ".\AI_JOB_AGENT.ps1 setup" -ForegroundColor Green
        exit 1
    }

    # Get the Node executable
    $nodeExe = $script:Node.Exe
    
    # Path to n8n directory
    $n8nDir = Join-Path $N8NHome 'node_modules\n8n'
    
    Write-Host ""
    Write-Host "[INFO] Starting n8n from: $n8nDir" -ForegroundColor Cyan
    Write-Host "[INFO] Using Node: $nodeExe" -ForegroundColor Cyan
    
    # Show version before launching
    Write-Host ""
    Write-Host "Version:" -ForegroundColor Cyan
    Push-Location $n8nDir
    & $nodeExe bin/n8n --version
    Pop-Location
    
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host " n8n URL: $N8N_URL" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host "[INFO] N8N_SECURE_COOKIE=$($env:N8N_SECURE_COOKIE)" -ForegroundColor Cyan
    Write-Host '[INFO] Press Ctrl+C to stop n8n' -ForegroundColor Yellow
    Write-Host ''
    
    # Launch n8n by running from its directory using node bin/n8n
    Push-Location $n8nDir
    & $nodeExe bin/n8n
    Pop-Location
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] n8n exited with code $LASTEXITCODE. Check setup.log" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}