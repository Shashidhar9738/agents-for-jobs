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
echo [INFO] Workspace: !WORKSPACE! >> "!LOGFILE!"
echo [INFO] Workspace: !WORKSPACE!

rem --- Create required folders
for %%D in (data output n8n logs) do (
  if not exist "!WORKSPACE!\%%D" mkdir "!WORKSPACE!\%%D" 2>>"!LOGFILE!"
)

rem --- Detect Python (py launcher, python, python3, or full paths)
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
  for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
  ) do (
    if not defined PYTHON_CMD if exist %%P set "PYTHON_CMD=%%~P"
  )
)
if not defined PYTHON_CMD (
  echo [ERROR] Python not found. Install from https://python.org and re-run.
  echo [ERROR] Python not found >> "!LOGFILE!"
  goto :fail
)
echo [INFO] Python: !PYTHON_CMD!
echo [INFO] Python: !PYTHON_CMD! >> "!LOGFILE!"

rem --- Detect Node / npm
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found. Download from https://nodejs.org and re-run.
  echo [ERROR] Node.js not found >> "!LOGFILE!"
  goto :fail
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js from https://nodejs.org and re-run.
  echo [ERROR] npm not found >> "!LOGFILE!"
  goto :fail
)

for /f "tokens=*" %%V in ('node -v') do ( echo [INFO] node %%V & echo [INFO] node %%V >> "!LOGFILE!" )
for /f "tokens=*" %%V in ('npm -v') do ( echo [INFO] npm %%V & echo [INFO] npm %%V >> "!LOGFILE!" )
for /f "tokens=*" %%V in ('!PYTHON_CMD! --version') do ( echo [INFO] %%V & echo [INFO] %%V >> "!LOGFILE!" )

rem --- Create requirements file if missing
if not exist "!WORKSPACE!\requirements-agent.txt" (
  echo [INFO] Creating requirements-agent.txt
  >>>"!WORKSPACE!\requirements-agent.txt" echo langgraph>=0.2.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo openai>=1.40.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo playwright>=1.50.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo pandas>=2.2.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo python-dotenv>=1.0.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo beautifulsoup4>=4.12.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo lxml>=5.2.0
  >>>"!WORKSPACE!\requirements-agent.txt" echo requests>=2.32.0
)

rem --- Upgrade pip
echo [STEP] Upgrading pip...
echo [STEP] Upgrading pip >> "!LOGFILE!"
!PYTHON_CMD! -m pip install --upgrade pip >> "!LOGFILE!" 2>&1

rem --- Install Python packages
echo [STEP] Installing Python packages...
echo [STEP] Installing Python packages >> "!LOGFILE!"
!PYTHON_CMD! -m pip install -r "!WORKSPACE!\requirements-agent.txt" >> "!LOGFILE!" 2>&1
if errorlevel 1 (
  echo [ERROR] Python package install failed. Check setup.log
  echo [ERROR] Python package install failed >> "!LOGFILE!"
  goto :fail
)
echo [INFO] Python packages installed.
echo [INFO] Python packages installed >> "!LOGFILE!"

rem --- Playwright browser
echo [STEP] Downloading Playwright Chromium browser...
echo [STEP] Downloading Playwright Chromium >> "!LOGFILE!"
!PYTHON_CMD! -m playwright install chromium >> "!LOGFILE!" 2>&1
if errorlevel 1 ( echo [WARN] Playwright download failed - run manually: python -m playwright install chromium )

rem --- Install n8n locally (no admin rights needed)
echo [STEP] Installing n8n (local, no admin required)...
echo [STEP] Installing n8n >> "!LOGFILE!"
npm install --prefix "!WORKSPACE!\n8n" n8n --omit=optional --no-audit --no-fund >> "!LOGFILE!" 2>&1
if errorlevel 1 (
  echo [ERROR] n8n install failed. Check setup.log
  echo [ERROR] n8n install failed >> "!LOGFILE!"
  goto :fail
)
echo [INFO] n8n installed.
echo [INFO] n8n installed >> "!LOGFILE!"

rem --- Init tracker CSV
if not exist "!WORKSPACE!\output\AppliedJobs.csv" (
  echo Date,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes > "!WORKSPACE!\output\AppliedJobs.csv"
  echo [INFO] Created AppliedJobs.csv
)

rem --- Start n8n
echo [STEP] Starting n8n in a new window...
echo [STEP] Starting n8n >> "!LOGFILE!"
set "N8N_BIN=!WORKSPACE!\n8n\node_modules\.bin\n8n.cmd"
if not exist "!N8N_BIN!" set "N8N_BIN=!WORKSPACE!\n8n\node_modules\n8n\bin\n8n"
start "n8n - AI Job Agent" cmd /k "cd /d \"!WORKSPACE!\" && set N8N_HOST=0.0.0.0&& set N8N_PORT=5678&& set N8N_PROTOCOL=http&& set N8N_SECURE_COOKIE=false&& set N8N_BASIC_AUTH_ACTIVE=true&& set N8N_BASIC_AUTH_USER=admin&& set N8N_BASIC_AUTH_PASSWORD=ChangeThisNow123!&& \"!N8N_BIN!\""

echo [%date% %time%] Setup completed successfully >> "!LOGFILE!"
echo.
echo ================================================
echo  SETUP COMPLETE
echo ================================================
echo  n8n is starting in a new window.
echo.
echo  Desktop URL : http://localhost:5678
echo  Laptop URL  : http://YOUR_DESKTOP_IP:5678
echo.
echo  Login    : admin
echo  Password : ChangeThisNow123!
echo.
echo  Import workflow from:
echo  n8n\job-application-agent.workflow.json
echo ================================================
pause
exit /b 0

:fail
echo.
echo ================================================
echo  SETUP FAILED
echo  Check setup.log in this folder for details.
echo ================================================
echo [%date% %time%] Setup failed >> "!LOGFILE!"
pause
exit /b 1
