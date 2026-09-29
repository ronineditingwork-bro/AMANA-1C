# Снимает службу уведомлений в Telegram, поставленную install_telegram_service.ps1.
# Запускать из папки AMANA-1C:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1

$taskName = "AMANA-1C Telegram Notify"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Служба '$taskName' не найдена — уже снята или не была установлена."
    exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Служба '$taskName' остановлена и снята."
