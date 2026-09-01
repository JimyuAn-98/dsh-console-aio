# 通用缓存层全面推广与技术债统一收口（实施方案 v1）

- 编号: `docs/plans/20260901-cache-and-tech-debt-v1.md`
- 日期: 2026-09-01
- 目标:
  1. 全面推广 `core/cache.py` 缓存机制至各重读数据页（Sessions、Plugins、Taskboard、Agents、Profiles）；
  2. 彻底清理各页面内的裸线程（`threading.Thread`）与私有 Signal，统一收口至 `app/services.py`（`DshService`）。

---

## 一、 背景与架构契约

### 1.1 背景
- 前期已在 `ui/pages_usage.py`（用量页）完成通用缓存层 `core/cache.py` 与 `RefreshIndicator` 控件的验证，实现了“数据源 mtime 探测 + 缓存秒开 + 异步按需重扫 + 状态指示灯”。
- 部分页面（如概览页 `OverviewPage.refresh`、`pages_dsh` 的 4 处线程、`pages_settings` 的 SSH 测试与诊断生成、`pages_sessions`、`pages_profiles`、`pages_plugins` 等）仍存在直接起 `threading.Thread` 或私有信号的过渡态代码。

### 1.2 架构约束
- **core 纯 Python 零 Qt**：严禁 import PySide，所有数据计算、文件 mtime 探测、命令执行、配置读写均在 core 模块完成。
- **app/services.py 唯一线程出口**：所有后台耗时任务均在 `DshService` 内部起线程，通过 `Signal` 转发到 Qt 事件循环。
- **ui 纯展示与信号订阅**：页面只调用 `self.app.service.<func>`，在 `_on_result` / `_on_finished` 等槽函数中处理回包，彻底消灭 `threading.Thread`。
- **三引号禁令**：新代码一律使用 `#` 注释，禁止包含中文的多行三引号 docstring。

---

## 二、 实施模块与步骤

### 2.1 步骤 1: core 层增加数据源 mtime 探测与数据聚合函数
在 `core/data.py` 中新增：
- `sessions_source_mtime(remote=None)`
- `plugins_source_mtime(profile, remote=None)`
- `taskboard_source_mtime(remote=None)`
- `agent_presets_source_mtime(remote=None)`
- `profiles_source_mtime(remote=None)`
- `read_sessions_data(remote=None)`
- `collect_overview_data(cfg, depls, smoke=False)`

### 2.2 步骤 2: app/services.py 补齐缺失的统一出口
扩充 `DshService`：
- `read_overview(cfg, depls, smoke=False, op="overview-read")`
- `read_sessions(remote=None, op="sessions-read")`
- `list_profiles(remote=None, op="profiles-list")`
- `check_tool_versions(tools, op="dsh-tool-versions")`
- `fetch_dsh_tags(op="dsh-tags")`
- `install_dsh(url, target, op="dsh-install")`
- `uninstall_dsh(keep_data, op="dsh-uninstall")`
- `test_ssh(host, user, port=22, op="settings-test-ssh")`
- `generate_diagnostics(cfg, app_version, base_dir, op="settings-gen-diag")`

### 2.3 步骤 3: 页面层清理裸线程并接入缓存
1. `ui/pages_sessions.py`：接入 `core_cache`，改调 `service.read_sessions`，删除私有线程与私有 Signal，添加 `RefreshIndicator`。
2. `ui/pages_plugins.py`：接入 `core_cache`，改调 `service.list_profiles` 与 `service.load_plugins`，添加 `RefreshIndicator`。
3. `ui/pages_taskboard.py`：接入 `core_cache` 与 `RefreshIndicator`，按需刷新。
4. `ui/pages_agents.py`：接入 `core_cache` 与 `RefreshIndicator`，按需刷新。
5. `ui/pages_profiles.py`：接入 `core_cache` 与 `RefreshIndicator`，改调 `service.list_profiles`，删除私有线程。
6. `ui/pages_dsh.py`：移除 4 处裸线程与 8 个私有 Signal，改调 service 对应方法。
7. `ui/pages_settings.py`：移除 2 处裸线程与 2 个私有 Signal，改调 service 对应方法。
8. `dsh-console-aio.py` (`OverviewPage`)：移除裸线程与私有 Signal，改调 `service.read_overview`。

### 2.4 步骤 4: 测试、验证与文档更新
- 跑 `py_compile` 与全量纯单元测试；
- 补齐 `tests/test_cache.py` 与 `tests/test_services.py` 单测；
- 跑 GUI 冒烟测试；
- 同步更新 `docs/ROADMAP.md` 与 `RELEASE_NOTES.md`，新建 note 记录。
