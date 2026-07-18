@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "WORKSPACE=%~dp0"
if "!WORKSPACE:~-1!"=="\" set "WORKSPACE=!WORKSPACE:~0,-1!"
set "N8N_HOME=%LOCALAPPDATA%\AIJobAgent\n8n"
set "LOGFILE=!WORKSPACE!\setup.log"
set "N8N_BIN=!N8N_HOME!\node_modules\.bin\n8n.cmd"

echo.
echo [INFO] ========== n8n Startup Script ==========
echo [INFO] Workspace: !WORKSPACE!
echo [INFO] n8n Home : !N8N_HOME!
echo [INFO] Log File : !LOGFILE!
echo [INFO] ==========================================
echo.

if not exist "!N8N_HOME!" mkdir "!N8N_HOME!"

rem --- Detect a supported Node version (22 or 20)
set "NODE_EXE="

for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_*") do (
  if exist "%%P\node-v22.23.1-win-x64\node.exe" (
    set "NODE_EXE=%%P\node-v22.23.1-win-x64\node.exe"
    goto :found_node
  )
)

for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\OpenJS.NodeJS.20_*") do (
  if exist "%%P\node-v20.20.2-win-x64\node.exe" (
    set "NODE_EXE=%%P\node-v20.20.2-win-x64\node.exe"
    goto :found_node
  )
)

:found_node

if not defined NODE_EXE (
  for /f "tokens=*" %%V in ('node -v 2^>nul') do set "SYS_NODE=%%V"
  if "!SYS_NODE!"=="v18" set "NODE_EXE=node"
  if "!SYS_NODE!"=="v20" set "NODE_EXE=node"
  if "!SYS_NODE!"=="v22" set "NODE_EXE=node"
)

if not defined NODE_EXE (
  echo.
  echo [ERROR] No supported Node.js found. System has: !SYS_NODE! (need 18, 20, or 22^)
  echo.
  echo [FIX] Install Node 22:
  echo   winget install --id OpenJS.NodeJS.22 -e --scope user --accept-package-agreements --accept-source-agreements
  echo.
  pause
  exit /b 1
)

echo [INFO] Using node: !NODE_EXE!
"!NODE_EXE!" -v

set "SYSTEM_CMD=C:\Windows\System32\cmd.exe"
set "ComSpec=!SYSTEM_CMD!"
set "npm_config_script_shell=!SYSTEM_CMD!"

if not exist "!N8N_HOME!\package.json" (
  echo [INFO] Initializing n8n folder...
  pushd "!N8N_HOME!"
  "!NODE_EXE!" -e "require('fs').writeFileSync('package.json', JSON.stringify({name:'n8n',version:'1.0.0',private:true}, null, 2))"
  popd
)

set "NEEDS_INSTALL=0"
if not exist "!N8N_BIN!" set "NEEDS_INSTALL=1"
if not exist "!N8N_HOME!\node_modules\n8n" set "NEEDS_INSTALL=1"

if "!NEEDS_INSTALL!"=="1" (
  echo.
  echo [INFO] Installing n8n v1.50.0...
  echo [INFO] This takes 5-15 minutes. Logs: !LOGFILE!
  echo.

  if exist "!N8N_HOME!\node_modules" (
    echo [INFO] Removing old node_modules...
    rmdir /s /q "!N8N_HOME!\node_modules"
  )
  if exist "!N8N_HOME!\package-lock.json" del /f /q "!N8N_HOME!\package-lock.json"

  pushd "!N8N_HOME!"
  set "npm_config_strict_ssl=false"
  set "NODE_TLS_REJECT_UNAUTHORIZED=0"

  npm install n8n@1.50.0 --legacy-peer-deps --no-audit --no-fund --loglevel=warn >>!LOGFILE! 2>&1
  set "INSTALL_EXIT=!ERRORLEVEL!"
  popd

  if not "!INSTALL_EXIT!"=="0" (
    echo.
    echo [ERROR] n8n install failed. Last 30 lines:
    echo.
    if exist "!LOGFILE!" (
      powershell -NoProfile -Command "Get-Content '!LOGFILE!' -Tail 30"
    ) else (
      echo (log file not found at !LOGFILE!^)
    )
    echo.
    pause
    exit /b 1
  )
)

if not exist "!N8N_BIN!" (
  echo.
  echo [ERROR] n8n launcher not found at: !N8N_BIN!
  echo [INFO] Try: delete !N8N_HOME! and run this script again
  echo.
  pause
  exit /b 1
)

echo.
echo [INFO] Starting n8n...
echo [INFO] URL    : http://192.168.29.164:5678/
echo [INFO] URL    : http://localhost:5678
echo [INFO] User   : Shashi.shashi727@gmail.com
echo [INFO] Pass   : Aishu@@9738082343
echo [INFO] Close this window to stop n8n
echo.

cd /d "!N8N_HOME!"
set "N8N_HOST=0.0.0.0"
set "N8N_PORT=5678"
set "N8N_SECURE_COOKIE=false"
set "N8N_BASIC_AUTH_ACTIVE=true"
set "N8N_EDITOR_BASE_URL=http://192.168.29.164:5678/"
set "WEBHOOK_URL=http://192.168.29.164:5678/"
set "N8N_BASIC_AUTH_USER=Shashi.shashi727@gmail.com"
set "N8N_BASIC_AUTH_PASSWORD=Aishu@@9738082343"

call "!N8N_BIN!"
pause
exit /b 0
