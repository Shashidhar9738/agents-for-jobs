param(
    [string]$WorkspacePath = (Get-Location).Path,
    [switch]$SkipWingetInstall,
    [switch]$SkipN8n,
    [switch]$SkipPythonPackages,
    [switch]$SkipPlaywrightBrowsers
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Yellow
}

function Ensure-Command {
    param(
        [Parameter(Mandatory = $true)][string]$CommandName,
        [Parameter(Mandatory = $true)][string]$WingetId,
        [switch]$SkipInstall
    )

    if (Get-Command $CommandName -ErrorAction SilentlyContinue) {
        Write-Info "$CommandName is already installed."
        return
    }

    if ($SkipInstall) {
        throw "$CommandName is missing and installs are skipped. Install it manually and rerun."
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install $CommandName manually and rerun."
    }

    Write-Info "Installing $CommandName via winget ($WingetId)..."
    winget install --id $WingetId --accept-source-agreements --accept-package-agreements --silent

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "$CommandName installation did not complete successfully."
    }

    Write-Info "$CommandName installed successfully."
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
        Write-Info "Created directory: $Path"
    }
}

function Invoke-Safe {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Script,
        [Parameter(Mandatory = $true)][string]$FailMessage
    )
    try {
        & $Script
    } catch {
        throw "$FailMessage`n$($_.Exception.Message)"
    }
}

Write-Step "Preparing workspace"
$resolvedWorkspace = Resolve-Path $WorkspacePath
Set-Location $resolvedWorkspace
Write-Info "Workspace: $resolvedWorkspace"

Ensure-Directory -Path (Join-Path $resolvedWorkspace 'data')
Ensure-Directory -Path (Join-Path $resolvedWorkspace 'output')
Ensure-Directory -Path (Join-Path $resolvedWorkspace 'n8n')
Ensure-Directory -Path (Join-Path $resolvedWorkspace 'logs')

Write-Step "Checking required tools"
Ensure-Command -CommandName 'node' -WingetId 'OpenJS.NodeJS.LTS' -SkipInstall:$SkipWingetInstall
Ensure-Command -CommandName 'npm' -WingetId 'OpenJS.NodeJS.LTS' -SkipInstall:$SkipWingetInstall
Ensure-Command -CommandName 'python' -WingetId 'Python.Python.3.12' -SkipInstall:$SkipWingetInstall

Write-Step "Capturing tool versions"
Write-Info "Node version: $(node -v)"
Write-Info "NPM version: $(npm -v)"
Write-Info "Python version: $(python --version)"

if (-not $SkipN8n) {
    Write-Step "Installing n8n globally"
    Invoke-Safe -Script {
        npm install -g n8n
    } -FailMessage "Failed to install n8n globally."
    Write-Info "n8n installed."
} else {
    Write-Info "Skipping n8n installation."
}

$requirementsPath = Join-Path $resolvedWorkspace 'requirements-agent.txt'
$requirementsContent = @(
    'langgraph>=0.2.0',
    'openai>=1.40.0',
    'playwright>=1.50.0',
    'pandas>=2.2.0',
    'python-dotenv>=1.0.0',
    'beautifulsoup4>=4.12.0',
    'lxml>=5.2.0',
    'requests>=2.32.0'
) -join "`n"

if (-not (Test-Path $requirementsPath)) {
    Set-Content -Path $requirementsPath -Value $requirementsContent -Encoding UTF8
    Write-Info "Created requirements file: $requirementsPath"
} else {
    Write-Info "Using existing requirements file: $requirementsPath"
}

if (-not $SkipPythonPackages) {
    Write-Step "Installing Python packages"
    Invoke-Safe -Script {
        python -m pip install --upgrade pip
        python -m pip install -r $requirementsPath
    } -FailMessage "Failed to install Python dependencies."
    Write-Info "Python dependencies installed."
} else {
    Write-Info "Skipping Python package installation."
}

if (-not $SkipPlaywrightBrowsers) {
    Write-Step "Downloading Playwright browser files"
    Invoke-Safe -Script {
        python -m playwright install chromium
    } -FailMessage "Failed to download Playwright browser files."
    Write-Info "Playwright browser files downloaded."
} else {
    Write-Info "Skipping Playwright browser download."
}

$csvPath = Join-Path $resolvedWorkspace 'output\AppliedJobs.csv'
if (-not (Test-Path $csvPath)) {
    'Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes' |
        Set-Content -Path $csvPath -Encoding UTF8
    Write-Info "Initialized tracker file: $csvPath"
}

Write-Step "Bootstrap complete"
Write-Host "Run n8n with: n8n" -ForegroundColor Green
Write-Host "Import workflow: n8n/job-application-agent.workflow.json" -ForegroundColor Green
