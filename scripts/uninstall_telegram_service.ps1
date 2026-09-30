# Snimaet sluzhbu uvedomlenii v Telegram, postavlennuyu install_telegram_service.ps1.
# Odin magazin (staroe povedenie):
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1
# Konkretnyy magazin:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_telegram_service.ps1 -Store aerodromnaya

param(
    [string]$Store
)

$taskName = if ($Store) { "AMANA-1C Telegram Notify - $Store" } else { "AMANA-1C Telegram Notify" }
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Sluzhba '$taskName' ne naydena - uzhe snyata ili ne byla ustanovlena."
    exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Sluzhba '$taskName' ostanovlena i snyata."
