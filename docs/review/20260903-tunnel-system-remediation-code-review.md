# 综合代码评审记录：动态 SSH 隧道重构与生命周期治理

> **评审范围**：自 commit `7d2d5af` 之后的所有工作区变更（含 19 个修改文件、8 个新增未跟踪文件）
> **评审时间**：2026-09-03
> **评审基准**：`AGENTS.md` 核心四原则、`docs/ARCHITECTURE.md` 分层契约、自动化测试套件
> **状态**：🟢 **全部整改通过，测试 100% 全绿，准予 Stage & Commit**

---

## 一、评审对象概览

本轮代码修改集中在通用动态 SSH 隧道管理架构、场景向导助手、生命周期治理及历史冗余配置清理：

1. **核心业务与数据层**：
   - `core/tunnels.py`（动态隧道生命周期、卡片模型封装、批量调度、常驻重连）
   - `core/tunnel_planner.py`（方案快照、冲突校验、三态连通性自检）
   - `core/config.py`（动态隧道规范化、监控端口单一事实源派生、废弃字段清理）
   - `core/data.py` & `core/diagnostics.py`（下游端口探测与诊断报告适配）
2. **信号桥与主程序**：
   - `app/services.py`（扩展 `stop_tunnel`、`start_all_tunnels`、`stop_all_tunnels` 异步出口）
   - `dsh-console-aio.py`（主程序顶层配置派生与系统托盘操作联动）
3. **前端页面与向导交互**：
   - `ui/pages_tunnels.py`（动态卡片流、一键批量启停、方案切换协同）
   - `ui/dialog_tunnel_wizard.py`（场景向导、四典型模板、高级自定义与端口占用预检）
   - `ui/pages_settings.py`（精简旧端口增删表格与场景模板，保存时自动剔除废弃标量）
   - `ui/pages_deployments.py`（部署列表端口匹配适配动态 tunnels）
4. **构建与测试支撑**：
   - `build_win.bat`（补充 PyInstaller `--hidden-import ui.dialog_tunnel_wizard`）
   - `tests/test_tunnel_lifecycle.py`、`tests/test_tunnels_dynamic.py`、`tests/test_tunnel_planner.py`、`tests/test_dialogs.py`、`tests/test_gui_ui.py`
5. **文档与设计资产**：
   - `docs/ARCHITECTURE.md`、`docs/ROADMAP.md`、`RELEASE_NOTES.md`、`docs/plans/`（2 篇）、`.agents/notes/`（3 篇）

---

## 二、测试实测结果

| 测试套件 | 命令 | 结果 | 说明 |
|---|---|---|---|
| **静态语法编译** | `python -m compileall -q dsh-console-aio.py core ui app tests` | 🟢 **PASS** (0 错误) | 语法完全合规，无编译错误 |
| **纯单元测试** | `pytest tests/ -q` | 🟢 **PASS** (424 通过, 84 跳过) | 纯函数、业务模型、配置派生单测全部通过 (4.16s) |
| **GUI 冒烟测试** | `pytest tests/test_gui_smoke.py -m gui -q` | 🟢 **PASS** (40/40 通过) | MainWindow 离屏构造与真实资源隔离冒烟正常 |
| **GUI 纯 UI 测试** | `pytest tests/test_gui_ui.py -m gui -q` | 🔴 **FAIL** (43 通过, **1 失败**) | `TestLayoutFacts::test_right_bar_sections_with_empty_ports` 断言失败 |
| **CLI 离屏冒烟** | `python dsh-console-aio.py --smoke` | 🟢 **PASS** (`SMOKE_OK`) | `--smoke` 命令行模式启动正常退出 |

---

## 三、关键缺陷与隐患发现（Defect Backlog）

### 🔴 缺陷 1：测试回归 —— 假环境隔离失效导致空端口断言失败
- **位置**：`tests/test_gui_ui.py:329` 与 `dsh-console-aio.py:83`
- **现象**：
  运行 `pytest tests/test_gui_ui.py -m gui` 时，`test_right_bar_sections_with_empty_ports` 失败：
  ```text
  AssertionError: {'L3080': (...), 'L3090': (...), ...} == {}
  Left contains 6 more items
  ```
- **根因分析**：
  在 `dsh-console-aio.py` 中，配置加载由原先的裸 `json.load()` 改为：
  ```python
  def _load_config():
      return dsh_config.load_derived(CONFIG_PATH)
  ```
  该行在模块加载（Import Time）时即被执行，且默认使用 `allow_empty_ports=False`。在测试环境下，即使 `fake_env` 明确提供了空端口配置，`normalize_tunnels` 仍会将空配置回退为默认端口（3080、8090、8022 等），并把 `local_ports` 填充了 6 个监控单元格，导致本应测试空端口状态的测试用例断言失败。
