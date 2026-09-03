# 系统架构（ARCHITECTURE · dsh 控制台）

> **单一权威来源**：本文档是 dsh 控制台前后端分层架构、信号-槽通讯契约、数据域映射与设计硬约束的唯一权威文档。
> 历史设计稿归档见 `docs/archive/UI_LAYERING.md` 与 `docs/archive/PYSIDE_MIGRATION.md`。

---

## 1. 整体三层架构

项目遵循经典的 Qt 桌面端分层架构，实现**业务逻辑与界面展示的彻底解耦**：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. 后端业务层 core/  (纯 Python, 严禁 import PySide)                         │
│    config.py         配置加载/派生常量(default_config_path/allow_empty_ports)│
│    data.py           数据域模型: 会话/workspace/profile/用量/价格/部署抽象   │
│    dshctl.py         dsh 启停/更新/进程探测/流式命令 stream_cmd              │
│    tunnel_mgr.py     纯 Python SSH 隧道底层管理器 (forward/reverse/persist)   │
│    tunnels.py        隧道卡片高层业务封装                                    │
│    tunnel_planner.py 隧道多方案/拓扑快照/端口冲突校验与自检                  │
│    cache.py          通用本地数据缓存与时间戳失效校验                        │
│    diagnostics.py    环境/端口/配置一键诊断报告生成 (敏感信息脱敏)           │
│    version.py        控制台自身版本比对与 GitHub 自更新                      │
│    keys.py           SSH 密钥管理 (私钥安全红线: 绝不读取明文)               │
│    env.py            环境检查 (git/node/npm/pnpm) / 一键安装 / 彻底卸载      │
│    ops.py            备份 ~/.dsh (排除凭据) / 日志路径 / 凭据存在性          │
│    profiles.py       Profile 复制与删除 (远程只读红线)                       │
│    sessions.py       会话归档/恢复/删除 (远程只读红线)                       │
│    plugins.py        插件列表/cordis patch 启停/官方 CLI 安装卸载            │
│    deployments.py    多部署快照与配置持久化                                  │
│    logs.py           dsh web 日志读取与过滤                                 │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ 纯数据事件 / 回调 / 阻塞计算
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. 信号桥接口层 app/services.py  (唯一允许起后台工作线程并转 Qt 信号处)        │
│    DshService(QObject):                                                     │
│      - 核心信号: status, log, card, monitor, finished, result               │
│      - 通用工作线程模板: _run_result_op (带 events 域函数), _run_core_op    │
│      - 页面业务接口: 启停/探测/安装/卸载/备份/诊断等统一触发入口            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Qt Signal (跨线程排队投递)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. 前端 UI 展示层 ui/ + 主程序 (只负责视图渲染 + 订阅信号 + 调用 service)    │
│    dsh-console-aio.py 主窗口骨架 (顶栏/左导航/系统托盘常驻/底部日志/启动入口)│
│    ui/pages_*.py      全 17 个管理页面 (overview/tunnels/dsh/sessions/theme…)│
│    ui/monitor.py      右侧健康监控折叠栏 (StatusPanel) + 线程安全日志桥      │
│    ui/base.py         BasePage (提供 safe_emit 页面销毁防崩机制)             │
│    ui/theme.py        主题引擎 (TOKENS 实时换肤 / 明暗变体 / QSS 生成)       │
│    ui/widgets.py      现代组件库 (卡片/列表/确认条 ConfirmBanner/刷新指示器) │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 信号-槽通讯契约（硬约束）

为保证 Qt GUI 线程安全与进程稳定，全员必须遵守以下契约：

### 2.1 线程与通信红线
1. **业务层（`core/`）零 Qt 依赖**：纯 Python 逻辑，只向调用方返回纯数据字典或通过回调抛出事件。
2. **`services.py` 是唯一线程出口**：除个别本地毫秒级小文件快读外，所有耗时 I/O、子进程、SSH 网络操作必须由 `DshService` 启动后台线程执行。
3. **禁止跨线程操作 UI**：后台线程**严禁**直接调用任何 QWidget 的方法，**严禁**跨线程无锁修改共享可变数据。所有结果必须通过 Qt Signal 投递回主线程事件循环。

### 2.2 `DshService` 核心信号表
```python
class DshService(QObject):
    status   = Signal(str)                  # 底部状态栏文案更新
    log      = Signal(str, str)             # 日志区输出: (text, tag) -> tag 为 "ok"|"err"|"warn"|""
    card     = Signal(str, bool)            # 隧道/服务卡片状态: (card_key, is_online)
    monitor  = Signal(object)               # 右栏探测结果: (local_ports, ssh_proc_count, remote_tunnels)
    finished = Signal(str, bool)            # 操作完成通知: (op_key, is_success)
    result   = Signal(str, object)          # 业务数据回填: (op_key, payload_dict)
```

