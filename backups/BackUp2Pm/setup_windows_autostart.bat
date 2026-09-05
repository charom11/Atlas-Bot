@echo off
TITLE Weather-Ensemble Auto-Start Setup
COLOR 0B

echo =========================================================================
echo  ⚡ INSTALLING 24/7 WINDOWS AUTO-START SHORTCUT
echo =========================================================================
echo.

powershell -Command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Startup') + '\WeatherEnsembleBot_Watchdog.lnk'); $Shortcut.TargetPath = '%~dp0run_24_7_windows_watchdog.bat'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.WindowStyle = 1; $Shortcut.Description = 'Weather Ensemble 24/7 Live Bot Watchdog'; $Shortcut.Save()"

echo [SUCCESS] Auto-start shortcut installed in your Windows Startup Folder!
echo.
echo Location: %%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup
echo Target:   %~dp0run_24_7_windows_watchdog.bat
echo.
echo Whenever your PC turns on or restarts, the bot will automatically start!
echo =========================================================================
pause
