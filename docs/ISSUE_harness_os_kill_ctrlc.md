# [Bug] `os.kill(pid, 0)` inside a tool-call child process kills the host web (Windows): SIGINT propagates through the shared ConPTY

## Summary

On Windows, `os.kill(pid, 0)` — the standard Unix "process existence check" — is **not** an existence check. Since `signal 0 == CTRL_C_EVENT` on Windows, it actually sends **Ctrl+C** (`GenerateConsoleCtrlEvent`). When a tool-call child process (e.g. a Python script spawned by the `bash` tool) executes `os.kill(os.getpid(), 0)`, the Ctrl+C propagates through the pseudoconsole (ConPTY) that hosts the tool-call shell — and the host web process, which shares that console, receives SIGINT and **exits gracefully**. The host web on `:3080` dies ~1 second later, taking the whole session down.

This is reproducible 11/11 in our environment and is a serious footgun: any agent that uses the Unix idiom `os.kill(pid, 0)` for liveness checks inside a tool call will silently kill the host.

## Environment

- Windows (no container/PID-namespace isolation; tool calls run as plain child processes of the host)
- Host: `dsh web` on `http://127.0.0.1:3080` (node + tsx, launched via `pnpm dsh web`)
- Python 3.12.9 (conda) executing `os.kill(os.getpid(), 0)`

## Reproduce

Run this inside a `bash` tool call (any agent session hosted by `dsh web`):

```bash
python -c "import os, time; os.kill(os.getpid(), 0); print('after-kill'); time.sleep(30)"
```

Expected: the python prints `after-kill` and sleeps; the process is untouched.

Actual:
1. `after-kill` prints (the calling python itself is **not** interrupted — the signal targets the shared console, not the caller's own group).
2. The host web on `:3080` dies within ~1–2 seconds — **clean SIGINT exit**: no `taskkill` invocation, no Windows Error Reporting crash record, no crash trace in the web's stderr log.
3. The in-flight tool call is aborted along with the host.

Running the exact same command in a normal terminal (PowerShell) does **not** affect the web — the web is not attached to that console.

## Evidence

| Context | `os.kill(own_pid, 0)` result | Host web |
|---|---|---|
| Inside harness tool call (bash child) | call succeeds, no exception | **dies (~1s), clean SIGINT exit** |
| Detached via WMI (`Win32_Process.Create`, no console) | raises `OSError(22, ..., 87)` (WinError 87 ERROR_INVALID_PARAMETER) | unaffected |
| Normal terminal (PowerShell console) | call succeeds | unaffected (web not on that console) |

- A process watchdog (polling `Win32_Process` every 200 ms for `taskkill`/`powershell`) recorded **zero** kill commands at the moment of death — the host was not killed by an external `taskkill`.
- No WER/Event-Log crash entries for node.exe at death time — consistent with graceful SIGINT shutdown.
- `GetConsoleWindow()` returns 0 for the tool-call python — misleading: ConPTY-attached processes have no window handle, but they **are** attached to the pseudoconsole.

## Root cause

- CPython on Windows: `os.kill(pid, sig)` maps `sig == 0` (== `CTRL_C_EVENT`) to `GenerateConsoleCtrlEvent`, i.e. it sends Ctrl+C to a console process group — it is **not** `kill(pid, 0)` liveness semantics.
- The `bash` tool (via the shell/subprocess service, `packages/subprocess/subprocess-local` + node-pty/ConPTY) runs tool-call shells in a pseudoconsole. The host web process is attached to / shares that console, so the Ctrl+C reaches the host and Node's default SIGINT handler shuts it down gracefully.

## Impact

- Any agent using `os.kill(pid, 0)` (a very common liveness idiom) inside a tool call kills the host session on Windows.
- The failure is silent from the host's perspective: clean exit, no crash logs, no kill commands — very hard to diagnose (we only pinned it down with a full process watchdog + detached-process control experiment).

## Suggested fixes (upstream)

1. **Console isolation**: run tool-call shells in a dedicated ConPTY/pseudoconsole that the host web process is **not** attached to, so console control events (`Ctrl+C`/`Ctrl+Break`) from tool children cannot reach the host. Process-group isolation alone is insufficient on Windows — the signal is delivered through the shared console.
2. Or: detach the host from the tool-call console entirely (host keeps no console; ConPTY only for the shell child).
3. At minimum: document loudly on Windows that `os.kill(pid, 0)` is Ctrl+C (not liveness), and consider a sandbox/seccomp-style policy note for tool runtimes.

## Our side (already fixed)

The consumer project removed `os.kill(pid, 0)` from its liveness check (now uses `tasklist` CSV by PID) — workaround: **never call `os.kill(pid, 0)` inside a tool-call child on Windows; use `tasklist`/`GetExitCodeProcess`-style checks instead.**
