param([switch]$Force)

$ErrorActionPreference = 'Continue'
try { chcp 65001 | Out-Null } catch { }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $here 'push.log'
$remote = 'root@10.30.41.183'
$port = 22085
$flag = '/ics2/tj-lecture/NEED_COOKIE'

function Log([string]$msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    try {
        [IO.File]::AppendAllText($log, $line + "`r`n", (New-Object Text.UTF8Encoding($false)))
    } catch { }
}

Log '[*] 0/2 检查服务器是否需要新 cookie ...'
$probe = ssh -o BatchMode=yes -o ConnectTimeout=10 -p $port $remote "test -f $flag && echo NEED || echo OK" 2>&1
if (-not $Force -and ($probe -notmatch 'NEED')) {
    Log '[=] 服务器 cookie 正常，跳过（-Force 可强制推送）'
    exit 0
}
Log '[!] 服务器缺 cookie，开始续期'

Log '[*] 1/2 从微信本地库续期 ...'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'refresh-cookie.ps1')
if ($LASTEXITCODE -ne 0) {
    Log '[x] 续期失败：微信里可能还没重新登录，先在电脑微信打开一次讲座页'
    exit 1
}

Log '[*] 2/2 推送到服务器 ...'
scp -o BatchMode=yes -P $port (Join-Path $here 'cookie.txt') "${remote}:/ics2/tj-lecture/cookie.txt"
if ($LASTEXITCODE -ne 0) {
    Log '[x] 推送失败：检查 SSH 是否可连'
    exit 1
}

Log '[ok] 已推送，服务器守护会在 5 分钟内自动加载'
exit 0
