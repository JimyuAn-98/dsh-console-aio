# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前快照：2026-08-31。**下一个开发任务已定 = 大菜第一阶段·技术债清理**（用户已拍板），
> 本文件核心是把它的精确清单和目标范式交代清楚，供新上下文直接开工。

---

## 一、当前状态（一句话）

PySide6 控制台 **17 页导航**（暗/浅亚克力 + 明暗变体切换 + 现代列表/卡片），**P0~P4 全部
完成 + P4 远程部署单独延后**；浅色主题、弹窗收敛（环境/安装→页面内分步）、dsh 卸载(保留/
含数据)均已落地；纯单元全过（沙箱内仅 tmp_path 写盘用例因环境限制失败，非回归）；
build_win.bat 与 CI 发版链路已打通。最近一批已提交 `5b00247`。

## 二、目录结构

```
dsh-console-aio.py   入口(主窗口壳 + 总览概览区(245-403) + 隧道页TunnelsPage(1281+)
                     + 日志桥 + 自绘工具栏 + --smoke/--diag-config)
core/                后端业务(纯 Python 零 Qt): config/data/dshctl/tunnels/tunnel_mgr/
                     tunnel_planner/version/keys/env/ops/profiles/sessions/plugins/
                     deployments/logs/cache/diagnostics
ui/                  前端: pages_*.py(15 个) + widgets.py(base/theme) ; dialogs.py 已退役删除
app/services.py      信号桥(DshService, 唯一"起后台线程+转信号"处; _run_result_op/_run_core_op 模板)
tools/dump_ui.py     离屏控件树 dump
installer/           Inno Setup 脚本
.github/workflows/release.yml  发版: 推 v* tag → PyInstaller + Inno → 上传安装包
.agents/notes/       决策记录(implemented/proposed)
```

> 注意：**总览页与隧道页不在独立 pages_*.py**，实现在主文件 `dsh-console-aio.py` 内
> （`OverviewPage` 概览 worker 在 245-403；`TunnelsPage` 在 1281+，含隧道方案规划器）。
> `docs/ARCHITECTURE.md` 是分层契约的权威来源，动 service/core 前先读它。

## 三、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**。默认 `pytest tests/` 只跑纯单元层，
   且**不包含 tmp_path 写盘用例的"全绿"预期**（本环境沙箱禁写 .pytest-tmp，这类用例在本机
   报 PermissionError，属环境限制；真机可过）。应用自带 `--smoke`（假隔离、构造即返回）
   是文档明示的离屏验证。
2. 后端（core）与 UI 之间一律 Qt 信号-槽；**services.py 是唯一"起后台线程 + 转信号"处**。
   `DshService` 两道通用模板：
   - `_run_result_op(op, func, *args)`：core 域函数 `func(events=None,...) -> dict`（含 "err"）
   - `_run_core_op(op, func, *args)`：core.data 纯数据函数（无 events 回调）→ `{"data","err"}`
   - 页面 connect `service.result(op, payload)` / `service.finished(op, ok)`，接收者为页面自身
     （页面销毁 Qt 自动断开）。**新页面禁止自起线程**。
3. 机器特定绝对路径、真实 IP/用户名不入库（config.json / 个人指南 gitignored）。
4. 写操作前 .bak 备份；凭据只做存在性提示，绝不读写明文。
5. **每次改动必跑**：`py_compile` 全量 + 相关纯单元。改 service/core 后跑对应 core 测试，
   改 UI 后做一次离屏构造冒烟（`QT_QPA_PLATFORM=offscreen` + 17 页导航）。
6. **Windows 严禁 `os.kill(pid,0)`**（== CTRL_C_EVENT，杀宿主；BUGS-002）。
7. **打包(frozen)运行 `__file__` 指向临时解压目录**——持久化路径一律走
   `core/config.default_config_path()` 与 `services.from_env`，**禁止新增 `__file__` 推导落盘**；
   同文件内同名函数禁止重复定义（后置覆盖前置，只在打包发作——BUG-009 教训）。
8. 三引号 docstring 禁令：经 JSON/补丁链路插入的多行字符串可能变双引号致 SyntaxError。
   新代码一律 `#` 注释；必须用三引号只写英文纯 ASCII。

## 四、环境信息

- **工作 Python**：`C:\ProgramData\miniconda3\python.exe`（3.12.9, PySide6 已装，本会话实测可用
  于 py_compile / pytest / 离屏冒烟）。conda env `console` 也存在于
  `C:\Users\1\.conda\envs\console\python.exe` 与 `C:\ProgramData\miniconda3\envs\console`
  （启动器 `启动dsh控制台.bat` 用 ProgramData 的 conda run -n console）。
- 端口 3080 = 正在运行的 dsh web，千万别碰。
- 本地打包：`build_win.bat`（PyInstaller onefile + Inno）；用 conda python 打包须把
  `%CONDA_PREFIX%\Library\bin` 加进 PATH（否则 ffi.dll 不入包闪退）。
- CI 发版：改版本四处（version.json / APP_VERSION / installer.iss 默认值 / RELEASE_NOTES）→
  提交 → `git tag vX.Y.Z && git push origin vX.Y.Z` → Action 自动构建并挂 Release。
- **CI 打包清单（新增懒加载页面必加）**：release.yml `--hidden-import ui.pages_X` +
  `--add-data ui/theme.qss` + `pip install -r requirements.txt`。
- 诊断：运行中 F12 控件指认；`--diag-config` 打配置链路（出键名不出值）。

## 五、下一步：大菜第一阶段 · 技术债清理（用户已拍板，本文件核心）

