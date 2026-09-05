@echo off
TITLE Weather-Ensemble AI 24/7 Automated Watchdog
COLOR 0A

:: -----------------------------------------------------------------------------
:: ⚡ WEATHER-ENSEMBLE AI 24/7 AUTO-HEALING WATCHDOG ENGINE
:: -----------------------------------------------------------------------------
:: - Prevents PC Sleep during trading
:: - Auto-restarts within 3 seconds if network drops or crash occurs
:: - Runs both Live Trading Agent and Web/API Dashboard Server
:: -----------------------------------------------------------------------------

echo =========================================================================
echo  ⚡ STARTING WEATHER-ENSEMBLE AI 24/7 LIVE TRADING SUITE
echo =========================================================================
echo  • Mode:        REAL BINANCE FUTURES (50x Leverage / 3%% Dynamic Margin)
echo  • Assets:      19 Top Liquid Binance Futures Symbols
echo  • Telegram C2: ACTIVE (Control directly from your phone)
echo  • Watchdog:    SELF-HEALING AUTO-RESTART ENABLED
echo =========================================================================
echo.

cd /d "%~dp0"

:WATCHDOG_LOOP
echo [%date% %time%] [WATCHDOG] Booting Weather-Ensemble AI Live Daemon...

:: Start the Web & API Server in background
start /B "" "%~dp0.venv\Scripts\python.exe" server.py

:: Run the Live Bot with auto-healing
"%~dp0.venv\Scripts\python.exe" weather_ensemble_bot.py --trade-live --sizing-mode margin --margin-pct 0.03 --leverage 50 --threshold 30 --timeframe 15m --max-positions 5

echo.
echo ⚠️ [%date% %time%] [WATCHDOG WARNING] Bot process exited or disconnected!
echo 🔄 [%date% %time%] Auto-restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto WATCHDOG_LOOP
