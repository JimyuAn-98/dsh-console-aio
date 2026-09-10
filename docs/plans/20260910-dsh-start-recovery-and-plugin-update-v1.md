# dsh 启动报错捕获、端口清理与插件管理更新能力（2026-09-10）

> 本文件合并并取代同批次的三份重复计划：
> `20260910-dsh-start-error-capture-and-plugin-profile-hang-fix-v1.md`、
> `20260910-dsh-start-log-monitoring-and-port-cleanup-v1.md`、
> `20260910-plugin-update-and-log-wait-v1.md`（早期 3-5s 轮询设计已被 15s 定稿取代）。

- **日期**：2026-09-10
- **目标**：彻底解决 dsh web 启动报错未在控制台捕获、端口被旧进程占用引起的「伪就绪」，实现 15s 增量日志流式观测与后续崩溃捕获；同时修复插件管理页 Profile 加载死锁并补齐插件更新能力。

## 一、背景与根因

用户执行 dsh 更新后启动 dsh，控制台只输出：

```
$ cd D:\Applications\deepseek-harness && pnpm.cmd dsh web
进程已启动 (PID 7944), 正在检测运行状态...
  $ node --import tsx/esm apps/cli/src/bin.ts "web"
dsh web 已就绪 -> http://127.0.0.1:3080 (20ms)
```

后无任何报错，但服务实际并未成功运行。排查 `%TEMP%\dsh-dash\dsh-web.err.log` 发现根因：更新后上游 `@deepseek-ai/dsh-settings` 去除了 `settingsNamespace` 导出，已装第三方插件 `dsh-better-sidebar` 初始化时报 `SyntaxError: The requested module '@deepseek-ai/dsh-settings' does not provide an export named 'settingsNamespace'`，Node 进程退出码 1 退出。

控制台未捕获该错误的原因：

1. **旧进程残留与伪就绪**：`stop_dsh` 的 node 匹配未涵盖 `apps/cli/src/bin.ts`，且未按 3080 端口查占用 PID，旧实例仍占端口；新实例启动后 `probe` 20ms 即返回 True，跳出等待循环。
2. **后台监视器遇 Token 提前退场**：原监视逻辑扫到 Token 即 `break`，500ms 后监视结束，未继续监听插件异步加载阶段的输出与退出。
3. **update_dsh 掩盖失败**：步骤 7/7 重启未校验返回值，秒崩也报「更新完成」。
4. **restart 时序笔误**：`if mode in ("start","restart")` 在前、`if mode in ("stop","restart")` 在后，导致重启先启动、再停止、再启动。
5. **托盘接线错误**：启动/重启 dsh 误把全局 `CONFIG` 当 mode 传入 `service.start_dsh`，且 `DshService` 缺 `stop_dsh`/`restart_dsh`。
6. **插件页 busy 死锁**：`_load_profiles` 先 `_set_busy(True)`；`_apply_profiles` 成功分支（`names` 非空）漏调 `_set_busy(False)`，随后 `_refresh(force=False)` 被首部 `if self._busy and not force: return` 拦截，`_busy` 永久为 True，界面锁死在「正在读取 Profile 列表...」。

---

## 二、改动设计

### 1. 后端业务层 `core/dshctl.py`

- **启动前端口预检**：`probe("127.0.0.1", dash_port)` 命中则先 `stop_dsh`，最多等 2s 释放；仍在占用则告警不阻断。
- **增量 tail 初始观测**：复用 `core.logs.Tailer` 记录 `dsh-web.out.log`/`dsh-web.err.log` 启动前偏移；`Popen` 后在工作线程做 15s（`range(30)` + `sleep(0.5)`）轮询：
  - 实时消费 err（tag `"err"` 红色）与 out（`classify_line`），并从中提取 Token；
  - `proc.poll()` 非 None（提前退出）→ 排空残流、输出 `启动失败: 进程已异常退出 (退出码 X)`、置卡片离线、清 Token、返回 False；
  - `probe` 成功 → 输出就绪并成功返回 True。
- **后台持续监视**：再挂 15s 后台线程，去掉「Token 即 break」，持续 tail 直到 `proc.poll()` 检测到后续退出并置卡片离线。
- **stop_dsh 精准清理**：`Get-NetTCPConnection -LocalPort $port -State Listen` 定位监听 PID 精准 kill；扩宽 node 命令行匹配（`apps/cli`、`bin.ts`、`deepseek-harness`）。
- **update_dsh 校验**：重启失败中止并置「更新完成但启动失败」。
- **run_dsh 修正**：`stop`/`start`/`restart` 返回对应布尔值；restart = stop → sleep 1s → start。

### 2. 信号桥与主程序 `app/services.py` / `dsh-console-aio.py`

- `start_dsh(mode="start", op="dsh")`：mode 类型防护（非 str 回退 "start"），透传 `ctl.run_dsh` 真实返回值到 `finished.emit`；补 `stop_dsh`/`restart_dsh`。
- 托盘菜单接线改为 `self.service.start_dsh("start")` / `stop_dsh()` / `restart_dsh()`。

### 3. 插件管理 `ui/pages_plugins.py`

- 修复 `_apply_profiles`：进入即 `_set_busy(False)` 与 `_pending = None`；`_profile_cb` 信号阻断与初值设定规范化；`_load_profiles` 显式设 `_pending`；清理重复的 `activated` 二次连接。
- 新增【更新】按钮（选中插件 → `pnpm.cmd dsh plugin --profile <name> update <pkg>`）。
- 新增【更新全部插件】按钮（→ `pnpm.cmd dsh plugin --profile <name> update`）。
- 【安装】放开选中依赖：未选中时 `QInputDialog` 输入 npm 包名/本地路径/Git 链接（`add <pkg>`）。
- `_refresh_btns` 联动态。

---

## 三、验证计划

1. 编译检查：`python -m compileall -q dsh-console-aio.py core ui app tests`
2. 纯单元：`python -m pytest tests/ -q`（新增启动报错捕获、进程提前退出、restart 时序、service 启停、插件页解 busy 与更新命令装配等 10 例）
3. GUI 冒烟（人工）：`python -m pytest tests/test_gui_smoke.py tests/test_gui_ui.py -m gui -q`
4. 人工验收：模拟 `dash_cmd` 报错退出，验证控制台红色错误堆栈与状态栏失败提示；进入插件管理验证 Profile 列表立即填充、更新/批量更新按钮与内联确认可用。
