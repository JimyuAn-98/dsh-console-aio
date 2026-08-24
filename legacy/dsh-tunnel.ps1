# dsh-tunnel.ps1 — 在家一键打通 185 上的三个转发口（正向隧道）
# 185 上的三个口分属:
#   8090 → 204 的 dsh GUI（204→185 反向隧道）
#   8022 → 204 的 SSH   （在家 scp/同步到 204 用）
#   8091 → Windows 本机 dsh GUI（Windows→185 反向隧道）
#
# 用法（在 Windows PowerShell 里）:
#   powershell -ExecutionPolicy Bypass -File C:\Users\1\dsh-tunnel.ps1
#   powershell -ExecutionPolicy Bypass -File C:\Users\1\dsh-tunnel.ps1 -Persist   # 断线自动重连
#   powershell -ExecutionPolicy Bypass -File C:\Users\1\dsh-tunnel.ps1 -NoBrowser # 不自动开浏览器
#   powershell -ExecutionPolicy Bypass -File C:\Users\1\dsh-tunnel.ps1 -Stop      # 关闭隧道
#
# 前置: Windows 的 ~/.ssh/id_ed25519 已授权到 185 的 tunnel 用户。

param(
    [switch]$NoBrowser,
    [switch]$Persist,
    [switch]$Loop,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'

# ── 配置（改这里）────────────────────────────────────────
$PublicIP   = '185.238.250.148'   # 公网服务器
$TunnelUser = 'tunnel'            # 公网服务器上的隧道用户
# 三条正向转发: 本机端口:目标=185的对应端口
$Forwards = @(
    '8090:127.0.0.1:8090',   # → 204 的 dsh GUI
    '8022:127.0.0.1:8022',   # → 204 的 SSH（scp/同步用）
    '8091:127.0.0.1:8091'    # → Windows 本机 dsh GUI
)
$GUIPort = 8090               # 浏览器访问 204 GUI 的本机端口（等待就绪用）
# ─────────────────────────────────────────────────────────

$KeyPath = Join-Path $env:USERPROFILE '.ssh\id_ed25519'
$LogFile = Join-Path $env:TEMP 'dsh-tunnel.log'
$Ssh     = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$Target  = "$TunnelUser@$PublicIP"

if ($Stop) {
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Target*" } |
        ForEach-Object { taskkill /PID $_.ProcessId /F | Out-Null; $n++ }
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*dsh-tunnel.ps1*' -and $_.CommandLine -like '*-Loop*' } |
        ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }
    if ($n -gt 0) { Write-Host "已关闭 $n 个隧道进程。" } else { Write-Host '没有正在运行的隧道。' }
    exit 0
}

if (-not (Test-Path $KeyPath)) {
    Write-Host "找不到密钥 $KeyPath — 先在 Windows 生成并授权到 185:" -ForegroundColor Yellow
    Write-Host "  ssh-keygen -t ed25519 -f $KeyPath -N `"`" -C `"hjy-win`"" -ForegroundColor Yellow
    Write-Host "  type $KeyPath.pub | ssh $Target `"mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`"" -ForegroundColor Yellow
    exit 1
}

# 公共 ssh 参数
$Common = @(
    '-N',
    '-i', $KeyPath,
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ConnectTimeout=10',
    '-o', 'BatchMode=yes'
)
$Fwd = @()
foreach ($f in $Forwards) { $Fwd += '-L'; $Fwd += $f }

# 常驻循环模式（由 -Persist 派生的隐藏窗口运行）
if ($Loop) {
    while ($true) {
        & $Ssh @Common @Fwd $Target *>> $LogFile
        Start-Sleep -Seconds 5
    }
    exit 0
}

function Test-Port([int]$Port) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        $c.Connect('127.0.0.1', $Port)
        return $true
    } catch {
        return $false
    } finally {
        $c.Close()
    }
}

function Get-OurSshProcess {
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$KeyPath*" -and $_.CommandLine -like "*$Target*" } |
        Select-Object -First 1
}

$needle = "-L ${Forwards[0]}"
$running = Get-OurSshProcess | Where-Object { $_.CommandLine -like "*$needle*" }

if ($running) {
    Write-Host "隧道已在运行（PID $($running.ProcessId)）。"
} else {
    $old = Get-OurSshProcess
    if ($old) {
        Write-Host "检测到旧配置的隧道进程（PID $($old.ProcessId)），自动关闭并重建…"
        taskkill /PID $($old.ProcessId) /F | Out-Null
        Start-Sleep -Seconds 1
    }

    if ($Persist) {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $PSCommandPath, '-NoBrowser', '-Loop'
        )
        Write-Host '常驻隧道已启动（断线 5 秒后自动重连，窗口可关闭）。'
    } else {
        Start-Process -FilePath $Ssh -WindowStyle Hidden -ArgumentList (@($Common + $Fwd + @($Target))) `
            -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err"
        Write-Host '隧道已启动（后台运行）。'
    }

    for ($i = 0; $i -lt 8; $i++) {
        if (Test-Port $GUIPort) { break }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Port $GUIPort)) {
        Write-Host '隧道端口暂未就绪，日志见:' -ForegroundColor Yellow
        Write-Host "  $LogFile" -ForegroundColor Yellow
        Write-Host '常见原因: 185 上反向隧道没起来 / IP 填错 / 防火墙。'
    }
}

# 打开 204 GUI（本机 8090）
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$GUIPort"
    Write-Host "浏览器已打开 http://127.0.0.1:$GUIPort （204 的 dsh）"
}
Write-Host "访问: http://127.0.0.1:8090 = 204 dsh | http://127.0.0.1:8091 = Windows dsh | scp -P 8022 → 204"
