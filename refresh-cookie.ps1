$ErrorActionPreference = 'Stop'
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# Refresh cookie.txt from WeChat's local Chromium cookie store.
# The cookie DB is exclusively locked while WeChat's webview containers run,
# so we briefly stop WeChatAppEx (page/mini-program containers, NOT the chat
# client) and copy the DB in the short window before it respawns.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here '.venv\Scripts\python.exe'
$extractor = Join-Path $here 'tools\extract_cookie.py'
$profilesRoot = Join-Path $env:APPDATA 'Tencent\xwechat\radium\web\profiles'
$localState = Join-Path $env:APPDATA 'Tencent\xwechat\radium\web\Local State'

if (-not (Test-Path $py)) { Write-Host '[x] .venv missing, run setup.cmd first'; exit 1 }
if (-not (Test-Path $profilesRoot)) { Write-Host "[x] WeChat profile not found: $profilesRoot"; exit 1 }
if (-not (Test-Path $localState)) { Write-Host "[x] WeChat Local State not found: $localState"; exit 1 }

$tmp = Join-Path $env:TEMP ('tj_cookie_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    $copied = 0
    foreach ($prof in Get-ChildItem $profilesRoot -Directory -ErrorAction SilentlyContinue) {
        $src = Join-Path $prof.FullName 'Network\Cookies'
        if (-not (Test-Path $src)) { continue }
        $dst = Join-Path $tmp ('cookies_' + $prof.Name)
        for ($i = 0; $i -lt 40; $i++) {
            Get-Process WeChatAppEx -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            try {
                $fs = [IO.File]::Open($src, 'Open', 'Read', 'ReadWrite')
                $o = [IO.File]::Create($dst)
                $fs.CopyTo($o); $o.Close(); $fs.Close()
                $copied++
                break
            } catch { Start-Sleep -Milliseconds 150 }
        }
    }
    Write-Host "[*] copied $copied cookie databases"

    & $py $extractor $tmp $localState (Join-Path $here 'cookie.txt')
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { exit $rc }
    Write-Host ''
    Write-Host '[*] verifying with doctor ...'
    & (Join-Path $here 'tjh.cmd') doctor
    exit $LASTEXITCODE
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
