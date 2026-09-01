# 方案与实施记录（PLANS）— 历史归档

> 本文档为**历史方案与决策记录**（已完成/归档内容）。
> 当前路线与状态见 `docs/ROADMAP.md`；已知问题见 `docs/BUGS.md`；愿景探索见
> `docs/VISION_部署子工具组.md`。

---

## 1. 配置编辑器方案（原"ABC 方案"）[已完成]

> 背景：早期讨论把"手改 config.json"降低门槛时，提出过 A/B/C 三级渐进方案。
> 用户最终选择：**方案 A + 轻量版 B**，并**已完成**。

- **方案 A — 配置向导（增强现有配置对话框）** [已完成]
  - 原 7 字段平铺对话框 → 分组向导：① 公网中转服务器 ② 本机 dsh ③ 隧道参数 ④ 轮询
  - 每个字段带灰色帮助文字；新增"测试 SSH 连接"按钮（在线验证免密）。
- **方案 B — 隧道创建向导 + 拓扑模板** [已完成(轻量版)]
  - 内置 3 个场景模板（在家→中继 / 实验室→直连 / 本机→中继反向），一键填充端口映射。
  - 完整版（任意新增/删除隧道卡片、动态生成卡片）**暂未实现**，作为后续可选。
- **方案 C — 连接向导 + 一键诊断 + 自动化** [规划/未做]

---

## 2. 一键安装 dsh（全新环境辅助）[已完成]

- 顶部**【安装 dsh】**按钮 → 安装向导（InstallDialog）
- 默认仓库地址：官方 deepseek-harness（可改）
- 流程：环境预检 → git clone → pnpm install → pnpm build → 写 dash_repo 到 config.json

---

## 3. 环境监测独立窗口（运维辅助）[已完成]

- 独立"环境检查"窗口；推荐版本以**当前开发机为基准**；卸载走系统设置提示。
- 每个工具一行（git/node/npm/pnpm），带 更新/安装/卸载 三按钮，点击先说明将执行什么、确认后执行。
- 更新：git → `git update-git-for-windows`；npm → `npm install -g npm@latest`；
  pnpm → `pnpm add -g pnpm@latest`；node → 提示用 nvm-windows 或官网。
- 安装：git/node → 官网下载页；pnpm → `npm install -g pnpm`；npm → 随 Node.js。
- 卸载：统一打开系统"设置-应用"页，不自动卸载。
- 命令后台线程执行（CREATE_NO_WINDOW + 超时），完成后弹结果框。

---

## 4. 历史脱敏（重要安全操作）[已完成]

> 2025-08-25：早期 3 个 commit（初版 / 脱敏legacy / 配置向导）含真实 IP 与用户名，已用 git-filter-repo 全局重写历史。

- 工具：git-filter-repo（pip install git-filter-repo），--replace-text 规则替换。
- 替换：185.238.250.148 → YOUR_PUBLIC_IP；10.1.12.204 → YOUR_LAB_IP；hjy → YOUR_USER；huangjiy → YOUR_NAME；路径 → 占位。
- 验证：7 个 commit 全部文件 + 提交信息 敏感命中 = 0。
- 已 force push 覆盖远程 main（83c483d → 7e4d209）。
- 注意：曾 clone 过旧仓库的人本地仍有旧提交副本，无法远程抹除；GitHub 侧旧对象会在 GC 后移除。
- 备份：本地 dsh-backup-history/.git-*（完整旧 .git 备份）。

---

## 5. v2 宏大计划：进化成"dsh 控制台"（2025-08-25）[已实现]

> 用户愿景：从"隧道管理工具"进化为专为 dsh 设计的控制台软件。已实现为 13 页
> PySide6 控制台（v0.3.0+）；后续路线见 `docs/ROADMAP.md`。以下**机制调研结论**仍有参考价值。

- **Profile 机制**：`dsh --profile <name>` 是真实命令（`dsh web` 等价于 `dsh --profile web`）。
  profile 位于 `~/.dsh/profiles/<name>/`：cordis.yml + cordis.patch.yml + package.json + node_modules。
