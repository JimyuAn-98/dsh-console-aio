# 已知问题（BUGS）

> 状态：待修 / 已修复。新增问题时按编号追加；修复后在条目后标注修复提交。

| 编号 | 问题 | 状态 | 备注 |
|------|------|------|------|
| BUG-001 | 插件停用/启用不生效。原记录方向（bundle名 vs entry id 映射）此前已实现；实修根因：启用删空禁用行后 `write_yaml([])` 写出**空文件**，dsh patch 层解析为 null 拒绝加载 → 运行中 web HMR 失效（启用不生效），profile 重启即启动失败 | 已修复（2026-08-29） | write_yaml 空容器写 `[]`/`{}`；启用未命中禁用行时追加 `disabled: false` 强启用行（对齐 dshmarket enableRow）；本机 web profile 坏文件已修复。查证：启停链路无需 build（dsh plugin 为纯 pnpm 转发器）。排查记录见 `.agents/notes/implemented/bug-fix/2026-08-29-plugin-enable-empty-patch.md` |
| BUG-002 | `os.kill(pid, 0)` Windows 语义陷阱：signal 0 == CTRL_C_EVENT，实际是向共享控制台广播 Ctrl+C（非 Unix 探活）；在宿主 harness 伪控制台内执行会 SIGINT 掉宿主 web | 已修复（2026-08-29） | `core/tunnel_mgr._pid_alive` 改用 tasklist CSV；上游同一 bug 见 deepseek-ai/deepseek-harness Discussion #4713；排查记录见 `.agents/notes/implemented/bug-fix/2026-08-29-os-kill-ctrlc-harness.md` |
| BUG-003 | 版本页"更新后不重启"：源码模式重启指向不存在的 app_pyside.py（FileNotFoundError 被吞） | 已修复（阶段2 波1） | 迁移 version 页到 core 时修复 |
| BUG-004 | 会话归档调用不存在的 `dsh_data.write_workspace`（AttributeError，归档/恢复自迁移起失效） | 已修复（阶段2 波2） | core 信封直写 workspace.json |
| BUG-005 | 隧道"停止后又被自动重连"：persist 停止标志随页面重建丢失 | 已修复（阶段1） | 停止标志改由 service 持有 |
| BUG-006 | 隧道页"运行更新"按钮引用未定义的 `_run_update`（点击静默报错） | 已修复（阶段1） | 从 tkinter 旧主程序恢复完整更新流至 `dshctl.update_dsh` |
| BUG-007 | 部署快照"会话大小"恒 0：`DshRemote.dir_stats` 本地分支只数子目录直接文件，而会话目录是 组/会话/文件 三层 | 已修复（2026-08-29） | 改 `_tree_size` 有界递归；概览页/部署页快照同源修复 |
| BUG-008 | 概览页快照结果经 bridge 发进底部日志区，`dep_status` 永远停在"读取中…"（技术债"裸线程未走信号"的实际代价） | 已修复（2026-08-29） | 概览页重设计：页面级 Signal + safe_emit 回 UI，数据改走 service.ctl 探测 |
