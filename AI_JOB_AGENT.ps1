# ============================================================================
#  AI Job Agent - provision and launch
#
#  Run in PowerShell. It works out what needs doing:
#    first run  -> installs Python deps, Playwright, Node, n8n; then launches
#    later runs -> launches n8n straight away
#
#  Explicit modes:
#    .\AI_JOB_AGENT.ps1 setup   force a full re-provision
#    .\AI_JOB_AGENT.ps1 start   skip provisioning, launch only
# ============================================================================

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('auto', 'setup', 'start')]
    [string]$Mode = 'auto'
)

# Native tools write to stderr routinely; Stop would abort on harmless noise.
$ErrorActionPreference = 'Continue'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Workspace  = $ScriptDir
$LogFile    = Join-Path $Workspace 'setup.log'
$EnvFile    = Join-Path $Workspace '.env'
$N8NHome    = Join-Path $env:LOCALAPPDATA 'AIJobAgent\n8n'
$N8NBin     = Join-Path $N8NHome 'node_modules\.bin\n8n.cmd'
$Marker     = Join-Path $N8NHome '.setup-complete'
$N8NVersion = '2.22.6'

Set-Location $Workspace

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    Write-Host $Message -ForegroundColor $Color
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" |
        Out-File -FilePath $LogFile -Append -Encoding utf8
}

Write-Host '================================================' -ForegroundColor Cyan
Write-Host ' AI Job Agent' -ForegroundColor Cyan
Write-Host '================================================' -ForegroundColor Cyan
Write-Host " Workspace    : $Workspace"
Write-Host " n8n version  : $N8NVersion" -ForegroundColor Yellow
Write-Host '================================================' -ForegroundColor Cyan
Write-Host ''

# --------------------------- ENVIRONMENT ------------------------------------

if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] No .env found at $EnvFile" -ForegroundColor Red
    Write-Host '[ERROR] Copy .env.example to .env and fill it in, then re-run.' -ForegroundColor Red
    exit 1
}

