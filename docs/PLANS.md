# 方案与实施记录（PLANS）

本目录记录 dsh-tunnel-console 的规划方案、目标与非目标、实施状态。方便回溯，避免方案遗忘。

各条目标注：**[规划]** 未开始 / **[进行中]** / **[已完成]** / **[决定不做]**。

---

## 1. 配置编辑器方案（原"ABC 方案"）

> 背景：早期讨论把"手改 config.json"降低门槛时，提出过 A/B/C 三级渐进方案。
> 用户最终选择：**方案 A + 轻量版 B**，并**已完成**。

- **方案 A — 配置向导（增强现有配置对话框）** **[已完成]**
  - 原 7 字段平铺对话框 → 分组向导：① 公网中转服务器 ② 本机 dsh ③ 隧道参数 ④ 轮询
  - 每个字段带灰色帮助文字；新增"测试 SSH 连接"按钮（在线验证免密）。
- **方案 B — 隧道创建向导 + 拓扑模板** **[已完成(轻量版)]**
  - 内置 3 个场景模板（在家→中继 / 实验室→直连 / 本机→中继反向），一键填充端口映射。
  - 完整版（任意新增/删除隧道卡片、动态生成卡片）**暂未实现**，作为后续可选。
- **方案 C — 连接向导 + 一键诊断 + 自动化（含 ssh-copy-id、自动装公钥）** **[规划/未做]**
  - 后续若要做"深度排障自动化"，在方案 C 基础上扩展。

---

## 2. 一键安装 dsh（全新环境辅助）

> 用户：辅助本地全新安装 dsh。[已完成]

- 顶部 **【安装 dsh】** 按钮 → 安装向导（InstallDialog）
- 默认仓库地址：官方 deepseek-harness（可改）
- 环境预检 → git clone → pnpm install → pnpm build → 写 dash_repo 到 config.json

---

## 3. 环境监测独立窗口（运维辅助） [已完成]

> 用户：环境监测做成**独立窗口**；推荐版本以**当前开发机为基准**（当前能跑 = 基准）；卸载走提示。

- **目标**：独立"环境检查"窗口，随时可看 git / node / npm / pnpm 的版本与状态。
- **推荐版本**：以当前开发电脑实际安装版本为基准（能跑即基准），直接写版本号（如 v24.19 / 11.17），不额外说明来源。
- **安装目录**：InstallDialog 目标目录改为"浏览…"按钮调用系统文件夹选择（filedialog.askdirectory）。
- **操作（更新/安装/卸载三按钮）**：
  - 每个工具一行，带 更新/安装/卸载 三个按钮；点击后先说明将执行什么，确认（是/否）后才执行。
  - 更新：git → git update-git-for-windows；npm → npm install -g npm@latest；pnpm → pnpm add -g pnpm@latest；node → 提示用 nvm-windows 或官网。
  - 安装：git/node → 打开官网下载页；pnpm → npm install -g pnpm；npm → 提示随 Node.js。
  - 卸载：统一打开系统"设置-应用-安装的应用"页（ms-settings:appsfeatures），不自动执行卸载。
  - 命令执行在后台线程（CREATE_NO_WINDOW + 超时），完成后弹结果框。

---

## 4. 其他想法 / 候选

- PyInstaller 打包单文件 exe（build_win.bat 已备） [规划]
- 多套拓扑配置切换 [规划]
- 配置热重载（保存后免重启）[规划]

---

*最近更新：2025（dsh-tunnel-console）*

---

## 5. 历史脱敏（重要安全操作） [已完成]

> 2025-08-25：早期 3 个 commit（初版 / 脱敏legacy / 配置向导）含真实 IP 与用户名，已用 git-filter-repo 全局重写历史。

- 工具：git-filter-repo（pip install git-filter-repo），--replace-text 规则替换。
- 替换：185.238.250.148 → YOUR_PUBLIC_IP；10.1.12.204 → YOUR_LAB_IP；hjy → YOUR_USER；huangjiy → YOUR_NAME；路径 → 占位。
- 验证：7 个 commit 全部文件 + 提交信息 敏感命中 = 0。
- 已 force push 覆盖远程 main（83c483d → 7e4d209）。
- 注意：曾 clone 过旧仓库的人本地仍有旧提交副本，无法远程抹除；GitHub 侧旧对象会在 GC 后移除。
- 备份：本地 dsh-backup-history/.git-*（完整旧 .git 备份）。

