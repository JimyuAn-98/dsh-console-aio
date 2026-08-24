# -*- coding: utf-8 -*-
"""
dsh-tunnel-console — dsh SSH 隧道管理 + 本机 dsh 启停 + 健康监控
                      （纯 Windows 原生 GUI）
唯一入口: 双击运行 或  python dsh-tunnel-console.py

功能:
  · 本机 dsh 卡片: 一键 启动 / 停止 本机 dsh web（pnpm dsh web）
  · 隧道卡片: 一键 启动 / 常驻 / 停止 各隧道脚本
    （dsh-tunnel / connect-lab-dsh / dsh-tunnel-reverse）
  · 更新卡片: 一键 运行 update-dsh（拉取→构建→重启, 实时滚动日志）
  · 健康监控(两行):
      本机端口行 — 探测本机监听的端口
      185 隧道行  — SSH 直查 185 上反向隧道端口是否在监听
  · 配置: IP/用户名/仓库路径/端口/轮询间隔等全部集中在 config.json,
          或点界面右上角"配置"按钮编辑。
仅依赖 Python 标准库 (tkinter), 无需 pip 安装任何东西。
"""

import os
import re
import json
import time
import socket
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

import tunnel_mgr  # 纯 Python 隧道管理器

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ─────────────────────────────────────────
#  默认配置（当 config.json 缺失/字段缺失时使用）
# ─────────────────────────────────────────
DEFAULTS = {
    "ssh_server": "185.238.250.148",
    "ssh_user": "tunnel",
    "dash_repo": r"D:\Applications\deepseek-harness",
    "dash_port": 3080,
    "dash_cmd": ["pnpm.cmd", "dsh", "web"],
    "poll_seconds": 4,
    "remote_poll_seconds": 20,
    "tcp_timeout": 0.8,
    "ssh_timeout": 10,
    "update_timeout": 1800,
    # 实验室直连 204
    "lab_server": "10.1.12.204",
    "lab_user": "hjy",
    "lab_port": 3090,
    # 本机 -> 185 反向隧道: 185 上暴露本机 GUI 的端口
    "reverse_port": 8091,
    "local_ports": [
        [3080, "本机dsh", "GUI"],
        [8090, "本机8090", "在家隧道→204GUI"],
        [8022, "本机8022", "在家隧道→204SSH"],
        [8091, "本机8091", "在家隧道→本机GUI"],
        [3090, "本机3090", "实验室→204GUI"],
    ],
    "remote_tunnels": [
        [8090, "185:8090", "←204 GUI"],
        [8022, "185:8022", "←204 SSH"],
        [8091, "185:8091", "←本机GUI"],
    ],
    # 正向隧道(在家打通 185 三个口) 在本机使用的端口
    "forward_ports": [8090, 8022, 8091],
}


