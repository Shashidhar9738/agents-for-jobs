@echo off
rem Run n8n on this machine for development.
rem
rem .env targets the desktop host (192.168.29.100), so the URLs are overridden
rem here to localhost. Nothing in .env is modified, which keeps the desktop
rem configuration intact when the repo is pushed.

setlocal
cd /d "%~dp0.."

set "N8N_HOST=127.0.0.1"
set "N8N_PORT=5678"
set "N8N_PROTOCOL=http"
set "WEBHOOK_URL=http://localhost:5678/"
set "N8N_EDITOR_BASE_URL=http://localhost:5678/"
set "N8N_SECURE_COOKIE=false"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N_RUNNERS_ENABLED=true"

rem Keep local workflow data separate from the desktop instance.
set "N8N_USER_FOLDER=%LOCALAPPDATA%\AIJobAgent\n8n-local"
if not exist "%N8N_USER_FOLDER%" mkdir "%N8N_USER_FOLDER%"

echo.
echo  n8n (local dev)
echo  ---------------------------------------------
echo   editor    : http://localhost:5678
echo   data dir  : %N8N_USER_FOLDER%
echo   pipeline  : http://localhost:8800  (run serve_dashboard.py too)
echo  ---------------------------------------------
echo.

n8n start

endlocal