### 2.3 工作线程模板
* `_run_result_op(op, func, *args)`：适用于带进度/日志 `events` 回调的业务函数（`func(events=None, ...)`），执行完毕后 emit `result(op, payload)` 与 `finished(op, ok)`。
* `_run_core_op(op, func, *args)`：适用于纯数据读取函数，自动包装为 `{"data": res, "err": ""}` 后 emit `result(op, payload)`。

### 2.4 Signal 连接与生命周期（页面销毁防护）
* **长生命周期接收者（MainWindow 级别）**：如主日志区、底部状态栏，仅在 `MainWindow` 初始化时 connect 一次，避免页面反复重建导致槽函数叠加。
* **短生命周期接收者（Page 级别）**：各页面在 `_build` 时 connect 自身所需的 `service.result` / `service.finished`，页面销毁时 Qt 会自动解除其槽绑定。
* **`safe_emit` 防护**：页面自建信号向自身发送时，一律使用 `BasePage.safe_emit(sig, *args)`，自动捕获并忽略页面快速切换销毁时引发的 `RuntimeError: Internal C++ object already deleted`。

---

## 3. 数据域与模块映射

| 数据域 | core 业务模块 | UI 页面 / 承载 | 关键职责与安全红线 |
|---|---|---|---|
| **隧道管理与向导** | `tunnel_mgr.py` + `tunnels.py` | `pages_tunnels.py` + `dialog_tunnel_wizard.py` | 声明式通用 TunnelItem 模型，场景向导 + 端口冲突检测，批量启停，PID 存盘 |
| **隧道方案规划** | `tunnel_planner.py` | `pages_tunnels.py` (规划器卡片) | 整套动态拓扑快照保存/切换，本地/远端端口冲突检测 |
| **本机 dsh 操控** | `dshctl.py` | `pages_dsh.py` (DSH 管理) | 启停进程、一键更新 (git pull + clean + build)、版本比对 |
| **环境与安装** | `env.py` | `pages_dsh.py` (页面内分步) | 工具链检查 (git/node/npm/pnpm)、一键全新安装、彻底卸载守卫 |
| **总览概览** | `data.py` + `diagnostics.py` | `pages_overview.py` | 运行状态卡 + 数据域指标速览 + 部署列表 |
| **会话与工作区** | `sessions.py` | `pages_sessions.py` | 会话分组、归档、恢复、彻底删除；**远程部署只读** |
| **插件管理** | `plugins.py` | `pages_plugins.py` | cordis.yml 语法解析、patch 层启停、官方 CLI 安装；**远程只读** |
| **Profile 管理** | `profiles.py` | `pages_profiles.py` | profile 列出、复制、删除 (web 主配置保护)；**远程只读** |
| **模型用量与价格**| `data.py` + `cache.py` | `pages_usage.py` | session zstd 批量解压聚合、按天/模型趋势图、价格表持久化 |
| **LLM 配置** | `data.py` | `pages_llm.py` | 默认模型切换、provider 浏览；**apiKeyEnv 仅读环境变量名** |
| **SSH 密钥** | `keys.py` | `pages_keys.py` | 密钥生成、指纹计算、公钥查看；**私钥内容绝不读取** |
| **备份与运维** | `ops.py` | `pages_ops.py` | `~/.dsh` 一键备份压缩包；**自动排除凭据文件** |
| **部署管理** | `deployments.py` | `pages_deployments.py` | 多主机配置、SSH 免密探测、只读快照 |
| **日志查看** | `logs.py` | `pages_logs.py` | dsh web 落盘日志实时 tail、着色与关键词过滤 |
| **设置与诊断** | `config.py` + `diagnostics.py` | `pages_settings.py` | 端口/命名热重载、一键诊断报告生成、配置导入导出 |
| **主题引擎** | `ui/theme.py` | `pages_theme.py` | TOKENS 全局色板、亚克力/明暗变体切换、实时 QSS 编译生成 |
| **关于与更新** | `version.py` | `pages_version.py` | 控制台自身版本比对、Release 自动下载与自更新 |

---

## 4. 三地网络拓扑与 SSH 鉴权信箱架构

控制台原生面向“家 - 办公室 - 实验室”三地异构部署环境，公网服务器仅充当纯 SSH 桥梁与零服务鉴权信箱：

