## 🎉 dsh-console-aio v0.8.1

**dsh All-In-One 控制台**：SSH 隧道管理 + 本机 dsh 启停/安装/更新 + 健康监控 + 17 页 dsh 数据域管理，PySide6 暗色亚克力界面。

### 下载
- **安装包（推荐）**：`dsh-console-aio-setup-0.8.1.exe` — 中文安装向导，无需 Python 环境，支持卸载/升级

### 本版亮点（v0.8.0 以来）
- 🧩 **dsh 双安装模式 + 自动检测**：源码克隆（可跑本地未发布代码）/ npm 全局包（`npm install -g @deepseek-ai/dsh`，与官方 npx 同源扁平布局）；DSH 管理页页头自动显示当前模式，启动/更新/卸载/版本切换全部按模式分流
- 📜 **长操作完整输出日志**：安装/更新/卸载/部署/启停全过程落盘 `%TEMP%\dsh-console-ops\*.log`（不受页面日志条数限制），落盘前对 Token 做脱敏；DSH 管理页「打开操作日志」一键查看
- 🩺 **失败摘要 + 进度心跳**：长命令静默期间每 15s 输出「已运行 N 秒」，失败时给出 `[失败摘要]` 与中文提示（如依赖版本解析失败），排查不再翻几千行日志
- 🗑️ **卸载删除加固**：原生 `rmdir` 快删 + Python 后序精修（清只读、跳过 junction/符号链接、每 2000 项进度），实测 75541 项源码树 31.1s 删净
- 🛰️ **节点访问**：总览「节点」区（本机 + 远程）、部署配置显式化（`node_key/web_port/tunnel_id/access_port`）、节点码 + `runtime.json` Token 落盘 + 公网鉴权信箱发现与同步
- 🔄 **一键更新升级**：安装版点「一键更新」直接下载最新安装包 → 自动退出 → 运行安装器
- 🧪 质量面：纯单元测试 549 例；`compileall` 全量通过

### 系统要求
- Windows 10/11 x64；安装包无需 Python

### 变更历史
详见仓库 RELEASE_NOTES.md 与程序内「关于与更新」页

---
**感谢使用！问题反馈请开 Issue：** https://github.com/JimyuAn-98/dsh-console-aio/issues
