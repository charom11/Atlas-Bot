@echo off
TITLE 1-Click Laptop Sync to GitHub (Push Changes)
COLOR 0B

:: =============================================================================
:: ⚡ 1-CLICK LAPTOP SYNC TO GITHUB (PUSH CHANGES)
:: =============================================================================
:: Safely stages, commits, and pushes your laptop changes to GitHub
:: (charom11/Atlas-Bot) while strictly protecting:
::  - .env / .env.local (private API keys and secrets)
::  - data\ (shadow telemetry database)
::  - local log files
:: =============================================================================

cd /d "%~dp0"

echo =========================================================================
echo  ⬆️  ATLAS-BOT: 1-CLICK LAPTOP ➔ GITHUB SYNC
echo =========================================================================
echo  • Repository: https://github.com/charom11/Atlas-Bot
echo  • Directory:  %CD%
echo =========================================================================
echo.

:: Resolve Python executable if available
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

:: If Python is available and sync_to_github.py exists, use it for rich handling
if defined PYTHON_EXE (
    if exist "%~dp0sync_to_github.py" (
        %PYTHON_EXE% "%~dp0sync_to_github.py" %*
        goto :FINISH
    )
    if exist "%~dp0..\sync_to_github.py" (
        %PYTHON_EXE% "%~dp0..\sync_to_github.py" %*
        goto :FINISH
    )
)

:: Fallback Pure Batch Mode using Git directly
where git >nul 2>&1
if errorlevel 1 (
    COLOR 0C
    echo =========================================================================
    echo  ❌ [ERROR] Git is not installed or not found in system PATH!
    echo =========================================================================
    echo  To push changes from this laptop to GitHub, please install Git:
    echo   • Via Terminal: winget install --id Git.Git -e
    echo   • Via Website:  https://git-scm.com/download/win
    echo =========================================================================
    goto :FINISH
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    COLOR 0C
    echo [ERROR] Current folder is not a Git repository!
    goto :FINISH
)

set "CURRENT_BRANCH="
for /f "tokens=*" %%i in ('git branch --show-current') do set "CURRENT_BRANCH=%%i"
if not defined CURRENT_BRANCH set "CURRENT_BRANCH=main"

echo [Active Branch: %CURRENT_BRANCH%]
echo.

git status -s
echo.

set "HAS_DIFF="
for /f "tokens=*" %%i in ('git status --porcelain') do set "HAS_DIFF=1"

if not defined HAS_DIFF (
    echo [1/2] Working tree is clean. Checking for unpushed commits...
    git push origin %CURRENT_BRANCH%
    if errorlevel 1 (
        echo [ERROR] Git push failed. Please check permissions or network.
    ) else (
        COLOR 0A
        echo ✅ Branch '%CURRENT_BRANCH%' is fully synced with GitHub!
    )
    goto :FINISH
)

set "COMMIT_MSG="
set /p "COMMIT_MSG=Enter commit message (Press ENTER for auto-timestamp): "
if not defined COMMIT_MSG (
    set "COMMIT_MSG=sync(laptop): updates from laptop [%DATE% %TIME%]"
)

echo [1/3] Staging changes (excluding private keys and logs)...
git add -A
git reset -- .env .env.local data/ *.log bot_output.log bot_output.log.1 .venv/ __pycache__/ >nul 2>&1

echo [2/3] Committing changes...
git commit -m "%COMMIT_MSG%"

echo [3/3] Pulling remote updates and pushing to GitHub (origin/%CURRENT_BRANCH%)...
git pull --rebase origin %CURRENT_BRANCH%
if errorlevel 1 (
    echo [WARN] Rebase encountered conflicts. Aborting rebase to keep your files safe.
    git rebase --abort >nul 2>&1
    goto :FINISH
)

git push origin %CURRENT_BRANCH%
if errorlevel 1 (
    COLOR 0C
    echo ❌ [ERROR] Push to GitHub failed!
) else (
    COLOR 0A
    echo =========================================================================
    echo  ✅ SYNC COMPLETE! Your laptop changes are now live on GitHub:
    echo  • https://github.com/charom11/Atlas-Bot/tree/%CURRENT_BRANCH%
    echo =========================================================================
)

:FINISH
echo.
echo Press any key to close...
pause >nul
