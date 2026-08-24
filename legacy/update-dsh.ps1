# update-dsh.ps1 — 更新 Windows 原生 dsh: git 拉取 → 依赖 → 构建 → 重启 GUI
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File C:\Users\YOUR_NAME\update-dsh.ps1
#
# ⚠ 会先停掉本机正在运行的 dsh web（当前 Windows dsh 会话会断），构建后自动重启。

param()
$ErrorActionPreference = 'Stop'

# ── 配置（改这里）────────────────────────
$Repo    = 'D:/path/to/deepseek-harness'   # Windows 上仓库位置
$GUIPort = 3080                                 # 本机 dsh GUI 端口
# ─────────────────────────────────────────

$LogDir  = Join-Path $env:TEMP 'dsh-update'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$GuiLog  = Join-Path $LogDir 'dsh-web.log'

function Assert-Ok([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "步骤失败: $step (exit $LASTEXITCODE)" }
}

Set-Location $Repo

# [1] 停掉当前 GUI（匹配命令行里带 "web --port 3080" 的 node 进程，含 pnpm 包装层）
$targets = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*web --port $GUIPort*" }
foreach ($p in $targets) {
    Write-Host "停止 dsh web (PID $($p.ProcessId))"
    taskkill /PID $($p.ProcessId) /T /F | Out-Null
}
Start-Sleep -Seconds 2

# [2] 拉取最新代码
$branch = (git branch --show-current).Trim()
Write-Host "→ git fetch + pull (分支 $branch)…"
git fetch origin
Assert-Ok 'git fetch'
git pull --ff-only origin $branch
Assert-Ok 'git pull'

# [3] 依赖 + 构建
Write-Host '→ pnpm install…'
pnpm install
Assert-Ok 'pnpm install'
Write-Host '→ pnpm run build（耗时较长）…'
pnpm run build
Assert-Ok 'pnpm run build'

# [4] 重启 GUI（后台，隐藏窗口）
Write-Host '→ 启动 dsh web…'
Start-Process -FilePath 'pnpm.cmd' -ArgumentList @('dsh', 'web', '--port', "$GUIPort") `
    -WorkingDirectory $Repo -WindowStyle Hidden `
    -RedirectStandardOutput $GuiLog -RedirectStandardError "$GuiLog.err"

Write-Host ''
Write-Host "✓ 更新完成。访问 http://127.0.0.1:$GUIPort"
Write-Host "GUI 日志: $GuiLog"
