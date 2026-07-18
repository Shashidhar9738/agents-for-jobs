$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspace = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($workspace)) {
    $workspace = (Get-Location).Path
}
$workspace = [System.IO.Path]::GetFullPath($workspace)
$logFile = Join-Path $workspace 'setup.log'

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = 'INFO'
    )

    $timestamp = Get-Date -Format 'dd-MM-yyyy HH:mm:ss'
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    Write-Log "Running: $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )

    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }

    return $null
}

function Install-WithWinget {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageId,
        [Parameter(Mandatory = $true)]
        [string]$DisplayName
    )

    Write-Log "Installing $DisplayName using winget"
    & winget install --id $PackageId --accept-source-agreements --accept-package-agreements --silent 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install $DisplayName"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $workspace, (Join-Path $workspace 'data'), (Join-Path $workspace 'output'), (Join-Path $workspace 'n8n'), (Join-Path $workspace 'logs') | Out-Null

    Set-Content -Path $logFile -Value "[$(Get-Date -Format 'dd-MM-yyyy HH:mm:ss')] Setup started"

    Write-Log "Workspace: $workspace"

    $wingetAvailable = $false
    $wingetCommand = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCommand) {
        $wingetAvailable = $true
    }

    $pythonCommand = Resolve-Command -Names @('py', 'python', 'python3')
    if (-not $pythonCommand) {
        if ($wingetAvailable) {
            Install-WithWinget -PackageId 'Python.Python.3.12' -DisplayName 'Python'
            $pythonCommand = Resolve-Command -Names @('py', 'python', 'python3')
        }
    }

    if (-not $pythonCommand) {
        throw 'Python was not found and winget is unavailable.'
    }

    $nodeCommand = Resolve-Command -Names @('node')
    if (-not $nodeCommand) {
        if ($wingetAvailable) {
            Install-WithWinget -PackageId 'OpenJS.NodeJS.LTS' -DisplayName 'Node.js'
            $nodeCommand = Resolve-Command -Names @('node')
        }
    }

    if (-not $nodeCommand) {
        throw 'Node.js was not found and winget is unavailable.'
    }

    $npmCommand = Resolve-Command -Names @('npm')
    if (-not $npmCommand) {
        if ($wingetAvailable) {
            Install-WithWinget -PackageId 'OpenJS.NodeJS.LTS' -DisplayName 'npm'
            $npmCommand = Resolve-Command -Names @('npm')
        }
    }

    if (-not $npmCommand) {
        throw 'npm was not found and winget is unavailable.'
    }

    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @('--version')
    Invoke-CheckedCommand -FilePath $nodeCommand -Arguments @('-v')
    Invoke-CheckedCommand -FilePath $npmCommand -Arguments @('-v')

    $requirementsPath = Join-Path $workspace 'requirements-agent.txt'
    if (-not (Test-Path $requirementsPath)) {
        Write-Log 'Creating requirements-agent.txt'
        @(
            'langgraph>=0.2.0',
            'openai>=1.40.0',
            'playwright>=1.50.0',
            'pandas>=2.2.0',
            'python-dotenv>=1.0.0',
            'beautifulsoup4>=4.12.0',
            'lxml>=5.2.0',
            'requests>=2.32.0'
        ) | Set-Content -Path $requirementsPath
    }

    Write-Log 'Installing Python dependencies'
    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @('-m', 'pip', 'install', '-r', $requirementsPath)

    Write-Log 'Downloading Playwright browser (Chromium)'
    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @('-m', 'playwright', 'install', 'chromium')

    $outputCsv = Join-Path $workspace 'output/AppliedJobs.csv'
    if (-not (Test-Path $outputCsv)) {
        Write-Log 'Creating output/AppliedJobs.csv'
        @('Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes') | Set-Content -Path $outputCsv
    }

    $workflowPath = Join-Path $workspace 'n8n/job-application-agent.workflow.json'
    if (-not (Test-Path $workflowPath)) {
        Write-Log 'Workflow file missing: n8n/job-application-agent.workflow.json' -Level 'WARN'
        Write-Log 'You can still run n8n and import workflow later.' -Level 'WARN'
    }

    Write-Log 'Installing n8n'
    Invoke-CheckedCommand -FilePath $npmCommand -Arguments @('install', '--prefix', (Join-Path $workspace 'n8n'), 'n8n@1.85.1', '--omit=optional', '--no-audit', '--no-fund')

    $n8nCmd = Join-Path $workspace 'n8n/node_modules/.bin/n8n.cmd'
    $n8nJs = Join-Path $workspace 'n8n/node_modules/n8n/bin/n8n.js'

    if (-not (Test-Path $n8nCmd) -and -not (Test-Path $n8nJs)) {
        throw 'n8n package did not produce a launcher.'
    }

    $env:N8N_HOST = '0.0.0.0'
    $env:N8N_PORT = '5678'
    $env:N8N_PROTOCOL = 'http'
    $env:N8N_SECURE_COOKIE = 'false'
    $env:N8N_BASIC_AUTH_ACTIVE = 'true'
    $env:N8N_BASIC_AUTH_USER = 'admin'
    $env:N8N_BASIC_AUTH_PASSWORD = 'ChangeThisNow123!'

    Write-Log 'Starting n8n in a new window'
    if (Test-Path $n8nCmd) {
        Start-Process -FilePath $n8nCmd -ArgumentList @('--host=0.0.0.0', '--port=5678') -WorkingDirectory $workspace -WindowStyle Normal | Out-Null
    } elseif (Test-Path $n8nJs) {
        Start-Process -FilePath $nodeCommand -ArgumentList @($n8nJs, '--host=0.0.0.0', '--port=5678') -WorkingDirectory $workspace -WindowStyle Normal | Out-Null
    }

    Write-Log 'Setup completed successfully'
    Write-Host ''
    Write-Host 'Setup complete.'
    Write-Host 'n8n URL on this desktop: http://localhost:5678'
    Write-Host 'n8n URL from laptop on same network: http://DESKTOP_IP:5678'
    Write-Host 'Username: admin'
    Write-Host 'Password: ChangeThisNow123!'
    Write-Host 'IMPORTANT: Change password immediately in this file before long-term use.'
    exit 0
}
catch {
    Write-Log $_.Exception.Message -Level 'ERROR'
    Write-Host ''
    Write-Host "Setup failed. Check $logFile for details."
    exit 1
}
