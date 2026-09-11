# dsh-console-aio

[![Release](https://img.shields.io/github/v/release/JimyuAn-98/dsh-console-aio)](https://github.com/JimyuAn-98/dsh-console-aio/releases)
[![Stars](https://img.shields.io/github/stars/JimyuAn-98/dsh-console-aio)](https://github.com/JimyuAn-98/dsh-console-aio)
[![License](https://img.shields.io/github/license/JimyuAn-98/dsh-console-aio)](LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white)](https://github.com/JimyuAn-98/dsh-console-aio)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt-41CD52?logo=qt&logoColor=white)](requirements.txt)

> 中文 | [English](#english)

**dsh All-In-One 控制台**（Windows GUI，PySide6 亚克力界面，支持深/浅主题）：SSH 隧道管理、本机 dsh 启停/安装/更新、健康监控，以及 17 个页面的 dsh 数据域管理（会话/Agent/Profile/插件/任务/用量/LLM/部署/日志/设置…）。

- 🚀 一键操作：本机 dsh 启停、SSH 隧道（启动/常驻/停止）、dsh 一键更新、全新环境一键安装
- 🖥️ 环境检查：git/node/npm/pnpm 版本与推荐基准，更新/安装/卸载引导
- 📡 健康监控：本机端口 + SSH 直查远端反向隧道，右栏一屏可见（可收起）
- 🗂️ 数据域管理：会话与工作区、Agent 模式、Profile、插件、任务看板、模型用量、LLM 配置、部署管理
- ⚡ 全局通用缓存：所有数据页面接入本地快照缓存与状态指示灯（绿/黄/红），进页秒开呈现，数据源变动按需刷新
- 🪟 系统托盘常驻：支持最小化至 Windows 系统托盘后台运行，鼠标悬停 Tooltip 实时状态监控，右键菜单一键启停 DSH 与隧道
- 🛡️ 全页内联确认：退役全部阻塞式弹窗，采用沉浸式内联确认条（ConfirmBanner），支持快捷键与操作说明
- 🔄 插件管理：官方 `dsh plugin` 安装/卸载、单个更新与「更新全部插件」批量升级（内联确认 + 流式日志）
- 🪵 日志管理：dsh web 输出实时 tail + 过滤 + 着色
- ⚙️ 设置页：全部配置标签页化，保存即热重载（弹窗收敛：极少模态框）
- 现代界面：PySide6 深色亚克力 + 现代列表/卡片组件 + 线程安全 + 一键打包分发

![主界面](docs/screenshots/main.png)

---

## 快速开始

### 方式一：安装包（推荐）
下载 **dsh-console-aio-setup-0.8.1.exe**（[GitHub Releases](https://github.com/JimyuAn-98/dsh-console-aio/releases)），双击安装即可使用（无需 Python 环境）。
安装后可创建桌面快捷方式；卸载走系统控制面板。

### 方式二：双击（源码）
双击 **启动dsh控制台.bat** —— 它优先使用 conda base 的 pythonw 启动，找不到再回退 PATH。
源码方式需已安装 PySide6（`pip install PySide6`）；打包版无需任何 Python 环境。

### 方式三：命令行
    python dsh-console-aio.py

> 💡 需要本机安装 Python 3（建议 Miniconda base，路径可改 启动dsh控制台.bat 顶部的 PYW）。

---

## 界面布局

    顶部:  [🐳 DSH Console v0.8 ]   部署:[本机 ▾]        [搜索][立即刷新]
    左导航            │ 中栏: 页面容器(17 页)                │ 右栏: 监控(可收起)
    总览               │ 总览: 运行状态+数据速览+部署+隧道      │ 本机端口 ●●●●●
    隧道               │ 插件: 列表|详情|配置 (三栏可拖拽)      │ 公网中转 反向隧道 ●●●
    会话与工作区       │ ...                                 │
    ...               │                                     │
    日志管理 / 设置    │                                     │
    ──────────────────┼──────────────────────────────────────┼─────────
    底部: 控制台输出(日志实时滚动) / 全局状态栏

  * ●=绿:健康/运行   ●=红:异常   * 切换顶部部署选择器 = 切换管理目标(远程只读)

![隧道管理](docs/screenshots/tunnel.png)

---

## 一键安装 dsh（全新环境）

**DSH 管理** 页「安装 dsh」卡支持两种安装方式，页头会**自动检测**本机当前是哪种模式（源码目录 / 全局包）：

| 安装方式 | 说明 |
|---|---|
| **npm 全局包（推荐）** | 官方 npm 包：`npm install -g @deepseek-ai/dsh`，免 clone / 免构建；更新用 `npm install -g @deepseek-ai/dsh@latest`、卸载用 `npm uninstall -g @deepseek-ai/dsh`；可选指定版本。用 npm 而非 pnpm 是因为 dsh 的插件加载器依赖扁平 `node_modules`（与官方 `npx` 同源布局） |
| **源码克隆** | `git clone + pnpm install + pnpm run build`，可跑本地未发布的 DSH 代码（开发用） |

两种方式都在页面内分步（step in place）执行：

1. **环境预检**：检查 git / node / npm / pnpm 是否可用，缺失会明确提示先装什么
2. 按所选方式安装（全局包：`npm install -g`；源码：clone → install → build）
3. 完成后写 config（全局包写 `dsh_install_mode=package`；源码把目标目录写进 `dash_repo`，重启后生效）

进度条 + 流式日志显示在页内安装卡；全过程另有一份**完整日志文件**，点页头「打开操作日志」随时复查。适合在没有 dsh 的新机器 / 新用户上从零搭好本机 dsh。

同页的「开发环境检查」卡内联展示 git / node / npm / pnpm 的版本与推荐基准，点「更新/安装/卸载」会先说明将执行什么，确认后才执行（环境检查/安装向导已退役模态弹窗，改为页面内分步）。

## 卸载 dsh

**DSH 管理** 页「卸载 dsh」卡按**当前检测到的安装方式**执行，均先停 web：

- **源码模式**：删除 `dash_repo` 源码目录并清空 config（只读 `.git` 有强制删除加固）
- **全局包模式**：`npm uninstall -g @deepseek-ai/dsh`（无残留，秒级）

两种模式都提供两档：

- **保留数据卸载**：只删源码 / 全局包；`~/.dsh` 数据（对话/会话/工作区/配置）保留
- **彻底卸载（含数据）**：额外删除 `~/.dsh` 数据目录——会清掉所有对话记录，**二次确认**后才执行

执行前会逐条列出将删除的具体路径；源码/数据目录删除有防误删守卫（绝不删用户主目录）。

---

## 设置（config.json）

所有可调项集中在 config.json；也可点顶栏 **【配置】** 进入「设置」页（标签页：隧道与部署 / 监控与命名），
**保存后端口/命名/监控点即时热重载**，无需重启。隧道 SSH 参数在下次启动隧道时生效。

- 场景模板一键填充（在家→中继隧道 / 实验室直连 / 本机反向）
- 测试 SSH 连接 在线验证免密连通
- 三处机器命名（本机/实验室/公网中转）与监测端口增删改，界面全部跟随

仓库自带一份 config.example.json（不含真实 IP 的模板）。首次使用请：

    copy config.example.json config.json   # 然后编辑其中的 IP/仓库路径/端口

若没有 config.json，程序会使用内置默认值正常运行。

| 字段 | 说明 | 默认 |
|------|------|------|
| ssh_server | 公网中转服务器 IP/域名 | YOUR_PUBLIC_IP |
| ssh_user | 中转服务器隧道用户名 | YOUR_USER |
| dash_repo | 本机 dsh 仓库路径 | <留空, 设置页里填> |
| dash_port | 本机 dsh GUI 端口 | 3080 |
| dash_cmd | 本机 dsh 启动命令 | ["pnpm.cmd","dsh","web"] |
| dsh_version_pin | 固定部署的 dsh 版本 tag（空=跟随默认分支） | 空 |
| node_id | 本机节点码（鉴权信箱 key，自动生成，可重新生成） | 自动 |
| local_ports | 本机端口监控 [端口,名称,说明] | 3080/8090/8022/8091/3090 |
| remote_tunnels | 远端反向隧道监控 [端口,名称,说明] | 8090/8022/8091 |
| local_name / ssh_name | 本机节点名 / 公网中转名（远端节点名在「部署管理」里按节点设置） | 本机/公网中转 |
| poll_seconds / remote_poll_seconds | 本机轮询 / SSH 直查间隔(秒) | 4 / 20 |
| *_timeout | 探测与更新超时 | ... |

> 真实 IP / 用户名 / 仓库路径只保存在本地 config.json（已 gitignore），请勿把它们写进 README 或任何被提交的文件。

![设置页](docs/screenshots/config-wizard.png)

---

## 工作原理

典型拓扑（多机 + 公网中转）：

    [实验室dsh 服务器(实验室)]          [Windows 本机]
      dsh GUI :3090               dsh GUI :3080
        |  反向隧道(常驻)               |  反向隧道(常驻)
        +-------------> 公网服务器 公网中转 <-------------+
                        8090->实验室dshGUI   8091->本机GUI
                        8022->实验室dshSSH
                            |
             在家/外部: 正向隧道访问

- 反向隧道在 公网服务器 上监听回环端口，默认仅绑定 127.0.0.1（安全）。
- 本机端口行反映本机监听状态；公网中转 反向隧道行通过 SSH 直查中转上的监听状态，才是"隧道是否配置成功"的真实指标。

### 隧道引擎
| 模块 | 作用 | 状态 |
|------|------|------|
| core/tunnel_mgr.py | 纯 Python 隧道管理器（forward/reverse, start/persist/stop） | ✅ |
| dsh-tunnel 卡片 | 在家正向隧道三连（8090/8022/8091） | ✅ 纯 Python |
| connect-lab-dsh 卡片 | 实验室局域网直连 实验室dsh（本机 3090） | ✅ 纯 Python |
| dsh-tunnel-reverse 卡片 | 本机 dsh -> 公网服务器 反向隧道（公网服务器:8091 -> 3080） | ✅ 纯 Python |
| update-dsh 卡片 | git 拉取 + pnpm 构建 + 重启（流式日志） | ✅ 纯 Python |

> 旧的 4 个 .ps1 已收进 legacy/ 目录，仅供历史参考，不再被界面调用。
> 连接参数（服务器 IP/用户名/端口）全部来自 config.json，无硬编码。

---

## 安全说明
- 中转服务器端口默认只绑回环，公网不可直达——除非你明确配置 GatewayPorts 并承担无鉴权 GUI 暴露公网的风险（=远程代码执行入口），否则请勿这样做。
- SSH 隧道需先配置好到中转/目标服务器的免密登录。
- 控制台不读取/不展示任何密钥明文；凭据只提示存在性。

---

## 数据域管理（17 页导航）

| 页面 | 功能 |
|------|------|
| 总览 | 运行状态卡 + 数据速览（会话/用量/任务板/插件）+ 节点列表（本机/远程：经隧道探活 + 免密链接复制/在浏览器打开） |
| DSH 管理 | 本机 dsh 操控（启动/重启/停止）+ 完整更新 + 环境/安装 + 版本发布日志（GitHub Releases 中文更新日志）+ 部署指定版本（切换/固定/回退） |
| 隧道 | 隧道卡片启停/常驻 + 本机 dsh 启停/更新 |
| 会话与工作区 | 分组/会话/详情三栏，归档/恢复/删除（二次确认） |
| Agent 模式 | 窄列表按名字选 + preset.yml 只读详情 |
| Profile 管理 | 列出 / 复制 / 删除 profile |
| 插件管理 | 列表/详情/cordis 合成配置三栏；官方 `dsh plugin` 命令安装/卸载/单个更新/批量更新全部；patch 层停用/启用（配置态与生效态徽章） |
| 任务看板 | ledger + scheduler 只读展示 |
| 模型用量 | 解压 session 聚合 token（按模型/天）+ 价格估算 + 明细卡 |
| LLM 配置 | 默认模型切换、自定义 provider 浏览（密钥只提示环境变量名） |
| 备份与凭据 | ~/.dsh 一键备份（排除凭据）、凭据存在性提示 |
| SSH 密钥 | 生成/指纹/公钥查看（私钥内容绝不读取） |
| 部署管理 | 节点（远端 dsh）配置：SSH + 远端 web 端口 + 关联正向隧道 + 节点标识；从公网信箱发现、复制/在浏览器打开免密链接、连接测试与只读快照 |
| 日志管理 | dsh web 落盘输出 tail + 过滤 + 着色 + token 脱敏 |
| 设置 | 配置标签页化，保存即热重载；诊断报告（脱敏可外发）与配置导入导出 |
| 主题 | 明/暗变体一键切换 + 全部界面颜色实时可调（即时预览），可存/载主题文件、设启动默认 |
| 关于与更新 | 当前版本 / 检查更新 / 更新日志 / 一键自动更新（安装版直接下载安装包、退出并运行安装程序） |

![总览](docs/screenshots/main.png)

![会话与工作区](docs/screenshots/sessions.png)

![插件管理](docs/screenshots/plugins.png)

![Agent 模式](docs/screenshots/agent-mode.png)

![Profile 管理](docs/screenshots/profiles.png)

![任务看板](docs/screenshots/tasks.png)

![模型用量统计](docs/screenshots/usage.png)

![LLM 配置](docs/screenshots/llm.png)

![备份与凭据](docs/screenshots/backup.png)

![SSH 密钥管理](docs/screenshots/ssh-key.png)

![部署管理](docs/screenshots/deploy.png)

![日志管理](docs/screenshots/logs.png)

---

## Roadmap（dsh 控制台进化路线）
- [x] 配置外置到 config.json（IP/用户/端口/轮询）+ 配置热重载（保存即生效）
- [x] 全部卡片 Python 化（core/tunnel_mgr.py + 纯 Python 更新）；旧 .ps1 收进 legacy/
- [x] **PySide6 现代界面**：深色亚克力 + 现代列表/卡片组件 + 17 页导航（含实时主题定制）
- [x] **明/暗主题**：浅色整套变体 + 主题页一键切换（深色为默认, config 持久化）
- [x] 一键安装 dsh + 环境检查（更新/安装/卸载引导；弹窗收敛：改 DSH 管理页页面内分步）
- [x] 卸载 dsh（保留数据 / 彻底卸载含 ~/.dsh, 危险操作双确认 + 防误删守卫）
- [x] 打包分发（PyInstaller + Inno Setup，GitHub Actions 自动发版）
- [x] **会话与工作区管理**：分组浏览 / 归档 / 恢复 / 删除（二次确认）
- [x] **Agent 模式管理**：窄列表 + preset.yml 详情
- [x] **Profile 管理**：列出 / 复制 / 删除
- [x] **dsh 插件管理**：列表 / 安装 / 卸载 / 单个与批量更新 / patch 层启停（配置态+生效态徽章）
- [x] **任务看板**：ledger + scheduler 只读展示
- [x] **模型用量统计**：token 聚合（按模型/天）+ 价格估算 + 明细
- [x] **LLM 配置**：默认模型切换 + provider 浏览
- [x] **备份与凭据**：~/.dsh 一键备份 / 凭据提示
- [x] **部署管理**：多部署只读总览 + 操作日志
- [x] **日志管理**：dsh web 输出 tail / 过滤 / 着色
- [x] **设置页**：配置标签页化 + 热重载（弹窗收敛第一步）
- [x] **版本管理**：当前版本 / 检查更新 / 更新日志 / 一键自动更新
- [ ] 多套拓扑配置切换
- [x] 明/暗主题切换（主题页, 浅色整套变体, 深色为默认）
- [ ] 多主题预设切换（Mica 深色/纯色）+ 布局记忆
- [x] 配置导出导入 + 诊断报告一键生成（设置页「诊断与配置」标签）
- [x] 用量趋势图表（按模型堆叠, 设置在用量页）
- [x] 全局命令面板 Ctrl+K（页面/部署/动作 搜索直达）
- [ ] 小白引导：首次使用向导 / 诊断助手 / 常见问题

## License
MIT © 2025 JimyuAn

---

<a name="english"></a>

# dsh-console-aio (English)

**dsh All-In-One console** (Windows GUI, PySide6 acrylic, dark/light themes): SSH tunnel management, local dsh start/stop/install/update, health monitoring, and a 17-page dsh data-domain console (sessions/agents/profiles/plugins/tasks/usage/LLM/deployments/logs/settings).

![Main window](docs/screenshots/main.png)

## Features
- One-click control: local dsh GUI start/stop, SSH tunnels (start/persist/stop), one-click dsh update
- **One-click dsh install**: repo URL + target dir → env pre-check → clone → pnpm install → build → auto-write config
- **Environment check**: git/node/npm/pnpm versions vs. recommended baseline, with update / install / uninstall actions
- Two-layer health monitor: local ports + reverse tunnels queried via SSH (collapsible right panel)
- Data-domain console: sessions, agents, profiles, plugins, task board, model usage, LLM config, deployments
- **Plugin manager**: official `dsh plugin` install/uninstall, single or "update all" batch upgrades, patch-layer toggles
- **Log viewer**: live tail of dsh web output with filtering, coloring and token masking
- **Settings page**: all config as tabs, hot-reload on save (dialog-free by design)
- Modern PySide6 UI: dark acrylic, modern list/card components, thread-safe

## Quick Start
- Download **dsh-console-aio-setup-0.8.1.exe** from [Releases](https://github.com/JimyuAn-98/dsh-console-aio/releases) (no Python needed), or run from source:
      python dsh-console-aio.py   (requires Python 3 + `pip install PySide6`)

## One-click dsh install
The **DSH Manage** page auto-detects which way dsh is installed (source checkout / global package) and shows it in the page header. The "Install dsh" card offers two modes:
- **npm global package (recommended)**: `npm install -g @deepseek-ai/dsh` — no clone, no build; update with `npm install -g @deepseek-ai/dsh@latest`, uninstall with `npm uninstall -g @deepseek-ai/dsh`; a specific version can be pinned. npm (not pnpm) is used because dsh's plugin loader relies on a flat `node_modules` — the same layout the official `npx` uses
- **Source checkout**: `git clone + pnpm install + pnpm run build` — for running unreleased local DSH code

Both run **in-page** (step in place) with a progress bar and streaming log:
1. Pre-check environment (git / node / npm / pnpm)
2. Install by the selected mode (global package: `npm install -g`; source: clone → install → build)
3. Write config on success (global package: `dsh_install_mode=package`; source: target dir into `dash_repo`)

The full output of every long operation is also saved to a log file — click "Open operation log" in the page header.

## Environment check
On the **DSH Manage** page, the "Development environment check" card shows git / node / npm / pnpm versions vs. a recommended baseline, each with Update / Install / Uninstall actions (confirm-before-run). The env check and install wizard are step-in-place cards on the page (the modal EnvDialog / InstallDialog windows are retired).

## Uninstall dsh
On the **DSH Manage** page, the "Uninstall dsh" card follows the **detected install mode** and always stops the web first:
- **Source mode**: deletes the source directory (`dash_repo`) and clears config (hardened force-delete for read-only `.git`)
- **Global package mode**: `npm uninstall -g @deepseek-ai/dsh` (clean and fast)

Both modes offer two options:
- **Keep data**: removes the source / global package only; `~/.dsh` (conversations/sessions/workspaces/config) is kept
- **Full uninstall (with data)**: additionally deletes `~/.dsh` — irreversible, requires a double confirmation

The exact paths to be deleted are listed before running; delete guards never touch the user home directory.

## Configuration
All tunables live in config.json; the **Config** button opens the Settings page (tabs: tunnels & deployments / monitoring & naming). **Saving hot-reloads** ports, naming and monitor probes — no restart needed.

![Settings](docs/screenshots/config-wizard.png)

See the Chinese section above for the full field table.

## Data-domain pages (17-page navigation)
| Page | What it does |
|--------|-------------|
| Overview | run-status card + data quick-look + node list (local/remote: probe via tunnel + copy/open passwordless link) |
| DSH manage | local dsh start/restart/stop + full update + env/install + release notes (GitHub Releases changelog viewer) + deploy a specific version (switch/pin/rollback) |
| Tunnels | tunnel card start/persist/stop + local dsh start/stop/update |
| Sessions & workspace | group/session/detail columns, archive/restore/delete (double confirm) |
| Agent presets | narrow name list + read-only preset.yml detail |
| Profiles | list / copy / delete profiles |
| Plugins | list/detail/composed-config columns; official `dsh plugin` install/uninstall/single-update/update-all; patch-layer enable/disable (config vs. effective badges) |
| Task board | ledger + scheduler read-only |
| Model usage | decompress sessions, aggregate tokens (by model/day) + cost estimate + daily trend chart |
| LLM config | switch default model, browse custom providers (API keys only hinted by env-var name) |
| Backup & credentials | one-click ~/.dsh backup (credentials excluded), credential presence hints |
| SSH keys | generate / fingerprints / public-key view (private keys are never read) |
| Deployments | remote dsh node config (SSH + remote web port + linked forward tunnel + node key), discover from relay mailbox, copy/open passwordless link, connection test & read-only snapshots |
| Logs | live tail of dsh web output with filtering, coloring, token masking |
| Settings | config as tabs, hot-reload on save; masked diagnostics report & config import/export |
| Theme | toggle dark/light variant + edit every UI color live (instant preview), save/load theme files, set startup default |
| About & update | current version / check update / changelog / one-click auto-update (installed build downloads and launches the installer) |

![Sessions](docs/screenshots/sessions.png)

![Plugins](docs/screenshots/plugins.png)

![Deployments](docs/screenshots/deploy.png)

![Logs](docs/screenshots/logs.png)

## Auto release (GitHub Actions)
Pushing a `v*` tag triggers the CI workflow: PyInstaller onefile → Inno Setup installer (`dsh-console-aio-setup-<version>.exe`) → attach to a GitHub Release.

    git tag v0.6.0
    git push origin v0.6.0

(Update `APP_VERSION` in code, `version.json`, the `installer.iss` default version and RELEASE_NOTES before tagging.)

## Security
- Relay ports bind loopback only by default; do not expose the unauthenticated GUI to public internet (remote-code-execution risk) unless you explicitly accept it.
- The console never reads or displays secret material; credentials are only hinted by presence.

## Roadmap
- [x] External config + hot-reload
- [x] PySide6 modern UI (dark acrylic + modern list/card components + 17-page navigation)
- [x] One-click dsh install + environment check
- [x] Packaged distribution (PyInstaller + Inno Setup, GitHub Actions auto-release)
- [x] Plugin manager (list / install / uninstall / single & batch update / patch-layer toggles with config & effective badges)
- [x] Log viewer (tail / filter / colorize)
- [x] Settings page (config as tabs + hot-reload)
- [x] Overview redesign (run status + data quick-look + deployments + tunnels)
- [x] Multiple topology profiles (tunnel plan snapshots + switch)
- [x] Dark/light theme variant + live color editing + theme files
- [ ] Layout memory / runtime Mica-vs-solid switch (deliberately not done)
- [x] Command palette (Ctrl+K) / config export-import / diagnostics report / usage charts
- [ ] Beginner onboarding (first-run wizard / diagnostics / FAQ)

## License
MIT © 2025 JimyuAn
