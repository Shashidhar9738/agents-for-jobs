@echo off
rem ===========================================================================
rem  AI Job Agent - provision and launch
rem
rem  Double-click this file. It works out what needs doing:
rem    first run  -> installs Python deps, Playwright, Node, n8n; then launches
rem    later runs -> launches n8n straight away
rem
rem  Explicit modes:
rem    AI_JOB_AGENT.cmd setup   force a full re-provision
rem    AI_JOB_AGENT.cmd start   skip provisioning, launch only
rem
rem  Replaces the old ONE_CLICK_DESKTOP_SETUP.cmd + START_N8N.cmd pair, which
rem  shared ~60 lines and had drifted apart on Node and n8n versions.
rem
rem  Delayed expansion is deliberately NOT enabled: it eats '!' in passwords
rem  loaded from .env. Anything that would need it lives in a subroutine.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "WORKSPACE=%~dp0"
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOGFILE=%WORKSPACE%\setup.log"
set "ENVFILE=%WORKSPACE%\.env"
set "N8N_HOME=%LOCALAPPDATA%\AIJobAgent\n8n"
set "N8N_BIN=%N8N_HOME%\node_modules\.bin\n8n.cmd"
set "MARKER=%N8N_HOME%\.setup-complete"
set "N8N_VERSION=1.50.0"

rem --- Validate the requested mode (the auto decision needs Node, see below)
set "MODE=%~1"
if not defined MODE set "MODE=auto"
if /i not "%MODE%"=="auto" if /i not "%MODE%"=="setup" if /i not "%MODE%"=="start" (
  echo [ERROR] Unknown mode "%MODE%". Use: setup ^| start ^| no argument.
  goto :fail
)

echo ================================================
echo  AI Job Agent
echo ================================================
echo  Workspace : %WORKSPACE%
echo  n8n home  : %N8N_HOME%
echo ================================================
echo.

if not exist "%N8N_HOME%" mkdir "%N8N_HOME%"

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
if not defined N8N_SECURE_COOKIE set "N8N_SECURE_COOKIE=false"

set "SYSTEM_CMD=%SystemRoot%\System32\cmd.exe"
if not exist "%SYSTEM_CMD%" set "SYSTEM_CMD=C:\Windows\System32\cmd.exe"
if not exist "%SYSTEM_CMD%" (
  echo [ERROR] Could not find cmd.exe at expected system paths.
  goto :fail
)
set "ComSpec=%SYSTEM_CMD%"
set "npm_config_script_shell=%SYSTEM_CMD%"

rem --- Resolve Node first: the health probe below needs it to load sqlite3.
rem This call cannot install (that is a provisioning step); a failure here just
rem means we have to provision.
call "%WORKSPACE%\find-node.cmd"
if not errorlevel 1 set "PATH=%NODE_DIR%;%PATH%"

if /i "%MODE%"=="auto" call :decide_mode
echo [INFO] Mode: %MODE%
echo.

if /i "%MODE%"=="start" goto :launch

rem =========================== provisioning ==================================

echo [%date% %time%] Setup started > "%LOGFILE%"
echo [INFO] Workspace: %WORKSPACE% >> "%LOGFILE%"

for %%D in (data output logs) do (
  if not exist "%WORKSPACE%\%%D" mkdir "%WORKSPACE%\%%D"
)

rem --- Node: install a supported runtime if none is present
call "%WORKSPACE%\find-node.cmd" install
if errorlevel 1 goto :fail
set "PATH=%NODE_DIR%;%PATH%"
echo [INFO] node : %NODE_EXE%
echo [INFO] node : %NODE_EXE% >> "%LOGFILE%"

rem --- Python
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

echo.
echo [STEP] Upgrading pip...
%PYTHON_CMD% -m pip install --upgrade pip >> "%LOGFILE%" 2>&1

