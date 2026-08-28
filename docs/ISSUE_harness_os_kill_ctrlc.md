# [Bug] 工具调用子进程执行 `os.kill(pid, 0)` 会杀死宿主 web（Windows）：Ctrl+C 经共享 ConPTY 传导（os.kill(pid, 0) = CTRL_C_EVENT on Windows）

## 概述

在 Windows 上，`os.kill(pid, 0)` —— Unix 世界标准的"进程存在性检查"惯用法 —— **并不是存在性检查**。
因为 Windows 中 `signal 0 == CTRL_C_EVENT`，它实际是**发送 Ctrl+C**（`GenerateConsoleCtrlEvent`）。
当工具调用子进程（例如 `bash` 工具拉起的 Python 脚本）执行 `os.kill(os.getpid(), 0)` 时，
Ctrl+C 会沿承载工具调用 shell 的伪控制台（ConPTY）传导——**宿主 web 进程与该伪控制台共享**，
收到 SIGINT 后**优雅退出**。`127.0.0.1:3080` 上的宿主 web 在约 1 秒内死亡，整个会话随之终止。

该问题在我们的环境中 11/11 复现，是一个严重的隐患：**任何 agent 在工具调用里用 Unix 惯用法
`os.kill(pid, 0)` 做存活检测，都会静默杀死宿主。**

## 环境

- Windows（无容器/PID namespace 隔离；工具调用是宿主的普通子进程）
- 宿主：`dsh web`（node + tsx，经 `pnpm dsh web` 启动，监听 `http://127.0.0.1:3080`）
- Python 3.12.9（conda）执行 `os.kill(os.getpid(), 0)`

## 复现步骤

在任意 `bash` 工具调用内运行（需会话托管在 `dsh web` 上）：

```bash
python -c "import os, time; os.kill(os.getpid(), 0); print('after-kill'); time.sleep(30)"
```

期望：python 打印 `after-kill` 后正常睡眠，进程不受影响。

实际：
1. `after-kill` 正常打印（调用方 python 自身**未被**中断——信号作用于共享控制台，而非调用者自己的进程组）。
2. 宿主 web（:3080）在 **1~2 秒内死亡**——**干净的 SIGINT 退出**：无 `taskkill` 调用、无 Windows
   错误报告（WER）崩溃记录、web stderr 日志无崩溃堆栈。
3. 随宿主一起，进行中的工具调用被中止。

同样的命令在普通终端（PowerShell）中执行**不会**影响 web——web 并不附着在那个控制台上。

## 证据

| 上下文 | `os.kill(own_pid, 0)` 结果 | 宿主 web |
|---|---|---|
| harness 工具调用内（bash 子进程） | 调用成功，无异常 | **死亡（~1s，SIGINT 优雅退出）** |
| WMI 分离进程（`Win32_Process.Create`，无控制台） | 抛 `OSError(22, ..., 87)`（WinError 87 ERROR_INVALID_PARAMETER） | 不受影响 |
| 普通终端（PowerShell 控制台） | 调用成功 | 不受影响（web 不在此控制台上） |

- 进程看门狗（每 200ms 轮询 `Win32_Process` 中的 `taskkill`/`powershell`）在死亡瞬间**零记录**——
  宿主不是被外部 `taskkill` 杀的。
- 死亡时刻无 node.exe 的 WER/事件日志崩溃条目——与 SIGINT 优雅退出一致。
- 工具调用 python 的 `GetConsoleWindow()` 返回 0——有误导性：附着在 ConPTY 上的进程没有窗口句柄，
  但**确实附着在伪控制台上**。

## 根因

- CPython（Windows）中 `os.kill(pid, sig)` 将 `sig == 0`（即 `CTRL_C_EVENT`）映射为
  `GenerateConsoleCtrlEvent`，即**发送 Ctrl+C 到控制台进程组**——不是 `kill(pid, 0)` 的存活检测语义。
- `bash` 工具（经 shell/subprocess 服务，`packages/subprocess/subprocess-local` + node-pty/ConPTY）
  在伪控制台中运行工具调用 shell。宿主 web 进程附着于/共享该控制台，因此 Ctrl+C 到达宿主，
  Node 默认的 SIGINT 处理器将其优雅关闭。

## 影响

- 任何 agent 在工具调用里使用 `os.kill(pid, 0)`（非常常见的存活检测惯用法）都会在 Windows 上杀死宿主会话。
- 从宿主视角失败是静默的：干净退出、无崩溃日志、无 kill 命令——极难排查
  （我们是在完整的进程看门狗 + 分离进程对照实验后才定位）。

## 建议修复（上游）

1. **控制台隔离**：让工具调用 shell 运行在宿主 web 进程**不附着**的独立 ConPTY/伪控制台，
   使工具子进程的控制台控制事件（Ctrl+C / Ctrl+Break）无法到达宿主。
   仅做进程组隔离在 Windows 上不够——信号是经共享控制台传递的。
2. 或者：宿主完全不持有控制台（ConPTY 只给 shell 子进程），与工具调用控制台彻底分离。
3. 至少：在 Windows 上明确文档化 `os.kill(pid, 0)` 是 Ctrl+C（而非存活检测），
   并在工具运行时层面提示/拦截此类调用。

## 我们这边的处理（已修复）

消费方项目已从其存活检测中移除 `os.kill(pid, 0)`（改用 `tasklist` CSV 按 PID 精确匹配）。
临时规避方案：**Windows 上不要在工具调用子进程里调用 `os.kill(pid, 0)`；改用
`tasklist` / `GetExitCodeProcess` 类检查。**
