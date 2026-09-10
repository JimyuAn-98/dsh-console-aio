# dsh 启动报错未捕获与插件管理 Profile 加载死锁治理

- Status: implemented
- Date: 2026-09-10
- Related: `docs/plans/20260910-dsh-start-recovery-and-plugin-update-v1.md`, `core/dshctl.py`, `app/services.py`, `ui/pages_plugins.py`, `dsh-console-aio.py`

## 背景

dsh 仓库更新后，第三方插件（如 dsh-better-sidebar）因上游 @deepseek-ai/dsh-settings 移除 `settingsNamespace` 导出，在服务初始化后的异步加载阶段抛 SyntaxError，Node 进程随即以退出码 1 退出。控制台此时只输出「已在后台启动, 等待 3080 端口就绪」并报成功，底部日志区没有任何报错，用户完全无从得知失败原因。同期「插件管理」页首次进入永久卡在「正在读取 Profile 列表...」。

## 根因剖析

- **子进程输出未回收**：`start_dsh` 用 Popen 把 stdout/stderr 重定向到 `%TEMP%/dsh-dash/dsh-web.{out,err}.log` 后，未做任何初始存活/输出观测就立即返回 True，错误堆栈全部滞留文件。
- **端口「伪就绪」**：`stop_dsh` 的 node 匹配规则不覆盖 `apps/cli/src/bin.ts`，旧实例仍占 3080；新实例启动后 `probe` 毫秒级成功，被误判为就绪并跳出等待循环。
- **Token 提前退场**：原监视逻辑扫到 Token 即 break，监视在 500ms 后即结束，错过后续插件异步加载阶段的崩溃。
- **update_dsh 掩盖失败**：第 7/7 步重启未校验 `start_dsh` 返回值，子进程秒崩也输出「更新完成」。
- **busy 死锁**：`_apply_profiles` 成功分支漏调 `_set_busy(False)`，随后 `_refresh(force=False)` 被首部 busy 检查直接 return，`_busy` 永久为 True，界面锁死。
- **restart 时序笔误**：`run_dsh` 对 "start"/"restart" 的处理使重启先启动、再停止、再启动。

## 修复决策

1. **启动前端口预检**：占用则先 `stop_dsh` 并等待释放（最多 2s）；仍在占用只告警不阻断。
2. **增量 tail 初始观测**：复用 `core.logs.Tailer` 记录启动前文件偏移；Popen 后在工作线程做 15s（30×500ms）轮询——流式转发 err（红色）与 out、捕获 Token、`proc.poll()` 提前退出则排空残流并报退出码、置卡片离线、返回 False。
3. **后台持续监视**：再挂 15s 监视线程，去掉「Token 即 break」，持续 tail 直到进程后续退出。
4. **stop_dsh 精准清理**：增加 `Get-NetTCPConnection -LocalPort` 定位监听 PID 精准 kill，并扩宽 node 命令行匹配（apps/cli、bin.ts、deepseek-harness）。
5. **update_dsh 校验返回值**：启动失败即中止并置状态「更新完成但启动失败」。
6. **restart 修正**：先 stop → sleep 1s → start。
7. **service/托盘接线**：补 `stop_dsh`/`restart_dsh`，透传真实返回；托盘菜单改传字符串 mode（原先误把全局 CONFIG 当 mode）。
8. **插件管理**：`_apply_profiles` 进入即 `_set_busy(False)`/`_pending=None`；新增单个/批量更新（官方 `dsh plugin update`）与 QInputDialog 安装输入。

## 拒绝的替代方案

- **3-5s 短轮询**：Node 冷启动加插件加载可超过 5s，早期方案被 15s 取代。
- **启动前不清理旧实例**：会继续造成伪就绪，掩盖真实崩溃。
- **运行中切换 Mica/纯色材质**：窗口材质须在显示前设置，运行中切换需重建整窗（挂着 service 桥/监控线程/全部页面），风险大于收益，维持不做。

## 影响

- 启动失败与后续崩溃现在都有中文日志与状态卡片反馈；update 不再误报成功。
- 新增 10 个单元测试；全量口径 435 单元 + 86 GUI 冒烟。本机沙箱因 `.pytest-tmp` 写权限限制无法执行全绿（环境限制，非回归）。
