# Stavit uvedomlenia v Telegram o novykh zakazakh kak zadachu Planirovshchika zadanii Windows:
# zapuskaetsya sama pri vkhode v Windows, rabotaet v fone bez otkrytogo okna,
# sama perezapuskaetsya raz v minutu, esli vdrug upadet (naprimer, propadet svyaz s 1C).
#
# Odin magazin (staroe povedenie, local_agent\.env):
#   powershell -ExecutionPolicy Bypass -File scripts\install_telegram_service.ps1
#
# Neskolko magazinov/baz 1C: ukazhite imya papki v local_agent\stores\ -
# nastroyki berutsya iz local_agent\stores\<imya>\.env, sozdaetsya otdelnaya sluzhba:
#   powershell -ExecutionPolicy Bypass -File scripts\install_telegram_service.ps1 -Store aerodromnaya
#
# Pered etim nuzhnyy .env dolzhen byt zapolnen (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, dlya
# magazina eshche ONEC_ODATA_URL/ONEC_USER/ONEC_PASSWORD i STORE_NAME) -
# sm. README.md, razdel "Uvedomleniya v Telegram o novykh zakazakh".
# Trebuet zapuska ot imeni administratora (Register-ScheduledTask inache otkazyvaet v dostupe).

param(
    [string]$PythonExe,
    [string]$Store
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($Store) {
    $taskName = "AMANA-1C Telegram Notify - $Store"
    $envFile = Join-Path $projectRoot "local_agent\stores\$Store\.env"
    $scriptArgs = "local_agent\telegram_notify.py $Store"
} else {
    $taskName = "AMANA-1C Telegram Notify"
    $envFile = Join-Path $projectRoot "local_agent\.env"
    $scriptArgs = "local_agent\telegram_notify.py"
}

if (-not (Test-Path $envFile)) {
    Write-Host "Ne nayden $envFile. Snachala nastroyte:"
    if ($Store) {
        Write-Host "  copy local_agent\stores\$Store\.env.example local_agent\stores\$Store\.env"
        Write-Host "  notepad local_agent\stores\$Store\.env"
    } else {
        Write-Host "  copy local_agent\.env.example local_agent\.env"
        Write-Host "  notepad local_agent\.env"
    }
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
    # Eto zaglushka Microsoft Store, ona ne rabotaet nadezhno vnutri Planirovshchika
    # zadanii. Ishchem nastoyashchiy python.exe ryadom (obychno v AppData\Local\Python).
    $real = Get-ChildItem "$env:LOCALAPPDATA\Python" -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($real) {
        $pythonExe = $real.FullName
    } else {
        Write-Host "Nayden tolko yarlyk Python iz Microsoft Store (WindowsApps), on ne podkhodit dlya sluzhby."
        Write-Host "Nastoyashchiy python.exe ne nayden avtomaticheski v $env:LOCALAPPDATA\Python."
        Write-Host "Zapustite skript s parametrom -PythonExe i ukazhite put yavno, naprimer:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\install_telegram_service.ps1 -PythonExe C:\Path\To\python.exe"
        exit 1
    }
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptArgs -WorkingDirectory $projectRoot
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
Write-Host "Proverit status: Get-ScheduledTask -TaskName ""$taskName"" | Get-ScheduledTaskInfo"
if ($Store) {
    Write-Host "Snyat sovsem: powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1 -Store $Store"
} else {
    Write-Host "Snyat sovsem: powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1"
}