- **修复方案**：
  1. `MainWindow` 在初始化（尤其是 `self.smoke=True` 或假环境）时，右侧监控栏 `StatusPanel` 应依据 `allow_empty_ports=self.smoke` 派生的配置进行初始化；
  2. 或在 `dsh-console-aio.py` 的 `_load_config()` 中根据运行参数（如 `--smoke`）动态传递 `allow_empty_ports`。

---

### 🔴 缺陷 2：配置逻辑陷阱 —— 用户无法清空隧道列表（空配置强制复活）
- **位置**：`core/config.py:56`（`normalize_tunnels`）
- **代码段**：
  ```python
  def normalize_tunnels(cfg, allow_empty_ports=False):
      raw = (cfg or {}).get("tunnels")
      if isinstance(raw, list) and len(raw) > 0:
          ...
      # 无 tunnels 时从旧字段合成
      ...
  ```
- **现象与影响**：
  当用户在界面中删除了所有隧道、或者方案中的 `tunnels` 明确为空列表 `[]` 时，`isinstance(raw, list) and len(raw) > 0` 判定为 False。
  系统会错误地认为该配置是“未配置 tunnels 的老旧历史配置”，从而强制从缺省值合成 3 条经典默认隧道（`dsh-tunnel`、`connect-lab-dsh`、`dsh-tunnel-reverse`）。
  **后果**：用户无法清空隧道，删除所有隧道后重启或切换方案，默认隧道会自动“复活”；`pages_tunnels.py` 中的空状态提示组件（`暂无配置的 SSH 隧道`）永远无法被展示。
- **修复方案**：
  应将判断条件改为只要键存在即认作声明式模型：
  ```python
  raw = (cfg or {}).get("tunnels")
  if raw is not None and isinstance(raw, list):
      # 显式配置了 tunnels 列表（包含空列表 []），按现有配置转换，不得回退合成
      out = []
      for idx, item in enumerate(raw):
          ...
      return out
  # 仅当 raw is None（即完全没有 tunnels 键的老配置）时，才回退从旧标量合成
  ```

---

### 🟡 隐患 3：方案切换停机与配置热重载的异步竞态风险
- **位置**：`ui/pages_tunnels.py:490-501`（`_plan_apply`）
- **代码段**：
  ```python
  # 1. 停止当前运行中的旧方案隧道
  self.app.service.stop_all_tunnels()

  # 2. 应用新方案并写入配置
  cfg = dsh_planner.apply_plan(dsh_config.load_config(), p)
  dsh_config.save_config(cfg)

  # 3. 刷新界面、重载配置并即时触发监控探测
  self._plan_refresh(select=p["name"])
  self.app.reload_config()
  self._render_cards()
  self.app.service.monitor_once()
  ```
- **现象与影响**：
  `self.app.service.stop_all_tunnels()` 是一个非阻塞的异步后台线程。
  主线程在发起停机后，毫秒级内紧接着执行了写配置、重载 `TunnelManager` 和 `monitor_once()` 探测。
  此时后台线程的 `taskkill` 或 SSH 进程退出可能尚未完成，新触发的 `monitor_once()` 极大概率探到旧进程占用的残存端口，导致右栏或自检短暂呈现冲突或异常红色；若用户紧接着快速点击【启动全部隧道】，新起的隧道进程甚至可能被尚未结束的旧 `stop_all` 杀死。
- **修复方案**：
  在 `_plan_apply` 中，可通过信号监听 `self.app.service.finished`（当 `op == "stop-all-tunnels"` 时）再行触发后续重载与探测，或在切换期间临时禁用操作按钮。

---

### 🟡 隐患 4：反向暴露端口冲突检测变量命名混淆
- **位置**：`core/tunnel_planner.py:134-145`
- **代码段**：
  ```python
  key = (host, lp)
  remote_rev_seen[key] = remote_rev_seen.get(key, []) + [tname]
  ...
  for (host, rp), names in remote_rev_seen.items():
      if len(names) > 1:
          issues.append({"level": "error", "msg": "公网暴露端口 %d 在服务器 %s 上被多条反向隧道重复暴露..." % (rp, host or "VPS", ", ".join(names))})
  ```
- **现象与影响**：
  虽然字典键名存入的是 `(host, lp)`（在反向规则中，`lp` 对应 remote forward 的第一个端口），但在下面的 `for` 循环中解构成了 `(host, rp)`。
  这属于变量命名混淆，虽然数值刚好能对上，但与第 117-118 行的 `lp/rp` 命名语义冲突，降低了代码可读性，后续维护极易引发理解错误。
