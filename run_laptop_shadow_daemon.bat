@echo off
TITLE V9.3.1 Shadow Observer Daemon - Laptop Watchdog
COLOR 0B

:: =============================================================================
:: ⚡ V9.3.1 SHADOW OBSERVER DAEMON - LAPTOP WATCHDOG
:: =============================================================================
:: Designed specifically for portable laptop environments (e.g. C:\downloads\...)
:: Features:
::  1. Auto-detects Python (.venv, system PATH, py launcher, or AppData)
::  2. Auto-verifies and installs required libraries (pandas, numpy, requests)
::  3. Zero-Risk Observer: Uses public Binance data (no API trading keys required)
::  4. Circuit breaker: Suppresses infinite restart loops if daemon crashes in < 10s
::  5. Prevents Windows PC Sleep on AC power while tracking forward telemetry
:: =============================================================================

cd /d "%~dp0"

echo =========================================================================
echo  📡 V9.3.1 SHADOW TELEMETRY OBSERVER - LAPTOP WATCHDOG
echo =========================================================================
echo  • Working Directory: %CD%
echo  • Safety Boundary:   STRICT OBSERVER (Zero live orders / Read-only)
echo  • Monitored Assets:  SOL, SUI, XRP, BTC, DOGE, ETH
echo =========================================================================
echo.

:: -----------------------------------------------------------------------------
:: STEP 1: RESOLVE PYTHON EXECUTABLE
:: -----------------------------------------------------------------------------
set "PYTHON_EXE="

:: Check 1: Local .venv in current directory
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

:: Check 2: System Python in PATH
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_EXE=python"
    )
)

:: Check 3: Python Launcher (py)
if not defined PYTHON_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_EXE=py -3"
    )
)

:: Check 4: Common Windows AppData Python paths
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" (
            set "PYTHON_EXE=%%D\python.exe"
        )
    )
)

:: Check 5: Common root Python paths
if not defined PYTHON_EXE (
    for /d %%D in ("C:\Python3*") do (
        if exist "%%D\python.exe" (
            set "PYTHON_EXE=%%D\python.exe"
        )
    )
)

:: If Python is still not found, halt gracefully with clear instructions
if not defined PYTHON_EXE (
    COLOR 0C
    echo.
    echo =========================================================================
    echo  ❌ [ERROR] PYTHON WAS NOT FOUND ON THIS LAPTOP!
    echo =========================================================================
    echo  The shadow daemon cannot run because Python is not installed.
    echo.
    echo  HOW TO FIX:
    echo  1. Download Python 3.10, 3.11, or 3.12 from:
    echo     https://www.python.org/downloads/
    echo  2. IMPORTANT: CHECK "Add python.exe to PATH" during installation.
    echo  3. After installing, double-click this script again.
    echo =========================================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Python Engine Resolved: %PYTHON_EXE%
%PYTHON_EXE% --version
echo.

:: -----------------------------------------------------------------------------
:: STEP 2: VERIFY CORE LIBRARIES FOR SHADOW TELEMETRY
:: -----------------------------------------------------------------------------
echo Checking Python libraries (pandas, numpy, requests)...
%PYTHON_EXE% -c "import pandas, numpy, requests" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  📦 [DEPENDENCY NOTICE] Installing required libraries (pandas, numpy, requests)...
    echo.
    %PYTHON_EXE% -m pip install --upgrade pip >nul 2>&1
    %PYTHON_EXE% -m pip install pandas numpy requests
    if errorlevel 1 (
        COLOR 0C
        echo.
        echo ❌ Failed to install dependencies. Check your internet connection.
        pause
        exit /b 1
    )
    echo.
    echo [OK] All shadow dependencies successfully installed!
    echo.
) else (
    echo [OK] Libraries verified.
)

:: Ensure telemetry data directory exists
if not exist "%~dp0data\shadow_v9_3_1" (
    mkdir "%~dp0data\shadow_v9_3_1" >nul 2>&1
)

:: -----------------------------------------------------------------------------
:: STEP 3: PREVENT WINDOWS SLEEP (AC POWER)
:: -----------------------------------------------------------------------------
powercfg /change standby-timeout-ac 0 >nul 2>&1

:: -----------------------------------------------------------------------------
:: STEP 4: WATCHDOG LOOP WITH CIRCUIT BREAKER
:: -----------------------------------------------------------------------------
echo.
echo =========================================================================
echo  🚀 STARTING V9.3.1 SHADOW OBSERVER DAEMON
echo =========================================================================
echo  • Polling Frequency: Every 15 seconds
echo  • Local Log:         v9_3_1_shadow_daemon.log
echo  • Telemetry Output:  data\shadow_v9_3_1\
echo =========================================================================
echo.

:WATCHDOG_LOOP
for /f %%i in ('powershell -command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "START_TIME=%%i"

echo [%date% %time%] [WATCHDOG] Booting V9.3.1 Shadow Daemon...
echo.

:: Launch the shadow daemon
%PYTHON_EXE% -u v9_3_1_shadow_daemon.py --poll-interval 15 --log-file v9_3_1_shadow_daemon.log
set "DAEMON_EXIT_CODE=%ERRORLEVEL%"

for /f %%i in ('powershell -command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - %START_TIME%"') do set "RUN_DURATION=%%i"

echo.
echo =========================================================================
echo  ⚠️ [%date% %time%] [WATCHDOG EVENT] Daemon Exited (Code: %DAEMON_EXIT_CODE%)
echo  • Run Duration: %RUN_DURATION% seconds
echo =========================================================================

:: CIRCUIT BREAKER: If it stopped in under 10 seconds, pause the restart loop!
if %RUN_DURATION% LSS 10 (
    COLOR 0C
    echo.
    echo  🚨 [CIRCUIT BREAKER TRIGGERED]
    echo  The shadow daemon exited immediately within %RUN_DURATION% seconds!
    echo  Possible causes:
    echo   1. Network issue reaching Binance public API (fapi.binance.com)
    echo   2. Missing strategy files in the folder
    echo.
    echo  The restart loop is PAUSED so you can inspect the error above.
    echo =========================================================================
    echo.
    echo Press any key to retry, or close this window to exit.
    pause >nul
    COLOR 0B
    goto WATCHDOG_LOOP
)

:: Normal auto-restart after network disconnect or temporary glitch
COLOR 0E
echo 🔄 Auto-restarting shadow daemon in 5 seconds... (Press Ctrl+C to cancel)
timeout /t 5 /nobreak >nul
COLOR 0B
goto WATCHDOG_LOOP
