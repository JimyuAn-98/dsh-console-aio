# 实测三处问题修复：安装状态跨页、卸载只读残留、隧道卡误报绿灯

- Status: implemented
- Date: 2026-09-10
- Related: `dsh-console-aio.py`, `ui/pages_dsh.py`, `core/env.py`, `core/tunnels.py`, `tests/test_core_env.py`, `tests/test_tunnel_mgr.py`

## 背景

另一台机器实测发现三处问题（BUG-010/011/012）：

1. dsh 安装过程中切到别的页面再切回，进度条与页内日志清空，只在底部主控制台还能看到输出。
2. 卸载 dsh 时，源码目录若在 `C:\Users` 下，`.git` 里的文件删不掉（疑似权限）。
3. 自定义的「在家正向隧道」没有运行时卡片却一直是绿灯，怀疑打包夹带了本机状态。

## 根因与决策

- **BUG-010 页面导航重建**：`MainWindow._show_page` 每次导航都 `deleteLater()` 旧页面并新建，进行中任务只存在于页面局部（`_inst_running` + 页内日志控件），重建即丢；后台线程仍在跑，但新页面的 `_on_service_log/step` 因 `_inst_running=False` 忽略事件。
  决策：引入 **常驻页面实例** `MainWindow._pages`（当前只登记 DSH 管理页）与可选 `on_show()` 钩子——实例跨导航保留，切回时只刷新版本发布信息，安装进度/日志控件内容不丢。**不做**全站页面缓存（涉及所有页面的 on_show 语义与内存，另行评估）。
- **BUG-011 只读文件**：git 的 `.git/objects` 文件被标记只读，Windows 下 `shutil.rmtree` 对只读文件抛 WinError 5。
  决策：`core/env.py::_rmtree_force` —— 先 `os.walk` 自底向上清只读位，再用带 `onexc/onerror` 兜底回调的 `shutil.rmtree`，最后用存在性检查把「删不净」变成明确中文报错（而不是静默成功）。
- **BUG-012 绿灯判定**：`card_states_from_monitor` 对正向隧道用「被监视端口是否监听」作代理，端口被其它进程占用就误报在线；与打包无关（`config.json`/`tunnel-pids.json` 未进包，`--add-data` 仅主题/logo/更新日志）。
  决策：卡片状态改以 **隧道进程存活** 为权威——`TunnelManager.running_map()` 读 `tunnel-pids.json` 并逐 pid 探活；反向隧道要求「进程存活 且 远端端口在听」。`card_states_from_monitor` 作为纯函数保留（端口维度仍供右栏/测试），由 `_sync_card_states` 用进程存活结果覆盖。

## 拒绝的替代方案

- **全站页面实例缓存**：能一并解决「每次导航重拉数据」，但需为每个页面定义 on_show 语义、回归面大，本次先用最小改动修 DSH 页。
- **卸载改用 `cmd /c rmdir /s /q` 或第三方库**：引入外部依赖/平台命令；`_rmtree_force` 纯标准库更可控。
- **绿灯改为「端口监听 且 进程存活」**：仍会在进程存活但端口被他人占用时误报，或反之；直接以进程存活为准更贴近「隧道在不在跑」。

## 影响

- 长任务跨导航不再丢状态；卸载能删净含只读文件的目录并如实报错；隧道卡不再被无关端口占用误导。
- 新增 `TestRmtreeForce`（只读目录删除）与 `TestRunningMap`（快照合并）单测。
- 已知遗留：全站页面缓存/on_show 语义未做；安装输出同时出现在页内与主控制台（去重待议，用户已提）。
