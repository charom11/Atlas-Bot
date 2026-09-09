@echo off
cd /d "%~dp0.."
if exist "sync_laptop_to_github.bat" (
    call sync_laptop_to_github.bat %*
) else (
    echo [ERROR] sync_laptop_to_github.bat not found in parent directory.
    pause
)
