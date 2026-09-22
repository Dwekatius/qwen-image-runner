$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$target = Join-Path $root "Launch.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "Qwen Image Runner.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = $root
$sc.Description = "Qwen Image Runner - local image studio for Qwen-Image-2.1"
$sc.Save()
Write-Output "shortcut created: $link"
