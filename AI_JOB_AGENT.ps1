# ============================================================================
#  AI Job Agent - provision and launch
#
#  Run in PowerShell. It works out what needs doing:
#    first run  -> installs Python deps, Playwright, Node, n8n; then launches
#    later runs -> launches n8n straight away
#
#  Launching starts two things: the pipeline dashboard server (background) and
#  n8n (foreground). Ctrl+C stops both.
#
#  Explicit modes:
#    .\AI_JOB_AGENT.ps1 setup   force a full re-provision
#    .\AI_JOB_AGENT.ps1 start   skip provisioning, launch only
#
#  Options:
#    -NoDashboard              launch n8n on its own
#    -DashboardPort 8801       serve the dashboard on another port
#    -Candidate priya          default candidate shown in the dashboard UI
#    -Deploy                   push and activate the workflows once n8n is up
# ============================================================================

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('auto', 'setup', 'start')]
    [string]$Mode = 'auto',

    [int]$DashboardPort = 8800,
    [string]$Candidate,
    [switch]$NoDashboard,
    [switch]$Deploy
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

# --------------------------- PYTHON DISCOVERY -------------------------------

function Find-Python {
    $candidates = @(
        'py', 'python', 'python3',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python310\python.exe')
    )
    foreach ($c in $candidates) {
        if ($c -match '\.exe$') {
            if (Test-Path $c) { return $c }
        } else {
            $found = (Get-Command $c -ErrorAction SilentlyContinue).Source
            if ($found -and (Get-Item $found).Length -gt 0) { return $found }
        }
    }
    return $null
}

# --------------------------- DASHBOARD --------------------------------------

# The pipeline server binds 127.0.0.1, so it has to run on the same machine as
# n8n - the stage nodes call http://localhost:8800 and nothing routes across
# hosts. Starting it here keeps the two together.

function Start-Dashboard {
    $dashboardScript = Join-Path $Workspace 'scripts\serve_dashboard.py'
    if (-not (Test-Path $dashboardScript)) {
        Write-Host "[WARN] serve_dashboard.py not found - dashboard skipped." -ForegroundColor Yellow
        return $null
    }

    $listening = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        Write-Host "[INFO] Port $DashboardPort already serving - reusing that dashboard." -ForegroundColor Cyan
        return $null
    }

    $python = Find-Python
    if (-not $python) {
        Write-Host '[WARN] Python not found - dashboard not started. Stages will fail.' -ForegroundColor Yellow
        return $null
    }

    $logDir = Join-Path $Workspace 'logs'
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    $outLog = Join-Path $logDir 'dashboard.log'
    $errLog = Join-Path $logDir 'dashboard.err.log'

    $argList = @("`"$dashboardScript`"", '--port', "$DashboardPort")
    if ($Candidate) { $argList += @('--candidate', $Candidate) }

    Write-Host "[INFO] Starting dashboard on http://127.0.0.1:$DashboardPort ..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $python -ArgumentList $argList `
        -WorkingDirectory $Workspace `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru

    # A bad import or a taken port kills it instantly; catch that now rather
    # than letting n8n come up in front of a dead backend.
    Start-Sleep -Seconds 2
    if ($proc.HasExited) {
        Write-Host "[ERROR] Dashboard exited immediately (code $($proc.ExitCode))." -ForegroundColor Red
        Write-Host "[ERROR] See $errLog" -ForegroundColor Red
        return $null
    }

    Write-Host "[INFO] Dashboard running (PID $($proc.Id))" -ForegroundColor Green
    Write-Host "[INFO] Dashboard log: $outLog" -ForegroundColor Gray
    return $proc
}

function Stop-Dashboard {
    param($Process)
    if (-not $Process) { return }
    if ($Process.HasExited) { return }
    Write-Host ''
    Write-Host "[INFO] Stopping dashboard (PID $($Process.Id))..." -ForegroundColor Cyan
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

# --------------------------- WORKFLOW DEPLOY --------------------------------

# Opt-in (-Deploy). Pushes the workflows and activates them - without that,
# triggers never fire and n8n records no executions at all. `n8n start` blocks,
# so this waits for the port in a background job and deploys once it answers.

function Start-DeployJob {
    $buildScript = Join-Path $Workspace 'scripts\build_n8n_workflows.py'
    if (-not (Test-Path $buildScript)) {
        Write-Host '[WARN] build_n8n_workflows.py not found - deploy skipped.' -ForegroundColor Yellow
        return $null
    }

    $python = Find-Python
    if (-not $python) {
        Write-Host '[WARN] Python not found - deploy skipped.' -ForegroundColor Yellow
        return $null
    }

    Write-Host "[INFO] Workflows will deploy once n8n answers on port $($env:N8N_PORT)." -ForegroundColor Cyan

    return Start-Job -ScriptBlock {
        param($python, $buildScript, $workspace, $port, $dashboardPort)

        # n8n takes a while to migrate its database on first boot.
        $ready = $false
        foreach ($attempt in 1..60) {
            $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conn) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) { return "[DEPLOY] n8n never opened port $port - workflows not deployed." }

        Start-Sleep -Seconds 3
        Set-Location $workspace
        $output = & $python $buildScript --pipeline "http://localhost:$dashboardPort" 2>&1
        return ($output | Out-String)
    } -ArgumentList $python, $buildScript, $Workspace, $env:N8N_PORT, $DashboardPort
}

function Complete-DeployJob {
    param($Job)
    if (-not $Job) { return }
    Write-Host ''
    Write-Host '--- workflow deploy output ---' -ForegroundColor Cyan
    Receive-Job -Job $Job -ErrorAction SilentlyContinue | Write-Host
    Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
}

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
    $pythonCmd = Find-Python
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

    # Dashboard first - n8n's stage nodes call it, so it should be up before
    # any workflow can fire.
    $dashboard = $null
    if (-not $NoDashboard) { $dashboard = Start-Dashboard }

    $deployJob = $null
    if ($Deploy) { $deployJob = Start-DeployJob }

    try {
        Write-Host ""
        Write-Host "[INFO] Starting n8n..." -ForegroundColor Cyan
        Write-Host "[INFO] Using: $n8nCmd" -ForegroundColor Cyan

        # Show version
        Write-Host ""
        Write-Host "Version:" -ForegroundColor Cyan
        & n8n --version

        Write-Host ""
        Write-Host "================================================" -ForegroundColor Cyan
        Write-Host " n8n URL   : $N8N_URL" -ForegroundColor Green
        if (-not $NoDashboard) {
            Write-Host " Dashboard : http://127.0.0.1:$DashboardPort" -ForegroundColor Green
        }
        Write-Host "================================================" -ForegroundColor Cyan
        Write-Host "[INFO] N8N_SECURE_COOKIE=$($env:N8N_SECURE_COOKIE)" -ForegroundColor Cyan
        Write-Host "[INFO] N8N_USER_FOLDER=$($env:N8N_USER_FOLDER)" -ForegroundColor Cyan
        Write-Host '[INFO] Press Ctrl+C to stop both' -ForegroundColor Yellow
        Write-Host ''

        # Launch n8n (blocks until stopped)
        n8n start

        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] n8n exited with code $LASTEXITCODE. Check setup.log" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }
    finally {
        Complete-DeployJob -Job $deployJob
        Stop-Dashboard -Process $dashboard
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