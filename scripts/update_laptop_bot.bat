@echo off
TITLE 1-Click Laptop Updater (No Git / No IDE Required)
COLOR 0A

:: =============================================================================
:: ⚡ 1-CLICK GITHUB BOT UPDATER FOR LAPTOP (ZERO GIT / ZERO IDE)
:: =============================================================================
:: Automatically downloads the latest code updates from GitHub (charom11/Atlas-Bot)
:: and updates all files without requiring Git or any IDE.
:: Preserves your .env (API keys) and data\ (telemetry).
:: =============================================================================

cd /d "%~dp0"

echo =========================================================================
echo  🔄 ATLAS-BOT 1-CLICK LAPTOP UPDATER
echo =========================================================================
echo  • Repository: https://github.com/charom11/Atlas-Bot
echo  • Mode:       Direct GitHub Sync (No Git or IDE needed)
echo =========================================================================
echo.

:: Resolve Python executable
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    where py >nul 2>&1 && set "PYTHON_EXE=py -3"
)
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
    )
)
if not defined PYTHON_EXE (
    for /d %%D in ("C:\Python3*") do (
        if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
    )
)

if not defined PYTHON_EXE (
    COLOR 0C
    echo [ERROR] Python not found on this laptop!
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Run the updater script
%PYTHON_EXE% update_from_github.py

echo.
echo Press any key to close this updater...
pause >nul
