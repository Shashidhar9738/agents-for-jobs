@echo off
REM N8N Credentials Setup Helper (Windows PowerShell)
REM This script guides you through setting up all credentials for the job application workflow

echo.
echo ========================================
echo N8N Credentials Setup Helper
echo ========================================
echo.

REM Check if n8n is running
echo [INFO] Checking if n8n is running...
timeout /t 2 /nobreak

set N8N_URL=http://localhost:5678
set N8N_USER=admin
set N8N_PASS=ChangeThisNow123!

REM Step 1: Get OpenAI API Key
echo.
echo [STEP 1] OpenAI API Key
echo ==============================
echo Get your API key from: https://platform.openai.com/api-keys
set /p OPENAI_KEY="Enter your OpenAI API Key (sk-proj-...): "

if "%OPENAI_KEY%"=="" (
    echo [ERROR] OpenAI API Key is required. Exiting.
    exit /b 1
)

REM Step 2: Gmail Setup (Optional)
echo.
echo [STEP 2] Gmail Notification Setup (Optional)
echo ============================================
set /p GMAIL_EMAIL="Enter your Gmail address (leave empty to skip): "

if not "%GMAIL_EMAIL%"=="" (
    echo.
    echo To set up Gmail OAuth2:
    echo 1. Go to: https://console.cloud.google.com
    echo 2. Create a new project
    echo 3. Enable Gmail API
    echo 4. Create OAuth 2.0 Credentials (Desktop app)
    echo 5. Download credentials.json
    echo.
    set /p GMAIL_CLIENT_ID="Enter Gmail Client ID: "
    set /p GMAIL_CLIENT_SECRET="Enter Gmail Client Secret: "
    set /p GMAIL_REFRESH_TOKEN="Enter Gmail Refresh Token: "
)

REM Step 3: Save to .env file
echo.
echo [STEP 3] Saving Configuration
echo ============================
(
    echo # Auto-generated n8n configuration
    echo OPENAI_API_KEY=%OPENAI_KEY%
    echo MINIMUM_MATCH_SCORE=80
    if not "%GMAIL_EMAIL%"=="" (
        echo NOTIFICATION_EMAIL=%GMAIL_EMAIL%
        echo GMAIL_CLIENT_ID=%GMAIL_CLIENT_ID%
        echo GMAIL_CLIENT_SECRET=%GMAIL_CLIENT_SECRET%
        echo GMAIL_REFRESH_TOKEN=%GMAIL_REFRESH_TOKEN%
    )
    echo N8N_USER=admin
    echo N8N_PASSWORD=ChangeThisNow123!
    echo N8N_HOST=0.0.0.0
    echo N8N_PORT=5678
) > .env

echo [SUCCESS] Configuration saved to .env

REM Step 4: Open n8n dashboard
echo.
echo [STEP 4] Opening n8n Dashboard
echo =============================
echo Starting n8n interface in browser...
timeout /t 2 /nobreak

start http://localhost:5678

echo.
echo [INFO] Next steps:
echo 1. Login to n8n: admin / ChangeThisNow123!
echo 2. Go to Credentials in the sidebar
echo 3. Create credentials:
echo    - OpenAI API
echo    - Gmail OAuth2 (if configured)
echo    - File System
echo 4. Import workflow: n8n-job-agent-workflow.json
echo 5. Activate and test the workflow
echo.

pause
