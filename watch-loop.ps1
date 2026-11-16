$ErrorActionPreference = 'Continue'
# Keep the watcher alive: restart it if it exits for any reason.
# Meant to be started by the scheduled task (hidden window).
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$watch = Join-Path $here 'watch.cmd'

while ($true) {
    if (-not (Test-Path $watch)) { Start-Sleep -Seconds 60; continue }
    & $watch
    $code = $LASTEXITCODE
    $line = "{0} WARN    watcher exited (code {1}), restarting in 60s" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $code
    [IO.File]::AppendAllText((Join-Path $here 'watch.log'), $line + "`r`n", (New-Object Text.UTF8Encoding($false)))
    Start-Sleep -Seconds 60
}
