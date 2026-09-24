# Создаёт на рабочем столе ярлык «Claude — Amana 1C», который открывает чат с Claude
# сразу в папке проекта. Запускать один раз из папки AMANA-1C:
#   powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1

$target = Join-Path $PSScriptRoot "open_claude.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Claude - Amana 1C.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = Split-Path $target
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,15"
$shortcut.Description = "Открыть чат с Claude для отчётов и заявок по 1С"
$shortcut.Save()

Write-Host "Готово: ярлык создан на рабочем столе — «Claude - Amana 1C»."
