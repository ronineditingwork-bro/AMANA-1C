# Udalyaet ezhednevnuyu zadachu svodki o postupleniyakh deneg, sozdannuyu
# install_daily_payments_service.ps1.
#
# Odin magazin:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_daily_payments_service.ps1
# Konkretnyy magazin:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_daily_payments_service.ps1 -Store aerodromnaya

param(
    [string]$Store
)

if ($Store) {
    $taskName = "AMANA-1C Daily Payments - $Store"
} else {
    $taskName = "AMANA-1C Daily Payments"
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Zadacha '$taskName' ne nayena (uzhe udalena ili ne byla sozdana)."
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Zadacha '$taskName' udalena."
