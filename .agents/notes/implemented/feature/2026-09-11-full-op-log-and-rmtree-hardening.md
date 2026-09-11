# 长操作完整输出日志：落盘、脱敏与「打开操作日志」

- Status: implemented
- Date: 2026-09-11
- Related: `app/services.py`, `ui/pages_dsh.py`, `core/env.py`, `tests/test_service_oplog.py`, `tests/test_core_rmtree_force.py`, `docs/ARCHITECTURE.md`

## 背景

用户要求「尽量捕获全执行过程中的输出（不管是部署还是卸载还是更新）」，同时卸载（BUG-011）在实机上仍报删不净但看不到具体是哪个文件删不掉。
页面日志控件有行数上限（安装/更新可达上千行），卸载路径当前只有零散 `line()`，删不净时只有一句结论，无法定位。

## 决策

- **长操作全过程落盘**：在信号桥 `DshService` 侧新增 `_begin_op(op)`（建 `<临时目录>/dsh-console-ops/<op>-<时间戳>.log` 并写头、把路径作为主日志提示）与 `_op_log_write/_op_log_close/latest_op_log`。选做在 service 而非各页面：events 回调是后端输出的唯一汇聚点，一处接入即覆盖所有长操作。
- **只对长操作落盘**（安装/更新/卸载/部署/启停/批量隧道/通用命令），读类 `_run_core_op` 与每 5s 的监控 `monitor_once` 不落盘，避免刷出大量文件。
- **落盘前脱敏**：`start_dsh` 会把含 `?token=...` 的 dsh 启动行当普通日志发出来；落盘会把 Token 持久化到明文临时文件，违反「Token 绝不写入日志」红线。故 `_op_log_write` 统一经 `_redact_secrets` 抹掉 `token=`/`Bearer`，控制台内存显示保持原样。
- **卸载删除逐行日志**：`_rmtree_force(path, log=None)` 增加可选单参回调，输出开始/无法删除项/重试/完成；`uninstall_dsh` 传 `log=line`，这些行经 events 既进控制台也进操作日志。
- **删除加固**：Windows `\\?\` 长路径前缀（>260）、`os.walk(onerror=...)`、3 次重试、`cmd rmdir /s /q` 兜底，最后仍以带路径的 OSError 收场（失败必须可见，不静默）。

## 拒绝的替代方案

- **每个页面各自写日志文件**：重复且容易漏；events 汇聚点唯一，收口在 service 最简洁。
- **所有 op 一律落盘**：读类操作会刷出大量无意义小文件，且监控每 5s 一次。
- **直接改 `core/dshctl.py` 不输出 Token 行**：会改变现有控制台行为（鉴权链接排查依赖它），且清不干净（其它命令输出也可能带凭据）；在「落盘」这一新增通道上脱敏是最小且充分的改动。

## 影响

- 安装/更新/卸载/部署/启停等失败时，可打开完整日志定位到具体命令行与错误；卸载删不净会逐条列出残留路径。
- 新增 `tests/test_core_rmtree_force.py`（只读目录删净 + 日志）与 `tests/test_service_oplog.py`（落盘/不落盘/Token 脱敏）。
- 顺带修正 3 个因「本地无法跑 pytest」而腐化的用例：`update_dsh` 替身补 `to_main` 形参、数据目录守卫用例改打桩 `_rmtree_force`、启停用例以 `finished` 信号为同步点（原以 `calls` 为同步点存在竞态）。

## 遗留

- BUG-011 的最终确认仍需实机复测（用户在家）。
- 安装输出同时出现在页内与主控制台，去重仍待议（用户已提，本次未动）。

## 补充（2026-09-11）：删除改为「原生快删 + Python 精修」

实机复测 BUG-011：日志停在 `[删除] 开始: C:\Users\JimyuAn\dsh` 之后长时间无输出，表现为卡死。

- **根因**：原实现先做一遍全树 `os.walk` 清只读位，再让 `shutil.rmtree` 走一遍全树，失败还要重试——大目录（pnpm `node_modules` 常有数十万条目）等于两到三遍 Python 级全树遍历，慢到像挂起，且中途没有任何日志。
- **本机复现**：3002 项 + 只读 `.git/objects` + junction 成环的目录，旧写法耗时明显；junction 本身在 Python 3.12+ 的 `os.walk` 已不会跟随（不会成环挂死），但目录体量才是主因。
- **改法**：
  1. 先跑原生 `cmd rmdir /s /q`（一次性删掉绝大多数条目，junction 只删链接本身；只读文件会被跳过）；
  2. 再 `_purge` 迭代式后序遍历精修残留：就地 `chmod` 清只读，遇到 junction/符号链接只用 `os.rmdir`/`os.remove` 删链接（绝不递归进目标，防环），每 2000 项打一条 `[删除] 已清理 N 项...` 进度日志；
  3. 仍删不净则列出残留文件清单与前 10 条失败原因，再抛带路径的 `OSError`。
- **效果**：同一测试树（3002 项 + 只读 + junction 环）**0.2s 删净**，全程 7 行日志可见进度。
- 测试：新增 junction 成环用例；`test_core_env.py::test_rmtree_failure_returns_error` 改为打桩 `_rmtree_force`（删除加固本身由 `test_core_rmtree_force.py` 覆盖）。
- **实机验证（2026-09-11 23:36）**：`C:\Users\JimyuAn\dsh` 源码树，快删阶段 0.5s（长路径使原生 rmdir 提前返回，实际清理由精修完成），精修处理 **75541 项 / 31.1s** 后 `[删除] 完成`；BUG-011 结案。
