# 架构（dsh 控制台 · 当前实现）

> 2026-08-25 初稿（tkinter 时代）→ **2026-08-29 重写**：PySide6 迁移 + UI 前后端分层重构
> （阶段 0–4）完成后的当前结构。旧 tkinter 设计已废弃，归档见 `legacy/`；
> 分层设计蓝图与信号-槽契约详见 `docs/UI_LAYERING.md`。

## 当前分层（2026-08-29）

```
┌─ 后端层 core/  (纯 Python, 严禁 import PySide) ────────────────┐
│  config.py      配置加载与派生常量(含 allow_empty_ports 隔离分支)     │
│  data.py        数据域: YAML/workspace/profiles/plugins/用量/部署     │
│                 (原根级 dsh_data.py 已归并于此, 兼容 shim 已删除)      │
│  dshctl.py      dsh 启停/完整更新/监控探测/流式命令 stream_cmd        │
│  tunnels.py     隧道启停/常驻重连(基于 core/tunnel_mgr.py)             │
│  version.py     控制台自身版本检查与自更新                           │
│  keys.py        SSH 密钥(私钥安全红线)                              │
│  env.py         环境检查/一键安装(dialogs 业务下沉)                  │
│  ops.py         备份/日志/凭据存在性                                 │
│  profiles.py    Profile 复制/删除(远程只读红线)                      │
│  sessions.py    会话归档/恢复/分组删除(远程只读红线)                  │
│  plugins.py     插件列表/启停/安装卸载(远程只读红线)                  │
│  deployments.py 部署快照/保存(远程只读红线)                          │
└─────────────────────────────────────────────────────────────────────┘
┌─ 接口层 app/services.py  (可 import PySide) ────────────────────────┐
│  DshService(QObject): status/log/card/monitor/result/finished 信号, │
│  起后台线程跑 core, events 回调转发为 Qt Signal(唯一起线程处)     │
└─────────────────────────────────────────────────────────────────────┘
┌─ UI 层  (只展示 + 订阅信号 + 调 service) ───────────────────────────┐
│  dsh-console-aio.py  主窗口壳(顶栏/导航/右栏/日志) + 总览页 + 隧道页  │
│  ui/pages_*.py   11 个管理页(sessions/agents/profiles/plugins/  │
│                      taskboard/usage/llm/ops/keys/version/          │
│                      deployments)                                   │
│  ui/dialogs.py   配置向导 / 安装向导 / 环境检查                  │
│  ui/base.py      BasePage(safe_emit 页面销毁竞态防护)            │
│  ui/theme.qss        主题(内嵌 QSS 兜底)                            │
└─────────────────────────────────────────────────────────────────────┘
```

## 数据与配置

| 项 | 位置 | 说明 |
|----|------|------|
| config.json | 仓库根(exe 旁), **gitignored** | dash_repo / dash_port / ssh 服务器 / 隧道 / 部署清单; `DSH_AIO_CONFIG` 环境变量可覆盖(测试隔离) |
| ~/.dsh | `DSH_HOME` 可覆盖 | profiles/ sessions/ storages/ task-board/ settings.yaml / .agent-presets |
| DshRemote | core/data.py | 本机 / 远程(ssh 免密只读)统一抽象 |
| core/tunnel_mgr.py | core/ | 纯 Python SSH 隧道管理器, 被 core.tunnels 使用 |

## 数据域 ↔ 实现映射

| 数据域 | core 模块 | UI 页面 | 说明 |
|--------|-----------|---------|------|
| 会话/工作区/归档 | sessions.py | ui/pages_sessions.py | 远程部署下写操作拒绝 |
| Agent 模式 | data.py | ui/pages_agents.py | .agent-presets 只读 |
| Profile 管理 | profiles.py | ui/pages_profiles.py | 复制/删除, web 拒删 |
| 插件管理 | plugins.py | ui/pages_plugins.py | 官方 dsh plugin 命令经 service.run_cmd |
| 任务看板 | data.py | ui/pages_taskboard.py | ledger-v2 + scheduler-v2 只读 |
| 模型用量/价格 | data.py | ui/pages_usage.py | zstd 解压聚合, 价格表可编辑 |
| LLM/模型配置 | data.py | ui/pages_llm.py | settings.yaml agent-default-model |
| 备份/日志/凭据 | ops.py | ui/pages_ops.py | 备份排除凭据 |
| SSH 密钥 | keys.py | ui/pages_keys.py | 私钥内容绝不读取 |
| 版本/自更新 | version.py | ui/pages_version.py | 控制台自身更新 |
| 部署管理 | deployments.py | ui/pages_deployments.py | 远程只读快照 |
| 隧道/本机 dsh | dshctl.py + tunnels.py | dsh-console-aio.py(TunnelsPage) | 卡片动作经 service 信号桥 |
| 总览 | data.py | dsh-console-aio.py(OverviewPage) | 部署状态快照(尚未走 service, 已知例外) |

## 信号-槽契约（硬约束）

- 业务层(core) **不 import PySide**，只向调用方抛纯数据事件/回调。
- services.py 是**唯一**起后台线程并转 Qt 信号的地方；UI 只订阅信号 + 调 service 方法。
- 禁止跨线程/跨进程直接改 UI（用户硬约束）。完整契约见 `docs/UI_LAYERING.md`。

## 测试与安全边界

- 默认 `python -m pytest tests/` 只跑**纯单元 294 例**（`-m "not gui"`）；
  构造 MainWindow 的测试(`test_gui_ui.py` / `test_gui_smoke.py`)一律 `-m gui` 人工执行——
  **绝不自动跑会触碰端口 3080 真实 dsh 的测试**(历史事故教训)。
- 纯单元测试隔离手段: DSH_AIO_CONFIG 假配置 + DSH_HOME 假目录 + monkeypatch 子进程 +
  service 通道拦截 + threading.Thread.start 硬拦截。
- 凭据安全红线: 私钥/API key 只显示存在性与指纹/环境变量名, 绝不读写明文; 远程写操作一律确认。

## 历史（tkinter 时代, 已废弃）

- 旧设计: 零依赖(仅 stdlib) tkinter 主程序 + `mgmt_*.py` 独立 Toplevel 管理窗口 +
  `core/data.py` 数据层 + "dsh 管理"菜单。
- 已由 PySide6 主框架替代(`07b70fd`), 旧 tkinter 主程序归档 `legacy/dsh-console-aio-tkinter.py`;
  迁移记录见 `docs/PYSIDE_MIGRATION.md` 与 `RELEASE_NOTES.md`。
