@echo off
rem ---------------------------------------------------------------------------
rem Loads KEY=VALUE pairs from a .env file into the current environment.
rem
rem Usage:  call "%~dp0load-env.cmd" "<path-to-.env>"
rem
rem IMPORTANT: the caller must NOT have delayed expansion enabled. Values that
rem contain '!' (very common in passwords) are silently mangled when delayed
rem expansion is on, which is exactly the bug this file exists to avoid.
rem
rem Format expectations: one KEY=VALUE per line, '#' starts a comment line,
rem no spaces around '='. Values containing '%' are not supported.
rem ---------------------------------------------------------------------------

if "%~1"=="" (
  echo [ERROR] load-env.cmd: no .env path supplied.
  exit /b 1
)
if not exist "%~1" (
  echo [ERROR] load-env.cmd: file not found: %~1
  exit /b 2
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~1") do set "%%A=%%B"
exit /b 0