- **插件机制**：cordis.yml 用 `insert:` 行加载插件（id + npm 包名）；`.dsh-market/` 为市场目录；
  安装 = 改 package.json + cordis.yml insert + pnpm install。
- **主题机制**：`~/.dsh/settings.yaml` 的 UI 配置项（skin-background、dsh-better-sidebar 等）；
  web 主题由 ui-theme 包（--dsw-* CSS token）实现。
- **运行时监控**：dsh 运行时产物在 `~/.dsh/sessions/`、`storages/`、`remote-web-ui`。

---

## 6. 功能全景清单（v0.3.0 时代调研）[已实现 ✅]

> 2025-08-25 调研 ~/.dsh 与 dsh CLI 后整理的功能域全景，v0.3.0 已全部实现（数据源说明保留参考）。

### A. 会话与工作区（mgmt_sessions.py）
- Session：`~/.dsh/sessions/<编码工作目录>/session-<uuid>/session.jsonl.zstd`（浏览/删除/导出）
- Workspace：`storages/workspace.json`（workspaceIds）
- 归档 Session：archivedSessionIds（恢复/彻底删除）
- Agent 模式：`~/.dsh/.agent-presets/<名>/`（preset.yml + agent.cordis.yml + .mjs 钩子）

### B. 配置与外观（mgmt_profiles / mgmt_plugins / mgmt_llm）
- Profile：`$DSH_HOME/profiles/<名>/`（列出/切换/复制）
- 插件：`dsh plugin --profile <名> add <package>` + cordis.yml insert + .dsh-market/
- LLM/模型：settings.yaml 的 agent-default-model + llm-pi-ai.providers；
  **密钥安全**：apiKeyEnv 只存环境变量名，绝不读写密钥明文

### C. 运行时与任务（mgmt_taskboard / mgmt_usage）
- 任务看板：`task-board/ledger-v2.json` + `scheduler-v2.json`
- 模型用量：解压 sessions 的 jsonl.zstd，`request/header` + `assistant/chunk`(usage) 聚合

### D. 安全与运维（mgmt_ops）
- 凭据：.credentials.yaml 只做存在性提示；SSH 配置 dsh-ssh.json；备份 zip 排除凭据；
  日志 TEMP/dsh-dash/*.log；pet 开关 settings.yaml

### E. SSH 密钥管理（mgmt_keys.py）
- 红线：私钥内容**绝不读取**，只展示 文件名/时间/算法/指纹；公钥可复制；
  生成 ed25519；部署提示手动 ssh-copy-id

---

## 7. 多部署管理（v0.4 方向）[已实现为 deployments 页]

> 用户愿景：在隧道基础上成为"对所有部署的 dsh 的管理"控制台。当前已实现 deployments
> 页（CRUD/连接测试/只读快照）；**远程部署子工具组**（隧道之上的安装/更新/日志）列入
> `docs/ROADMAP.md` P4。

- 架构：DshRemote 抽象（本地=文件系统；远程=SSH 只读命令 + cat 拉取），部署清单在
  gitignored 的 config.json deployments 数组；复用 SSH 免密凭据；远程写操作一律确认。
- 安全原则：只读优先；部署信息只存 gitignored 文件。

---

## 8. UI 前后端分层重构简史（2026-08-28 ~ 2026-08-29）[已完成]

- 阶段0：dsh_core（config/dshctl/tunnels）+ DshService 信号桥 + dsh 更新流恢复
- 阶段1：主窗口/隧道页/监控走 service；_stream_cmd 收敛 dshctl.stream_cmd
- 阶段2：11 个页面业务逐波下沉 core（波1 version/keys，波2 ops/profiles/sessions，
  波3 plugins/deployments，波4 dialogs→env）
- 阶段3/4：数据层归并 core/data.py（删 dsh_data shim）、四个纯读页统一经 service
- 最终形态：core 纯 Python 零 Qt；UI 零子进程业务；全信号-槽；纯单元 307 例。
  迁移细节见 `docs/UI_LAYERING.md` 与 `.agents/notes/`。
