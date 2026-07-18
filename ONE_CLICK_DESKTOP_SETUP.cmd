@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo AI Job Agent - One Click Desktop Setup
echo ================================================
echo.

set "WORKSPACE=%~dp0"
set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOGFILE=%WORKSPACE%\setup.log"

echo [%date% %time%] Setup started > "%LOGFILE%"

call :info "Workspace: %WORKSPACE%"

call :ensure_dir "%WORKSPACE%\data"
call :ensure_dir "%WORKSPACE%\output"
call :ensure_dir "%WORKSPACE%\n8n"
call :ensure_dir "%WORKSPACE%\logs"

call :require_command winget "Microsoft.DesktopAppInstaller"
if errorlevel 1 goto :fail

call :install_if_missing node "OpenJS.NodeJS.LTS"
if errorlevel 1 goto :fail

call :install_if_missing python "Python.Python.3.12"
if errorlevel 1 goto :fail

call :refresh_path

call :require_command node "OpenJS.NodeJS.LTS"
if errorlevel 1 goto :fail

call :require_command npm "OpenJS.NodeJS.LTS"
if errorlevel 1 goto :fail

call :require_command python "Python.Python.3.12"
if errorlevel 1 goto :fail

call :run "node -v"
if errorlevel 1 goto :fail

call :run "npm -v"
if errorlevel 1 goto :fail

call :run "python --version"
if errorlevel 1 goto :fail

call :info "Installing n8n globally"
call :run "npm install -g n8n"
if errorlevel 1 goto :fail

if not exist "%WORKSPACE%\requirements-agent.txt" (
  call :info "Creating requirements-agent.txt"
  > "%WORKSPACE%\requirements-agent.txt" echo langgraph^>=0.2.0
  >> "%WORKSPACE%\requirements-agent.txt" echo openai^>=1.40.0
  >> "%WORKSPACE%\requirements-agent.txt" echo playwright^>=1.50.0
  >> "%WORKSPACE%\requirements-agent.txt" echo pandas^>=2.2.0
  >> "%WORKSPACE%\requirements-agent.txt" echo python-dotenv^>=1.0.0
  >> "%WORKSPACE%\requirements-agent.txt" echo beautifulsoup4^>=4.12.0
  >> "%WORKSPACE%\requirements-agent.txt" echo lxml^>=5.2.0
  >> "%WORKSPACE%\requirements-agent.txt" echo requests^>=2.32.0
)

call :info "Installing Python dependencies"
call :run "python -m pip install --upgrade pip"
if errorlevel 1 goto :fail

call :run "python -m pip install -r \"%WORKSPACE%\requirements-agent.txt\""
if errorlevel 1 goto :fail

call :info "Downloading Playwright browser (Chromium)"
call :run "python -m playwright install chromium"
if errorlevel 1 goto :fail

if not exist "%WORKSPACE%\output\AppliedJobs.csv" (
  call :info "Creating output\AppliedJobs.csv"
  > "%WORKSPACE%\output\AppliedJobs.csv" echo Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes
)

if not exist "%WORKSPACE%\n8n\job-application-agent.workflow.json" (
  call :warn "Workflow file missing: n8n\job-application-agent.workflow.json"
  call :warn "You can still run n8n and import workflow later."
)

call :info "Setting n8n environment for LAN access"
set "N8N_HOST=0.0.0.0"
set "N8N_PORT=5678"
set "N8N_PROTOCOL=http"
set "N8N_SECURE_COOKIE=false"
set "N8N_BASIC_AUTH_ACTIVE=true"
set "N8N_BASIC_AUTH_USER=admin"
set "N8N_BASIC_AUTH_PASSWORD=ChangeThisNow123!"

call :info "Starting n8n in a new window"
start "n8n-server" cmd /k "set N8N_HOST=%N8N_HOST%&& set N8N_PORT=%N8N_PORT%&& set N8N_PROTOCOL=%N8N_PROTOCOL%&& set N8N_SECURE_COOKIE=%N8N_SECURE_COOKIE%&& set N8N_BASIC_AUTH_ACTIVE=%N8N_BASIC_AUTH_ACTIVE%&& set N8N_BASIC_AUTH_USER=%N8N_BASIC_AUTH_USER%&& set N8N_BASIC_AUTH_PASSWORD=%N8N_BASIC_AUTH_PASSWORD%&& n8n"

call :info "Setup completed successfully"
echo.
echo Setup complete.
echo n8n URL on this desktop: http://localhost:5678
echo n8n URL from laptop on same network: http://DESKTOP_IP:5678
echo Username: admin
echo Password: ChangeThisNow123!
echo IMPORTANT: Change password immediately in this file before long-term use.
echo.
echo [%date% %time%] Setup completed successfully >> "%LOGFILE%"
exit /b 0

:install_if_missing
set "CMD_NAME=%~1"
set "WINGET_ID=%~2"
where %CMD_NAME% >nul 2>nul
if %errorlevel%==0 (
  call :info "%CMD_NAME% already installed"
  exit /b 0
)

call :info "Installing %CMD_NAME% using winget (%WINGET_ID%)"
winget install --id "%WINGET_ID%" --accept-source-agreements --accept-package-agreements --silent >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  call :error "Failed to install %CMD_NAME%. Check setup.log"
  exit /b 1
)
exit /b 0

:require_command
set "CMD_NAME=%~1"
where %CMD_NAME% >nul 2>nul
if %errorlevel%==0 exit /b 0
call :error "%CMD_NAME% not found. Install package: %~2"
exit /b 1

:refresh_path
set "PATH=%PATH%;C:\Program Files\nodejs;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%AppData%\npm"
exit /b 0

:ensure_dir
if not exist "%~1" (
  mkdir "%~1" >> "%LOGFILE%" 2>&1
  if errorlevel 1 (
    call :error "Failed to create directory: %~1"
    exit /b 1
  )
)
exit /b 0

:run
set "CMDLINE=%~1"
call :info "Running: %CMDLINE%"
cmd /c %CMDLINE% >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  call :error "Command failed: %CMDLINE%"
  exit /b 1
)
exit /b 0

:info
echo [INFO] %~1
echo [INFO] %~1 >> "%LOGFILE%"
exit /b 0

:warn
echo [WARN] %~1
echo [WARN] %~1 >> "%LOGFILE%"
exit /b 0

:error
echo [ERROR] %~1
echo [ERROR] %~1 >> "%LOGFILE%"
exit /b 0

:fail
echo.
echo Setup failed. Check "%LOGFILE%" for details.
echo [%date% %time%] Setup failed >> "%LOGFILE%"
exit /b 1
