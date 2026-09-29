# Ставит уведомления в Telegram о новых заказах как задачу Планировщика заданий Windows:
# запускается сама при входе в Windows, работает в фоне без открытого окна,
# сама перезапускается раз в минуту, если вдруг упадёт (например, пропадёт связь с 1С).
#
# Запускать один раз, из папки AMANA-1C:
#   powershell -ExecutionPolicy Bypass -File scripts\install_telegram_service.ps1
#
# Перед этим local_agent\.env должен быть заполнен (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) —
# см. README.md, раздел «Уведомления в Telegram о новых заказах».

$ErrorActionPreference = "Stop"

$taskName = "AMANA-1C Telegram Notify"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $projectRoot "local_agent\.env"

if (-not (Test-Path $envFile)) {
    Write-Host "Не найден local_agent\.env. Сначала настройте бота:" -ForegroundColor Yellow
    Write-Host "  copy local_agent\.env.example local_agent\.env"
    Write-Host "  notepad local_agent\.env   (впишите TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID)"
    exit 1
}

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Host "Не найден python в PATH. Установите Python и повторите." -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "local_agent\telegram_notify.py" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# На случай повторного запуска этого скрипта — сначала снимаем старую версию задачи, если есть.
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Уведомления в Telegram о новых заказах клиентов 1С (AMANA-1C). Ставится и снимается скриптами в scripts/." | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host "Готово: служба '$taskName' создана и запущена." -ForegroundColor Green
Write-Host "Теперь будет запускаться сама при каждом входе в Windows, окно PowerShell для неё больше не нужно."
Write-Host "Проверить статус: Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "Остановить совсем: powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1"
