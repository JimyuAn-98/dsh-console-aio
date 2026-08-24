# dsh-tunnel-reverse.ps1 — Windows → 185 反向隧道（手机/外部访问本机 dsh）
# 访问: http://YOUR_PUBLIC_IP:8091（映射到本机 127.0.0.1:3090）
#
# 用法（Windows PowerShell）:
#   powershell -ExecutionPolicy Bypass -File dsh-tunnel-reverse.ps1            # 后台隧道
#   powershell -ExecutionPolicy Bypass -File dsh-tunnel-reverse.ps1 -Persist   # 常驻重连（推荐）
#   powershell -ExecutionPolicy Bypass -File dsh-tunnel-reverse.ps1 -Stop      # 关闭
#
# 前置: Windows 的 ~/.ssh/id_ed25519（YOUR_USER-win）已授权到 185 的 tunnel 用户。
# 默认绑定 185 回环（安全）; 想公网直连（手机浏览器），把 -R 的端口前加 0.0.0.0:
#   且 185 sshd 需 GatewayPorts clientspecified。⚠ 无鉴权 GUI 暴露公网风险自负。

param(
    [switch]$NoBrowser,
    [switch]$Persist,
    [switch]$Loop,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'

# ── 配置（改这里）────────────────────────
$PublicIP   = 'YOUR_PUBLIC_IP'   # 公网服务器
$TunnelUser = 'tunnel'            # 公网服务器上的隧道用户
$LocalGUI   = 3080                # 本机 dsh GUI 端口（已从 3090 改到 3080，避免和连 204 的本地转发冲突）
$RemoteGUI  = 8091                # 185 上暴露的端口（8090/8022 已被 204 隧道占用）
# ─────────────────────────────────────────

$KeyPath = Join-Path $env:USERPROFILE '.ssh\id_ed25519'
$LogFile = Join-Path $env:TEMP 'dsh-tunnel-reverse.log'
$Ssh     = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$Target  = "$TunnelUser@$PublicIP"

if ($Stop) {
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Target*" } |
        ForEach-Object { taskkill /PID $_.ProcessId /F | Out-Null; $n++ }
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*dsh-tunnel-reverse.ps1*' -and $_.CommandLine -like '*-Loop*' } |
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
$Fwd = @('-R', "${RemoteGUI}:127.0.0.1:${LocalGUI}")

# 常驻循环（由 -Persist 派生的隐藏窗口运行）
if ($Loop) {
    while ($true) {
        & $Ssh @Common @Fwd '-o' 'BatchMode=yes' $Target *>> $LogFile
        Start-Sleep -Seconds 5
    }
    exit 0
}

# 探测免密（YOUR_USER-win 应已授权到 185）。
# 注意: 不能复用 $Common —— 它带 -N（纯转发不退出），探针会永远挂着。
$keyAuth = $false
$ErrorActionPreference = 'Continue'
& $Ssh -i $KeyPath -o BatchMode=yes -o ConnectTimeout=5 $Target 'exit 0' 2>$null
if ($LASTEXITCODE -eq 0) { $keyAuth = $true }
$ErrorActionPreference = 'Stop'

if (-not $keyAuth) {
    Write-Host '未检测到 185 的免密登录。请先装公钥:' -ForegroundColor Yellow
    Write-Host "  type $KeyPath.pub | ssh $Target `"mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`"" -ForegroundColor Yellow
    exit 1
}

$needle = "-R ${RemoteGUI}:127.0.0.1:${LocalGUI}"
$running = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$Target*" -and $_.CommandLine -like "*$needle*" } |
    Select-Object -First 1

if ($running) {
    Write-Host "反向隧道已在运行（PID $($running.ProcessId)）。"
} else {
    if ($Persist) {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $PSCommandPath, '-NoBrowser', '-Loop'
        )
        Write-Host '常驻反向隧道已启动（断线 5 秒自动重连）。'
    } else {
        Start-Process -FilePath $Ssh -WindowStyle Hidden -ArgumentList (@($Common + $Fwd + @($Target))) `
            -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err"
        Write-Host '反向隧道已启动（后台运行）。'
    }
}

# 反向隧道不自动开浏览器——185 上的是回环绑定，外网 URL 打开也是空白；
# 手机/外部访问请用 SSH 客户端做本地端口转发后访问 127.0.0.1:<转发端口>。
Write-Host "隧道已就绪: 185 的 127.0.0.1:$RemoteGUI → 本机 127.0.0.1:$LocalGUI"
Write-Host "（回环绑定，需经 SSH 端口转发访问；公网直连需 GatewayPorts + 0.0.0.0:，风险自负）"