echo [STEP] Installing Python packages...
%PYTHON_CMD% -m pip install -r "%WORKSPACE%\requirements-agent.txt" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [ERROR] Python package install failed. Check setup.log
  goto :fail
)
echo [INFO] Python packages installed.

echo [STEP] Downloading Playwright Chromium...
%PYTHON_CMD% -m playwright install chromium >> "%LOGFILE%" 2>&1
if errorlevel 1 echo [WARN] Playwright download failed - run manually: py -m playwright install chromium

rem --- n8n
echo [STEP] Installing n8n v%N8N_VERSION% in user profile ^(no admin needed^)...

rem npm is npm.cmd, a batch file: without CALL it never returns to this script.
if not exist "%N8N_HOME%\package.json" (
  pushd "%N8N_HOME%"
  call "%NPM_CMD%" init -y >> "%LOGFILE%" 2>&1
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
  echo [WARN] Missing, broken, or wrong-version n8n detected. Reinstalling...
  echo [WARN] Missing, broken, or wrong-version n8n detected. Reinstalling... >> "%LOGFILE%"
  if exist "%N8N_HOME%\node_modules" rmdir /s /q "%N8N_HOME%\node_modules"
  if exist "%N8N_HOME%\package-lock.json" del /f /q "%N8N_HOME%\package-lock.json"
)

rem Pinned, not "n8n" latest: current n8n needs node >=22.22, which would mean
rem installing under one runtime and launching under another.
pushd "%N8N_HOME%"
call "%NPM_CMD%" install n8n@%N8N_VERSION% --legacy-peer-deps --omit=optional --no-audit --no-fund >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [WARN] Standard n8n install failed. Retrying with ignore-scripts... >> "%LOGFILE%"
  call "%NPM_CMD%" install n8n@%N8N_VERSION% --legacy-peer-deps --omit=optional --no-audit --no-fund --ignore-scripts >> "%LOGFILE%" 2>&1
)
if errorlevel 1 (
  popd
  echo [WARN] npm install failed - will fall back to npx at launch.
  set "USE_NPX=1"
  goto :provisioned
)
popd

rem The --ignore-scripts fallback above installs sqlite3 without building its
rem native binding, which fails only later at DB init. Verify before claiming
rem success, and repair if needed.
call :check_n8n_health
if not defined N8N_HEALTHY (
  echo [ERROR] n8n installed but cannot load sqlite3, and the rebuild failed.
  echo [ERROR] Usually this means node-gyp had to compile from source.
  echo [FIX]   Install "Desktop development with C++" via Visual Studio Build
  echo [FIX]   Tools, then re-run: %~nx0 setup
  goto :fail
)
echo [INFO] n8n installed and verified.

:provisioned
rem Application trackers (output\<candidate>\AppliedJobs.csv) are created by the
rem pipeline from config\workspace.json - do not duplicate the schema here.
echo [%date% %time%] Setup completed > "%MARKER%"
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
echo.
echo [STEP] Starting n8n in a new window...

rem The child inherits this process's environment, so credentials never appear
rem on a command line. Quoting a nested command in `cmd /k "..."` is not
rem reliable, so hand it a one-line launcher instead.
set "LAUNCHER=%N8N_HOME%\run-n8n.cmd"
> "%LAUNCHER%" echo @echo off
>>"%LAUNCHER%" echo cd /d "%N8N_HOME%"
if defined USE_NPX (
  >>"%LAUNCHER%" echo "%NODE_EXE%" "%NODE_DIR%node_modules\npm\bin\npx-cli.js" n8n@%N8N_VERSION% start
) else (
  >>"%LAUNCHER%" echo call "%N8N_BIN%"
)
>>"%LAUNCHER%" echo pause
start "n8n - AI Job Agent" "%SYSTEM_CMD%" /k "%LAUNCHER%"

echo [INFO] n8n is starting in a separate window.
pause
exit /b 0

rem ============================== launch =====================================

