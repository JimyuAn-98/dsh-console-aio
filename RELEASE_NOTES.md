# Release Notes

## v0.2.1 (未发布)

### 新增
- **隧道配置向导（替代手改 config.json）**
  - 配置对话框升级为分组向导：① 公网中转服务器 ② 本机 dsh ③ 隧道参数 ④ 轮询
  - 内置 3 个场景模板（在家→中继 / 实验室→直连实验室dsh / 本机→中继反向），一键填充端口映射
  - 支持在界面里直接编辑 forward_ports / lab_server / lab_user / lab_port / reverse_port（原来只能手改 JSON）
  - 新增"测试 SSH 连接"按钮：填好服务器即可在线验证免密能否连通
  - 每个字段带灰色帮助文字，降低配置门槛（面向使用者）
- **一键安装 dsh（辅助全新环境）**
  - 顶部新增"安装 dsh"按钮，打开安装向导
  - 填 dsh 仓库地址（默认官方 deepseek-harness）与目标目录
  - 自动环境预检（git / node / npm / pnpm 是否可用，缺失会明确提示）
  - 后台流式执行 clone → pnpm install → pnpm build
  - 安装完成后自动把 dash_repo 写入 config.json（重启生效）

## v0.1.0 (草案)

首个开源版本。把 dsh 日常的 SSH 隧道管理、本机 dsh 启停、服务健康监控封装成一个零依赖的 Windows GUI。

### 新增
- **隧道引擎全量 Python 化（v0.2）**
  - 新增 tunnel_mgr.py：纯 Python SSH 隧道管理器（forward/reverse、start/persist/stop、断线重连）
  - dsh-tunnel / connect-lab-dsh / dsh-tunnel-reverse 三张卡片全部改由 Python 建隧道
  - update-dsh 改为纯 Python：git fetch/pull + pnpm install/build + 重启 GUI（流式日志）
  - 旧的 4 个 .ps1 已收进 legacy/，不再被界面调用
- **操控区（5 张卡片）**
  - 本机 dsh：一键 启动 / 停止（后台 pnpm dsh web，匹配 dsh+web 进程精确停止）
  - 三条 SSH 隧道：启动 / 常驻 / 停止（调用对应 .ps1）
  - update-dsh：一键运行完整更新（git 拉取 → 构建 → 重启，实时滚动日志）
- **健康监控（两层）**
  - 本机端口行：探测本机监听端口（每 4s）
  - 公网服务器 反向隧道行：SSH 直查公网中转服务器上反向隧道监听状态（每 20s）——
    这才是"隧道是否配置成功"的真实指标
  - 窗口全程不弹控制台（CREATE_NO_WINDOW）
- **配置外置**
  - 所有可调项集中在 config.json（IP / 用户名 / 仓库路径 / 端口 / 轮询间隔）
  - GUI 右上角【配置】对话框可编辑常用项
  - 无 config.json 时自动回退内置默认值
- **零依赖**：仅 Python 标准库（tkinter）

### 修复
- 修复 bat 启动器闪退（UTF-8 中文被 cmd 按 GBK 解析 + if 块内括号干扰配对）
- 修复子进程输出 gbk 解码崩溃（errors=replace）
- 修复 update-dsh 被误当作可启停（它是一次性更新，只有一个运行按钮）
- 修复 pythonw 环境下监控子进程弹出控制台窗口

### 使用
见 README（中英双语）。