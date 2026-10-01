# Stavit svodku o postupleniyakh deneg (bank + kassa + ekvairing) kak ezhednevnuyu zadachu
# Planirovshchika zadanii Windows: zapuskaetsya raz v den v zadannoe vremya, podvodit itog
# za segodnya i zavershaetsya (eto ne postoyanno rabotayushchiy protsess, v otlichie ot
# install_telegram_service.ps1).
#
# Odin magazin (staroe povedenie, local_agent\.env):
#   powershell -ExecutionPolicy Bypass -File scripts\install_daily_payments_service.ps1 -At 20:00
#
# Neskolko magazinov/baz 1C: ukazhite imya papki v local_agent\stores\:
#   powershell -ExecutionPolicy Bypass -File scripts\install_daily_payments_service.ps1 -At 20:00 -Store aerodromnaya
#
# Pered etim nuzhnyy .env dolzhen byt zapolnen (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) -
# sm. README.md.
# Trebuet zapuska ot imeni administratora (Register-ScheduledTask inache otkazyvaet v dostupe).

param(
    [string]$At = "20:00",
    [string]$PythonExe,
    [string]$Store
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($Store) {
    $taskName = "AMANA-1C Daily Payments - $Store"
    $envFile = Join-Path $projectRoot "local_agent\stores\$Store\.env"
    $scriptArgs = "local_agent\daily_payments.py $Store"
} else {
    $taskName = "AMANA-1C Daily Payments"
    $envFile = Join-Path $projectRoot "local_agent\.env"
    $scriptArgs = "local_agent\daily_payments.py"
}

if (-not (Test-Path $envFile)) {
    Write-Host "Ne nayden $envFile. Snachala nastroyte (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)."
    exit 1
}

$pythonExe = $PythonExe
if (-not $pythonExe) {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Host "Ne nayden python v PATH. Ustanovite Python i povtorite."
    exit 1
}
if ($pythonExe -like "*\WindowsApps\python.exe") {
    # Eto zaglushka Microsoft Store, ona ne rabotaet nadezhno vnutri Planirovshchika zadanii.
    $real = Get-ChildItem "$env:LOCALAPPDATA\Python" -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($real) {
        $pythonExe = $real.FullName
    } else {
        Write-Host "Nayden tolko yarlyk Python iz Microsoft Store (WindowsApps), on ne podkhodit dlya sluzhby."
        Write-Host "Zapustite skript s parametrom -PythonExe i ukazhite put yavno."
        exit 1
    }
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptArgs -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$taskParams = @{
    TaskName = $taskName
    Action = $action
    Trigger = $trigger
    Settings = $settings
    Description = "Ezhednevnaya svodka v Telegram o postupleniyakh deneg (bank/kassa/ekvairing), AMANA-1C."
}
Register-ScheduledTask @taskParams | Out-Null

Write-Host ""
Write-Host "Gotovo: zadacha '$taskName' sozdana, budet zapuskatsya kazhdyy den v $At."
Write-Host "Proverit: Get-ScheduledTask -TaskName ""$taskName"" | Get-ScheduledTaskInfo"
Write-Host "Zapustit seychas dlya proverki: Start-ScheduledTask -TaskName ""$taskName"""
if ($Store) {
    Write-Host "Snyat sovsem: Unregister-ScheduledTask -TaskName ""$taskName"" -Confirm:`$false"
} else {
    Write-Host "Snyat sovsem: Unregister-ScheduledTask -TaskName ""$taskName"" -Confirm:`$false"
}
