# Starts Desktop Agent automatically when you sign in to Windows.
# Usage: open PowerShell in the project folder (NOT as administrator) and run:
#     powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1
# Remove it later with:  Unregister-ScheduledTask -TaskName "DesktopAgent" -Confirm:$false

$ErrorActionPreference = "Stop"
$project = (Resolve-Path ".").Path

# Prefer pythonw.exe so no console window stays open in the background.
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python.exe -ErrorAction Stop).Source }

$action  = New-ScheduledTaskAction -Execute $python -Argument "-m desktop_agent serve" -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "DesktopAgent" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Desktop Agent: scheduled agents and reminders" -Force | Out-Null

Write-Host "Desktop Agent will now start each time you sign in." -ForegroundColor Green
Write-Host "Start it now without signing out:  Start-ScheduledTask -TaskName DesktopAgent"
