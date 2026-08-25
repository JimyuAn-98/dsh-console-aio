# PySide6 页面迁移规范（PYSIDE_MIGRATION）

> 状态：进行中 · 最后更新：2026-08-25
> 本文件是 PySide6 批量页面迁移的**唯一权威框架**。所有参与迁移的 subagent 必须先读本文件 + AGENTS.md（含 4 条核心工作原则），再动手。

## 1. 背景与目标

dsh-console-aio 原为 tkinter 零依赖 GUI。现决定 UI 层迁移到 PySide6（现代暗色主题 + 线程安全 + 可打包 exe）。
- **数据层复用**：dsh_data.py（纯函数）与 tunnel_mgr.py 完全复用，零改动。
- **UI 框架**：现代暗色 QSS 主题（ui/theme.qss），app_pyside.py 为主框架。
- **最终形态**：全部页面迁完并验证后，整合为新 dsh-console-aio.py（内容为 PySide6），旧 tkinter 版归档 legacy/。

## 2. 核心工作原则（必须遵守）

1. **文档工作一定要做全**：每页迁移后同步更新本文件的「页面清单」；不留下无文档改动。
2. **框架性的东西一定在最开始就定好**：架构/接口/范式以本文件为准，不在中途改框架。
3. **逻辑实现一定要最简洁**：能复用 PySide6 控件/布局、dsh_data、tunnel_mgr 现有能力，就不要重复造轮子。
4. **测试和评审工作一定要完善**：每页 py_compile + 离屏构造 + 导航 smoke 由开发者做全；真实 SSH/启动服务等需用户机器配合的留用户实测。

## 3. 目录 / 包结构

    dsh/
      app_pyside.py                # PySide6 主框架(入口/加载器) - 活跃开发
      dsh-console-aio.py           # 旧 tkinter 主程序 - 只读保留，迁完归档
      mgmt_*.py                    # 旧 tkinter 页面 - 只读保留，迁完归档
      dsh_data.py / tunnel_mgr.py  # 数据层/隧道 - 复用，零改动
      ui/theme.qss                 # QSS 主题(独立，可编辑器打开)
      pyside/                      # PySide6 页面包(本规范的核心产物)
        __init__.py
        base.py                    # BasePage 基类
        pages_overview.py          # 总览页
        pages_tunnels.py           # 隧道页
        pages_sessions.py          # 会话与工作区页
        ...                        # 其余 pages_*.py

## 4. 页面范式（BasePage）

所有 PySide6 页面是 BasePage(QWidget) 子类，构造签名 **(app)**，app 即主窗口 MainWindow，通过 self.app 访问主窗口能力。

    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

    class BasePage(QWidget):
        def __init__(self, app, parent=None):
            super().__init__(parent)
            self.app = app          # MainWindow 实例
            self._build()

        def _build(self):
            pass                    # 子类实现 UI

### 页面可用的主窗口能力（通过 self.app）

| 方法/属性 | 说明 |
|---|---|
| app.loge(text, tag) | 写主日志区(tag: ok/err/warn/空)，线程安全 |
| app.set_status(text) | 更新底部状态栏，线程安全 |
| app._current_deploy | 当前部署 dict(None=本机)；页面据此构造 DshRemote 做远程操作 |
| app.DASH_REPO | dsh 仓库路径(页面需要 cwd 时用) |

参考样板：pyside/pages_tunnels.py(TunnelsPage) 与 pyside/pages_overview.py(OverviewPage) 是**已完成的范式**，新页面照着它们写。

### 线程安全（重要）

- 只允许主线程操作 Qt 组件。
- 后台线程(SSH/子进程/IO)只做计算，结果经 app.loge / app.set_status(内部走 LogBridge queued signal)回到主线程，绝不直接改 UI 组件。
- 子进程一律 creationflags=subprocess.CREATE_NO_WINDOW；批处理 shim 用 .cmd 后缀；text=True, errors='replace'。

## 5. 页面清单与状态

| 导航项 | key | 页面文件 | 类名 | 状态 |
|---|---|---|---|---|
| 总览 | overview | pages_overview.py | OverviewPage | 已迁 |
| 隧道 | tunnels | pages_tunnels.py | TunnelsPage | 已迁 |
| 会话与工作区 | sessions | pages_sessions.py | SessionPage | 待迁 |
| Agent 模式 | agents | pages_agents.py | AgentPage | 待迁 |
| Profile 管理 | profiles | pages_profiles.py | ProfilePage | 待迁 |
| 插件管理 | plugins | pages_plugins.py | PluginPage | 待迁 |
| 任务看板 | taskboard | pages_taskboard.py | TaskboardPage | 待迁 |
| 模型用量 | usage | pages_usage.py | UsagePage | 待迁 |
| LLM 配置 | llm | pages_llm.py | LlmPage | 待迁 |
| 备份与运维 | ops | pages_ops.py | OpsPage | 待迁 |
| SSH 密钥 | keys | pages_keys.py | KeysPage | 待迁 |
| 关于与更新 | version | pages_version.py | VersionPage | 待迁 |
| 部署管理 | deployments | pages_deployments.py | DeploymentPage | 待迁 |

## 6. 页面加载方式（主框架 _show_page）

app_pyside.py 的 _show_page(key) 按 key 分发。迁移一个页面 = 在 pyside/ 新建 pages_<key>.py 实现 XxxPage(BasePage)，再在 _show_page 的 key 分支里 import 并构造。

注意：页面类必须定义在模块可被 import 的顶层；所有页面类在 if __name__ == '__main__': 之前定义(防直接运行时未定义)。

## 7. 每页验收标准（开发者做全）

1. python -m py_compile <文件> 通过。
2. 离屏构造：QT_QPA_PLATFORM=offscreen 构造页面不崩。
3. 导航 smoke：主框架 _show_page('<key>') 后当前栈页类型正确。
4. 渲染截图 PNG，供用户目测观感。
5. 同步更新第 5 节状态为已迁。

## 8. subagent 任务模板

subagent 的 prompt 必须包含：本文件路径、AGENTS.md 路径、旧 tkinter 页面源文件(mgmt_<key>.py)、目标 pyside/pages_<key>.py、范式样板(pages_tunnels.py)、验收清单。subagent 只产出页面文件 + 必要的 self.app 调用，不修改主框架路由(路由由主任务统一改)。

## 9. 尚未纳入本规范的部分（后续阶段）

- 配置向导/安装/环境检查 对话框(tk.Toplevel)的 PySide6 迁移。
- 健康监控(右侧栏实时端口/隧道状态)接入。
- 打包适配(QSS add-data + 冻结路径)。