- **修复方案**：
  统一变量命名为 `(host, exposed_port)`。

---

## 四、合规性与规范审查结果

| 审查维度 | 标准要求 | 检查结论 |
|---|---|---|
| **分层解耦** | `core/` 严禁 import PySide，纯业务无 UI | 🟢 **完全合规**。经全局检索，`core/tunnels.py` 与 `core/tunnel_planner.py` 零 Qt 依赖。 |
| **线程安全** | 严禁后台线程直接操作 QWidget，必须经 Signal 回主线程 | 🟢 **完全合规**。向导与管理页面的耗时操作均通过 `services.py` 桥接，使用类级 Signal。 |
| **进程防御** | Windows 子进程必须 `CREATE_NO_WINDOW`，文本模式 `errors="replace"`，防挂起 | 🟢 **完全合规**。`tunnel_mgr.py` 严格使用 `NO_WINDOW`，`_pid_alive` 采用 CSV 避免了 `os.kill(pid, 0)` 的 Ctrl+C 陷阱。 |
| **凭据安全** | 绝不读取写入私钥明文，IP/用户仅保留占位符 | 🟢 **完全合规**。SSH 仅使用标准路径，Token 仅内存流转，示例配置均已脱敏。 |
| **三引号禁令** | 防止补丁链路引号损坏，新代码使用 `#` 纯注释 | 🟢 **完全合规**。全部新模块均使用 `#` 行注释代替 docstring。 |
| **旧配置兼容** | 老用户升级零配置损坏 | 🟢 **基本合规**（需修复空列表被强制兜底的缺陷 2）。 |

---

## 五、评审结论与建议

### 结论：**需要针对缺陷 1 与缺陷 2 进行靶向修复，暂不宜直接 Stage**

本次重构的架构设计非常优秀，成功打破了原有的硬编码 3 卡片限制，并彻底解除了设置页历史端口表格对动态监控的污染。但在细节边界处理上：
1. **测试隔离（Defect 1）**：破坏了离屏测试用例 `test_right_bar_sections_with_empty_ports`；
2. **状态完整性（Defect 2）**：使“清空全部隧道”变成不可能的状态。

### 建议操作步骤：
1. **优先修复** `core/config.py` 中的 `normalize_tunnels` 逻辑（允许 `raw == []`）；
2. **修复** `dsh-console-aio.py` / `test_gui_ui.py` 中的 `allow_empty_ports` 隔离传导；
3. **消除** `core/tunnel_planner.py` 中的变量命名混淆；
4. 运行 `pytest tests/test_gui_ui.py -m gui` 确认所有 44 个 UI 测试全绿；
5. 测试通过后再执行分批 Stage 与 Commit。

---

## 六、整改复审与最终验收结论（2026-09-03 复审）

开发团队对上述评审意见已完成 100% 针对性整改，经独立复审与自动化测试验证：

### 1. 整改要点复核
- ✅ **缺陷 1 已彻底解决**：`dsh-console-aio.py` 支持 `--smoke` 及 `allow_empty` 参数，`MainWindow` 正确透传隔离模式，`fake_env.py` 补充了 `"tunnels": []`。测试 `test_right_bar_sections_with_empty_ports` 恢复通过。
- ✅ **缺陷 2 已彻底解决**：`core/config.py:normalize_tunnels` 判断逻辑修正为 `raw is not None and isinstance(raw, list)`，显式空列表 `[]` 不再被错误合成默认隧道。新增专用回归测试 `test_normalize_tunnels_explicit_empty_list`。
- ✅ **隐患 3 已彻底解决**：`ui/pages_tunnels.py` 的 `_plan_apply` 重构为基于 `service.finished` 信号流的异步状态机，旧隧道停止前置协调完毕后再写盘并触发探测，彻底消除端口误报与停机并发竞态。
- ✅ **隐患 4 已彻底解决**：`core/tunnel_planner.py` 统一重命名为 `(host, exp_port)`，变量语义与数据结构完全对齐。

### 2. 全量测试与门禁验证
- `compileall`：0 错误
- 纯单测：425/425 通过 (4.15s)
- GUI 基础冒烟：40/40 通过 (0.42s)
- GUI UI 测试：44/44 通过 (0.65s)
- **全量测试套件**（`pytest tests/ -m "gui or not gui"`）：**509/509 全部通过 (5.26s)**
- `git diff --check`：0 空白/格式异常
- CLI 离屏启动：`SMOKE_OK pages= 1 deploys= 1`

### 3. 最终结论
**准予通过评审。代码质量高、分层清晰、测试完善，完全符合入库要求，可立即进行 Stage 与 Commit。**
