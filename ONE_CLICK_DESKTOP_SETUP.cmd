@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ================================================
echo  AI Job Agent - One Click Desktop Setup
echo ================================================
echo.

set "WORKSPACE=%~dp0"
if "!WORKSPACE:~-1!"=="\" set "WORKSPACE=!WORKSPACE:~0,-1!"
set "LOGFILE=!WORKSPACE!\setup.log"

echo [%date% %time%] Setup started > "!LOGFILE!"
echo [INFO] Workspace: !WORKSPACE!
echo [INFO] Workspace: !WORKSPACE! >> "!LOGFILE!"

for %%D in (data output n8n logs) do (
  if not exist "!WORKSPACE!\%%D" mkdir "!WORKSPACE!\%%D"
)

rem --- Detect Python
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  where python3 >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python3"
)
if not defined PYTHON_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYTHON_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PYTHON_CMD (
  if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
)
if not defined PYTHON_CMD (
  echo [ERROR] Python not found. Install from https://python.org and re-run.
  echo [ERROR] Python not found >> "!LOGFILE!"
  goto :fail
)
echo [INFO] Python: !PYTHON_CMD!
echo [INFO] Python: !PYTHON_CMD! >> "!LOGFILE!"

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

for /f "tokens=*" %%V in ('node -v') do echo [INFO] node %%V
for /f "tokens=*" %%V in ('npm -v') do echo [INFO] npm %%V

rem --- Create requirements file
if not exist "!WORKSPACE!\requirements-agent.txt" (
  echo [INFO] Creating requirements-agent.txt
  echo langgraph^>=0.2.0 > "!WORKSPACE!\requirements-agent.txt"
  echo openai^>=1.40.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo playwright^>=1.50.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo pandas^>=2.2.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo python-dotenv^>=1.0.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo beautifulsoup4^>=4.12.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo lxml^>=5.2.0 >> "!WORKSPACE!\requirements-agent.txt"
  echo requests^>=2.32.0 >> "!WORKSPACE!\requirements-agent.txt"
)

rem --- Upgrade pip
echo.
echo [STEP] Upgrading pip...
!PYTHON_CMD! -m pip install --upgrade pip >> "!LOGFILE!" 2>&1

rem --- Install Python packages
echo [STEP] Installing Python packages...
!PYTHON_CMD! -m pip install -r "!WORKSPACE!\requirements-agent.txt" >> "!LOGFILE!" 2>&1
if errorlevel 1 (
  echo [ERROR] Python package install failed. Check setup.log
  goto :fail
)
echo [INFO] Python packages installed.

rem --- Playwright browser
echo [STEP] Downloading Playwright Chromium...
!PYTHON_CMD! -m playwright install chromium >> "!LOGFILE!" 2>&1
if errorlevel 1 echo [WARN] Playwright download failed - run manually: py -m playwright install chromium

rem --- Install n8n locally
echo [STEP] Installing n8n locally ^(no admin needed^)...
if not exist "!WORKSPACE!\n8n\package.json" (
  pushd "!WORKSPACE!\n8n"
  npm init -y >> "!LOGFILE!" 2>&1
  if errorlevel 1 (
    popd
    echo [ERROR] n8n bootstrap failed. Check setup.log
    goto :fail
  )
  popd
)
pushd "!WORKSPACE!\n8n"
npm install n8n --omit=optional --no-audit --no-fund >> "!LOGFILE!" 2>&1
set "NPM_EXIT=!ERRORLEVEL!"
popd
if not "!NPM_EXIT!"=="0" (
  echo [ERROR] n8n install failed. Check setup.log
  goto :fail
)
if errorlevel 1 (
  echo [ERROR] n8n install failed. Check setup.log
  goto :fail
)
echo [INFO] n8n installed.

rem --- Init CSV
if not exist "!WORKSPACE!\output\AppliedJobs.csv" (
  echo Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes > "!WORKSPACE!\output\AppliedJobs.csv"
)

rem --- Start n8n
echo.
echo [STEP] Starting n8n...
set "N8N_BIN=!WORKSPACE!\n8n\node_modules\.bin\n8n.cmd"
if not exist "!N8N_BIN!" set "N8N_BIN=!WORKSPACE!\n8n\node_modules\n8n\bin\n8n"
if not exist "!N8N_BIN!" (
  echo [ERROR] n8n launcher not found. Check setup.log
  goto :fail
)
start "n8n - AI Job Agent" cmd /k "set N8N_HOST=0.0.0.0 && set N8N_PORT=5678 && set N8N_SECURE_COOKIE=false && set N8N_BASIC_AUTH_ACTIVE=true && set N8N_BASIC_AUTH_USER=admin && set N8N_BASIC_AUTH_PASSWORD=ChangeThisNow123! && call ""!N8N_BIN!"""

echo [%date% %time%] Setup completed >> "!LOGFILE!"
echo.
echo ================================================
echo  SETUP COMPLETE
echo ================================================
echo  Desktop : http://localhost:5678
echo  Laptop  : http://YOUR_DESKTOP_IP:5678
echo  Login   : admin
echo  Password: ChangeThisNow123!
echo  Import  : n8n\job-application-agent.workflow.json
echo ================================================
pause
exit /b 0

:fail
echo.
echo ================================================
echo  SETUP FAILED - check setup.log for details
echo ================================================
echo [%date% %time%] Setup failed >> "!LOGFILE!"
pause
exit /b 1