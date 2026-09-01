# 决策记录: 通用缓存层全面推广与技术债统一收口

- **状态**: Implemented
- **日期**: 2026-09-01
- **分类**: architecture / technical-debt

## 背景与问题

在前期功能快速迭代过程中，控制台逐步扩展了会话、Profile、插件、任务看板、Agent 模式等多个数据域页面。在此期间积累了以下两类技术债：
1. **数据读取缺少统一缓存**：除用量页外，其他页面每次切换导航均需触发全量磁盘/SSH 读取，不仅影响界面响应速度，也缺乏统一的“无变化/有变化/失败”状态反馈。
2. **UI 页面私起线程与私有 Signal 蔓延**：部分早期页面（如 `DshManagePage`、`SettingsPage`、`SessionsPage`、`ProfilesPage`、`OverviewPage`）直接在页面内部 `threading.Thread(...)` 或定义私有 `Signal`，破坏了 `AGENTS.md` 中“`core/` 纯 Python 零 Qt -> `app/services.py` 唯一后台线程出口与信号桥 -> `ui/` 纯展示与事件驱动”的架构分层硬约束。

## 决策内容

### 1. 通用缓存层全面推广
- **机制统一**：会话（Sessions）、Profile、插件（Plugins）、任务看板（Taskboard）、Agent 模式 全面接入 `core/cache.py` 与 `RefreshIndicator`。
- **按需刷新**：进入页面时先读本地缓存（`read_cache`），若时间戳未落后（`not needs_refresh`）直接秒开呈现并亮绿灯；源时间戳变动或用户点击刷新时发起后台读取，回包后对比签名（`data_changed`）并亮黄灯，错误亮红灯。
- **Profile 联动与写后刷新**：插件页 Profile 下拉切换时以 `plugins_<profile>` 为 key 隔离缓存；所有写操作（启停、归档、修改）完成后强制刷新缓存。

### 2. Core 纯数据层扩展
- 在 `core/data.py` 中新增各域 mtime 探测纯函数：`sessions_source_mtime`、`plugins_source_mtime`、`taskboard_source_mtime`、`agent_presets_source_mtime`、`profiles_source_mtime`。
- 新增脱离 Qt 的聚合读取纯函数：`read_sessions_data`（会话+工作区）、`collect_overview_data`（总览纯数据快照）。

### 3. Service 信号桥收口与裸线程清理
- 在 `app/services.py` 的 `DshService` 中新增 `step = Signal(int, str)` 信号，并标准化提供 9 个服务方法：`read_overview`、`read_sessions`、`list_profiles`、`check_tool_versions`、`fetch_dsh_tags`、`install_dsh`、`uninstall_dsh`、`test_ssh`、`generate_diagnostics`。
- 彻底清理 UI 层所有页面的裸线程（`threading.Thread`）与私有 `Signal`，UI 页面仅通过 `service.<method>` 触发并由 `_on_result` / `_on_finished` 槽接收。

## 放弃的备选方案

- **在页面内各自定义后台 Worker QThread**：放弃。QThread 会增加页面自身生命周期管理的复杂度，且无法做到集中流式日志管理与任务取消。
- **全局统一定时轮询各页面数据**：放弃。控制台定位为轻量级管理工具，小白用户本地及远程 SSH 资源有限，采用“进页时按需探测 + 手动即时刷新”的策略更轻量可靠。

## 影响面与测试

- **影响文件**：
  - `core/data.py`
  - `app/services.py`
  - `ui/pages_sessions.py`
  - `ui/pages_profiles.py`
  - `ui/pages_plugins.py`
  - `ui/pages_taskboard.py`
  - `ui/pages_agents.py`
  - `ui/pages_dsh.py`
  - `ui/pages_settings.py`
  - `dsh-console-aio.py`
  - `tests/test_core_cache.py`
  - `tests/test_services.py`
  - `tests/test_dialogs.py`
  - `tests/test_gui_smoke.py`
  - `tests/test_gui_ui.py`
- **验证结果**：
  - `compileall` 编译零错误；
  - 400 个 pytest 纯单元测试全过；
  - 83 个 GUI 冒烟测试全过；
  - `python dsh-console-aio.py --smoke` 冒烟通过。
