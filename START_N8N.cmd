@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "WORKSPACE=%~dp0"
if "!WORKSPACE:~-1!"=="\" set "WORKSPACE=!WORKSPACE:~0,-1!"
set "N8N_HOME=%LOCALAPPDATA%\AIJobAgent\n8n"
set "N8N_DIR=!N8N_HOME!"
set "LOGFILE=!WORKSPACE!\setup.log"
set "N8N_BIN=!N8N_DIR!\node_modules\.bin\n8n.cmd"

if not exist "!N8N_DIR!" mkdir "!N8N_DIR!"

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install Node.js and retry.
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Re-install Node.js and retry.
  exit /b 1
)

set "SYSTEM_CMD=%SystemRoot%\System32\cmd.exe"
if not exist "!SYSTEM_CMD!" set "SYSTEM_CMD=C:\Windows\System32\cmd.exe"
if not exist "!SYSTEM_CMD!" (
  echo [ERROR] Could not find cmd.exe at expected system paths.
  exit /b 1
)
set "ComSpec=!SYSTEM_CMD!"
set "npm_config_script_shell=!SYSTEM_CMD!"

if not exist "!N8N_DIR!\package.json" (
  pushd "!N8N_DIR!"
  npm init -y >> "!LOGFILE!" 2>&1
  if errorlevel 1 (
    popd
    echo [ERROR] Failed to bootstrap n8n folder. Check setup.log.
    exit /b 1
  )
  popd
)

set "NEEDS_REINSTALL=0"
if not exist "!N8N_BIN!" set "NEEDS_REINSTALL=1"

if "!NEEDS_REINSTALL!"=="0" (
  pushd "!N8N_DIR!"
  npm ls n8n --depth=0 >nul 2>&1
  set "NPM_LS_EXIT=!ERRORLEVEL!"
  popd
  if not "!NPM_LS_EXIT!"=="0" set "NEEDS_REINSTALL=1"
)

if "!NEEDS_REINSTALL!"=="1" (
  echo [WARN] Incomplete or broken n8n install detected. Reinstalling cleanly...
  echo [WARN] Incomplete or broken n8n install detected. Reinstalling cleanly... >> "!LOGFILE!"

  if exist "!N8N_DIR!\node_modules" rmdir /s /q "!N8N_DIR!\node_modules"
  if exist "!N8N_DIR!\package-lock.json" del /f /q "!N8N_DIR!\package-lock.json"

  if not exist "!N8N_DIR!\package.json" (
    pushd "!N8N_DIR!"
    npm init -y >> "!LOGFILE!" 2>&1
    set "NPM_INIT_EXIT=!ERRORLEVEL!"
    popd
    if not "!NPM_INIT_EXIT!"=="0" (
      echo [ERROR] Failed to initialize package.json. Check setup.log.
      exit /b 1
    )
  )

  echo [INFO] Installing n8n in !N8N_DIR!. This may take a few minutes.
  pushd "!N8N_DIR!"
  npm install n8n --legacy-peer-deps --omit=optional --no-audit --no-fund >> "!LOGFILE!" 2>&1
  set "NPM_INSTALL_EXIT=!ERRORLEVEL!"
  if not "!NPM_INSTALL_EXIT!"=="0" (
    echo [WARN] Standard install failed. Retrying with ignore-scripts fallback... >> "!LOGFILE!"
    npm install n8n --legacy-peer-deps --omit=optional --no-audit --no-fund --ignore-scripts >> "!LOGFILE!" 2>&1
    set "NPM_INSTALL_EXIT=!ERRORLEVEL!"
  )
  popd

  if not "!NPM_INSTALL_EXIT!"=="0" (
    echo [ERROR] n8n install failed. Check setup.log.
    exit /b 1
  )
)

if not exist "!N8N_BIN!" (
  echo [ERROR] n8n launcher not found after reinstall. Check setup.log.
  exit /b 1
)

echo [INFO] Starting n8n on http://localhost:5678
echo [INFO] n8n home: !N8N_DIR!
start "n8n - AI Job Agent" cmd /k "set N8N_HOST=0.0.0.0 && set N8N_PORT=5678 && set N8N_SECURE_COOKIE=false && set N8N_BASIC_AUTH_ACTIVE=true && set N8N_BASIC_AUTH_USER=admin && set N8N_BASIC_AUTH_PASSWORD=ChangeThisNow123! && call ""!N8N_BIN!"""

echo [INFO] Done. Open http://localhost:5678
exit /b 0
