# -*- coding: utf-8 -*-
# dsh_core/dshctl.py - 本机 dsh 启停 / 更新 / 监控探测(纯 Python, 不 import PySide)。
#
# 由 dsh-console-aio.py 中散落在 Qt 类里的业务逻辑抽出: _run_dsh/_dsh_start/_dsh_stop/
# _probe/_ssh_proc_count/_probe_remote_tunnels(原 _stream_cmd 流程已并入 stream_cmd)。
#
# 通讯约定: 本类不碰 UI。进度/结果通过 events(kind, payload) 回调向外报告(纯数据):
#   events('log',    (text, tag))
#   events('status', text)
#   events('card',   (key, online_bool))
# 由 app/services.py 把 events 转发到 Qt Signal。绝无跨线程直接改 UI。

import os
import socket
import subprocess
import threading


class DshCtl:
    """本机 dsh 启停 + 健康监控探测。d 为 config.derived() 的结果(无 globals 依赖)。"""

    def __init__(self, d):
        self.d = d

    # ---------- 日志/状态工具(经 events 回 UI, 不直接碰 UI) ----------
    def _log(self, events, msg, tag=""):
        if events:
            events("log", (msg, tag))

    def _status(self, events, msg):
        if events:
            events("status", msg)

    # ---------- 本机 dsh 启停 ----------
    def run_dsh(self, mode, events=None):
        if mode in ("start", "restart"):
            self.start_dsh(events)
        if mode in ("stop", "restart"):
            self.stop_dsh(events)
            if mode == "restart":
                self._log(events, "  停止完成, 重新启动...", "warn")
                self.start_dsh(events)

    def start_dsh(self, events=None):
        dash_repo = self.d.get("dash_repo") or ""
        dash_cmd = self.d.get("dash_cmd") or []
        dash_port = self.d.get("dash_port") or 3080
        if not os.path.isdir(dash_repo):
            self._log(events, "  仓库不存在: %s" % dash_repo, "err")
            self._status(events, "启动失败: 仓库目录不存在")
            return False
        self._log(events, "  $ cd %s && %s" % (dash_repo, " ".join(dash_cmd)))
        try:
            logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-dash")
            os.makedirs(logdir, exist_ok=True)
            out = open(os.path.join(logdir, "dsh-web.out.log"), "ab")
            err = open(os.path.join(logdir, "dsh-web.err.log"), "ab")
            subprocess.Popen(dash_cmd, cwd=dash_repo, stdout=out, stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            self._log(events, "  已在后台启动, 等待 %d 端口就绪..." % dash_port, "ok")
            self._status(events, "已触发本机 dsh 启动 -> http://127.0.0.1:%d" % dash_port)
            if events:
                events("card", ("dsh-web", True))
            return True
        except FileNotFoundError:
            self._log(events, "  找不到 %s, 请确认 pnpm 在 PATH 或修改配置" % dash_cmd[0], "err")
            self._status(events, "启动失败: 找不到启动命令")
            return False
        except Exception as e:
            self._log(events, "  异常: %s" % e, "err")
            self._status(events, "启动出错: %s" % e)
            return False

    def stop_dsh(self, events=None):
        ps = ("$n=0\n"
              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction SilentlyContinue |\n"
              "  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } |\n"
              "  ForEach-Object { Write-Output ('stop node ' + $_.ProcessId); taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }\n"
              "if($n -eq 0){ Write-Output 'no dsh web process' }\n")
        self._log(events, "  $ stopping dsh web (node, 匹配 dsh+web)...")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                "Bypass", "-Command", ps],
                               capture_output=True, text=True, errors="replace",
                               timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            for ln in ((r.stdout or "").splitlines() or ["(无输出)"]):
                self._log(events, "    " + ln, "ok" if r.returncode == 0 else "err")
            self._status(events, "已停止本机 dsh web" if r.returncode == 0
                         else "停止本机 dsh 出错")
            if events:
                events("card", ("dsh-web", False))
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            self._log(events, "  [停止] 超时(60s)", "err")
            self._status(events, "停止本机 dsh 超时")
            return False
        except Exception as e:
            self._log(events, "  异常: %s" % e, "err")
            self._status(events, "停止出错: %s" % e)
            return False

    # ---------- dsh 完整更新(原 tkinter 主程序 _run_update, PySide6 迁移时丢失, 现恢复) ----------
    def update_dsh(self, events=None):
        # 步骤: 停 web -> git 拉取 -> 清理旧构建 -> 依赖 -> 构建 -> 重启; 任一命令失败即中止。
        # 清理一步不可省: dsh 仓库的 lib/ 构建产物被 gitignore, git pull 不会动它; 上游
        # 改名/删导出后, 过期生成物会让 tsdown 报 MISSING_EXPORT(CI 干净 checkout 无此问题,
        # 本地增量构建必踩)。clean 用 dsh 仓库自带脚本(只删构建产物, 保留 node_modules)。
        dash_repo = self.d.get("dash_repo") or ""
        if not os.path.isdir(dash_repo):
            self._log(events, "  仓库不存在: %s" % dash_repo, "err")
            self._status(events, "更新失败: 仓库目录不存在")
            return False
        self._log(events, "[更新] 步骤1/7: 停止当前 dsh web", "warn")
        self.stop_dsh(events)
        import time as _t
        _t.sleep(2)
        steps = [
            ("步骤2/7: git fetch", ["git", "fetch", "origin", "--prune"]),
            ("步骤3/7: git pull --ff-only", ["git", "pull", "--ff-only"]),
            ("步骤4/7: 清理旧构建产物", ["pnpm.cmd", "run", "clean"]),
            ("步骤5/7: pnpm install", ["pnpm.cmd", "install"]),
            ("步骤6/7: pnpm run build", ["pnpm.cmd", "run", "build"]),
        ]
        for label, cmd in steps:
            self._log(events, "[更新] " + label, "warn")
            # 旧版 tkinter 的 git fetch cwd 传了 None(会在控制台目录而非 dsh 仓库执行,
            # 是隐患), 此处统一在 dsh 仓库内执行。
            if not self.stream_cmd(cmd, cwd=dash_repo, events=events):
                self._status(events, "更新失败: " + label)
                return False
        self._log(events, "[更新] 步骤7/7: 重启 dsh web", "warn")
        self.start_dsh(events)
        self._log(events, "  [更新] 完成, 访问 http://127.0.0.1:%d" % self.d["dash_port"], "ok")
        self._status(events, "更新完成")
        return True

    # ---------- 通用命令流(流式打日志) ----------
    def stream_cmd(self, cmd, cwd=None, env=None, events=None, timeout_override=None):
        self._log(events, "  $ " + " ".join(cmd))
        timeout = timeout_override or self.d.get("update_timeout") or 1800
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 encoding="utf-8", errors="replace", bufsize=1, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            self._log(events, "  找不到命令: " + str(cmd[0] if cmd else "?"), "err")
            return False
        import time as _t
        deadline = _t.time() + timeout
        while True:
            line = p.stdout.readline() if p.stdout else None
            if line:
                self._log(events, "    " + line.rstrip())
                continue
            if p.poll() is not None:
                break
            if _t.time() > deadline:
                p.kill()
                self._log(events, "  [stream] 超时, 已强制终止", "err")
                return False
            _t.sleep(0.1)
        rc = p.wait()
        if rc != 0:
            self._log(events, "  [stream] 命令失败 (exit %s)" % rc, "err")
            return False
        return True

    # ---------- 健康监控探测(原 _probe / _ssh_proc_count / _probe_remote_tunnels) ----------
    def probe(self, host, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.d.get("tcp_timeout") or 0.8)
            import time as _t
            t0 = _t.time()
            s.connect((host, port))
            s.close()
            return True, int((_t.time() - t0) * 1000)
        except Exception:
            return False, -1

    def ssh_proc_count(self):
        try:
            out = subprocess.run(
                ["tasklist", "/NH", "/FI", "IMAGENAME eq ssh.exe"],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return sum(1 for ln in out.splitlines() if "ssh.exe" in ln)
        except Exception:
            return -1

    def probe_remote_tunnels(self):
        pts = [p for p, _, _ in self.d.get("remote_tunnels", [])]
        if not pts:
            return {}
        server = self.d.get("ssh_server") or ""
        user = self.d.get("ssh_user") or ""
        ports = "|".join(str(p) for p in pts)
        cmd = "ss -tln | grep -E ':(%s) '" % ports
        try:
            p = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 "-o", "LogLevel=ERROR", "%s@%s" % (user, server), cmd],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if p.returncode != 0:
                return None
            text = p.stdout or ""
            return {pt: (":%d " % pt) in text or (":%d" % pt) in text for pt in pts}
        except Exception:
            return None

    def monitor_tick(self, on_result=None):
        "# 一次性探测本机端口+ssh+远程隧道(供后台线程调用)。on_result(kind,payload) 纯数据回调。"
        local = {}
        for port, _, _ in self.d.get("local_ports", []):
            local[port] = self.probe("127.0.0.1", port)
        if self.d.get("ssh_server"):
            local["__ssh__"] = self.probe(self.d["ssh_server"], 22)
        ssh_count = self.ssh_proc_count()
        remote = self.probe_remote_tunnels()
        if on_result:
            on_result("monitor", (local, ssh_count, remote))
        return local, ssh_count, remote


__all__ = ["DshCtl"]
