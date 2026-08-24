# connect-lab-dsh.ps1 — 实验室局域网内连接 204 的 dsh GUI（正向隧道）
# 访问: http://127.0.0.1:3090（= 204 的 dsh）
#
# 用法（Windows PowerShell）:
#   powershell -ExecutionPolicy Bypass -File connect-lab-dsh.ps1            # 后台隧道
#   powershell -ExecutionPolicy Bypass -File connect-lab-dsh.ps1 -Persist   # 常驻重连
#   powershell -ExecutionPolicy Bypass -File connect-lab-dsh.ps1 -Stop      # 关闭
#
# 前置: Windows 的 ~/.ssh/id_ed25519 已授权到 204 的 YOUR_USER 用户
#（Windows 没有 ssh-copy-id，手动装公钥）:
#   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh YOUR_USER@YOUR_LAB_IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"

param(
    [switch]$NoBrowser,
    [switch]$Persist,
    [switch]$Loop,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'

# ── 配置（改这里）────────────────────────
$ServerHost = 'YOUR_LAB_IP'    # 实验室服务器
$ServerUser = 'YOUR_USER'            # 服务器用户名
$LocalGUI   = 3090             # 本机浏览器访问的端口
$RemoteGUI  = 3090             # 服务器上 dsh GUI 监听的端口
# ─────────────────────────────────────────

$KeyPath = Join-Path $env:USERPROFILE '.ssh\id_ed25519'
$LogFile = Join-Path $env:TEMP 'dsh-lab-tunnel.log'
$Ssh     = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$Target  = "$ServerUser@$ServerHost"

if ($Stop) {
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Target*" } |
        ForEach-Object { taskkill /PID $_.ProcessId /F | Out-Null; $n++ }
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*connect-lab-dsh.ps1*' -and $_.CommandLine -like '*-Loop*' } |
        ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }
    if ($n -gt 0) { Write-Host "已关闭 $n 个隧道进程。" } else { Write-Host '没有正在运行的隧道。' }
    exit 0
}

$Common = @(
    '-N',
    '-i', $KeyPath,
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ConnectTimeout=10'
)
$Fwd = @('-L', "${LocalGUI}:127.0.0.1:${RemoteGUI}")

# 常驻循环（由 -Persist 派生的隐藏窗口运行，需密钥认证）
if ($Loop) {
    while ($true) {
        & $Ssh @Common @Fwd '-o' 'BatchMode=yes' $Target *>> $LogFile
        Start-Sleep -Seconds 5
    }
    exit 0
}

# 检测免密（注意: 不能复用 $Common —— 它带 -N 会挂住，探针必须独立）
$keyAuth = $false
$ErrorActionPreference = 'Continue'
& $Ssh -i $KeyPath -o BatchMode=yes -o ConnectTimeout=5 $Target 'exit 0' 2>$null
if ($LASTEXITCODE -eq 0) { $keyAuth = $true }
$ErrorActionPreference = 'Stop'

function Test-Port([int]$Port) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); return $true } catch { return $false }
    finally { $c.Close() }
}

$needle = "-L ${LocalGUI}:127.0.0.1:${RemoteGUI}"
$running = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$Target*" -and $_.CommandLine -like "*$needle*" } |
    Select-Object -First 1

if ($running) {
    Write-Host "隧道已在运行（PID $($running.ProcessId)）。"
} else {
    $old = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Target*" } | Select-Object -First 1
    if ($old) {
        Write-Host "检测到旧配置的隧道进程（PID $($old.ProcessId)），自动关闭并重建…"
        taskkill /PID $($old.ProcessId) /F | Out-Null
        Start-Sleep -Seconds 1
    }

    if ($Persist -and -not $keyAuth) {
        Write-Host '提示: 常驻模式需要密钥认证。请先装公钥（见脚本头部注释），本次改用前台模式。' -ForegroundColor Yellow
        $Persist = $false
    }

    if ($Persist) {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $PSCommandPath, '-NoBrowser', '-Loop'
        )
        Write-Host '常驻隧道已启动（断线 5 秒后自动重连）。'
    } elseif ($keyAuth) {
        Start-Process -FilePath $Ssh -WindowStyle Hidden -ArgumentList (@($Common + $Fwd + @($Target))) `
            -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err"
        Write-Host '隧道已启动（后台运行）。'
    } else {
        # 无密钥: 前台运行，密码提示可见；窗口保持打开即隧道运行中
        Write-Host "连接 $Target ... 按提示输入密码。窗口保持打开即隧道运行中，按 Ctrl+C 关闭。"
        & $Ssh @Common @Fwd $Target
        Write-Host '隧道已关闭。'
        exit 0
    }

    for ($i = 0; $i -lt 8; $i++) {
        if (Test-Port $LocalGUI) { break }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Port $LocalGUI)) {
        Write-Host '隧道端口暂未就绪，日志见:' -ForegroundColor Yellow
        Write-Host "  $LogFile" -ForegroundColor Yellow
        Write-Host '常见原因: 204 的 dsh 没起 / 密码输错 / 防火墙。'
    }
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$LocalGUI"
    Write-Host "浏览器已打开 http://127.0.0.1:$LocalGUI"
}
