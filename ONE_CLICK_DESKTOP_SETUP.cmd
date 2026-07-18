@echo off
rem Delayed expansion is deliberately NOT enabled: it eats '!' in passwords and
rem other values loaded from .env. Blocks that would need it use subroutines.
setlocal
cd /d "%~dp0"

echo ================================================
echo  AI Job Agent - One Click Desktop Setup
echo ================================================
echo.

set "WORKSPACE=%~dp0"
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOGFILE=%WORKSPACE%\setup.log"
set "ENVFILE=%WORKSPACE%\.env"
set "N8N_HOME=%LOCALAPPDATA%\AIJobAgent\n8n"

echo [%date% %time%] Setup started > "%LOGFILE%"
echo [INFO] Workspace: %WORKSPACE%
echo [INFO] Workspace: %WORKSPACE% >> "%LOGFILE%"

rem --- Load configuration (never hardcode credentials in this file)
if not exist "%ENVFILE%" (
  echo [ERROR] No .env found at %ENVFILE%
  echo [ERROR] Copy .env.example to .env and fill it in, then re-run.
  goto :fail
)
call "%WORKSPACE%\load-env.cmd" "%ENVFILE%"
if errorlevel 1 (
  echo [ERROR] Failed to load %ENVFILE%
  goto :fail
)
if not defined N8N_PORT set "N8N_PORT=5678"
if not defined N8N_HOST set "N8N_HOST=0.0.0.0"

for %%D in (data output logs) do (
  if not exist "%WORKSPACE%\%%D" mkdir "%WORKSPACE%\%%D"
)
if not exist "%N8N_HOME%" mkdir "%N8N_HOME%"

rem --- Detect Python
set "PYTHON_CMD="
call :find_cmd py
call :find_cmd python
call :find_cmd python3
if not defined PYTHON_CMD call :find_python_exe "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON_CMD call :find_python_exe "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON_CMD call :find_python_exe "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON_CMD (
  echo [ERROR] Python not found. Install from https://python.org and re-run.
  echo [ERROR] Python not found >> "%LOGFILE%"
  goto :fail
)
echo [INFO] Python: %PYTHON_CMD%
echo [INFO] Python: %PYTHON_CMD% >> "%LOGFILE%"

rem --- Detect Node and npm
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found. Download from https://nodejs.org and re-run.
  goto :fail
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Re-install Node.js from https://nodejs.org
  goto :fail
)

set "SYSTEM_CMD=%SystemRoot%\System32\cmd.exe"
if not exist "%SYSTEM_CMD%" set "SYSTEM_CMD=C:\Windows\System32\cmd.exe"
if not exist "%SYSTEM_CMD%" (
  echo [ERROR] Could not find cmd.exe at expected system paths.
  goto :fail
)
set "ComSpec=%SYSTEM_CMD%"
set "npm_config_script_shell=%SYSTEM_CMD%"

for /f "tokens=*" %%V in ('node -v') do echo [INFO] node %%V
for /f "tokens=*" %%V in ('npm -v') do echo [INFO] npm %%V

rem --- Create requirements file
if not exist "%WORKSPACE%\requirements-agent.txt" (
  echo [INFO] Creating requirements-agent.txt
  echo langgraph^>=0.2.0 > "%WORKSPACE%\requirements-agent.txt"
  echo openai^>=1.40.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo playwright^>=1.50.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo pandas^>=2.2.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo python-dotenv^>=1.0.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo beautifulsoup4^>=4.12.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo lxml^>=5.2.0 >> "%WORKSPACE%\requirements-agent.txt"
  echo requests^>=2.32.0 >> "%WORKSPACE%\requirements-agent.txt"
)

rem --- Upgrade pip
echo.
echo [STEP] Upgrading pip...
%PYTHON_CMD% -m pip install --upgrade pip >> "%LOGFILE%" 2>&1

rem --- Install Python packages
echo [STEP] Installing Python packages...
%PYTHON_CMD% -m pip install -r "%WORKSPACE%\requirements-agent.txt" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [ERROR] Python package install failed. Check setup.log
  goto :fail
)
echo [INFO] Python packages installed.

rem --- Playwright browser
echo [STEP] Downloading Playwright Chromium...
%PYTHON_CMD% -m playwright install chromium >> "%LOGFILE%" 2>&1
if errorlevel 1 echo [WARN] Playwright download failed - run manually: py -m playwright install chromium

