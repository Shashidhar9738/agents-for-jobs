@echo off
rem ---------------------------------------------------------------------------
rem Locates a Node.js runtime that n8n 1.50.x can run on, optionally installing
rem one via winget when none is present.
rem
rem Usage:  call "%~dp0find-node.cmd" [install]
rem
rem On success sets, in the CALLER's environment:
rem   NODE_EXE  full path to node.exe
rem   NODE_DIR  directory containing it (trailing backslash)
rem   NPM_CMD   full path to npm.cmd for that runtime
rem
rem Why 18/20/22 and not 24: n8n 1.50.0 declares "node >=18.10" with no upper
rem bound, so 24 passes the declared check, but 1.50 predates Node 24 and its
rem native deps (sqlite) have no prebuilds for that ABI. Preferring 20 keeps the
rem runtime contemporary with the pinned n8n version.
rem
rem IMPORTANT: the caller must NOT have delayed expansion enabled.
rem ---------------------------------------------------------------------------

set "NODE_EXE="
set "NODE_DIR="
set "NPM_CMD="

call :scan
if defined NODE_EXE goto :resolve

if /i not "%~1"=="install" goto :nonode

rem --- Nothing usable found: install Node 20 LTS into the user profile.
where winget >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No supported Node.js and winget is unavailable to install one.
  goto :nonode
)
echo [STEP] No supported Node.js found - installing Node 20 LTS via winget...
echo [INFO] This installs into your user profile; no admin rights needed.
winget install --id OpenJS.NodeJS.20 -e --scope user --accept-package-agreements --accept-source-agreements
call :scan
if not defined NODE_EXE goto :nonode

:resolve
for %%I in ("%NODE_EXE%") do set "NODE_DIR=%%~dpI"
set "NPM_CMD=%NODE_DIR%npm.cmd"
if not exist "%NPM_CMD%" set "NPM_CMD=npm"
exit /b 0

:nonode
echo.
echo [ERROR] No supported Node.js found ^(need 18, 20, or 22^).
echo.
echo [FIX] Install Node 20 manually, then re-run:
echo   winget install --id OpenJS.NodeJS.20 -e --scope user --accept-package-agreements --accept-source-agreements
echo.
exit /b 1

rem --------------------------- subroutines -----------------------------------

:scan
call :find_winget_node "OpenJS.NodeJS.20_*"
call :find_winget_node "OpenJS.NodeJS.22_*"
if not defined NODE_EXE call :check_system_node
goto :eof

:find_winget_node
rem Match any patch release rather than one hardcoded version.
if defined NODE_EXE goto :eof
for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\%~1") do (
  for /d %%Q in ("%%P\node-v*-win-x64") do (
    if exist "%%Q\node.exe" call :set_node "%%Q\node.exe"
  )
)
goto :eof

:check_system_node
rem `node -v` prints e.g. v22.23.1, so compare the major-version prefix only.
for /f "tokens=*" %%V in ('node -v 2^>nul') do set "SYS_NODE=%%V"
if not defined SYS_NODE goto :eof
set "SUPPORTED="
if "%SYS_NODE:~0,3%"=="v18" set "SUPPORTED=1"
if "%SYS_NODE:~0,3%"=="v20" set "SUPPORTED=1"
if "%SYS_NODE:~0,3%"=="v22" set "SUPPORTED=1"
if not defined SUPPORTED (
  echo [INFO] System Node %SYS_NODE% is not supported by the pinned n8n; looking for 18/20/22.
  goto :eof
)
for /f "tokens=*" %%W in ('where node 2^>nul') do call :set_node "%%W"
goto :eof

:set_node
if not defined NODE_EXE set "NODE_EXE=%~1"
goto :eof