目标：**消灭"页面自起裸线程 / UI 直连 core 数据"的过渡态，统一经 `DshService` 收口**，
让后续所有页面开发建立在对 service 的统一依赖上。收敛模板见"铁律2"（`_run_result_op`/
`_run_core_op` + `service.result/finished` 信号）。逐项清单（都是已存在的过渡态）：

### 5.1 总览概览 worker —— 优先级最高
- 位置：`dsh-console-aio.py` 245-403（`OverviewPage`/概览区）。
- 现状：`worker`（403 `threading.Thread`）**直接调 `dsh_data.read_*`**（379-388）与
  `service.ctl.probe / probe_remote_tunnels`（391-400），经 `safe_emit(self._data, payload)` 回填。
- 目标：新增 `DshService.fetch_overview_snapshot(op="overview")`，把 worker 逻辑搬进 service
  （起线程 + 组装 payload + emit `result("overview", payload)`）；页面 `_apply_data(p)` 改为
  connect `service.result("overview")`。业务函数建议下沉 `core/data.py`（如 `data.overview_snapshot()`）
  保持 service 只做"起线程+转信号"。
- 注意：worker 里既有 `dsh_data.read_*`（走 `_run_core_op` 语义）又有 `service.ctl.probe*`
  （走 service 自己的 ctl）；建议在 service 里合成一个方法，避免页面拆两路信号。

### 5.2 pages_dsh（ui/pages_dsh.py）—— 本会话刚重写，含 4 处裸线程
- `_env_refresh`（267-268）：`core_env.tool_versions` → `_env_done` 信号。
- `_start_install`（402）：`core_env.install_dsh(events)` → 进度/日志/完成。
- `_start_uninstall`（524）：`core_env.uninstall_dsh(events)` → 进度/日志/完成。
- `_fetch_tags`（588）：`core.dshctl.fetch_dsh_tags` → `_tags_done`。
- 目标：各加一个 service 方法（`fetch_env_versions / install_dsh / uninstall_dsh / fetch_dsh_tags`），
  页面改为 connect `service.result`。**注意 install/uninstall 是流式 events（step/log）**，
  service 需把 events 转成既有 log 信号或专用信号——建议在 service 里新增
  `run_result_with_events` 模板或在方法内把 events 映射到 `result`/日志。

### 5.3 pages_settings（ui/pages_settings.py）
- `_test_ssh`（213-215）：`core_env.test_ssh` → `_ssh_done`。
- `_gen_diag`（393-394）：`core.diagnostics` 生成诊断报告 → `_diag_done`（可复用于报告导出）。
- 目标：`service.test_ssh(...)` / `service.gen_diag(...)`。

### 5.4 三个纯读列表页
- `pages_sessions`（189）：`dsh_data` workspace/group 读取 → `_data`。
- `pages_profiles`（131）：profiles 列表 → `_data`。
- `pages_plugins`（220）：Profile 列表读取 → `_profiles`。
- 目标：走 `_run_core_op` 新增 `service.read_sessions_list / read_profiles / read_plugins_profiles`
  （core 里对应的纯读函数签名不带 events，最贴 `_run_core_op` 模板）。

### 5.5 TunnelsPage 隧道方案读写（主文件 1348-1469，优先级较低）
- 现状：同步 `dsh_planner.load_plans/apply_plan/upsert_plan/delete_plan/validate_plan/self_check`
  直接在主线程跑（本地小文件，不阻塞，无自起线程）。ROADMAP 列为"待审视"。
- 评估：皆本地快 IO，**不属硬阻塞线程债**；可保留同步（省事），或顺手迁
  `core/tunnel_planner.py` 已有纯函数层。**建议：本项可暂缓**，先做 5.1-5.4。

### 5.6 完成标准 & 验证
- 标准：`grep -r threading.Thread ui/` 仅剩 base.py 无；`grep -r "core import" ui/` 页面不再
  直接 import 业务模块（除纯常量）。分层验收清单四条全过（见 docs/ARCHITECTURE.md）。
- 验证：每次改动 py_compile + 相关纯单元；离屏 17 页导航冒烟（含总览/隧道/设置/会话/
  profiles/插件/DSH 页）；核心逻辑在 core 层加纯单测。
- 每完成一项在 `docs/ROADMAP.md`「未做/候选」的"技术债"行勾掉，并更新 RELEASE_NOTES + 决策
  note（`.agents/notes/implemented/architecture/` 下，命名 `2026-08-31-tech-debt-*.md`）。

### 5.7 完成后（下一件候选，顺序返回到 ROADMAP）
- 弹窗收敛剩余：危险确认 `QMessageBox.question`（存量约 20 处）→ 页面内确认条组件（A2），按页分批。
- 候选功能：托盘常驻 / 多主题预设切换（Mica 深色/纯色） / 布局记忆 / 主题文件跨机导入导出 /
  多套拓扑配置切换。

## 六、协作提醒

- 用户**人工验收 GUI**：外观/交互类改动由用户重启控制台拍板，不要自行判定完成；用户自行
  维护 README 截图（docs/screenshots），提交用明确路径 add，**避免 `git add -A` 扫进用户
  进行中的文件**（但本会话改代码时 `git add -A` 是干净的，可放心）。
- 用户偏好：现代简约观感、少弹窗、固定栏宽不互相挤压、状态文字在标题右侧、"一件一件来"。
- 上一个交接文档（2026-08-30 v0.6.0）已在本次重写整并；发版流程与打包清单见"四、环境信息"。
