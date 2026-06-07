@echo off
REM Phygital Studio - single-click launcher (Windows).
REM
REM What it does on double-click:
REM   1. Creates sidecar/.venv on first run + installs deps (one-time, ~30s).
REM   2. Kills any stale sidecar process on port 18765.
REM   3. Starts sidecar in the background (pythonw, no console window).
REM   4. Waits for /health to respond.
REM   5. Copies the sidecar token to the clipboard.
REM   6. Registers itself in HKCU\...\Run so sidecar autostarts on login.
REM
REM After this you just open Figma -> Plugins -> Development -> Cloud.ru
REM Brand Generations, click the gear, Paste the token, sign in, generate.

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SIDECAR_DIR=%ROOT%\sidecar"
set "PORT=18765"
set "VENV=%SIDECAR_DIR%\.venv"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "PY=%VENV%\Scripts\python.exe"
set "TOKEN_FILE=%LOCALAPPDATA%\PhygitalStudio\sidecar.token"
set "QUIET=%1"

if not exist "%SIDECAR_DIR%" (
  echo ERROR: sidecar directory not found at %SIDECAR_DIR%
  if /i not "%QUIET%"=="--quiet" pause
  exit /b 1
)

REM --- Locate Python 3.11+ on first run --------------------------------------

if not exist "%PY%" (
  echo First run: locating Python 3.11+ and creating virtualenv...
  set "PY_EXE="
  for %%P in (py.exe python3.12.exe python3.11.exe python.exe python3.exe) do (
    if not defined PY_EXE (
      where %%P >nul 2>&1 && set "PY_EXE=%%P"
    )
  )
  if not defined PY_EXE (
    echo ERROR: Python 3.11+ not found in PATH.
    echo Install from https://www.python.org/downloads/  ^(check "Add to PATH"^)
    if /i not "%QUIET%"=="--quiet" pause
    exit /b 1
  )
  REM Prefer "py -3.11" if py-launcher is available
  if /i "!PY_EXE!"=="py.exe" (
    py -3.12 -m venv "%VENV%" 2>nul || py -3.11 -m venv "%VENV%" 2>nul || py -3 -m venv "%VENV%"
  ) else (
    "!PY_EXE!" -m venv "%VENV%"
  )
  if not exist "%PY%" (
    echo ERROR: failed to create virtualenv at %VENV%
    if /i not "%QUIET%"=="--quiet" pause
    exit /b 1
  )
  "%PY%" -m pip install --upgrade pip >nul
  echo Installing sidecar package ^(this happens once^)...
  "%PY%" -m pip install -e "%SIDECAR_DIR%"
)

REM --- Kill stale sidecar process on PORT, if any ----------------------------

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
  taskkill /PID %%a /F >nul 2>&1
)

REM --- Start sidecar in background (no console window) -----------------------

set "PHYGITAL_HOST=127.0.0.1"
set "PHYGITAL_PORT=%PORT%"
pushd "%SIDECAR_DIR%"
start "" /b "%PYW%" -m app.main
popd

REM --- Wait for /health (up to ~12s) ----------------------------------------

echo Waiting for sidecar on http://localhost:%PORT% ...
set "HEALTH_OK=0"
for /l %%i in (1,1,40) do (
  curl -fsS "http://localhost:%PORT%/health" >nul 2>&1 && set "HEALTH_OK=1" && goto :health_done
  REM ~0.3s sleep
  ping -n 1 -w 300 127.0.0.1 >nul
)
:health_done

if "%HEALTH_OK%"=="0" (
  echo.
  echo ERROR: sidecar did not respond within ~12s.
  echo Check %%LOCALAPPDATA%%\PhygitalStudio\logs\sidecar.log
  if /i not "%QUIET%"=="--quiet" pause
  exit /b 1
)

REM --- Copy token to clipboard ----------------------------------------------

if not exist "%TOKEN_FILE%" (
  echo WARNING: token file missing at %TOKEN_FILE%
  if /i not "%QUIET%"=="--quiet" pause
  exit /b 1
)

REM `type | clip` пишет с trailing newline. Используем powershell для clean copy.
powershell -NoProfile -Command "[System.IO.File]::ReadAllText('%TOKEN_FILE%').Trim() | Set-Clipboard" 2>nul || (
  type "%TOKEN_FILE%" | clip
)

REM --- Register autostart on user login (HKCU Run) --------------------------
REM Используем /quiet чтобы launcher не показывал терминальное окно при логине.
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PhygitalStudio" /t REG_SZ /d "\"%~f0\" --quiet" /f >nul 2>&1

REM --- Done ------------------------------------------------------------------

set /p TOKEN=<"%TOKEN_FILE%"
set "TOKEN_PREVIEW=!TOKEN:~0,10!..."

if /i "%QUIET%"=="--quiet" (
  exit /b 0
)

echo.
echo ────────────────────────────────────────────────────────────────
echo   [OK] Sidecar is running on http://localhost:%PORT%
echo   [OK] Token copied to clipboard ^(%TOKEN_PREVIEW%^)
echo   [OK] Autostart registered ^(HKCU\...\Run\PhygitalStudio^)
echo.
echo   Next steps in Figma ^(one-time^):
echo     1. Plugins -^> Development -^> Import plugin from manifest...
echo        ^(pick figma-plugin\manifest.json from this repo^)
echo     2. Plugins -^> Development -^> Cloud.ru Brand Generations
echo     3. Click [gear] -^> Paste ^(Ctrl+V^)
echo     4. Sign in with your Phygital+ email + password
echo.
echo   Future Windows logins: sidecar starts automatically.
echo ────────────────────────────────────────────────────────────────
echo.

timeout /t 8 /nobreak >nul 2>&1
endlocal
