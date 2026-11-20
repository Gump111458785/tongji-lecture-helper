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

# 计划任务里 ssh 的 stdin 是永不关闭的句柄，ssh 会一直等它 → 必须 -n（接空设备）。
# 再加一层硬超时，防止 TCP 半开连接把整个任务挂死（2026-11-20 16:42 就卡过一次）。
function Invoke-Cmd {
    param([string]$Exe, [string[]]$ArgList, [int]$Seconds)
    $tag = [guid]::NewGuid().ToString('N')
    $o = Join-Path $here ("_t_$tag.out")
    $e = Join-Path $here ("_t_$tag.err")
    $proc = Start-Process -FilePath $Exe -ArgumentList $ArgList -NoNewWindow -PassThru `
        -RedirectStandardOutput $o -RedirectStandardError $e
    $done = $proc.WaitForExit($Seconds * 1000)
    $text = ''
    if ($done) {
        $text = ((Get-Content $o -Raw -ErrorAction SilentlyContinue) + (Get-Content $e -Raw -ErrorAction SilentlyContinue))
    } else {
        try { $proc.Kill() } catch { }
    }
    Remove-Item $o, $e -Force -ErrorAction SilentlyContinue
    $code = -1
    if ($done) { $code = $proc.ExitCode }
    return [pscustomobject]@{ Done = $done; ExitCode = $code; Text = $text }
}

$sshOpt = @('-n', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
    '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2')

Log '[*] 0/2 检查服务器是否需要新 cookie ...'
$probe = Invoke-Cmd -Exe 'ssh' -Seconds 30 `
    -ArgList ($sshOpt + @('-p', $port, $remote, "test -f $flag && echo NEED || echo OK"))
if (-not $probe.Done) {
    Log '[x] SSH 探测 30 秒无响应（网络不通），本次跳过'
    exit 1
}
if (-not $Force -and ($probe.Text -notmatch 'NEED')) {
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
$push = Invoke-Cmd -Exe 'scp' -Seconds 120 `
    -ArgList (@('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
        '-P', $port, (Join-Path $here 'cookie.txt'), "${remote}:/ics2/tj-lecture/cookie.txt"))
if (-not $push.Done) {
    Log '[x] scp 120 秒无响应，推送失败'
    exit 1
}
if ($push.ExitCode -ne 0) {
    Log '[x] 推送失败：检查 SSH 是否可连'
    exit 1
}

Log '[ok] 已推送，服务器守护会在 5 分钟内自动加载'
exit 0
