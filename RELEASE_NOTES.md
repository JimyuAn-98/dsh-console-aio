# Release Notes

## v0.4.0 (未发布)

### 新增：多部署管理（dsh 控制台新方向）

- 架构：dsh_data.py 新增 DshRemote 抽象（本机直接文件系统 / 远程 SSH 只读命令 + 文件拉取），部署清单存 config.json 的 deployments（gitignored）
- 部署管理窗口（mgmt_deployments.py）：部署 CRUD、连接测试、只读状态总览（dsh 版本 / 会话数 / 大小 / 插件数 / profile 数 / agent 预设数 / 在线离线）
- **页面部署联动**：8 个管理页（会话/Agent/Profile/插件/看板/用量/LLM/主题）数据源随顶部部署选择器切换（DshRemote），远程不可达时优雅提示
- **总览部署状态卡片**：总览页汇总所有部署快照（版本/会话/插件/在线离线）
- **SSH 密钥管理**（mgmt_keys）：安全红线——私钥内容绝不读取/展示/复制，只显示文件名/时间/指纹（ssh-keygen -lf）；公钥可查看复制；生成 ed25519 密钥
- 移除顶部"dsh 管理"菜单（全页面化后左导航即入口）
- 安全：远程默认只读，ssh BatchMode + 超时；写操作留待阶段 B

## v0.3.0 (未发布)

### 新增：dsh 管理（v2 架构）

- 架构：数据层 dsh_data.py（~/.dsh 各数据域，零依赖最小 YAML 解析器）+ 管理窗口模块 mgmt_*.py + 主程序顶部“dsh 管理”菜单动态加载
- 会话与工作区管理：按工作目录分组浏览/归档/恢复/删除（二次确认）
- Agent 模式管理：浏览 preset 与说明
- Profile 管理：列出/复制/删除 profile
- 插件管理：浏览已装 bundle、dsh plugin 官方命令安装/卸载、patch 层停用/启用
- 任务看板：ledger + scheduler 只读展示
- 模型用量统计：解压 session 聚合 token（按模型/天），价格估算（内置单价可编辑）
- LLM 配置：默认模型切换 + 自定义 provider 浏览（密钥仅环境变量名提示）
- 主题外观：settings.yaml UI 开关切换
- 备份与运维：~/.dsh 一键备份（排除凭据）、日志浏览、凭据存在性提示
- 版本管理（关于与更新）：显示当前版本、检查更新（读远程 version.json）、更新日志、一键自动更新（源码版：下载→备份→替换→重启；安装版：引导下载新安装包）
- **打包发布**：PyInstaller 单文件 exe + Inno Setup 安装包（中文向导、开始菜单/桌面快捷方式、卸载、升级）；首次启动自动引导配置（可跳过）

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
- **环境检查独立窗口（运维辅助）**
  - 顶部新增"环境"按钮，独立窗口查看 git/node/npm/pnpm 版本
  - 显示推荐基准版本（直接写版本号：git 2.53 / node v24.19 / npm 11.17 / pnpm 11.7）
  - 每个工具带 更新/安装/卸载 三按钮：点击先说明将执行什么，确认后才执行
  - 更新：git 自带升级器 / npm i -g npm@latest / pnpm add -g pnpm@latest；node 提示用 nvm 或官网
  - 更新/安装 pnpm 时自动把全局 bin 目录注入 PATH（解决新版 pnpm 的 PATH 检查报错）
  - 安装：git/node 打开官网下载页；pnpm 用 npm i -g pnpm；npm 随 Node.js
  - 卸载：git/node 引导到 Windows 设置-应用-安装的应用；npm/pnpm 用命令行卸载（npm uninstall -g）
  - 安装 dsh 的目标目录支持系统文件夹选择弹窗（浏览…）
  - 安全：早期含真实 IP 的历史提交已用 git-filter-repo 重写脱敏并 force push

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