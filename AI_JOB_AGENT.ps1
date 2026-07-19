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
$N8NVersion = '1.50.0'

Set-Location $Workspace

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    Write-Host $Message -ForegroundColor $Color
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" |
        Out-File -FilePath $LogFile -Append -Encoding utf8
}

# Runs a native command, appends its combined output to the log, returns exit code.
function Invoke-Logged {
    param([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory = $Workspace)
    $p = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$LogFile.out" -RedirectStandardError "$LogFile.err"
    foreach ($f in @("$LogFile.out", "$LogFile.err")) {
        if (Test-Path $f) {
            Get-Content $f | Out-File -FilePath $LogFile -Append -Encoding utf8
            Remove-Item $f -Force
        }
    }
    return $p.ExitCode
}

if (-not (Test-Path $N8NHome)) {
    New-Item -ItemType Directory -Path $N8NHome -Force | Out-Null
}

Write-Host '================================================' -ForegroundColor Cyan
Write-Host ' AI Job Agent' -ForegroundColor Cyan
Write-Host '================================================' -ForegroundColor Cyan
Write-Host " Workspace : $Workspace"
Write-Host " n8n home  : $N8NHome"
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
    # Strip a single matching pair of surrounding quotes, if present.
    if ($value.Length -ge 2 -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    Set-Item -Path "env:$name" -Value $value
}

if (-not $env:N8N_PORT)          { $env:N8N_PORT = '5678' }
if (-not $env:N8N_HOST)          { $env:N8N_HOST = '0.0.0.0' }
if (-not $env:N8N_SECURE_COOKIE) { $env:N8N_SECURE_COOKIE = 'false' }
$env:N8N_USER_FOLDER = $N8NHome

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
if (-not $Node) { Write-Host '[INFO] Node.js not found - will install during provisioning.' -ForegroundColor Yellow }

if ($Mode -eq 'auto') {
    $Mode = 'start'
    if (-not (Test-Path $Marker)) { $Mode = 'setup' }
    if (-not (Test-Path $N8NBin)) { $Mode = 'setup' }
    if (-not $Node)               { $Mode = 'setup' }
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

    # --- Node
    if (-not $script:Node) {
        Write-Host '[STEP] Installing Node.js...' -ForegroundColor Yellow
        $nodeVersion   = '22.11.0'
        $nodeInstaller = Join-Path $env:TEMP "node-v$nodeVersion-x64.msi"
        $nodeUrl       = "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-x64.msi"

        Write-Host "[INFO] Downloading Node.js $nodeVersion..." -ForegroundColor Cyan
        try {
            Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeInstaller -UseBasicParsing -ErrorAction Stop
        } catch {
            Write-Log "[ERROR] Node.js download failed: $_" 'Red'
            return $false
        }

        Write-Host '[INFO] Installing Node.js (this may take a moment)...' -ForegroundColor Cyan
        $p = Start-Process msiexec.exe -ArgumentList "/i `"$nodeInstaller`" /quiet /norestart" -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Write-Log "[ERROR] Node.js installation failed (exit $($p.ExitCode))." 'Red'
            return $false
        }

        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $script:Node = Find-Node
        if (-not $script:Node) {
            Write-Log '[ERROR] Node installed but not detectable. Open a new shell and re-run.' 'Red'
            return $false
        }
    }
    Write-Log "[INFO] Node: $($script:Node.Exe)" 'Green'

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
            # The Windows Store alias is a 0-byte stub that opens the Store; skip it.
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
    Invoke-Logged $pythonCmd @('-m', 'pip', 'install', '--upgrade', 'pip') | Out-Null

    Write-Host '[STEP] Installing Python packages...' -ForegroundColor Yellow
    if ((Invoke-Logged $pythonCmd @('-m', 'pip', 'install', '-r', $requirementsFile)) -ne 0) {
        Write-Log '[ERROR] Python package install failed. Check setup.log' 'Red'
        return $false
    }
    Write-Log '[INFO] Python packages installed.' 'Green'

    Write-Host '[STEP] Downloading Playwright Chromium...' -ForegroundColor Yellow
    if ((Invoke-Logged $pythonCmd @('-m', 'playwright', 'install', 'chromium')) -ne 0) {
        Write-Log '[WARN] Playwright download failed - run manually: py -m playwright install chromium' 'Yellow'
    }

    # --- n8n
    Write-Host "[STEP] Installing n8n v$N8NVersion in user profile (no admin needed)..." -ForegroundColor Yellow
    $npm = $script:Node.Npm

    if (-not (Test-Path (Join-Path $N8NHome 'package.json'))) {
        if ((Invoke-Logged $npm @('init', '-y') $N8NHome) -ne 0) {
            Write-Log '[ERROR] n8n bootstrap failed. Check setup.log' 'Red'
            return $false
        }
    }

    # Reinstall when the binary is missing or the installed version is not the pinned one.
    $needsReinstall = -not (Test-Path $N8NBin)
    if (-not $needsReinstall) {
        $installedPkg = Join-Path $N8NHome 'node_modules\n8n\package.json'
        if (Test-Path $installedPkg) {
            $installed = (Get-Content $installedPkg -Raw | ConvertFrom-Json).version
            if ($installed -ne $N8NVersion) {
                Write-Log "[INFO] Installed n8n is $installed, want $N8NVersion." 'Yellow'
                $needsReinstall = $true
            }
        } else {
            $needsReinstall = $true
        }
    }

    if ($needsReinstall) {
        Write-Host '[WARN] Missing, broken, or wrong-version n8n detected. Reinstalling...' -ForegroundColor Yellow
        foreach ($stale in @('node_modules', 'package-lock.json')) {
            $p = Join-Path $N8NHome $stale
            if (Test-Path $p) { Remove-Item -Recurse -Force $p }
        }
    }

    Write-Host '[INFO] Installing n8n (this may take a few minutes)...' -ForegroundColor Cyan
    $npmArgs = @("n8n@$N8NVersion", '--legacy-peer-deps', '--omit=optional', '--no-audit', '--no-fund')
    $code = Invoke-Logged $npm (@('install') + $npmArgs) $N8NHome
    if ($code -ne 0) {
        Write-Log '[WARN] Standard n8n install failed. Retrying with --ignore-scripts...' 'Yellow'
        $code = Invoke-Logged $npm (@('install') + $npmArgs + '--ignore-scripts') $N8NHome
    }
    if ($code -ne 0) {
        Write-Log '[WARN] npm install failed - will fall back to npx at launch.' 'Yellow'
        $script:UseNpx = $true
        return $true
    }

    # --- Verify sqlite3 native binding
    Write-Host '[STEP] Verifying n8n installation...' -ForegroundColor Yellow
    $sqlitePath = (Join-Path $N8NHome 'node_modules\sqlite3') -replace '\\', '/'
    $probe      = "require('$sqlitePath'); console.log('ok')"

    Invoke-Logged $script:Node.Exe @('-e', $probe) $N8NHome | Out-Null
    $healthy = ($LASTEXITCODE -eq 0)

    if (-not $healthy) {
        Write-Log '[WARN] sqlite3 has no native binding - attempting rebuild.' 'Yellow'
        $env:npm_config_ignore_scripts = 'false'
        Invoke-Logged $npm @('rebuild', 'sqlite3') $N8NHome | Out-Null
        Invoke-Logged $script:Node.Exe @('-e', $probe) $N8NHome | Out-Null
        $healthy = ($LASTEXITCODE -eq 0)
        if ($healthy) { Write-Log '[INFO] sqlite3 repaired.' 'Green' }
    }

    if (-not $healthy) {
        Write-Log '[ERROR] n8n cannot load sqlite3 and the rebuild failed.' 'Red'
        Write-Host '[ERROR] Usually this means node-gyp had to compile from source.' -ForegroundColor Red
        Write-Host "[FIX]   Install 'Desktop development with C++' via Visual Studio Build" -ForegroundColor Red
        Write-Host '[FIX]   Tools, then re-run: .\AI_JOB_AGENT.ps1 setup' -ForegroundColor Red
        return $false
    }

    Write-Log '[INFO] n8n installed and verified.' 'Green'
    return $true
}

# --------------------------- LAUNCH -----------------------------------------

function Invoke-Launch {
    # Prefer the pinned local install; only fall back to a PATH n8n, then npx.
    $exe = $null
    if (-not $script:UseNpx) {
        $candidates = @(
            $N8NBin,
            (Join-Path $env:APPDATA 'npm\n8n.cmd'),
            (Join-Path $Workspace 'node_modules\.bin\n8n.cmd')
        )
        foreach ($c in $candidates) {
            if ($c -and (Test-Path $c)) { $exe = $c; break }
        }
        if (-not $exe) {
            $onPath = (Get-Command n8n -ErrorAction SilentlyContinue).Source
            if ($onPath) { $exe = $onPath }
        }
    }

    Write-Host ''
    if ($exe) {
        Write-Host "[INFO] Starting n8n from: $exe" -ForegroundColor Cyan
    } else {
        Write-Host '[WARN] n8n not found locally - falling back to npx.' -ForegroundColor Yellow
        Write-Host "[WARN] Run '.\AI_JOB_AGENT.ps1 setup' for a proper install." -ForegroundColor Yellow
    }

    $displayHost = if ($env:N8N_HOST -eq '0.0.0.0') { 'localhost' } else { $env:N8N_HOST }
    Write-Host "[INFO] URL: http://${displayHost}:$($env:N8N_PORT)" -ForegroundColor Cyan
    Write-Host "[INFO] N8N_SECURE_COOKIE=$($env:N8N_SECURE_COOKIE)" -ForegroundColor Cyan
    Write-Host '[INFO] Press Ctrl+C to stop n8n' -ForegroundColor Yellow
    Write-Host ''

    if ($exe) {
        & $exe start
    } else {
        if (-not $script:Node) {
            Write-Host '[ERROR] No Node.js available - cannot launch via npx.' -ForegroundColor Red
            exit 1
        }
        & $script:Node.Npx --yes "n8n@$N8NVersion" start
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] n8n exited with code $LASTEXITCODE. Check setup.log" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# --------------------------- MAIN -------------------------------------------

$UseNpx = $false

if ($Mode -eq 'setup') {
    if (-not (Invoke-Provision)) { exit 1 }

    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Setup completed" |
        Out-File -FilePath $Marker -Encoding utf8
    Write-Log '[INFO] Setup completed.' 'Green'

    $displayHost = if ($env:N8N_HOST -eq '0.0.0.0') { 'localhost' } else { $env:N8N_HOST }
    Write-Host ''
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host ' SETUP COMPLETE' -ForegroundColor Green
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host " Desktop : http://${displayHost}:$($env:N8N_PORT)"
    Write-Host " Laptop  : http://YOUR_DESKTOP_IP:$($env:N8N_PORT)"
    Write-Host " n8n home: $N8NHome"
    Write-Host ' Import  : n8n-job-agent-workflow.json'
    Write-Host ''
    Write-Host ' n8n 1.x does not use N8N_BASIC_AUTH_* - on first launch the browser'
    Write-Host ' will ask you to create an owner account. Credentials are not printed.'
    Write-Host '================================================' -ForegroundColor Cyan
    Write-Host ''
}

Invoke-Launch
