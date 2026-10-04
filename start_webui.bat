@echo off
setlocal
cd /d "%~dp0"

echo === Your Guitar Chronicle WebUI ===
for /f "delims=" %%i in ('git branch --show-current') do set CURRENT_BRANCH=%%i
echo Repository: %CD%
echo Branch: %CURRENT_BRANCH%

echo.
echo [1/4] Checking automatic update...
git rev-parse --verify "@{upstream}" >nul 2>&1
if errorlevel 1 (
    echo No upstream branch. Starting with local code.
    goto :prepare
)
set HAS_LOCAL_CHANGES=
for /f "delims=" %%i in ('git status --porcelain') do set HAS_LOCAL_CHANGES=1
if defined HAS_LOCAL_CHANGES (
    echo Uncommitted changes found. Starting with local code.
    goto :prepare
)
git pull --ff-only
if errorlevel 1 goto :error

:prepare
echo.
echo [2/4] Preparing Python environment...
cd app

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv with py -3.12...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :error
)

call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo.
echo [3/4] Updating editable install...
python ../scripts/install_dependencies.py
if errorlevel 1 goto :error

echo.
echo [4/4] Starting WebUI...
echo Close this window or press Ctrl+C to stop.
echo.

ygc-web
goto :eof

:error
echo.
echo Failed to start Your Guitar Chronicle WebUI.
pause
exit /b 1