```
┌───────────────────────────────── 局域网 (单位/学校) ─────────────────────────────────┐
│                                                                                     │
│   ┌────────────────────────┐       局域网直连 SSH       ┌────────────────────────┐  │
│   │     办公室 (Win)       │ ◄────────────────────────► │     实验室 (Ubuntu)    │  │
│   │  ★ 安装控制台 + 部署dsh  │                           │  ★ 部署 dsh             │  │
│   └───────────┬────────────┘                            └───────────┬────────────┘  │
└───────────────┼─────────────────────────────────────────────────────┼───────────────┘
                │                                                     │
                │ SSH 反向隧道 ①                                      │ SSH 反向隧道 ②
                │ (办公室推端口到公网 8091)                             │ (实验室推端口到公网 8090)
                ▼                                                     ▼
   ┌───────────────────────────────────────────────────────────────────────────────┐
   │                            公网服务器 (Linux VPS)                             │
   │  - 8091: 办公室反向口    | ~/.dsh_runtime/office.token                          │
   │  - 8090: 实验室反向口    | ~/.dsh_runtime/lab.token                             │
   └───────────────────────────────────────▲───────────────────────────────────────┘
                                           │
                                           │ SSH 正向隧道
                                           │ (拉取公网 8091/8090 到家里本地)
                                           │
                                ┌──────────┴───────────┐
                                │       家 (Win)       │
                                │   ★ 安装控制台 (客户端) │
                                └──────────────────────┘
```

### 4.1 dsh 0.1.2+ 浏览器鉴权流转机制 (Token Mailbox)
1. **启动与捕获**：办公室/实验室 dsh 启动时输出随机一次性 Token（`http://127.0.0.1:PORT/?token=...`），被各端控制台/守护脚本从 stdout 捕获。
2. **状态信箱（零公网服务）**：反向隧道建立时，通过已有 SSH 执行 `mkdir -p ~/.dsh_runtime && echo "<TOKEN>" > ~/.dsh_runtime/<node>.token`（文件权限 `600`，不依赖任何第三方公网 Web 服务）。
3. **家里拉取与免密登入**：家里控制台拉取隧道时，通过 SSH 读取信箱 Token，UI 组装 `http://127.0.0.1:<LOCAL_PORT>/?token=<TOKEN>` 并调用系统浏览器打开。
4. **Cookie 长期生效**：浏览器完成 Token $\rightarrow$ 签名 Cookie 交换（针对当前本地 Authority 生效，有效期 30 天），后续 30 天内直接打开免输入 Token。

---

## 5. 数据与配置存储

| 配置文件 / 路径 | 定位与读取方式 | 安全与隔离规则 |
|---|---|---|
| `config.json` | 仓库根目录（打包后在 exe 旁） | **必须 gitignored**。统一通过 `core.config.default_config_path()` 获取绝对路径，支持 `DSH_AIO_CONFIG` 环境变量覆盖。 |
| `~/.dsh/` | dsh 本体运行时主目录 | 存放 profiles、sessions、storages、settings.yaml 等，支持 `DSH_HOME` 环境变量覆盖。 |
| `model_prices.json` | 软件运行目录（`config.json` 同级） | 自定义模型价格表持久化，统一通过 `core.data` 加载与保存。 |
| `themes/*.json` | `themes/` 目录（gitignored） | 用户自定义保存的主题配色方案。 |
| `tunnel-pids.json` | 软件运行目录（gitignored） | 正在运行的 SSH 隧道进程 PID 记录，用于退出或异常时的精准清理。 |

---

## 6. 测试与安全红线

1. **端口 3080 安全红线**：
   - 默认单元测试（`pytest tests/`）只跑纯单元测试层（`-m "not gui"`）。
   - 绝不自动运行任何会触碰 3080 端口真实 dsh 实例的测试；GUI 构造测试仅供人工带 `-m gui` 显式执行。
2. **Windows `os.kill` 陷阱防线**：
   - Windows 下严禁使用 `os.kill(pid, 0)`（等同于广播 `CTRL_C_EVENT`，会直接杀死共享控制台的宿主 web 进程）；进程探活一律使用 `tasklist` CSV 或底层 Win32 API。
3. **打包路径规则**：
   - 打包（PyInstaller frozen）环境下，`__file__` 指向临时解压目录 `_MEIxxxxxx`。所有需要持久化落盘的文件（如 `config.json`、`model_prices.json`、日志等）**严禁**使用 `__file__` 相对路径推导，必须使用 `core.config.default_config_path()` 获取真实 exe 所在目录。
4. **敏感信息保护**：
   - 私钥、API Token 等敏感信息只做存在性检测，绝不读取明文、绝不写入日志、绝不上传诊断报告。

---

## 7. 历史归档索引

* 阶段性 PySide6 页面迁移历史：`docs/archive/PYSIDE_MIGRATION.md`
* 早期设计方案（ABC 方案与 v0.3 调研）：`docs/archive/PLANS.md`
* 初始 UI 分层重构设计稿：`docs/archive/UI_LAYERING.md`
* 上游 Harness ConPTY 信号 Bug 分析稿：`docs/archive/ISSUE_harness_os_kill_ctrlc.md`
* 旧版个人运维指南：`docs/archive/个人使用指南.txt`
