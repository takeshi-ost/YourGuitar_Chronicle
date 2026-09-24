@echo off
setlocal
cd /d "%~dp0"

set SOURCE=phase0_proto\data\chronicle.db
set TARGET=phase0_proto\tests\data\ygc_test_snapshot.db

if not exist "%SOURCE%" (
    echo Source DB not found: %SOURCE%
    pause
    exit /b 1
)

if not exist "phase0_proto\tests\data" mkdir "phase0_proto\tests\data"

echo Creating consistent SQLite test snapshot...
phase0_proto\.venv\Scripts\python.exe -c "import sqlite3; src=sqlite3.connect(r'%SOURCE%'); dst=sqlite3.connect(r'%TARGET%'); src.backup(dst); dst.close(); src.close()"
if errorlevel 1 (
    echo Failed to create test DB snapshot.
    pause
    exit /b 1
)

echo.
echo Test DB updated:
echo %TARGET%
echo.
echo The file is intentionally Git-managed.
git status --short "%TARGET%"
echo.
echo Review it, then commit normally when desired.
pause
