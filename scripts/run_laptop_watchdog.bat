@echo off
TITLE Weather-Ensemble AI - Laptop Watchdog (Self-Healing and Auto-Setup)
COLOR 0A

:: =============================================================================
:: ⚡ WEATHER-ENSEMBLE AI - LAPTOP AUTONOMOUS WATCHDOG
:: =============================================================================
:: Designed specifically for portable laptop environments (e.g. C:\downloads\...)
:: Features:
::  1. Auto-resolves Python (.venv, system PATH, py launcher, or AppData)
::  2. Automatically checks and installs missing dependencies (pip)
::  3. Validates .env configuration and prevents blind crash loops
::  4. Circuit breaker: Suppresses infinite restart loops if bot crashes in < 10s
::  5. Prevents Windows PC Sleep on AC power while trading
:: =============================================================================

cd /d "%~dp0"

echo =========================================================================
echo  ⚡ WEATHER-ENSEMBLE AI - LAPTOP WATCHDOG INITIALIZER
echo =========================================================================
echo  • Working Directory: %CD%
echo  • Mode:              Auto-Detecting Python and Environment...
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
    echo  The watchdog cannot run because Python is not installed or not in PATH.
    echo.
    echo  HOW TO FIX:
    echo  1. Download and install Python 3.10, 3.11, or 3.12 from:
    echo     https://www.python.org/downloads/
    echo  2. IMPORTANT: During installation, CHECK the box that says:
    echo     "Add python.exe to PATH"
    echo  3. After installation completes, double-click this script again.
    echo =========================================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Python Engine Resolved: %PYTHON_EXE%
%PYTHON_EXE% --version
echo.

:: -----------------------------------------------------------------------------
:: STEP 2: VERIFY .ENV CONFIGURATION
:: -----------------------------------------------------------------------------
if not exist "%~dp0.env" (
    COLOR 0E
    echo -------------------------------------------------------------------------
    echo  ⚠️ [CONFIG WARNING] .env file not found in %CD%
    if exist "%~dp0.env.example" (
        echo  Creating initial .env template from .env.example...
        copy "%~dp0.env.example" "%~dp0.env" >nul
        echo  [OK] Created .env template. Please enter your API keys inside .env!
    ) else (
        echo  Please create a .env file with your BINANCE_API_KEY and BINANCE_API_SECRET.
    )
    echo -------------------------------------------------------------------------
    echo.
    timeout /t 3 >nul
    COLOR 0A
)

:: -----------------------------------------------------------------------------
:: STEP 3: VERIFY CORE DEPENDENCIES
:: -----------------------------------------------------------------------------
echo Checking Python dependencies (pandas, requests, dotenv, ccxt)...
%PYTHON_EXE% -c "import pandas, requests, dotenv, ccxt" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  📦 [DEPENDENCY NOTICE] Missing required libraries on this laptop.
    echo  Installing dependencies from requirements.txt...
    echo.
    %PYTHON_EXE% -m pip install --upgrade pip >nul 2>&1
    if exist "%~dp0requirements.txt" (
        %PYTHON_EXE% -m pip install -r "%~dp0requirements.txt"
    ) else (
        %PYTHON_EXE% -m pip install pandas numpy scipy requests ccxt websocket-client psutil python-dotenv rich
    )
    if errorlevel 1 (
        COLOR 0C
        echo.
        echo ❌ Failed to install dependencies. Please check your internet connection.
        pause
        exit /b 1
    )
    echo.
    echo [OK] All dependencies successfully installed!
    echo.
) else (
    echo [OK] Dependencies verified.
)

:: -----------------------------------------------------------------------------
:: STEP 4: PREVENT WINDOWS SLEEP (AC POWER)
:: -----------------------------------------------------------------------------
powercfg /change standby-timeout-ac 0 >nul 2>&1

:: -----------------------------------------------------------------------------
:: STEP 5: WATCHDOG EXECUTION LOOP WITH CIRCUIT BREAKER
:: -----------------------------------------------------------------------------
echo.
echo =========================================================================
echo  🚀 STARTING 24/7 AUTONOMOUS LAPTOP WATCHDOG
echo =========================================================================
echo  • Target Script: main.py
echo  • Sizing Mode:   Dynamic Margin (3%% Risk, 50x Leverage Cap)
echo  • Circuit Break: Auto-pause on instant crash to prevent restart loop
echo =========================================================================
echo.

:WATCHDOG_LOOP
for /f %%i in ('powershell -command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "START_TIME=%%i"

echo [%date% %time%] [WATCHDOG] Launching Weather-Ensemble Trading Engine...
echo.

:: Launch the bot
%PYTHON_EXE% -u main.py --trade-live --sizing-mode margin --margin-pct 0.03 --leverage 50 --threshold 30 --timeframe 15m --max-positions 5 --directional-cap 5
set "BOT_EXIT_CODE=%ERRORLEVEL%"

for /f %%i in ('powershell -command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - %START_TIME%"') do set "RUN_DURATION=%%i"

echo.
echo =========================================================================
echo  ⚠️ [%date% %time%] [WATCHDOG EVENT] Process Exited (Code: %BOT_EXIT_CODE%)
echo  • Run Duration: %RUN_DURATION% seconds
echo =========================================================================

:: CIRCUIT BREAKER: If the bot died in under 10 seconds, it's a critical crash or config error!
:: DO NOT blindly restart in an infinite loop!
if %RUN_DURATION% LSS 10 (
    COLOR 0C
    echo.
    echo  🚨 [CIRCUIT BREAKER TRIGGERED] 
    echo  The bot stopped immediately within %RUN_DURATION% seconds!
    echo  Possible causes:
    echo   1. Missing or invalid Binance API keys in .env
    echo   2. Network/VPN connection blocked to fapi.binance.com
    echo   3. Syntax or import error in custom scripts
    echo.
    echo  The restart loop has been PAUSED to let you read the error above.
    echo =========================================================================
    echo.
    echo Press any key to retry starting the bot, or close this window to exit.
    pause >nul
    COLOR 0A
    goto WATCHDOG_LOOP
)

:: Normal Watchdog behavior for long runs (network disconnect or reboot)
COLOR 0E
echo 🔄 Auto-restarting daemon in 5 seconds... (Press Ctrl+C to cancel)
timeout /t 5 /nobreak >nul
COLOR 0A
goto WATCHDOG_LOOP