---

## 6. 宏大计划：进化成"dsh 控制台"（dsh Console） [规划中]

> 用户愿景：从"隧道管理工具"进化为专为 dsh 设计的控制台软件，帮小白用户上手 dsh。
> 2025-08-25 调研了本地 deepseek-harness checkout，确认以下机制全部真实存在，路线可落地。

### 调研结论（机制依据）

- **Profile 机制**：`dsh --profile <name>` 是真实命令（`dsh web` 等价于 `dsh --profile web`）。
  profile 位于 `~/.dsh/profiles/<name>/`，包含：cordis.yml（配置树）、cordis.patch.yml（补丁）、package.json + node_modules + pnpm-workspace.yaml（独立依赖）。
  → profile 管理 = 列出/切换/创建 ~/.dsh/profiles 下的目录，用 `dsh --profile <name>` 启动。
- **插件机制**：cordis.yml 用 `insert:` 行加载插件（id + npm 包名，如 @deepseek-ai/dsh-cordis-host-runner）；
  profile 目录有 `.dsh-market/`（插件市场目录）；插件安装 = 改 profile 的 package.json + cordis.yml insert + pnpm install。
  → 插件管理 = 读取/编辑 cordis.yml（YAML 增删 insert 行）+ 管理 profile 依赖。
- **主题机制**：~/.dsh/settings.yaml 已有 UI 配置项（skin-background、dsh-better-sidebar、ui-onboarding 等）；
  web 主题由 ui-theme 包（--dsw-* CSS token，light/dark）实现。
  → 主题管理 = 读写 settings.yaml 的 UI 配置 + 提供预览。
- **运行时监控**：dsh 运行时产物在 ~/.dsh/sessions/（会话）、storages/（存储）、remote-web-ui（远端访问配置）。
  → 运行时监控 = 进程状态 + 3080 端口 + web 日志流 + 会话/任务看板。

### 分阶段路线（小步快跑）

- **阶段 0（已完成）**：隧道管理 + 健康监控 + 一键安装 dsh + 环境检查。
- **阶段 1：dsh 运行时监控**
  - dsh 进程状态卡片（PID / 启动时间 / 端口），web 日志实时流（复用 _stream_cmd 思想，tail 日志文件）
  - 会话/存储占用概览
- **阶段 2：dsh profile 管理**
  - 列出 ~/.dsh/profiles 下的 profile，显示当前使用的 profile
  - 一键切换默认 profile（写 config.json 或 settings.yaml），复制/新建 profile
- **阶段 3：dsh 插件管理**
  - 解析当前 profile 的 cordis.yml，列出已加载插件
  - 从 .dsh-market 或 npm 搜索插件 → 安装（改 cordis.yml + package.json + pnpm install，流式日志）→ 卸载/启停
  - 危险操作确认 + 配置备份（复制 cordis.yml）
- **阶段 4：dsh web 主题管理**
  - 读 settings.yaml 的 UI 配置项，提供主题切换（light/dark、皮肤开关）
  - 主题预览（打开 web UI 或截图级预览）
- **阶段 5：小白引导**
  - 首次使用向导（检测环境 → 装 dsh → 配置中转 → 建隧道 → 打开 web）
  - 一键诊断（环境/SSH 免密/端口/进程逐项检查并报告）
  - FAQ 内嵌

### 工程约束
- 保持零依赖（tkinter）；YAML 解析用 PyYAML 会破坏零依赖 → 自己写最小 YAML 子集解析器，或仅在存在 PyYAML 时启用（回退只读）。
- 所有写操作前备份（cordis.yml / settings.yaml / config.json 复制 .bak）。
- 敏感信息（IP/用户名/凭据）只在本机 ~/.dsh 与 gitignored 文件，不进仓库。
- 每个阶段先出"只读展示"，确认后再加"写操作"。

---

## 7. 功能全景清单（dsh 控制台 候选功能域）

> 2025-08-25 调研 ~/.dsh 与 dsh CLI 后整理。标注 [优先] 为推荐先做的。

### A. 会话与工作区（用户已提）
- **Session 管理** [优先]：~/.dsh/sessions/<编码工作目录>/session-<uuid>/session.jsonl.zstd
  - 按工作目录浏览会话；查看会话数量/大小；删除；导出（解压 jsonl）。
