$WshShell = New-Object -ComObject WScript.Shell
$StartupFolder = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$ShortcutPath = Join-Path $StartupFolder "WeatherEnsembleBot_Watchdog.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "d:\Bot2\run_24_7_windows_watchdog.bat"
$Shortcut.WorkingDirectory = "d:\Bot2"
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Weather Ensemble 24/7 Live Bot Watchdog"
$Shortcut.Save()
Write-Host "Auto-start shortcut created successfully at: $ShortcutPath"
