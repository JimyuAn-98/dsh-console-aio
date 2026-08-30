# -*- coding: utf-8 -*-
"""
tunnel_mgr.py — 纯 Python SSH 隧道管理器（零依赖, Windows）
用系统自带的 ssh.exe 建立端口转发, 由 GUI 直接调度, 不再依赖 .ps1。

支持的隧道形态:
  forward : ssh -N -L <本地>:127.0.0.1:<远端>  (在家打通的"正向隧道")
  reverse : ssh -N -R <远端>:127.0.0.1:<本地>  (本机/实验室dsh -> 公网中转的"反向隧道")

生命周期（由调用方 GUI 负责线程调度）:
  start()       启动隧道(后台 CREATE_NO_WINDOW), 记录 PID
  is_running()  按状态端口探测隧道是否在线
  stop()        按记录的 PID + 特征命令行 taskkill(连子进程)

所有连接参数(IP/用户/端口)由调用方传入, 本模块不含任何硬编码。
"""

import os
import sys
import json
import time
import socket
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PIDFILE = "tunnel-pids.json"


def _pid_path(base_dir):
    return os.path.join(base_dir, _PIDFILE)


def _read_pids(base_dir):
    try:
        with open(_pid_path(base_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pids(base_dir, pids):
    try:
        with open(_pid_path(base_dir), "w", encoding="utf-8") as f:
            json.dump(pids, f, indent=2)
        return True
    except OSError:
        return False


def tcp_ok(host, port, timeout=0.8):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def tunnels_snapshot(base_dir):
    # 隧道常驻进程快照(诊断报告等只读场景): {key: {"pid": int, "alive": bool}}。
    # pid 文件的记录值是 dict(含 sig/host/user 等, 此处只取 pid 字段, 明文不入快照);
    # 兼容旧裸 int 记录; 单条坏记录跳过不拖垮快照; 文件缺失/损坏返回 {}。
    out = {}
    for key, rec in _read_pids(base_dir).items():
        pid = rec.get("pid") if isinstance(rec, dict) else rec
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        out[key] = {"pid": pid, "alive": _pid_alive(pid)}
    return out


def _pid_alive(pid):
    # Windows 进程存在性检查。⚠ 严禁 os.kill(pid, 0): Windows 上 signal 0 == CTRL_C_EVENT,
    # os.kill(pid, 0) 实际是"向共享控制台发 Ctrl+C"(非 Unix 的杀 0 探活语义)。在宿主 harness
    # 的伪控制台里执行会把 Ctrl+C 传导给宿主 web(实测 3080 宿主被 SIGINT 优雅退出, 2026-08-29
    # 排查实锤: WMI 无控制台进程调用抛 WinError 87, 控制台内调用则传播 Ctrl+C)。
    # 改用 tasklist CSV 按 PID 精确匹配, 纯子进程零信号副作用。
    pid = int(pid)
    try:
        out = subprocess.run(
            ["tasklist", "/NH", "/FO", "CSV", "/FI", "PID eq %d" % pid],
            capture_output=True, text=True, errors="replace",
            timeout=10, creationflags=NO_WINDOW).stdout or ""
        # CSV 行形如 "python.exe","123","Console","1","12,345 K";
        # 精确比对第 2 列, 避免子串误判(如 123 命中 1234)。无任务时输出纯文本提示, 无逗号 → 判 False。
        for line in out.splitlines():
            if '"' not in line:
                continue
            fields = [f.strip('"') for f in line.split('","')]
            if len(fields) >= 2 and fields[1] == str(pid):
                return True
        return False
    except Exception:
        return False


def _taskkill(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True, errors="replace",
                       timeout=15, creationflags=NO_WINDOW)
    except Exception:
        pass


def _kill_by_cmdline(sig):
    """杀掉命令行中含 sig 的 ssh 进程(PowerShell 按特征匹配, 可靠零依赖)。返回个数。"""
    if not sig:
        return 0
    ps = (
        "$n=0; "
        "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -like '*%(sig)s*' } | "
        "ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }; "
        "Write-Output $n"
    ) % {"sig": sig}
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, errors="replace",
            timeout=30, creationflags=NO_WINDOW)
        parts = (r.stdout or "").split()
        try:
            return int(parts[-1]) if parts else 0
        except ValueError:
            return 0
    except Exception:
        return 0


class Tunnel:
    def __init__(self, base_dir, key, host, user, mode="forward",
                 forwards=None, watch_port=None, pidfile="tunnel-pids.json"):
        self.base_dir = base_dir
        self.pidfile = pidfile
        self.key = key
        self.host = host
        self.user = user
        self.mode = mode
        self.forwards = forwards or []
        self.watch_port = watch_port
        self._log = lambda msg, tag="": print("[%s] %s" % (key, msg))

    def set_logger(self, fn):
        self._log = fn

    def _flags(self):
        fl = []
        for a, b, c in self.forwards:
            if self.mode == "forward":
                fl += ["-L", "%d:%s:%d" % (a, b, c)]
            else:
                fl += ["-R", "%d:%s:%d" % (a, b, c)]
        return fl

    def callsig(self):
        """命令行特征(首条转发 + 主机), 用于唯一匹配这条隧道。"""
        f = self._flags()
        return (" ".join(f[:2]), "%s@%s" % (self.user, self.host))

    def build_cmd(self):
        key = os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519")
        cmd = ["ssh", "-N", "-i", key,
               "-o", "ServerAliveInterval=30",
               "-o", "ServerAliveCountMax=3",
               "-o", "ExitOnForwardFailure=yes",
               "-o", "ConnectTimeout=10",
               "-o", "BatchMode=yes"]
        cmd += self._flags()
        cmd += ["%s@%s" % (self.user, self.host)]
        return cmd

    def start(self):
        cmd = self.build_cmd()
        self._log("$ ssh " + " ".join(cmd[2:]))
        logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-tunnel")
        os.makedirs(logdir, exist_ok=True)
        def _open(name):
            return open(os.path.join(logdir, "%s.%s" % (self.key, name)), "ab")
        try:
            out = _open("out.log")
            err = _open("err.log")
            self.proc = subprocess.Popen(cmd, stdout=out, stderr=err,
                                         creationflags=NO_WINDOW)
        except FileNotFoundError:
            self._log("找不到 ssh.exe（请启用 Windows 的 OpenSSH 客户端）", "err")
            return False
        sig, _ = self.callsig()
        pids = _read_pids(self.base_dir)
        pids[self.key] = {"pid": self.proc.pid, "sig": sig,
                          "mode": self.mode, "host": self.host,
                          "user": self.user, "forwards": list(self.forwards),
                          "watch": self.watch_port}
        if not _write_pids(self.base_dir, pids):
            self._log("警告: PID 文件写入失败(隧道仍在运行, 但重启后可能无法自动恢复)", "warn")
        self._log("已启动（PID %d），等待端口就绪…" % self.proc.pid, "ok")
        return True

    def is_running(self):
        if self.watch_port:
            return tcp_ok("127.0.0.1", self.watch_port)
        pids = _read_pids(self.base_dir)
        rec = pids.get(self.key)
        return bool(rec and rec.get("pid") and _pid_alive(rec["pid"]))

    def stop(self):
        killed = 0
        pids = _read_pids(self.base_dir)
        rec = pids.get(self.key)
        if rec and rec.get("pid"):
            pid = rec["pid"]
            if _pid_alive(pid):
                _taskkill(pid)
                self._log("已停止 PID %d" % pid, "ok")
                killed += 1
            pids.pop(self.key, None)
            if not _write_pids(self.base_dir, pids):
                self._log("警告: PID 文件更新失败", "warn")
        sig, _ = self.callsig()
        killed += _kill_by_cmdline(sig)
        if not killed:
            self._log("未发现运行中的隧道进程", "warn")
        return killed


def _main_demo(argv):
    """命令行干跑演示(供测试, 不经 GUI):
       python tunnel_mgr.py <key> <host> <user> <port[,port..]> <start|stop|status>
    """
    if len(argv) < 6:
        print("usage: tunnel_mgr.py <key> <host> <user> <ports> <start|stop|status>")
        return 2
    key, host, user = argv[1], argv[2], argv[3]
    ports = [int(p) for p in argv[4].split(",")]
    act = argv[5]
    fw = [(p, "127.0.0.1", p) for p in ports]
    t = Tunnel(os.getcwd(), key, host, user, mode="forward", forwards=fw,
               watch_port=ports[0])
    if act == "start":
        return 0 if t.start() else 1
    elif act == "stop":
        t.stop()
        return 0
    else:
        print("running=", t.is_running())
        return 0


if __name__ == "__main__":
    sys.exit(_main_demo(sys.argv))
