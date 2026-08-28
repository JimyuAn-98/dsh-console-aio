# os.kill(pid, 0) 在 harness 伪控制台内传播 Ctrl+C 杀死宿主 web（Windows）

- Status: implemented
- Date: 2026-08-29
- Related: 上游同一 bug 已由 djs326 在 deepseek-ai/deepseek-harness Discussion #4713 报告
  （根因结论一致，含 0xC000013A 退出码证据）; 我方以回复形式补充独立证据，不再另开新帖。
  本地 issue 文稿 docs/ISSUE_harness_os_kill_ctrlc.md 保留为内部参考。

## 背景

控制台项目 `core/tunnel_mgr.py::_pid_alive` 原用 `os.kill(pid, 0)` 做进程存活检测（Unix 惯用法）。
在 harness（dsh web :3080）工具调用内运行包含该调用的测试时，宿主 web 反复在 ~1 秒内死亡：
11/11 复现；同一命令在用户自己的终端执行则无害。期间还误伤过两次 3080（本会话历史事故）。

## 排查过程（要点）

- 测试内容逐一证伪：全部 25 例无副作用通过；TestPidAlive 单独 0.02s 通过；web 在测试结束前后死亡。
- 排除项：pytest teardown（裸 `python -c` 同样复现）、stop_dsh/taskkill（watchdog 抓进程：原始死亡瞬间
  零 taskkill/powershell，唯一一次 stop_dsh 是用户点「重启」的恢复操作）、WER 崩溃（事件日志无 node 崩溃）、
  symlink（python.exe 为 conda HardLink，用户终端同二进制无害）、无控制台假象（ConPTY 的 GetConsoleWindow()=0）。
- 决定性实验：WMI 分离进程（无控制台）执行同一调用 → 抛 `OSError(22, ..., 87)`（WinError 87）且 web 无恙；
  工具调用树内执行 → 调用成功且 web 被 SIGINT 优雅退出（无 taskkill/无 WER/无崩溃日志，全吻合）。

## 根因机制

Windows 上 `signal 0 == CTRL_C_EVENT`，`os.kill(pid, 0)` 的语义是「向共享控制台发送 Ctrl+C」
（GenerateConsoleCtrlEvent），并非 Unix 的杀 0 探活。harness 用 node-pty/ConPTY 承载工具调用 shell，
宿主 web 与该伪控制台共享 → 工具调用子进程发 Ctrl+C → 宿主 node 收到 SIGINT 优雅退出。

## 决策

- `_pid_alive` 移除 os.kill，改用 `tasklist /NH /FO CSV /FI "PID eq N"` 精确匹配（顺带修复 PID 子串误判）。
- 全项目 grep 确认无其它 os.kill；注释写明 Windows 语义差异防回归。
- 向 deepseek-harness 提交 issue（文稿已备）。

## 影响

- 控制台项目：测试 299 例全过，3080 宿主 0 复发（已免疫）。
- harness 侧：任何 agent 在工具调用里误用 `os.kill(pid, 0)` 做探活都会自杀宿主，属 harness 控制台
  隔离/文档缺陷，需上游修复。
