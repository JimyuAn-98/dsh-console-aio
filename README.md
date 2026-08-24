# dsh-tunnel-console

> 中文 | [English](#english)

**SSH 隧道可视化管理器 + 服务健康监控**（Windows GUI）。把平时要敲命令行的 SSH 隧道启动/停止/常驻，和一整套服务的健康监控，打包成一个零依赖的图形界面。

- 🚀 一键操作：本机 dsh 启停、三条 SSH 隧道（启动/常驻/停止）、dsh 一键更新、全新环境一键安装 dsh
- 🖥️ 环境检查：独立窗口查看 git/node/npm/pnpm 版本与推荐基准，更新/卸载引导；安装目录支持系统文件夹选择
- 📡 健康监控：本机端口 + SSH 直查远端反向隧道，两层监控一屏可见
- ⚙️ 配置外置：IP / 用户名 / 仓库路径 / 端口 / 轮询间隔全部集中在 config.json
- 🧩 零依赖：仅用 Python 标准库（tkinter），无需 pip 安装任何东西

---

## 快速开始

### 方式一：双击（推荐）
双击 **启动dsh控制台.bat** —— 它优先使用 conda base 的 pythonw 启动，找不到再回退 PATH。

### 方式二：命令行
    python dsh-tunnel-console.py

> 💡 需要本机安装 Python 3（建议 Miniconda base，路径可改 启动dsh控制台.bat 顶部的 PYW）。

---

## 界面布局（示意）

    顶部:  [ dsh 控制台 ]    本机轮询 4s · SSH直查 20s    [安装 dsh] [配置] [立即刷新]

    操控区(5张卡片):  本机 dsh | dsh-tunnel | connect-lab-dsh | dsh-tunnel-reverse | update-dsh
                      启动/停止 | 启动/常驻/停止 | ... | ... | 运行更新
                      ●运行中  ●运行中  ○停止  ...  ○空闲

    健康监控(两行):
      本机端口:      ●3080  ●8090  ●8022  ●8091  ●3090
      公网服务器 反向隧道:  ●8090  ●8022  ●8091   ●公网服务器 SSH

    运行日志(实时滚动) / 底部状态栏

  * ●=绿:健康/运行   ●=红:异常/未就绪

---

## 一键安装 dsh（全新环境）

顶部点 **【安装 dsh】** 打开安装向导：填 dsh 的 git 仓库地址（默认官方 deepseek-harness）与目标目录，工具会自动：

1. **环境预检**：检查 git / node / npm / pnpm 是否可用，缺失会明确提示先装什么
2. **git clone**：拉取 dsh 源码到目标目录
3. **pnpm install**：安装依赖
4. **pnpm run build**：构建
5. 完成后**自动把目标目录写进 config.json 的 dash_repo**（重启后生效）

适合在没有 dsh 的新机器 / 新用户上，从零一键搭好本机 dsh。

---

## 配置（config.json）

所有可调项都在同目录的 config.json，也可点界面右上角 【配置】 打开隧道配置向导（保存后重启生效）。

向导把参数分成 4 组，并提供内置场景模板一键填充端口映射：
- ① 公网中转服务器：IP / 用户名，可点 测试 SSH 连接 在线验证免密能否连通
- ② 本机 dsh：仓库路径 / 端口 / 启动命令
- ③ 隧道参数：在家正向端口(forward_ports)、实验室直连(lab_server / lab_user / lab_port)、本机反向(reverse_port)——这些原来只能手改 JSON，现在都能在界面里编辑
- ④ 轮询：本机 / 远端健康检查间隔

首次使用可直接在向导里点一个场景模板(如 在家→中继隧道)，把占位符 YOUR_* 改成真实 IP/用户名即可，无需手动编辑 JSON。

仓库自带一份 config.example.json（不含真实 IP 的模板）。首次使用请：

    copy config.example.json config.json   # 然后编辑其中的 IP/仓库路径/端口

若没有 config.json，程序会使用内置默认值正常运行。

| 字段 | 说明 | 默认 |
|------|------|------|
| ssh_server | 公网中转服务器 IP/域名 | YOUR_PUBLIC_IP |
| ssh_user | 中转服务器隧道用户名 | YOUR_USER |
| dash_repo | 本机 dsh 仓库路径 | <留空, 在向导里填> |
| dash_port | 本机 dsh GUI 端口 | 3080 |
| dash_cmd | 本机 dsh 启动命令 | ["pnpm.cmd","dsh","web"] |
| local_ports | 本机端口监控 [端口,名称,说明] | 3080/8090/8022/8091/3090 |
| remote_tunnels | 远端反向隧道监控 [端口,名称,说明] | 8090/8022/8091 |
| poll_seconds / remote_poll_seconds | 本机轮询 / SSH 直查间隔(秒) | 4 / 20 |
| *_timeout | 探测与更新超时 | ... |

> 真实 IP / 用户名 / 仓库路径只保存在本地 config.json（已 gitignore），请勿把它们写进 README 或任何被提交的文件。

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
             在家/外部: dsh-tunnel.ps1 正向隧道访问

- 反向隧道（实验室dsh->公网服务器、本机->公网服务器）在 公网服务器 上监听回环端口，默认仅绑定 127.0.0.1（安全）。
- 本机端口行反映本机是否建立了正向隧道等本地监听；公网服务器 反向隧道行通过 SSH 直查 公网服务器 上监听状态，才是"隧道是否配置成功"的真实指标。

### 隧道引擎
| 模块 | 作用 | 状态 |
|------|------|------|
| tunnel_mgr.py | 纯 Python 隧道管理器（forward/reverse, start/persist/stop） | ✅ |
| dsh-tunnel 卡片 | 在家正向隧道三连（8090/8022/8091） | ✅ 纯 Python |
| connect-lab-dsh 卡片 | 实验室局域网直连 实验室dsh（本机 3090） | ✅ 纯 Python |
| dsh-tunnel-reverse 卡片 | 本机 dsh -> 公网服务器 反向隧道（公网服务器:8091 -> 3080） | ✅ 纯 Python |
| update-dsh 卡片 | git 拉取 + pnpm 构建 + 重启（流式日志） | ✅ 纯 Python |

> 旧的 4 个 .ps1 已收进 legacy/ 目录，仅供历史参考，不再被界面调用。
> 连接参数（服务器 IP/用户名/端口）全部来自 config.json，无硬编码。

---

## 安全说明
- 中转服务器端口默认只绑回环，公网不可直达——除非你明确配置 GatewayPorts 并承担无鉴权 GUI 暴露公网的风险（=远程代码执行入口），否则请勿这样做。
- SSH 隧道需先配置好到中转/目标服务器的免密登录（见各 .ps1 头部注释）。

---

## Roadmap（可能的下一步）
- [x] 配置外置到 config.json（IP/用户/端口/轮询）
- [x] 全部卡片 Python 化（tunnel_mgr.py + 纯 Python 更新）
- [x] 旧 .ps1 收进 legacy/
- [ ] 打包成单文件 exe（PyInstaller）
- [ ] 配置热重载（保存后无需重启）
- [ ] 多套拓扑配置切换

## License
MIT © 2025 dsh-tools

---

<a name="english"></a>

# dsh-tunnel-console (English)

A **visual SSH-tunnel manager + service health monitor** for Windows. Wrap the command-line chore of starting/stopping SSH tunnels and monitoring services into one zero-dependency GUI.

## Features
- One-click control: local dsh GUI start/stop, three SSH tunnels (start/persist/stop), one-click dsh update
- Two-layer health monitor: local ports + remote reverse-tunnels queried via SSH
- External config: IP / user / repo path / ports / poll intervals all in config.json
- Zero dependencies: pure Python stdlib (tkinter)

## Quick Start
- Double-click 启动dsh控制台.bat (uses conda base pythonw first, falls back to PATH), or run:
      python dsh-tunnel-console.py
- Requires Python 3 (Miniconda base recommended; the pythonw path is editable at the top of the .bat).

## Configuration
All tunables live in config.json (also editable via the **Config** button; save takes effect after restart). See the Chinese section above for the field table.

## How it works
- Reverse tunnels (实验室dsh->公网服务器, local->公网服务器) listen on 公网服务器's loopback (127.0.0.1 only, safe by default).
- The local-ports row shows local listeners; the 公网服务器 tunnel row SSH-queries the real listener status on 公网服务器 — that's the true "is my tunnel configured" signal.

## Security
- Relay ports bind loopback only by default; do not expose the unauthenticated GUI to public internet (remote-code-execution risk) unless you explicitly accept it.

## License
MIT © 2025 dsh-tools