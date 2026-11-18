$ErrorActionPreference = 'Stop'
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# Refresh cookie.txt from WeChat's local Chromium cookie store.
# The cookie DB is exclusively locked while WeChat's webview containers run,
# so we briefly stop WeChatAppEx (page/mini-program containers, NOT the chat
# client) and copy the DB in the short window before it respawns.
# 微信偶尔会在我们复制的瞬间写库，导致某个 profile 复制失败；这里整轮重试 3 次。

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
    $targets = @()
    foreach ($prof in Get-ChildItem $profilesRoot -Directory -ErrorAction SilentlyContinue) {
        $src = Join-Path $prof.FullName 'Network\Cookies'
        if (Test-Path $src) { $targets += , @($prof.Name, $src) }
    }

    $copied = 0
    for ($round = 1; $round -le 3; $round++) {
        $copied = 0
        foreach ($t in $targets) {
            $name = $t[0]
            $src = $t[1]
            $dst = Join-Path $tmp ('cookies_' + $name)
            for ($i = 0; $i -lt 60; $i++) {
                Get-Process WeChatAppEx -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
                try {
                    $fs = [IO.File]::Open($src, 'Open', 'Read', 'ReadWrite')
                    $o = [IO.File]::Create($dst)
                    $fs.CopyTo($o); $o.Close(); $fs.Close()
                    $copied++
                    break
                } catch { Start-Sleep -Milliseconds 100 }
            }
        }
        if ($copied -eq $targets.Count) { break }
        Write-Host "[!] round $round copied $copied / $($targets.Count), retrying ..."
        Start-Sleep -Seconds 2
    }
    Write-Host "[*] copied $copied cookie databases"

    if ($copied -eq 0) {
        Write-Host '[x] 一个库都没复制成功：微信可能正在写库，稍后重试，或先完全退出微信'
        exit 1
    }

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