- **Workspace 管理** [优先]：storages/workspace.json（workspaceIds 列表）
  - 列出/重命名/新建 workspace；设置默认工作目录。
- **归档 Session 管理**：workspace.json 的 archivedSessionIds
  - 列出归档会话；恢复（移出归档）；彻底删除。
- **Agent 模式管理** [优先]：~/.dsh/.agent-presets/<名>/（preset.yml + agent.cordis.yml + .mjs 钩子）
  - 列出可用模式（anchored-standard / liangshen 等）；查看说明；切换默认；复制新建。

### B. 配置与外观（用户已提）
- **Profile 管理** [优先]：$DSH_HOME/profiles/<名>/（dsh --profile <名> 启动）
  - 列出/切换/新建/复制 profile；显示当前 profile；dsh web 等价 --profile web。
- **插件管理** [优先]：`dsh plugin --profile <名> add <package>` + cordis.yml insert 行 + .dsh-market/
  - 列出已加载插件（解析 cordis.yml insert）；安装/卸载（dsh plugin 命令转发 pnpm，流式日志）；启停（注释 insert 行）。
- **主题/皮肤管理**：settings.yaml 的 UI 配置（skin-background / dsh-better-sidebar / ui-onboarding 等）+ ui-theme(--dsw-* token)
  - 切换皮肤开关/侧边栏配置；light/dark；主题预览。
- **LLM / 模型配置** [优先]：settings.yaml 的 agent-default-model + llm-pi-ai.providers
  - 查看/切换默认模型（provider / model / reasoningEffort），可选模型来自内置 provider 与自定义 provider 的 models 列表
  - 自定义 provider 管理：列出（baseURL / api 协议 / models），新增/编辑/删除（写前备份 settings.yaml）
  - **密钥安全设计**：apiKeyEnv 只存环境变量名，密钥在系统环境变量里 → 控制台只显示"使用了哪个环境变量、是否已设置"，引导用户配置环境变量，绝不读写密钥明文

### C. 运行时与任务（新增发现）
- **任务看板** [优先]：task-board/ledger-v2.json + scheduler-v2.json（tasks / scheduler / recentRequests）
  - 查看任务列表/状态；暂停恢复定时调度；新建简单定时任务。
- **运行时监控**（已有健康监控的深化）：dsh 进程 PID/端口/启动时间；web 日志流；sessions 存储占用。
- **模型/Provider 配置**：settings.yaml 的 agent-default-model（provider/model/reasoningEffort）+ llm-pi-ai providers
  - 查看当前默认模型；切换 provider/模型（改 settings.yaml，备份后写）。
- **模型用量 / 价格统计** [优先]：数据源 = 解压全部 ~/.dsh/sessions/*/session-*/session.jsonl.zstd
  - `request/header` 事件提供 provider + model；`assistant/chunk`(type=usage) 提供 inputTokens / outputTokens
  - 聚合：按模型 / 按天 / 按会话；显示 token 总量、调用次数
  - 价格估算：内置主流模型单价表（可编辑），输出估算费用
  - 后台线程解压扫描（~/.dsh/sessions 约几十 MB 可控），结果缓存

### D. 安全与运维（新增发现）
- **凭据管理**：.credentials.yaml —— 只做"是否存在/最后修改时间"提示，不明文展示密钥；引导用户自行编辑。
- **SSH 配置**：dsh-ssh.json —— 查看/编辑 dsh 自身 SSH 参数。
- **远端 Web 访问**：settings.yaml remote-web-ui.publicBaseUrl —— 查看/修改公网访问地址。
- **备份/迁移** [优先]：一键备份整个 ~/.dsh（zip，排除凭据）；导入/恢复。
- **日志管理**：dsh web 日志文件查看/清理（TEMP/dsh-dash/*.log）。
- **数据统计**：.anonymous-user-id —— 查看/关闭匿名统计。
- **pet 开关**：settings.yaml pet.enabled。

### 建议实施顺序
1. Session + Workspace + 归档（同一批数据域，UI 类似）
2. Agent 模式管理
3. Profile + 插件管理（dsh plugin 命令现成）
4. 任务看板
5. 主题 + LLM/模型配置（切换默认模型 + 自定义 provider + 用量价格统计 + 密钥引导）
6. 备份/迁移 + 凭据提示 + 其余只读项
