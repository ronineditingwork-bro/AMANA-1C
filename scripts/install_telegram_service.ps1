# Stavit uvedomlenia v Telegram o novykh zakazakh kak zadachu Planirovshchika zadanii Windows:
# zapuskaetsya sama pri vkhode v Windows, rabotaet v fone bez otkrytogo okna,
# sama perezapuskaetsya raz v minutu, esli vdrug upadet (naprimer, propadet svyaz s 1C).
#
# Zapuskat odin raz, iz papki AMANA-1C:
#   powershell -ExecutionPolicy Bypass -File scripts\install_telegram_service.ps1
#
# Pered etim local_agent\.env dolzhen byt zapolnen (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) -
# sm. README.md, razdel "Uvedomleniya v Telegram o novykh zakazakh".

$ErrorActionPreference = "Stop"

$taskName = "AMANA-1C Telegram Notify"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $projectRoot "local_agent\.env"

if (-not (Test-Path $envFile)) {
    Write-Host "Ne nayden local_agent\.env. Snachala nastroyte bota:"
    Write-Host "  copy local_agent\.env.example local_agent\.env"
    Write-Host "  notepad local_agent\.env"
    exit 1
}

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Host "Ne nayden python v PATH. Ustanovite Python i povtorite."
    exit 1
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "local_agent\telegram_notify.py" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn

$settingsParams = @{
    RestartCount = 999
    RestartInterval = (New-TimeSpan -Minutes 1)
    ExecutionTimeLimit = (New-TimeSpan)
    MultipleInstances = "IgnoreNew"
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$taskParams = @{
    TaskName = $taskName
    Action = $action
    Trigger = $trigger
    Settings = $settings
    Description = "Uvedomleniya v Telegram o novykh zakazakh klientov 1C (AMANA-1C)."
}
Register-ScheduledTask @taskParams | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "Gotovo: sluzhba '$taskName' sozdana i zapushchena."
Write-Host "Teper budet zapuskatsya sama pri kazhdom vkhode v Windows."
Write-Host "Proverit status: Get-ScheduledTask -TaskName ""AMANA-1C Telegram Notify"" | Get-ScheduledTaskInfo"
Write-Host "Snyat sovsem: powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1"
