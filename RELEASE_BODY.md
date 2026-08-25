## 🎉 dsh-console-aio v0.3.0 — 首个发布版

**dsh All-In-One 控制台**：SSH 隧道管理 + dsh 安装/更新 + 环境检查 + 9 个 dsh 数据域管理窗口，零依赖 Windows GUI。

### 下载
- **安装包（推荐）**：`dsh-console-aio-setup-0.3.0.exe` — 中文安装向导，无需 Python 环境，支持卸载/升级
- **便携版**：`dsh-console-aio.exe` — 单文件，解压即用

### 功能总览
- 🚀 隧道管理：三条 SSH 隧道（启动/常驻/停止）+ 本机 dsh 启停/一键更新/一键安装
- 🖥️ 环境检查：git/node/npm/pnpm 版本 + 更新/安装/卸载引导
- 📡 健康监控：本机端口 + SSH 直查远端反向隧道，两层监控
- 🗂️ dsh 管理（v2 架构）：会话与工作区、Agent 模式、Profile、插件、任务看板、模型用量、LLM 配置、主题外观、备份运维
- 🔄 版本管理：检查更新 + 更新日志 + 一键更新
- 📦 首次启动自动引导配置（可跳过）

### 安装包使用说明
1. 运行安装包 → 中文向导 → 完成（可选桌面快捷方式）
2. 首次启动检测未配置 → 引导打开配置向导
3. 日常使用：隧道卡片一键启停，顶部【dsh 管理】菜单进入 9 个管理窗口

### 系统要求
- Windows 10/11 x64
- 安装包无需 Python；便携版/源码运行需要 Python 3（建议 Miniconda）

### 变更历史
详见仓库 RELEASE_NOTES.md（更新日志窗口内也可查看）

---
**感谢使用！问题反馈请开 Issue：** https://github.com/JimyuAn-98/dsh-console-aio/issues
