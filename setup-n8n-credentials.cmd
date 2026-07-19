@echo off
rem ---------------------------------------------------------------------------
rem n8n Credentials Setup Helper (Windows batch)
rem
rem Prompts for the workflow credentials and MERGES them into .env. Existing
rem keys this script does not manage (vault key, API tokens, OpenRouter key)
rem are preserved, and a timestamped backup is taken before any write.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "WORKSPACE=%~dp0"
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "ENVFILE=%WORKSPACE%\.env"
set "ENVTMP=%WORKSPACE%\.env.tmp"

rem Keys this script owns and will rewrite. Kept out of the IF block below
rem because an unescaped ')' inside a parenthesized block confuses the parser.
set "MANAGED=(OPENAI_API_KEY|MINIMUM_MATCH_SCORE|NOTIFICATION_EMAIL|GMAIL_CLIENT_ID|GMAIL_CLIENT_SECRET|GMAIL_REFRESH_TOKEN)="

echo.
echo ========================================
echo  N8N Credentials Setup Helper
echo ========================================
echo.

if exist "%ENVFILE%" (
  echo [INFO] Existing .env found. It will be merged, not overwritten.
  echo [INFO] Keys this script manages get replaced; everything else is kept.
) else (
  echo [INFO] No .env yet - a new one will be created.
)
echo.
set "CONFIRM="
set /p CONFIRM="Continue? [y/N]: "
if /i not "%CONFIRM%"=="y" (
  echo [INFO] Cancelled. Nothing was changed.
  goto :end
)

rem --- Step 1: OpenAI API key
echo.
echo [STEP 1] OpenAI API Key
echo ==============================
echo Get your API key from: https://platform.openai.com/api-keys
set "OPENAI_KEY="
set /p OPENAI_KEY="Enter your OpenAI API Key (sk-proj-...): "

if not defined OPENAI_KEY (
  echo [ERROR] OpenAI API Key is required. Exiting.
  goto :end
)

rem --- Step 2: Gmail (optional)
echo.
echo [STEP 2] Gmail Notification Setup (Optional)
echo ============================================
set "GMAIL_EMAIL="
set /p GMAIL_EMAIL="Enter your Gmail address (leave empty to skip): "

if defined GMAIL_EMAIL (
  echo.
  echo To set up Gmail OAuth2:
  echo 1. Go to: https://console.cloud.google.com
  echo 2. Create a new project
  echo 3. Enable Gmail API
  echo 4. Create OAuth 2.0 Credentials ^(Desktop app^)
  echo 5. Download credentials.json
  echo.
  set "GMAIL_CLIENT_ID="
  set "GMAIL_CLIENT_SECRET="
  set "GMAIL_REFRESH_TOKEN="
  set /p GMAIL_CLIENT_ID="Enter Gmail Client ID: "
  set /p GMAIL_CLIENT_SECRET="Enter Gmail Client Secret: "
  set /p GMAIL_REFRESH_TOKEN="Enter Gmail Refresh Token: "
)

rem --- Step 3: Merge into .env
echo.
echo [STEP 3] Saving Configuration
echo ============================

if exist "%ENVFILE%" (
  copy /y "%ENVFILE%" "%ENVFILE%.bak" >nul
  echo [INFO] Backup written to .env.bak

  rem Strip the keys we are about to rewrite. Names and paths travel via
  rem environment variables, not argv, so no secret is exposed in the process
  rem command line.
  rem WriteAllLines with UTF8Encoding($false), not Set-Content -Encoding utf8:
  rem PowerShell 5.1 emits a BOM, which would corrupt the first key on load.
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$keep = Get-Content -LiteralPath $env:ENVFILE | Where-Object { $_ -notmatch ('^' + $env:MANAGED) }; [System.IO.File]::WriteAllLines($env:ENVTMP, $keep, (New-Object System.Text.UTF8Encoding($false)))"
  if errorlevel 1 (
    echo [ERROR] Could not rewrite .env - original left untouched.
    goto :end
  )
  move /y "%ENVTMP%" "%ENVFILE%" >nul
) else (
  echo # Local n8n + workflow configuration> "%ENVFILE%"
  echo # This file is gitignored and stays on your machine>> "%ENVFILE%"
)

>>"%ENVFILE%" echo.
>>"%ENVFILE%" echo OPENAI_API_KEY=%OPENAI_KEY%
>>"%ENVFILE%" echo MINIMUM_MATCH_SCORE=80
if defined GMAIL_EMAIL (
  >>"%ENVFILE%" echo NOTIFICATION_EMAIL=%GMAIL_EMAIL%
  >>"%ENVFILE%" echo GMAIL_CLIENT_ID=%GMAIL_CLIENT_ID%
  >>"%ENVFILE%" echo GMAIL_CLIENT_SECRET=%GMAIL_CLIENT_SECRET%
  >>"%ENVFILE%" echo GMAIL_REFRESH_TOKEN=%GMAIL_REFRESH_TOKEN%
)

echo [SUCCESS] Configuration merged into .env

rem --- Step 4: Open n8n dashboard
echo.
echo [STEP 4] Opening n8n Dashboard
echo =============================
if not defined N8N_PORT set "N8N_PORT=5678"
echo Opening http://localhost:%N8N_PORT% ...
start "" "http://localhost:%N8N_PORT%"

echo.
echo [INFO] Next steps:
echo 1. Sign in to n8n with your owner account
echo    ^(n8n 1.x creates this in the browser on first launch^)
echo 2. Go to Credentials in the sidebar
echo 3. Create credentials:
echo    - OpenAI API
echo    - Gmail OAuth2 ^(if configured^)
echo    - File System
echo 4. Import workflow: n8n-job-agent-workflow.json
echo 5. Activate and test the workflow
echo.

:end
pause
endlocal
