# Snimaet sluzhbu uvedomlenii v Telegram, postavlennuyu install_telegram_service.ps1.
# Zapuskat iz papki AMANA-1C:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1

$taskName = "AMANA-1C Telegram Notify"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Sluzhba '$taskName' ne naydena - uzhe snyata ili ne byla ustanovlena."
    exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Sluzhba '$taskName' ostanovlena i snyata."