rem --- Install n8n in user profile (outside repository)
echo [STEP] Installing n8n in user profile ^(no admin needed^)...
set "N8N_BIN=%N8N_HOME%\node_modules\.bin\n8n.cmd"

rem npm is npm.cmd, a batch file: without CALL it never returns to this script.
if not exist "%N8N_HOME%\package.json" (
  pushd "%N8N_HOME%"
  call npm init -y >> "%LOGFILE%" 2>&1
  if errorlevel 1 (
    popd
    echo [ERROR] n8n bootstrap failed. Check setup.log
    goto :fail
  )
  popd
)

set "NEEDS_REINSTALL=0"
if not exist "%N8N_BIN%" set "NEEDS_REINSTALL=1"
if "%NEEDS_REINSTALL%"=="0" call :check_n8n_pkg

if "%NEEDS_REINSTALL%"=="1" (
  echo [WARN] Incomplete or broken n8n install detected. Reinstalling...
  echo [WARN] Incomplete or broken n8n install detected. Reinstalling... >> "%LOGFILE%"
  if exist "%N8N_HOME%\node_modules" rmdir /s /q "%N8N_HOME%\node_modules"
  if exist "%N8N_HOME%\package-lock.json" del /f /q "%N8N_HOME%\package-lock.json"
)

pushd "%N8N_HOME%"
call npm install n8n --legacy-peer-deps --omit=optional --no-audit --no-fund >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [WARN] Standard n8n install failed. Retrying with ignore-scripts fallback... >> "%LOGFILE%"
  call npm install n8n --legacy-peer-deps --omit=optional --no-audit --no-fund --ignore-scripts >> "%LOGFILE%" 2>&1
)
if errorlevel 1 (
  popd
  echo [ERROR] n8n install failed. Check setup.log
  goto :fail
)
popd

if not exist "%N8N_BIN%" (
  echo [ERROR] n8n launcher not found after install. Check setup.log
  goto :fail
)
echo [INFO] n8n installed.

rem Application trackers (output\<candidate>\AppliedJobs.csv) are created by the
rem pipeline from config\workspace.json - do not duplicate the schema here.

rem --- Start n8n
echo.
echo [STEP] Starting n8n...
if not exist "%N8N_BIN%" set "N8N_BIN=%N8N_HOME%\node_modules\n8n\bin\n8n"
if not exist "%N8N_BIN%" (
  echo [ERROR] n8n launcher not found. Check setup.log
  goto :fail
)

rem The child window inherits this process's environment, so credentials never
rem appear on a command line. Quoting a nested command in `cmd /k "..."` is not
rem reliable, so hand it a one-line launcher instead.
set "LAUNCHER=%N8N_HOME%\start-n8n.cmd"
> "%LAUNCHER%" echo @echo off
>>"%LAUNCHER%" echo call "%N8N_BIN%"
>>"%LAUNCHER%" echo pause
start "n8n - AI Job Agent" "%SYSTEM_CMD%" /k "%LAUNCHER%"

echo [%date% %time%] Setup completed >> "%LOGFILE%"
echo.
echo ================================================
echo  SETUP COMPLETE
echo ================================================
echo  Desktop : http://localhost:%N8N_PORT%
echo  Laptop  : http://YOUR_DESKTOP_IP:%N8N_PORT%
echo  n8n home: %N8N_HOME%
echo  Import  : n8n\job-application-agent.workflow.json
echo.
echo  n8n 1.x does not use N8N_BASIC_AUTH_* - on first launch the browser
echo  will ask you to create an owner account. Credentials are not printed.
echo ================================================
pause
exit /b 0

rem --------------------------- subroutines -----------------------------------

:find_cmd
if defined PYTHON_CMD goto :eof
where %1 >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=%1"
goto :eof

:find_python_exe
if exist "%~1" set "PYTHON_CMD=%~1"
goto :eof

:check_n8n_pkg
pushd "%N8N_HOME%"
call npm ls n8n --depth=0 >nul 2>&1
if errorlevel 1 set "NEEDS_REINSTALL=1"
popd
goto :eof

:fail
echo.
echo ================================================
echo  SETUP FAILED - check setup.log for details
echo ================================================
echo [%date% %time%] Setup failed >> "%LOGFILE%"
pause
exit /b 1
