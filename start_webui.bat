@echo off
setlocal
cd /d "%~dp0"

echo === Your Guitar Chronicle WebUI ===
for /f "delims=" %%i in ('git branch --show-current') do set CURRENT_BRANCH=%%i
echo Repository: %CD%
echo Branch: %CURRENT_BRANCH%

echo.
echo [1/4] Pulling latest changes...
git pull --ff-only
if errorlevel 1 goto :error

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
python -m pip install -e ".[dev]"
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
