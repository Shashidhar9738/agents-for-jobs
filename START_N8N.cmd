@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "WORKSPACE=%~dp0"
if "!WORKSPACE:~-1!"=="\" set "WORKSPACE=!WORKSPACE:~0,-1!"
set "N8N_HOME=%LOCALAPPDATA%\AIJobAgent\n8n"
set "N8N_DIR=!N8N_HOME!"
set "LOGFILE=!WORKSPACE!\setup.log"
set "N8N_BIN=!N8N_DIR!\node_modules\.bin\n8n.cmd"

echo [INFO] n8n Startup Script
echo [INFO] Workspace : !WORKSPACE!
echo [INFO] n8n Home  : !N8N_DIR!
echo.

if not exist "!N8N_DIR!" mkdir "!N8N_DIR!"

rem --- Detect a supported Node version (18/20/22). Prefer winget Node 22/20 over system Node 24.
set "NODE_EXE="
set "NPM_EXE="

for %%N in (22 20) do (
  if not defined NODE_EXE (
    for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\OpenJS.NodeJS.%%N_*") do (
      if not defined NODE_EXE (
        for /r "%%P" %%F in (node.exe) do (
          if not defined NODE_EXE set "NODE_EXE=%%F"
        )
      )
    )
  )
)

if not defined NODE_EXE (
  for /f "tokens=*" %%V in ('node -v 2^>nul') do set "SYS_NODE_VER=%%V"
  if "!SYS_NODE_VER:~1,2!"=="18" set "NODE_EXE=node"
  if "!SYS_NODE_VER:~1,2!"=="20" set "NODE_EXE=node"
  if "!SYS_NODE_VER:~1,2!"=="22" set "NODE_EXE=node"
)

if not defined NODE_EXE (
  echo [ERROR] No supported Node.js version found (need 18, 20, or 22).
  echo [ERROR] Your system has Node 24 which is NOT supported by n8n.
  echo [INFO]  Run this in PowerShell to install Node 22:
  echo         winget install --id OpenJS.NodeJS.22 -e --scope user --accept-package-agreements --accept-source-agreements
  echo.
  pause
  exit /b 1
)

echo [INFO] Using node: !NODE_EXE!

rem --- Locate npm for the chosen node
set "NODE_DIR="
for %%F in ("!NODE_EXE!") do set "NODE_DIR=%%~dpF"
set "NODE_DIR=!NODE_DIR:~0,-1!"
set "NPM_CLI=!NODE_DIR!\node_modules\npm\bin\npm-cli.js"
if not exist "!NPM_CLI!" (
  rem Fallback: try npm on PATH
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] npm not found.
    pause
    exit /b 1
  )
  set "NPM_CLI="
)

set "SYSTEM_CMD=C:\Windows\System32\cmd.exe"
set "ComSpec=!SYSTEM_CMD!"
set "npm_config_script_shell=!SYSTEM_CMD!"
set "npm_config_strict_ssl=false"
set "NODE_TLS_REJECT_UNAUTHORIZED=0"

if not exist "!N8N_DIR!\package.json" (
  pushd "!N8N_DIR!"
  if defined NPM_CLI (
    "!NODE_EXE!" "!NPM_CLI!" init -y >> "!LOGFILE!" 2>&1
  ) else (
    npm init -y >> "!LOGFILE!" 2>&1
  )
  popd
)

set "NEEDS_REINSTALL=0"
if not exist "!N8N_BIN!" set "NEEDS_REINSTALL=1"

if "!NEEDS_REINSTALL!"=="1" (
  echo [WARN] n8n not installed. Installing now - this takes 5-10 minutes...
  echo [WARN] n8n not installed. Installing now... >> "!LOGFILE!"

  if exist "!N8N_DIR!\node_modules" rmdir /s /q "!N8N_DIR!\node_modules"
  if exist "!N8N_DIR!\package-lock.json" del /f /q "!N8N_DIR!\package-lock.json"

  pushd "!N8N_DIR!"
  if defined NPM_CLI (
    "!NODE_EXE!" "!NPM_CLI!" install n8n@1.50.0 --legacy-peer-deps --no-audit --no-fund --loglevel=warn >> "!LOGFILE!" 2>&1
  ) else (
    npm install n8n@1.50.0 --legacy-peer-deps --no-audit --no-fund --loglevel=warn >> "!LOGFILE!" 2>&1
  )
  set "NPM_INSTALL_EXIT=!ERRORLEVEL!"
  popd

  if not "!NPM_INSTALL_EXIT!"=="0" (
    echo [ERROR] n8n install failed (exit !NPM_INSTALL_EXIT!). See setup.log for details.
    echo [INFO]  Last 20 lines of setup.log:
    powershell -NoProfile -Command "if(Test-Path '!LOGFILE!'){Get-Content '!LOGFILE!' -Tail 20}else{'(log not found)'}"
    echo.
    pause
    exit /b 1
  )
)

if not exist "!N8N_BIN!" (
  echo [ERROR] n8n launcher not found at: !N8N_BIN!
  echo [INFO]  Last 20 lines of setup.log:
  powershell -NoProfile -Command "if(Test-Path '!LOGFILE!'){Get-Content '!LOGFILE!' -Tail 20}else{'(log not found)'}"
  echo.
  pause
  exit /b 1
)

echo [INFO] Starting n8n on http://localhost:5678
echo [INFO] n8n home: !N8N_DIR!
echo.

start "n8n - AI Job Agent" cmd /k "^"!NODE_EXE!^" ^"!N8N_DIR!\node_modules\n8n\bin\n8n^" --tunnel=false & echo n8n started & echo Open http://localhost:5678"

echo [INFO] n8n window opened.
echo [INFO] Wait ~30 seconds then open: http://localhost:5678
echo [INFO] Login: admin / ChangeThisNow123!
echo.
pause
exit /b 0