:launch
rem Node was already resolved (and PATH prepended) before the mode decision.
if not defined NODE_EXE (
  echo [ERROR] No supported Node.js. Run "%~nx0 setup" to install one.
  goto :fail
)
echo [INFO] Using node: %NODE_EXE%
"%NODE_EXE%" -v

if not exist "%N8N_BIN%" (
  echo [WARN] n8n not found at %N8N_BIN%
  echo [WARN] Falling back to npx. Run "%~nx0 setup" for a proper install.
  set "USE_NPX=1"
)

echo.
echo [INFO] Starting n8n...
if defined N8N_EDITOR_BASE_URL echo [INFO] URL    : %N8N_EDITOR_BASE_URL%
echo [INFO] URL    : http://localhost:%N8N_PORT%
echo [INFO] Sign in with the owner account you created on first launch.
echo [INFO] Close this window to stop n8n
echo.

cd /d "%N8N_HOME%"
if defined USE_NPX (
  echo [INFO] Launching via: npx n8n@%N8N_VERSION% start
  "%NODE_EXE%" "%NODE_DIR%node_modules\npm\bin\npx-cli.js" n8n@%N8N_VERSION% start
  if errorlevel 1 "%NODE_DIR%npx.cmd" --yes n8n@%N8N_VERSION% start
) else (
  call "%N8N_BIN%"
)
pause
exit /b 0

rem =========================== subroutines ===================================

:decide_mode
rem Provision when the marker is absent, the install is missing, or the install
rem is present but cannot actually run.
set "MODE=start"
if not exist "%MARKER%" set "MODE=setup"
if not exist "%N8N_BIN%" set "MODE=setup"
if not defined NODE_EXE set "MODE=setup"
if /i "%MODE%"=="start" call :check_n8n_health
if not defined N8N_HEALTHY set "MODE=setup"
goto :eof

:check_n8n_health
rem A correct version number is NOT proof the install works. An install done
rem with --ignore-scripts leaves sqlite3 without its compiled .node binding, so
rem n8n starts and then dies with "There was an error initializing DB /
rem DriverPackageNotInstalledError". Probe the thing that actually breaks.
set "N8N_HEALTHY="
pushd "%N8N_HOME%"
"%NODE_EXE%" -e "require('sqlite3')" >nul 2>&1
if errorlevel 1 (
  popd
  echo [WARN] n8n is installed but sqlite3 has no native binding - repairing.
  call :repair_sqlite
  goto :eof
)
popd
set "N8N_HEALTHY=1"
goto :eof

:repair_sqlite
rem npm resolves `node` from PATH, not from the npm.cmd being invoked, so the
rem chosen runtime must lead PATH or node-gyp builds against the wrong ABI and
rem then demands Visual Studio. PATH is already prepended by the caller.
pushd "%N8N_HOME%"
set "npm_config_ignore_scripts=false"
call "%NPM_CMD%" rebuild sqlite3 >> "%LOGFILE%" 2>&1
"%NODE_EXE%" -e "require('sqlite3')" >nul 2>&1
if not errorlevel 1 set "N8N_HEALTHY=1"
popd
if defined N8N_HEALTHY (
  echo [INFO] sqlite3 repaired.
) else (
  echo [WARN] sqlite3 rebuild failed - falling back to a full reinstall.
)
goto :eof

:find_cmd
if defined PYTHON_CMD goto :eof
where %1 >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=%1"
goto :eof

:find_python_exe
if exist "%~1" set "PYTHON_CMD=%~1"
goto :eof

:check_n8n_pkg
rem Version-aware: a drifted install is repaired, not silently kept.
pushd "%N8N_HOME%"
call "%NPM_CMD%" ls n8n@%N8N_VERSION% --depth=0 >nul 2>&1
if errorlevel 1 set "NEEDS_REINSTALL=1"
popd
goto :eof

:fail
echo.
echo ================================================
echo  FAILED - check setup.log for details
echo ================================================
echo [%date% %time%] Failed >> "%LOGFILE%"
pause
exit /b 1
