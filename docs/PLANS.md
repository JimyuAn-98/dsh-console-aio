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
