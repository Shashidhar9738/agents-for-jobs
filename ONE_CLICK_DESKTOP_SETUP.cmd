@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo AI Job Agent - One Click Desktop Setup
echo ================================================
echo.

set "WORKSPACE=%~dp0"
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOGFILE=%WORKSPACE%\setup.log"

echo [%date% %time%] Setup started > "%LOGFILE%"

call :info "Workspace: %WORKSPACE%"

call :ensure_dir "%WORKSPACE%\data"
call :ensure_dir "%WORKSPACE%\output"
call :ensure_dir "%WORKSPACE%\n8n"
call :ensure_dir "%WORKSPACE%\logs"

set "WINGET_AVAILABLE=0"
where winget >nul 2>nul
if not errorlevel 1 set "WINGET_AVAILABLE=1"

call :refresh_path

call :require_command node "OpenJS.NodeJS.LTS"
if errorlevel 1 (
  if "%WINGET_AVAILABLE%"=="1" (
    call :install_if_missing node "OpenJS.NodeJS.LTS"
    if errorlevel 1 goto :fail
  ) else (
    call :error "node was not found and winget is unavailable."
    goto :fail
  )
)

call :require_command npm "OpenJS.NodeJS.LTS"
if errorlevel 1 (
  if "%WINGET_AVAILABLE%"=="1" (
    call :install_if_missing node "OpenJS.NodeJS.LTS"
    if errorlevel 1 goto :fail
  ) else (
    call :error "npm was not found and winget is unavailable."
    goto :fail
  )
)

call :resolve_python_command
if not defined PYTHON_CMD (
  if "%WINGET_AVAILABLE%"=="1" (
    call :install_if_missing python "Python.Python.3.12"
    if errorlevel 1 goto :fail
    call :refresh_path
    call :resolve_python_command
  ) else (
    call :error "Python was not found and winget is unavailable."
    goto :fail
  )
)

if not defined PYTHON_CMD (
  call :error "Python command not found after setup."
  goto :fail
)

call :run_command "%PYTHON_CMD%" --version
if errorlevel 1 goto :fail

call :run_command node -v
if errorlevel 1 goto :fail

call :run_command npm -v
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
call :run_command "%PYTHON_CMD%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

call :run_command "%PYTHON_CMD%" -m pip install -r "%WORKSPACE%\requirements-agent.txt"
if errorlevel 1 goto :fail

call :info "Downloading Playwright browser (Chromium)"
call :run_command "%PYTHON_CMD%" -m playwright install chromium
if errorlevel 1 goto :fail

if not exist "%WORKSPACE%\output\AppliedJobs.csv" (
  call :info "Creating output\AppliedJobs.csv"
  > "%WORKSPACE%\output\AppliedJobs.csv" echo Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes
)

if not exist "%WORKSPACE%\n8n\job-application-agent.workflow.json" (
  call :warn "Workflow file missing: n8n\job-application-agent.workflow.json"
  call :warn "You can still run n8n and import workflow later."
)

call :info "Installing n8n"
call :run_command npm install --prefix "%WORKSPACE%\n8n" n8n@1.85.1 --omit=optional --no-audit --no-fund
if errorlevel 1 goto :fail

set "N8N_LOCAL_JS=%WORKSPACE%\n8n\node_modules\n8n\bin\n8n.js"
set "N8N_LOCAL_CMD=%WORKSPACE%\n8n\node_modules\.bin\n8n.cmd"
if not exist "%N8N_LOCAL_JS%" if not exist "%N8N_LOCAL_CMD%" (
  call :error "n8n package did not produce a launcher."
  goto :fail
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
if exist "%N8N_LOCAL_CMD%" (
  start "n8n-server" "%N8N_LOCAL_CMD%" --host=%N8N_HOST% --port=%N8N_PORT%
) else (
  start "n8n-server" node "%N8N_LOCAL_JS%" --host=%N8N_HOST% --port=%N8N_PORT%
)

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
if not errorlevel 1 (
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
if not errorlevel 1 exit /b 0
call :error "%CMD_NAME% not found. Install package: %~2"
exit /b 1

:resolve_python_command
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  exit /b 0
)
where python3 >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python3"
  exit /b 0
)
exit /b 0

:refresh_path
set "PATH=%PATH%;%ProgramFiles%\nodejs;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%LOCALAPPDATA%\Programs\Python\Python310;%LOCALAPPDATA%\Programs\Python\Python310\Scripts;%LOCALAPPDATA%\Programs\Python\Python39;%LOCALAPPDATA%\Programs\Python\Python39\Scripts;%LOCALAPPDATA%\Programs\Python\Python38;%LOCALAPPDATA%\Programs\Python\Python38\Scripts;%LOCALAPPDATA%\Programs\Python\Python37;%LOCALAPPDATA%\Programs\Python\Python37\Scripts;%APPDATA%\npm"
if exist "%ProgramFiles%\Python311" set "PATH=%PATH%;%ProgramFiles%\Python311;%ProgramFiles%\Python311\Scripts"
if exist "%ProgramFiles%\Python310" set "PATH=%PATH%;%ProgramFiles%\Python310;%ProgramFiles%\Python310\Scripts"
if exist "%ProgramFiles%\Python39" set "PATH=%PATH%;%ProgramFiles%\Python39;%ProgramFiles%\Python39\Scripts"
if exist "%ProgramFiles%\Python38" set "PATH=%PATH%;%ProgramFiles%\Python38;%ProgramFiles%\Python38\Scripts"
if exist "%ProgramFiles%\Python37" set "PATH=%PATH%;%ProgramFiles%\Python37;%ProgramFiles%\Python37\Scripts"
if exist "%ProgramFiles%\nodejs" set "PATH=%PATH%;%ProgramFiles%\nodejs"
if exist "%APPDATA%\npm" set "PATH=%PATH%;%APPDATA%\npm"
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

:run_command
set "RUN_CMD=%~1"
shift
call :info "Running: %RUN_CMD% %*"
"%RUN_CMD%" %* >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  call :error "Command failed: %RUN_CMD% %*"
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