foreach ($line in (Get-Content $EnvFile)) {
    if ($line -match '^\s*#') { continue }
    if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { continue }
    $name  = $Matches[1]
    $value = $Matches[2].Trim()
    if ($value.Length -ge 2 -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    Set-Item -Path "env:$name" -Value $value
}

if (-not $env:N8N_PORT)          { $env:N8N_PORT = '5678' }
if (-not $env:N8N_HOST)          { $env:N8N_HOST = 'localhost' }
if (-not $env:N8N_SECURE_COOKIE) { $env:N8N_SECURE_COOKIE = 'false' }
$env:N8N_USER_FOLDER = $N8NHome

$N8N_URL = "${env:N8N_HOST}:${env:N8N_PORT}"

Write-Host "[DEBUG] Built URL: '$N8N_URL'" -ForegroundColor Magenta
Write-Host ""

# --------------------------- NODE DISCOVERY ---------------------------------

function Find-Node {
    $candidates = @(
        (Get-Command node -ErrorAction SilentlyContinue).Source,
        (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Nodejs\node.exe')
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) {
            $dir = Split-Path -Parent $path
            if (Test-Path (Join-Path $dir 'npm.cmd')) {
                return [pscustomobject]@{
                    Exe = $path
                    Dir = $dir
                    Npm = (Join-Path $dir 'npm.cmd')
                    Npx = (Join-Path $dir 'npx.cmd')
                }
            }
        }
    }
    return $null
}

$Node = Find-Node
if (-not $Node) { 
    Write-Host '[ERROR] Node.js not found. Please install Node.js 20.x LTS.' -ForegroundColor Red
    exit 1
}

# Check if n8n is installed globally
$globalN8n = (Get-Command n8n -ErrorAction SilentlyContinue).Source
if (-not $globalN8n) {
    Write-Host '[INFO] n8n not found globally - will install during setup.' -ForegroundColor Yellow
}

if ($Mode -eq 'auto') {
    $Mode = 'start'
    if (-not (Test-Path $Marker)) { $Mode = 'setup' }
    if (-not $globalN8n) { $Mode = 'setup' }
}

Write-Host "[INFO] Mode: $Mode" -ForegroundColor Green
Write-Host ''

# --------------------------- PROVISIONING -----------------------------------

function Invoke-Provision {
    "=== Setup started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
        Out-File -FilePath $LogFile -Encoding utf8
    Write-Log "[INFO] Workspace: $Workspace"

    foreach ($d in @('data', 'output', 'logs')) {
        $dir = Join-Path $Workspace $d
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }

    # --- Python
    $pythonCmd = $null
    $pythonCandidates = @(
        'py', 'python', 'python3',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python310\python.exe')
    )
    foreach ($c in $pythonCandidates) {
        if ($c -match '\.exe$') {
            if (Test-Path $c) { $pythonCmd = $c; break }
        } else {
            $found = (Get-Command $c -ErrorAction SilentlyContinue).Source
            if ($found -and (Get-Item $found).Length -gt 0) { $pythonCmd = $found; break }
        }
    }
    if (-not $pythonCmd) {
        Write-Log '[ERROR] Python not found. Install from https://python.org and re-run.' 'Red'
        return $false
    }
    Write-Log "[INFO] Python: $pythonCmd" 'Green'

    $requirementsFile = Join-Path $Workspace 'requirements-agent.txt'
    if (-not (Test-Path $requirementsFile)) {
        Write-Host '[INFO] Creating requirements-agent.txt' -ForegroundColor Cyan
        @'
langgraph>=0.2.0
openai>=1.40.0
playwright>=1.50.0
pandas>=2.2.0
python-dotenv>=1.0.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
requests>=2.32.0
'@ | Out-File -FilePath $requirementsFile -Encoding utf8
    }

    Write-Host '[STEP] Upgrading pip...' -ForegroundColor Yellow
    $pipUpgrade = & $pythonCmd -m pip install --upgrade pip 2>&1
    $pipUpgrade | Out-File -FilePath $LogFile -Append -Encoding utf8

    Write-Host '[STEP] Installing Python packages...' -ForegroundColor Yellow
    $pipInstall = & $pythonCmd -m pip install -r "$requirementsFile" 2>&1
    $pipInstall | Out-File -FilePath $LogFile -Append -Encoding utf8
    
    if ($LASTEXITCODE -ne 0) {
        Write-Log '[ERROR] Python package install failed. Check setup.log' 'Red'
        return $false
    }
    Write-Log '[INFO] Python packages installed.' 'Green'

    Write-Host '[STEP] Downloading Playwright Chromium...' -ForegroundColor Yellow
    $playwrightInstall = & $pythonCmd -m playwright install chromium 2>&1
    $playwrightInstall | Out-File -FilePath $LogFile -Append -Encoding utf8

    # --- n8n Installation (Global)
    Write-Host ""
    Write-Host "[STEP] Installing n8n $N8NVersion globally..." -ForegroundColor Yellow
    
    $npm = $script:Node.Npm
    
    # Check if already installed globally
    $existingN8n = (Get-Command n8n -ErrorAction SilentlyContinue).Source
    if ($existingN8n) {
        Write-Host "Removing existing global n8n..." -ForegroundColor Yellow
        & $npm uninstall -g n8n 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
    
    Write-Host "Installing n8n $N8NVersion globally (this may take a few minutes)..." -ForegroundColor Cyan
    $npmInstall = & $npm install -g "n8n@$N8NVersion" 2>&1
    $npmInstall | Out-File -FilePath $LogFile -Append -Encoding utf8
    
    if ($LASTEXITCODE -ne 0) {
        Write-Log '[ERROR] n8n global install failed. Check setup.log' 'Red'
        return $false
    }

    # Verify installation
    $installedVersion = & n8n --version 2>$null
    if (-not $installedVersion) {
        Write-Log '[ERROR] n8n installed but not found in PATH.' 'Red'
        return $false
    }
    
    $installedVersion = $installedVersion.Trim()
    Write-Host "Installed Version : $installedVersion" -ForegroundColor Green

    if ($installedVersion -ne $N8NVersion) {
        Write-Host ""
        Write-Host "ERROR: Wrong version installed!" -ForegroundColor Red
        Write-Host "Expected : $N8NVersion"
        Write-Host "Actual   : $installedVersion"
        return $false
    }

    Write-Log "[INFO] n8n $N8NVersion installed globally and verified." "Green"
    return $true
}

# --------------------------- LAUNCH -----------------------------------------

function Invoke-Launch {
    # Check if n8n is available
    $n8nCmd = (Get-Command n8n -ErrorAction SilentlyContinue).Source
    if (-not $n8nCmd) {
        Write-Host ""
        Write-Host "[ERROR] n8n not found. Run setup first:" -ForegroundColor Red
        Write-Host ".\AI_JOB_AGENT.ps1 setup" -ForegroundColor Green
        exit 1
    }

    Write-Host ""
    Write-Host "[INFO] Starting n8n..." -ForegroundColor Cyan
    Write-Host "[INFO] Using: $n8nCmd" -ForegroundColor Cyan
    
    # Show version
    Write-Host ""
    Write-Host "Version:" -ForegroundColor Cyan
    & n8n --version
    
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host " n8n URL: $N8N_URL" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host "[INFO] N8N_SECURE_COOKIE=$($env:N8N_SECURE_COOKIE)" -ForegroundColor Cyan
    Write-Host "[INFO] N8N_USER_FOLDER=$($env:N8N_USER_FOLDER)" -ForegroundColor Cyan
    Write-Host '[INFO] Press Ctrl+C to stop n8n' -ForegroundColor Yellow
    Write-Host ''
    
    # Launch n8n
    n8n start
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] n8n exited with code $LASTEXITCODE. Check setup.log" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# --------------------------- MAIN -------------------------------------------

if ($Mode -eq 'setup') {
    if (-not (Invoke-Provision)) { 
        Write-Host ""
        Write-Host "[ERROR] Setup failed." -ForegroundColor Red
        exit 1 
    }

    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Setup completed" |
        Out-File -FilePath $Marker -Encoding utf8
    Write-Log '[INFO] Setup completed.' 'Green'

    Write-Host ''
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host ' SETUP COMPLETE' -ForegroundColor Green
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host " n8n URL    : $N8N_URL" -ForegroundColor Green
    Write-Host " n8n version: $N8NVersion" -ForegroundColor Green
    Write-Host " Import     : n8n-job-agent-workflow.json"
    Write-Host ''
    Write-Host ' n8n 2.x does not use N8N_BASIC_AUTH_* - on first launch the browser'
    Write-Host ' will ask you to create an owner account. Credentials are not printed.'
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host ''
}

# Always launch if we reach this point
Invoke-Launch