def load_config():
    """读取 config.json 并合并默认值。返回配置 dict。"""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULTS:
                    cfg[k] = v
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(cfg):
    """把配置写回 config.json。返回 True 成功 / False 失败。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# 读入配置 → 模块级常量（运行期修改需重建/重启后读取）
CONFIG = load_config()

SSH_SERVER   = CONFIG["ssh_server"]
SSH_USER     = CONFIG["ssh_user"]
DASH_REPO    = CONFIG["dash_repo"]
DASH_PORT    = CONFIG["dash_port"]
DASH_CMD     = list(CONFIG["dash_cmd"])
POLL_SECONDS = CONFIG["poll_seconds"]
REMOTE_POLL_SECONDS = CONFIG["remote_poll_seconds"]
TCP_TIMEOUT  = CONFIG["tcp_timeout"]
SSH_TIMEOUT  = CONFIG["ssh_timeout"]
UPDATE_TIMEOUT = CONFIG["update_timeout"]
LOCAL_PORTS  = [tuple(x[:3]) for x in CONFIG["local_ports"]]
REMOTE_TUNNELS = [tuple(x[:3]) for x in CONFIG["remote_tunnels"]]
FORWARD_PORTS = list(CONFIG["forward_ports"])
LAB_SERVER   = CONFIG["lab_server"]
LAB_USER     = CONFIG["lab_user"]
LAB_PORT     = CONFIG["lab_port"]
REVERSE_PORT = CONFIG["reverse_port"]

# 各操控项（order 决定卡片排列顺序）
# actions 决定该卡片显示的按钮:
#   start / persist / stop   (隧道脚本, 支持 -Persist / -Stop)
#   start / stop             (本机 dsh, 本地服务)
#   run                      (update-dsh: 一次完整更新, 无启停语义)
ITEMS = [
    {"type": "dsh",    "key": "dsh-web", "title": "本机 dsh", "port": DASH_PORT,
     "actions": ["start", "stop"],
     "desc": "启动/停止本机 dsh GUI\n(后台 pnpm dsh web,\n访问 http://127.0.0.1:%d)" % DASH_PORT},
    {"type": "py", "key": "dsh-tunnel", "port": 8090,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "在家 → 打通 185 三个转发口\n8090→204GUI / 8022→204SSH / 8091→本机GUI\n(纯 Python, 不再调用 ps1)"},
    {"type": "py", "key": "connect-lab-dsh", "port": LAB_PORT,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "实验室局域网 → 直连 204 dsh GUI (本机 3090)\n(纯 Python)"},
    {"type": "py", "key": "dsh-tunnel-reverse", "port": 0,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "本机 dsh → 185 反向隧道\n185:8091 → 本机 3080\n(纯 Python)"},
    {"type": "py", "key": "update-dsh", "port": -1,
     "backend": "python", "actions": ["run"],
     "desc": "运行一次完整更新:\ngit 拉取→依赖→构建→重启,\n期间 GUI 短暂断连\n(纯 Python)"},
]

LOG_RING = 4000
LOG_TAIL = 1500

F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 9)
COLOR_ON = "#2e8b57"
COLOR_OFF = "#999"
COLOR_RED = "#e07a7a"
COLOR_WARN = "#e5c07b"
ACCENT = "#1f6feb"

BTN_TEXT = {"start": "启动", "persist": "常驻", "stop": "停止", "run": "运行更新"}


def script_path(cfg):
    return os.path.join(BASE_DIR, cfg["file"])


def tcp_ok(host, port, timeout=TCP_TIMEOUT):
    """TCP 连接测试: 返回 (ok, 延迟ms)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.connect((host, port))
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, -1
    finally:
        s.close()


def ssh_proc_count():
    """统计 ssh.exe 进程数, 用于反向隧道卡片的兜底显示"""
    try:
        out = subprocess.run(
            ["tasklist", "/NH", "/FI", "IMAGENAME eq ssh.exe"],
            capture_output=True, text=True, errors="replace", timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
        return sum(1 for ln in out.splitlines() if "ssh.exe" in ln)
    except Exception:
        return -1


def probe_remote_tunnels():
    """
    SSH 直查公网服务器上反向隧道端口是否在监听。
    返回: {port: True/False}, 全部失败时返回 None 表示 SSH 不可达。
    """
    ports = "|".join(str(p[0]) for p in REMOTE_TUNNELS)
    cmd = ("ss -tln | grep -E ':(%s) '" % ports)
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "LogLevel=ERROR", f"{SSH_USER}@{SSH_SERVER}", cmd],
            capture_output=True, text=True, errors="replace", timeout=SSH_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode != 0:
            return None
        text = p.stdout or ""
        result = {}
        for port, _, _ in REMOTE_TUNNELS:
            result[port] = bool(re.search(r":%d\b" % port, text))
        return result
    except Exception:
        return None


class ConfigDialog(tk.Toplevel):
    """编辑 config.json 的对话框。保存后通过 self.saved_cfg 回传。"""

    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("配置 · config.json")
        self.resizable(False, False)
        self.configure(padx=12, pady=12)
        self.result = None
        self._vars = {}

        rows = [
            ("ssh_server", "公网服务器 IP", "185.238.250.148"),
            ("ssh_user", "隧道用户名", "tunnel"),
            ("dash_repo", "本机 dsh 仓库路径", ""),
            ("dash_port", "本机 dsh 端口", ""),
            ("dash_cmd", "启动命令 (空格分隔)", "pnpm.cmd dsh web"),
            ("poll_seconds", "本机轮询(秒)", ""),
            ("remote_poll_seconds", "SSH 直查间隔(秒)", ""),
        ]
        for i, (key, label, _ph) in enumerate(rows):
            ttk.Label(self, text=label + ":").grid(row=i, column=0, sticky="w", pady=2)
            v = tk.StringVar()
            default = cfg.get(key)
            if key == "dash_cmd" and isinstance(default, list):
                default = " ".join(default)
            v.set(str(default if default is not None else ""))
            ent = ttk.Entry(self, textvariable=v, width=46)
            ent.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=2)
            self._vars[key] = v

        btns = ttk.Frame(self)
        btns.grid(row=len(rows), column=0, columnspan=2, pady=(14, 0))
        ttk.Button(btns, text="保存", command=self._on_save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        ttk.Label(self, text="local_ports / remote_tunnels 请直接编辑 config.json",
                  font=F_SMALL, foreground="#888").grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # 让窗口作为对话框置顶于主窗
        self.transient(master)
        self.grab_set()

    def _on_save(self):
        try:
            cfg = {}
            cfg["ssh_server"] = self._vars["ssh_server"].get().strip() or "185.238.250.148"
            cfg["ssh_user"] = self._vars["ssh_user"].get().strip() or "tunnel"
            cfg["dash_repo"] = self._vars["dash_repo"].get().strip()
            cfg["dash_port"] = int(self._vars["dash_port"].get())
            cfg["dash_cmd"] = self._vars["dash_cmd"].get().strip().split()
            cfg["poll_seconds"] = int(self._vars["poll_seconds"].get())
            cfg["remote_poll_seconds"] = int(self._vars["remote_poll_seconds"].get())
        except ValueError:
            messagebox.showerror("输入错误", "端口/轮询间隔必须为整数。", parent=self)
            return
        self.result = cfg
        self.destroy()


class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("dsh 控制台 · 隧道与健康监控")
        # 窗口尺寸自适应屏幕: 默认 1200x840, 但不超过屏幕可用高度,
        # 否则日志区和底部状态栏会被挤到屏幕外。
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w = min(1200, max(1000, sw - 80))
        h = min(840, max(600, sh - 160))   # 留出标题栏+任务栏+系统缩放余量
        root.geometry(f"{w}x{h}")
        root.minsize(940, 600)

        self.monitor_stop = threading.Event()
        self.remote_state = None   # {port: bool}, None=SSH不可达
        self._build_ui()
        self._start_monitor()

    # ── UI ────────────────────────────────
    def _build_ui(self):
        pad = 10
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=pad, pady=(pad, 4))
        ttk.Label(top, text="dsh 控制台", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, text=f"  本机轮询 {POLL_SECONDS}s · SSH直查 {REMOTE_POLL_SECONDS}s",
                  font=F_SMALL, foreground="#666").pack(side="left")
        ttk.Button(top, text="配置", command=self._open_config).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="立即刷新", command=self._force_refresh).pack(side="right")

        cards = ttk.LabelFrame(self.root, text="操控", padding=8)
        cards.pack(fill="x", padx=pad, pady=4)
        self.cards = {}
        for i, cfg_item in enumerate(ITEMS):
            cards.columnconfigure(i, weight=1)
            self.cards[cfg_item["key"]] = self._build_card(cards, cfg_item, i)

        # ── 健康监控 ──
        mon = ttk.LabelFrame(self.root, text="健康监控", padding=8)
        mon.pack(fill="x", padx=pad, pady=4)
        self.mon_widgets = {}

        ttk.Label(mon, text="本机端口", font=F_BOLD,
                  foreground="#555").pack(anchor="w")
        row1 = ttk.Frame(mon)
        row1.pack(fill="x", pady=(2, 8))
        for port, label, note in LOCAL_PORTS:
            self._add_mon_cell(row1, f"L{port}", label, f"端口 {port}", note)

        ttk.Label(mon, text="185 反向隧道（SSH 直查, 仅绑回环）", font=F_BOLD,
                  foreground="#555").pack(anchor="w")
        row2 = ttk.Frame(mon)
        row2.pack(fill="x", pady=(2, 4))
        for port, label, note in REMOTE_TUNNELS:
            self._add_mon_cell(row2, f"R{port}", label, f"185 端口 {port}", note)
        f = ttk.Frame(row2)
        f.pack(side="left", expand=True, fill="both", padx=4)
        dot185 = tk.Label(f, text="●", font=("Segoe UI", 13), fg=COLOR_OFF)
        dot185.pack()
        ttk.Label(f, text="185 SSH", font=F_BOLD).pack()
        self.det185 = ttk.Label(f, text="--", font=F_SMALL, foreground="#888")
        self.det185.pack()
        ttk.Label(f, text="公网 :22", font=F_SMALL, foreground="#aaa").pack()
        self.mon_widgets["185"] = (dot185, self.det185)

        # ── 日志 ──
        logf = ttk.LabelFrame(self.root, text="运行日志", padding=8)
        logf.pack(fill="both", expand=True, padx=pad, pady=4)
        self.log_text = tk.Text(logf, height=8, wrap="word", font=F_MONO,
                                state="disabled", bg="#1e1e1e", fg="#e6e6e6")
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log_text.tag_configure("ok",   foreground="#7ecb6a")
        self.log_text.tag_configure("err",  foreground=COLOR_RED)
        self.log_text.tag_configure("warn", foreground=COLOR_WARN)

        self.status = ttk.Label(self.root, text="就绪",
                                anchor="w", font=F_SMALL, relief="sunken")
        self.status.pack(fill="x", side="bottom")

    def _add_mon_cell(self, parent, key, label, portline, note):
        f = ttk.Frame(parent)
        f.pack(side="left", expand=True, fill="both", padx=4)
        dot = tk.Label(f, text="●", font=("Segoe UI", 12), fg=COLOR_OFF)
        dot.pack()
        ttk.Label(f, text=label, font=F_BOLD).pack()
        det = ttk.Label(f, text="--", font=F_SMALL, foreground="#888")
        det.pack()
        ttk.Label(f, text=portline, font=F_SMALL, foreground="#aaa").pack()
        self.mon_widgets[key] = (dot, det)

    def _open_config(self):
        from copy import deepcopy
        dlg = ConfigDialog(self.root, deepcopy(CONFIG))
        self.root.wait_window(dlg)
        if dlg.result:
            # 合并: 只覆盖对话框编辑过的字段, 保留 local_ports/remote_tunnels
            # /forward_ports/lab_*/reverse_port 等对话框外字段。
            merged = dict(CONFIG)
            merged.update(dlg.result)
            success = save_config(merged)
            if success:
                messagebox.showinfo("已保存", "配置已写入 config.json\n重启程序后生效。")
                self.log("[配置] 已更新并保存到 config.json（重启后生效）", "ok")
            else:
                messagebox.showerror("保存失败", "无法写入 config.json（请检查文件权限）。")

    def _build_card(self, parent, cfg_item, col):
        title = cfg_item.get("title") or (
            os.path.basename(cfg_item["file"]) if cfg_item.get("file") else cfg_item["key"])
        f = ttk.Frame(parent, padding=6, relief="groove", borderwidth=1)
        f.grid(row=0, column=col, sticky="nsew", padx=3)
        header = ttk.Frame(f)
        header.pack(fill="x")
        accent = cfg_item["type"] in ("dsh", "update")
        ttk.Label(header, text=title, font=F_BOLD,
                  foreground=ACCENT if accent else "#000").pack(side="left")
        st = tk.Label(header, text="○ 停止" if cfg_item["type"] != "update" else "○ 空闲",
                      font=F_SMALL, fg=COLOR_OFF)
        st.pack(side="right")
        ttk.Label(f, text=cfg_item["desc"], font=F_SMALL, foreground="#666",
                  wraplength=200, justify="left").pack(anchor="w", pady=(2, 6))

        btns = ttk.Frame(f)
        btns.pack(fill="x")
        for act in cfg_item["actions"]:
            ttk.Button(btns, text=BTN_TEXT[act], width=7,
                       command=lambda c=cfg_item, a=act: self.action(c, a)).pack(side="left", padx=2)
        return {"frame": f, "st": st, "cfg": cfg_item}

    # ── 日志 / 状态 ────────────────────────
    def log(self, msg, tag=""):
        self.root.after(0, lambda: self._log_do(msg, tag))

    def _log_do(self, msg, tag):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        if int(self.log_text.index("end-1c").split(".")[0]) > LOG_RING:
            self.log_text.delete("1.0", f"{LOG_RING - LOG_TAIL}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, msg):
        self.root.after(0, lambda: self.status.configure(text=msg))

    # ── 动作分发 ───────────────────────────
    def action(self, cfg_item, mode):
        t = cfg_item["type"]
        if t == "dsh":
            self.log("[本机 dsh] 模式: " + mode, "warn")
            self.set_status(f"正在 {mode} 本机 dsh ...")
            threading.Thread(target=self._run_dsh, args=(mode,), daemon=True).start()
            return
        if cfg_item.get("backend") == "python":
            if cfg_item["key"] == "update-dsh":
                self.log("[update-dsh] 开始运行更新 (纯 Python)", "warn")
                self.set_status("正在运行更新（构建较久，请耐心等待）...")
                threading.Thread(target=self._run_update, daemon=True).start()
                return
            # 纯 Python 隧道
            self.log(f"[{cfg_item['key']}] 模式: {mode}（Python）", "warn")
            self.set_status(f"正在执行 {mode} → {cfg_item['key']} (Python) ...")
            threading.Thread(target=self._run_python_tunnel,
                             args=(cfg_item, mode), daemon=True).start()
            return
            # 纯 Python 隧道（不再调 ps1）
            self.log(f"[{cfg_item['key']}] 模式: {mode}（Python）", "warn")
            self.set_status(f"正在执行 {mode} → {cfg_item['key']} (Python) ...")
            threading.Thread(target=self._run_python_tunnel,
                             args=(cfg_item, mode), daemon=True).start()
            return
        # ps1 隧道
        path = script_path(cfg_item)
        if not os.path.exists(path):
            messagebox.showerror("找不到脚本",
                                 f"{path}\n不存在。请确认脚本与 dsh-tunnel-console.py 放在同一目录。")
            return
        self.log(f"[{cfg_item['key']}] 模式: {mode}", "warn")
        self.set_status(f"正在执行 {mode} → {os.path.basename(path)} ...")
        threading.Thread(target=self._run_ps1, args=(cfg_item, path, mode), daemon=True).start()

    # ── 本机 dsh ───────────────────────────
    def _run_dsh(self, mode):
        if mode == "start":
            self._dsh_start()
        elif mode == "stop":
            self._dsh_stop()

    def _dsh_start(self):
        if not os.path.isdir(DASH_REPO):
            self.log(f"  仓库不存在: {DASH_REPO}", "err")
            self.set_status("启动失败: 仓库目录不存在")
            return
        self.log(f"  $ cd {DASH_REPO} && {' '.join(DASH_CMD)}")
        try:
            logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-dash")
            os.makedirs(logdir, exist_ok=True)
            out = open(os.path.join(logdir, "dsh-web.out.log"), "ab")
            err = open(os.path.join(logdir, "dsh-web.err.log"), "ab")
            subprocess.Popen(DASH_CMD, cwd=DASH_REPO,
                             stdout=out, stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            self.log(f"  已在后台启动, 等待 {DASH_PORT} 端口就绪…", "ok")
            self.set_status(f"已触发本机 dsh 启动 → http://127.0.0.1:{DASH_PORT}")
        except FileNotFoundError:
            self.log(f"  找不到 {DASH_CMD[0]}, 请确认 pnpm 在 PATH 或修改配置", "err")
            self.set_status("启动失败: 找不到启动命令")
        except Exception as e:
            self.log(f"  异常: {e}", "err")
            self.set_status(f"启动出错: {e}")

    def _dsh_stop(self):
        ps = ("$n=0\n"
              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction SilentlyContinue |\n"
              "  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } |\n"
              "  ForEach-Object { Write-Output ('stop node ' + $_.ProcessId); taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }\n"
              "Get-CimInstance Win32_Process -Filter \"Name='pnpm.cmd'\" -ErrorAction SilentlyContinue |\n"
              "  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } |\n"
              "  ForEach-Object { Write-Output ('stop pnpm ' + $_.ProcessId); taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }\n"
              "if($n -eq 0){ Write-Output 'no dsh web process' }\n")
        self.log("  $ stopping dsh web (node/pnpm, 匹配 dsh+web)…")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                "Bypass", "-Command", ps],
                               capture_output=True, text=True, errors="replace",
                               timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
            for ln in (out.splitlines() or ["(无输出)"]):
                self.log("    " + ln, "ok" if r.returncode == 0 else "err")
            self.set_status("已停止本机 dsh web" if r.returncode == 0
                            else "停止本机 dsh 出错")
        except subprocess.TimeoutExpired:
            self.log("  [停止] 超时(60s)", "err")
            self.set_status("停止本机 dsh 超时")
        except Exception as e:
            self.log(f"  异常: {e}", "err")
            self.set_status(f"停止出错: {e}")

    # ── 更新（纯 Python: git + pnpm, 流式日志） ──
    def _run_update(self):
        repo = DASH_REPO
        if not os.path.isdir(repo):
            self.log(f"  仓库不存在: {repo}", "err")
            self.set_status("更新失败: 仓库目录不存在")
            return
        # [1] 停掉当前 dsh web（与 _dsh_stop 相同匹配逻辑）
        self.log("[更新] 步骤1/5: 停止当前 dsh web", "warn")
        self._stop_dsh_web_silent()
        time.sleep(2)
        # [2..5] git + pnpm
        steps = [
            ("[更新] 步骤2/5: git fetch + pull",
             ["git", "fetch", "origin", "--prune"], None),
            ("[更新] 步骤2.5/5: git pull --ff-only",
             ["git", "pull", "--ff-only"], repo),
            ("[更新] 步骤3/5: pnpm install",
             ["pnpm.cmd", "install"], repo),
            ("[更新] 步骤4/5: pnpm run build",
             ["pnpm.cmd", "run", "build"], repo),
        ]
        for label, cmd, cwd in steps:
            self.log(label, "warn")
            if not self._stream_cmd(cmd, cwd=cwd):
                self.set_status("更新失败: " + label)
                return
        # [5] 重启 GUI
        self.log("[更新] 步骤5/5: 重启 dsh web", "warn")
        self._dsh_start()
        self.log("  [更新] 完成 ✓ 访问 http://127.0.0.1:%d" % DASH_PORT, "ok")
        self.set_status("更新完成")

    def _stream_cmd(self, cmd, cwd=None):
        """流式运行命令, 输出逐行打进日志。返回 True/False。"""
        self.log("  $ " + " ".join(cmd))
        try:
            p = subprocess.Popen(
                cmd, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            self.log(f"  找不到命令: {cmd[0]}", "err")
            return False
        deadline = time.time() + UPDATE_TIMEOUT
        while True:
            line = p.stdout.readline() if p.stdout else None
            if line:
                self.log("    " + line.rstrip())
                continue
            if p.poll() is not None:
                break
            if time.time() > deadline:
                p.kill()
                self.log("  [更新] 超时，已强制终止", "err")
                return False
            time.sleep(0.1)
        rc = p.wait()
        if rc != 0:
            self.log(f"  [更新] 步骤失败 (exit {rc})", "err")
            return False
        return True

    def _stop_dsh_web_silent(self):
        """静默停止本机 dsh web（复用 _dsh_stop 的杀进程逻辑, 不打日志回显）。"""
        ps = ("$n=0; "
              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction SilentlyContinue | "
              "Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } | "
              "ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }; "
              "Get-CimInstance Win32_Process -Filter \"Name='pnpm.cmd'\" -ErrorAction SilentlyContinue | "
              "Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } | "
              "ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }")
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                            "Bypass", "-Command", ps],
                           capture_output=True, text=True, errors="replace",
                           timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

    # ── 纯 Python 隧道 ──────────────────────
    def _build_tunnel(self, cfg_item):
        """根据 config 构造一条 Tunnel。返回 tunnel_mgr.Tunnel 实例。"""
        key = cfg_item["key"]
        if key == "dsh-tunnel":
            # 在家正向: 本机 8090/8022/8091 -> 185 同端口
            forwards = [(p, "127.0.0.1", p) for p in FORWARD_PORTS]
            host, user, mode = SSH_SERVER, SSH_USER, "forward"
            watch = FORWARD_PORTS[0] if FORWARD_PORTS else None
        elif key == "connect-lab-dsh":
            # 实验室直连: 本机 3090 -> 204 的 3090 (局域网, 不经 185)
            forwards = [(LAB_PORT, "127.0.0.1", LAB_PORT)]
            host, user, mode = LAB_SERVER, LAB_USER, "forward"
            watch = LAB_PORT
        elif key == "dsh-tunnel-reverse":
            # 本机 -> 185 反向: 185 的 reverse_port -> 本机 dsh
            forwards = [(REVERSE_PORT, "127.0.0.1", DASH_PORT)]
            host, user, mode = SSH_SERVER, SSH_USER, "reverse"
            watch = None   # 反向隧道本机无法直接探测; 用 PID 轨道判断
        else:
            raise ValueError("unknown tunnel: " + key)
        t = tunnel_mgr.Tunnel(
            BASE_DIR, key, host, user,
            mode=mode, forwards=forwards, watch_port=watch)
        t.set_logger(lambda msg, tag="": self.log("  " + msg, tag))
        return t

    def _run_python_tunnel(self, cfg_item, mode):
        key = cfg_item["key"]
        if mode == "stop":
            self._stop_py_tunnel(cfg_item)
            return
        # start / persist
        t = self._build_tunnel(cfg_item)
        ok = t.start()
        if not ok:
            self.set_status(f"启动失败: {key}")
            return
        self.set_status(f"{key} 已启动 (Python)")
        if mode == "persist":
            self._start_persist(cfg_item, t)
        # 等端口就绪
        import time as _t
        for _ in range(6):
            if t.is_running():
                self.log(f"  [{key}] 端口就绪。", "ok")
                break
            _t.sleep(1)

    def _start_persist(self, cfg_item, t):
        """启动后台探活重连线程。GUI 存活期间, 隧道断开则自动重启。"""
        key = cfg_item["key"]
        stop_flag = threading.Event()
        if not hasattr(self, "_py_persist"):
            self._py_persist = {}   # key -> stop_event
        # 停掉旧的
        old = self._py_persist.get(key)
        if old:
            old.set()
        self._py_persist[key] = stop_flag

        def loop():
            while not stop_flag.is_set():
                if not t.is_running():
                    self.log(f"  [{key}] 隧道断开, 尝试重连…", "warn")
                    t.start()
                stop_flag.wait(5)
        th = threading.Thread(target=loop, daemon=True)
        th.start()
        self.log(f"  [{key}] 常驻模式已启用（断线自动重连）", "ok")

    def _stop_py_tunnel(self, cfg_item):
        key = cfg_item["key"]
        if hasattr(self, "_py_persist") and self._py_persist.get(key):
            self._py_persist[key].set()
            self._py_persist.pop(key, None)
            self.log(f"  [{key}] 已取消常驻重连", "warn")
        t = self._build_tunnel(cfg_item)
        n = t.stop()
        self.set_status(f"{key} 已停止 (Python)" if n else f"{key} 停止(无进程)")

    # ── 隧道脚本 ───────────────────────────
    def _run_ps1(self, cfg_item, path, mode):
        key = cfg_item["key"]
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", path]
        if mode == "persist":
            args.append("-Persist")
        elif mode == "stop":
            args.append("-Stop")
        self.log(f"  $ powershell {display_args(args)}")

        try:
            if mode == "stop":
                r = subprocess.run(args, capture_output=True, text=True,
                                   errors="replace", timeout=120,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
                for ln in (out.splitlines() or ["(无输出)"]):
                    self.log("    " + ln, "ok" if r.returncode == 0 else "err")
                if r.returncode == 0:
                    self.log("  [停止] 完成", "ok")
                    self.set_status(f"已发送停止: {os.path.basename(path)}")
                else:
                    self.log(f"  [停止] 退出码 {r.returncode}", "err")
                    self.set_status(f"停止 {key} 返回非 0")
            else:
                subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
                self.log(f"  已触发 {mode}, 等待端口/进程就绪…", "ok")
                self.set_status(f"已触发 {mode} → {os.path.basename(path)}")
        except subprocess.TimeoutExpired:
            self.log("  [停止] 超时(120s)", "err")
            self.set_status(f"停止 {key} 超时")
        except Exception as e:
            self.log(f"  异常: {e}", "err")
            self.set_status(f"执行出错: {e}")

    def _force_refresh(self):
        threading.Thread(target=self._tick, daemon=True).start()
        threading.Thread(target=self._remote_tick, daemon=True).start()

    # ── 健康监控 ───────────────────────────
    def _start_monitor(self):
        self.monitor_stop.clear()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._remote_loop, daemon=True).start()

    def _monitor_loop(self):
        while not self.monitor_stop.is_set():
            self._tick()
            self.monitor_stop.wait(POLL_SECONDS)

    def _remote_loop(self):
        while not self.monitor_stop.is_set():
            self._remote_tick()
            self.monitor_stop.wait(REMOTE_POLL_SECONDS)

    def _tick(self):
        results = {}
        for port, _, _ in LOCAL_PORTS:
            results[port] = tcp_ok("127.0.0.1", port)
        results["185"] = tcp_ok(SSH_SERVER, 22)
        ssh_count = ssh_proc_count()
        self._render(results, ssh_count)

    def _remote_tick(self):
        state = probe_remote_tunnels()
        self.remote_state = state
        self._render_remote(state)

    def _render(self, results, ssh_count):
        # 本机端口健康（不含 185 公网连通, 概念分开）
        local_ok = [port for port, (ok, _) in results.items()
                    if port != "185" and ok]
        local_total = len(LOCAL_PORTS)
        ssh_ok = results.get("185", (False, -1))[0]
        ssh_txt = "185 在线" if ssh_ok else "185 不可达"
        summary = (f"本机端口 {len(local_ok)}/{local_total} · {ssh_txt}"
                   f" · ssh.exe {ssh_count if ssh_count >= 0 else '?'}")
        def apply():
            for port, (ok, dt) in results.items():
                if port == "185":
                    dot, det = self.mon_widgets["185"]
                    dot.configure(fg=COLOR_ON if ok else COLOR_RED)
                    det.configure(text="在线" if ok else "不可达")
                    continue
                key = f"L{port}"
                if key not in self.mon_widgets:
                    continue
                dot, det = self.mon_widgets[key]
                dot.configure(fg=COLOR_ON if ok else COLOR_RED)
                det.configure(text=f"{dt}ms" if ok else "未就绪")
            for key, card in self.cards.items():
                cfg_item = card["cfg"]
                port = cfg_item["port"]
                if port is None or port < 0:
                    card["st"].configure(text="○ 空闲", fg=COLOR_OFF)
                    continue
                on = False
                if cfg_item.get("backend") == "python":
                    # 纯 Python 隧道: 用隧道管理器判断(forward 看端口, reverse 看 PID 轨道)
                    on = self._py_tunnel_running(cfg_item)
                elif port:
                    on = port in results and results[port][0]
                else:
                    on = ssh_count > 0
                card["st"].configure(text="● 运行中" if on else "○ 停止",
                                     fg=COLOR_ON if on else COLOR_OFF)
            self.status.configure(text=summary)
        self.root.after(0, apply)

    def _py_tunnel_running(self, cfg_item):
        """纯 Python 隧道在线判断: forward 探测端口, reverse 查 PID 轨道。"""
        try:
            t = self._build_tunnel(cfg_item)
            return t.is_running()
        except Exception:
            return False

    def _render_remote(self, state):
        def apply():
            if state is None:
                for port, _, _ in REMOTE_TUNNELS:
                    key = f"R{port}"
                    dot, det = self.mon_widgets[key]
                    dot.configure(fg=COLOR_WARN)
                    det.configure(text="SSH不可达")
                return
            for port, _, _ in REMOTE_TUNNELS:
                key = f"R{port}"
                dot, det = self.mon_widgets[key]
                on = bool(state.get(port))
                dot.configure(fg=COLOR_ON if on else COLOR_RED)
                det.configure(text="隧道在线" if on else "未监听")
        self.root.after(0, apply)


def display_args(args):
    skip = {"powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"}
    return " ".join(a for a in args if a not in skip)


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
