# -*- coding: utf-8 -*-
"""
dsh-console-aio — dsh SSH 隧道管理 + 本机 dsh 启停 + 健康监控
                      （纯 Windows 原生 GUI）
唯一入口: 双击运行 或  python dsh-console-aio.py

功能:
  · 本机 dsh 卡片: 一键 启动 / 停止 本机 dsh web（pnpm dsh web）
  · 隧道卡片: 一键 启动 / 常驻 / 停止 各隧道脚本
    （dsh-tunnel / connect-lab-dsh / dsh-tunnel-reverse）
  · 更新卡片: 一键 运行 update-dsh（拉取→构建→重启, 实时滚动日志）
  · 健康监控(两行):
      本机端口行 — 探测本机监听的端口
      公网服务器 隧道行  — SSH 直查 公网服务器 上反向隧道端口是否在监听
  · 配置: IP/用户名/仓库路径/端口/轮询间隔等全部集中在 config.json,
          或点界面右上角"配置"按钮编辑。
仅依赖 Python 标准库 (tkinter), 无需 pip 安装任何东西。
"""

import os
import re
import sys

if getattr(sys, "frozen", False):
    # 打包(exe)环境: 显式指定 tcl/tk 库目录(conda 布局下 PyInstaller 不会自动收集)
    _meip = getattr(sys, "_MEIPASS", "")
    if _meip:
        os.environ.setdefault("TCL_LIBRARY", os.path.join(_meip, "tcl8.6"))
        os.environ.setdefault("TK_LIBRARY", os.path.join(_meip, "tk8.6"))
import json
import time
import socket
import threading
import importlib
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import tunnel_mgr
import dsh_data  # 纯 Python 隧道管理器

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
APP_VERSION = "0.3.0"   # 与 RELEASE_NOTES.md 对齐; 更新检查用

# ─────────────────────────────────────────
#  默认配置（当 config.json 缺失/字段缺失时使用）
#  仅包含通用/无敏感信息的值: 真实 IP/用户名/路径只存在用户本地的 config.json
# ─────────────────────────────────────────
DEFAULTS = {
    "ssh_server": "YOUR_PUBLIC_IP",   # 请填公网中转服务器 IP/域名
    "ssh_user": "YOUR_USER",           # 请填中转服务器用户名
    "dash_repo": "",                   # 本机 dsh 仓库路径(留空则提示在配置向导填写)
    "dash_port": 3080,
    "dash_cmd": ["pnpm.cmd", "dsh", "web"],
    "poll_seconds": 4,
    "remote_poll_seconds": 20,
    "tcp_timeout": 0.8,
    "ssh_timeout": 10,
    "update_timeout": 1800,
    # 实验室直连(可选, 未配置时置空)
    "lab_server": "",
    "lab_user": "",
    "lab_port": 3090,
    # 本机反向隧道: 中继端口 -> 本机 dsh
    "reverse_port": 8091,
    "local_ports": [
        [3080, "本机dsh", "GUI"],
        [8090, "本地8090", "正向隧道"],
        [8022, "本地8022", "正向隧道"],
        [8091, "本地8091", "正向隧道"],
        [3090, "本地3090", "实验室直连"],
    ],
    "remote_tunnels": [
        [8090, "中继:8090", "远端监听"],
        [8022, "中继:8022", "远端监听"],
        [8091, "中继:8091", "远端监听"],
    ],
    # 正向隧道在中继侧使用的端口
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
# 左导航页面注册: (显示名, key); PAGE_MODULES: key -> (模块, Page类)
NAV_ITEMS = [
    ("总览", "overview"),
    ("会话与工作区", "sessions"),
    ("Agent 模式", "agents"),
    ("Profile 管理", "profiles"),
    ("插件管理", "plugins"),
    ("任务看板", "taskboard"),
    ("模型用量", "usage"),
    ("LLM 配置", "llm"),
    ("主题外观", "theme"),
    ("备份与运维", "ops"),
    ("SSH 密钥", "keys"),
    ("关于与更新", "version"),
    ("部署管理", "deployments"),
]
PAGE_MODULES = {
    "sessions": ("mgmt_sessions", "SessionPage"),
    "agents": ("mgmt_agents", "AgentPage"),
    "profiles": ("mgmt_profiles", "ProfilePage"),
    "plugins": ("mgmt_plugins", "PluginPage"),
    "taskboard": ("mgmt_taskboard", "TaskboardPage"),
    "usage": ("mgmt_usage", "UsagePage"),
    "llm": ("mgmt_llm", "LlmPage"),
    "theme": ("mgmt_theme", "ThemePage"),
    "ops": ("mgmt_ops", "OpsPage"),
    "keys": ("mgmt_keys", "KeysPage"),
    "version": ("mgmt_version", "VersionPage"),
    "deployments": ("mgmt_deployments", "DeploymentPage"),
}

ITEMS = [
    {"type": "dsh",    "key": "dsh-web", "title": "本机 dsh", "port": DASH_PORT,
     "actions": ["start", "restart", "stop"],
     "desc": "启动/重启/停止本机 dsh GUI\n(后台 pnpm dsh web,\n访问 http://127.0.0.1:%d)" % DASH_PORT},
    {"type": "py", "key": "dsh-tunnel", "port": 8090,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "在家 → 打通 公网服务器 三个转发口\n8090→实验室dshGUI / 8022→实验室dshSSH / 8091→本机GUI"},
    {"type": "py", "key": "connect-lab-dsh", "port": LAB_PORT,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "实验室局域网 → 直连 实验室dsh dsh GUI (本机 3090)"},
    {"type": "py", "key": "dsh-tunnel-reverse", "port": 0,
     "backend": "python", "actions": ["start", "persist", "stop"],
     "desc": "本机 dsh → 公网服务器 反向隧道\n公网服务器:8091 → 本机 3080"},
    {"type": "py", "key": "update-dsh", "port": -1,
     "backend": "python", "actions": ["run"],
     "desc": "运行一次完整更新:\ngit 拉取→依赖→构建→重启,\n期间 GUI 短暂断连"},
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

BTN_TEXT = {"start": "启动", "restart": "重启", "persist": "常驻", "stop": "停止", "run": "运行更新"}


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
    """配置向导: 分组 + 场景模板 + SSH 测试 + 完整隧道参数编辑。
    保存后 self.result 持有用户改动字段(dict), 由上层合并写回 config.json。"""

    HELP = {
        "ssh_server": "公网可达的中转服务器 IP/域名(需已配置免密 SSH 登录)",
        "ssh_user": "中转服务器上用于建隧道的用户名(需已配置免密)",
        "ssh_port": "SSH 连接端口(仅用于测试, 默认 22)",
        "dash_repo": "本机 dsh 仓库绝对路径, 如 D:/Applications/deepseek-harness",
        "dash_port": "本机 dsh GUI 端口(默认 3080)",
        "dash_cmd": "启动命令(空格分隔): pnpm.cmd dsh web",
        "forward_ports": "在家正向隧道本机端口, 逗号分隔: 8090,8022,8091",
        "lab_server": "实验室服务器 IP(局域网直连用)",
        "lab_user": "实验室服务器 SSH 用户名",
        "lab_port": "实验室 dsh 本机映射端口(默认 3090)",
        "reverse_port": "本机 dsh 暴露到中继的端口(公网服务器:端口 → 本机)",
        "poll_seconds": "本机健康检查间隔(秒)",
        "remote_poll_seconds": "SSH 直查中继监听状态的间隔(秒)",
    }

    TEMPLATES = {
        "在家→中继隧道": {"ssh_server": "YOUR_PUBLIC_IP", "ssh_user": "YOUR_USER",
                          "forward_ports": "8090,8022,8091", "reverse_port": "8091"},
        "实验室→直连实验室dsh": {"lab_server": "YOUR_LAB_IP", "lab_user": "YOUR_USER",
                           "lab_port": "3090"},
        "本机→中继反向": {"reverse_port": "8091"},
    }

    LABELS = {
        "ssh_server": "服务器 IP/域名", "ssh_user": "用户名", "ssh_port": "SSH 端口",
        "dash_repo": "仓库路径", "dash_port": "端口", "dash_cmd": "启动命令",
        "forward_ports": "在家正向端口", "lab_server": "实验室 IP",
        "lab_user": "实验室用户", "lab_port": "实验室映射端口",
        "reverse_port": "反向端口", "poll_seconds": "本机轮询(秒)",
        "remote_poll_seconds": "远端轮询(秒)",
    }

    def __init__(self, master, cfg):
        super().__init__(master)
        self._master = master
        self.title("隧道配置向导")
        self.configure(padx=15, pady=10)
        self.result = None
        self._vars = {}
        self._cfg = cfg
        self._row = 0
        self._build()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        tpl = ttk.LabelFrame(wrap, text="场景模板 (一键填充, 把占位符改成真实 IP/用户名)", padding=8)
        tpl.pack(fill="x", pady=(0, 8))
        for name in list(self.TEMPLATES) + ["自定义"]:
            ttk.Button(tpl, text=name, command=lambda n=name: self._apply(n)).pack(side="left", padx=3, ipadx=2)
        body = ttk.Frame(wrap)
        body.pack(fill="both", expand=True)
        self._body = body
        self._sec("① 公网中转服务器")
        self._field("ssh_server", None)
        self._field("ssh_user", None)
        self._field("ssh_port", "22")
        self._test_btn = ttk.Button(body, text="测试 SSH 连接", command=self._test_ssh)
        self._test_btn.grid(row=self._row, column=1, sticky="w", padx=(6, 0), pady=1)
        self._test_lbl = ttk.Label(body, text="", font=F_SMALL, wraplength=340, justify="left")
        self._test_lbl.grid(row=self._row, column=2, sticky="w", padx=6)
        self._row += 1
        self._sec("② 本机 dsh")
        self._field("dash_repo", None)
        self._field("dash_port", None)
        self._field("dash_cmd", None)
        self._sec("③ 隧道参数")
        self._field("forward_ports", None)
        self._field("lab_server", None)
        self._field("lab_user", None)
        self._field("lab_port", None)
        self._field("reverse_port", None)
        self._sec("④ 轮询与超时")
        self._field("poll_seconds", None)
        self._field("remote_poll_seconds", None)
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="保存", command=self._on_save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        self.transient(self._master)
        self.grab_set()

    def _sec(self, title):
        ttk.Label(self._body, text=title, font=F_BOLD, foreground="#0af").grid(
            row=self._row, column=0, columnspan=3, sticky="w", pady=(11, 3))
        self._row += 1

    def _field(self, key, placeholder):
        body = self._body
        ttk.Label(body, text=self.LABELS[key] + ":").grid(row=self._row, column=0, sticky="w", pady=1)
        v = tk.StringVar()
        default = self._cfg.get(key)
        if key == "dash_cmd" and isinstance(default, list):
            default = " ".join(default)
        if placeholder and default in (None, ""):
            default = placeholder
        v.set(str(default if default is not None else ""))
        ent = ttk.Entry(body, textvariable=v, width=38)
        ent.grid(row=self._row, column=1, sticky="ew", padx=(6, 0), pady=1)
        self._vars[key] = v
        ttk.Label(body, text=self.HELP[key], font=F_SMALL, foreground="#888",
                  wraplength=420, justify="left").grid(
            row=self._row + 1, column=0, columnspan=3, sticky="w")
        self._row += 2

    def _apply(self, name):
        tpl = self.TEMPLATES.get(name)
        if not tpl:
            return
        for k, val in tpl.items():
            if k in self._vars:
                self._vars[k].set(val)

    def _test_ssh(self):
        host = self._vars["ssh_server"].get().strip()
        user = self._vars["ssh_user"].get().strip()
        port = self._vars["ssh_port"].get().strip() or "22"
        if not host or not user:
            self._test_lbl.configure(text="请先填服务器 IP 和用户名", foreground="#c33")
            return
        self._test_btn.configure(state="disabled")
        self._test_lbl.configure(text="测试中…", foreground="#888")

        def worker():
            try:
                import shutil
                ssh = shutil.which("ssh")
                if not ssh:
                    raise FileNotFoundError("ssh 不在 PATH 中")
                r = subprocess.run(
                    [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                     "-o", "StrictHostKeyChecking=accept-new",
                     "-p", port, user + "@" + host, "echo ok"],
                    capture_output=True, text=True, errors="replace", timeout=18,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                ok = r.returncode == 0
                if ok:
                    msg, col = "✅ SSH 连接成功, 免密可用", "#3c3"
                else:
                    err = (r.stderr or r.stdout or "").strip().replace("\n", " ")[:180]
                    msg, col = "❌ 失败 - 检查 IP/用户名/免密配置: " + err, "#c33"
            except Exception as e:
                msg, col = "测试异常: " + str(e)[:140], "#c33"
            self.after(0, lambda: (self._test_lbl.configure(text=msg, foreground=col),
                                   self._test_btn.configure(state="normal")))

        threading.Thread(target=worker, daemon=True).start()

    def _on_save(self):
        try:
            cfg = {}
            cfg["ssh_server"] = self._vars["ssh_server"].get().strip() or "YOUR_PUBLIC_IP"
            cfg["ssh_user"] = self._vars["ssh_user"].get().strip() or "tunnel"
            cfg["dash_repo"] = self._vars["dash_repo"].get().strip()
            cfg["dash_port"] = int(self._vars["dash_port"].get().strip())
            cfg["dash_cmd"] = self._vars["dash_cmd"].get().strip().split()
            # forward_ports 支持 "8090,8022,8091" 或 "[8090, 8022, 8091]" 两种写法
            _fp_raw = self._vars["forward_ports"].get().strip().strip("[]").replace(" ", "")
            cfg["forward_ports"] = [int(x) for x in _fp_raw.split(",") if x]
            cfg["poll_seconds"] = int(self._vars["poll_seconds"].get().strip())
            cfg["remote_poll_seconds"] = int(self._vars["remote_poll_seconds"].get().strip())
            cfg["lab_server"] = self._vars["lab_server"].get().strip()
            cfg["lab_user"] = self._vars["lab_user"].get().strip()
            lp = self._vars["lab_port"].get().strip()
            cfg["lab_port"] = int(lp) if lp else int(self._cfg.get("lab_port", 3090))
            rp = self._vars["reverse_port"].get().strip()
            cfg["reverse_port"] = int(rp) if rp else int(self._cfg.get("reverse_port", 8091))
        except ValueError:
            messagebox.showerror("输入错误", "端口/轮询间隔/端口列表必须为整数.", parent=self)
            return
        self.result = cfg
        self.destroy()


class InstallDialog(tk.Toplevel):
    # 辅助本地安装 dsh: 填仓库地址/目标目录 -> 环境预检 -> clone+安装+构建。
    # 安装命令在后台线程执行, 流式输出到主界面日志区。

    DEFAULT_URL = "https://github.com/deepseek-ai/deepseek-harness.git"

    def __init__(self, master):
        super().__init__(master)
        self._master = master
        self.title("安装 dsh")
        self.configure(padx=15, pady=12)
        self.result = None
        self._url = tk.StringVar(value=self.DEFAULT_URL)
        self._dir = tk.StringVar()
        self._env_lbl = None
        self._build()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="一键安装本机 dsh（无需求会提前提示）",
                  font=F_BOLD).pack(anchor="w", pady=(0, 4))
        # 仓库地址
        ttk.Label(wrap, text="dsh 仓库地址（git 克隆源）:").pack(anchor="w", pady=(6, 0))
        ttk.Entry(wrap, textvariable=self._url, width=64).pack(anchor="w", fill="x")
        ttk.Label(wrap, text="默认使用官方 deepseek-harness，可改成你自己的仓库。",
                  font=F_SMALL, foreground="#888").pack(anchor="w")
        # 目标目录
        ttk.Label(wrap, text="安装到的目标目录（如 C:/Users/你的名字/dsh）:").pack(anchor="w", pady=(10, 0))
        drow = ttk.Frame(wrap)
        drow.pack(anchor="w", fill="x")
        ttk.Entry(drow, textvariable=self._dir, width=54).pack(side="left", fill="x", expand=True)
        ttk.Button(drow, text="浏览…", command=self._browse_dir).pack(side="left", padx=4)
        ttk.Label(wrap, text="留空则默认安装到用户主目录下的 dsh 文件夹。",
                  font=F_SMALL, foreground="#888").pack(anchor="w")
        # 环境预检
        ttk.Label(wrap, text="环境预检:", font=F_BOLD).pack(anchor="w", pady=(12, 2))
        self._env_lbl = tk.Label(wrap, text="检查中…", font=F_SMALL, justify="left", anchor="w")
        self._env_lbl.pack(anchor="w", fill="x")
        # 按钮
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="开始安装", command=self._start).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)
        self.transient(self._master)
        self.grab_set()
        self._check_env()

    def _check_env(self):
        # 异步检查 git / node / npm / pnpm 是否可用。
        def worker():
            import shutil
            lines = []
            for tool in ("git", "node", "npm", "pnpm"):
                path = shutil.which(tool)
                status = "OK" if path else "缺失"
                lines.append(f"  {tool:5s}: {status}" + (f"  ({path})" if path else ""))
            text = "\n".join(lines)
            missing = [l.split(":")[0].strip() for l in lines if "缺失" in l]
            if missing:
                text += "\n\n⚠ 缺少: " + ", ".join(missing) + "  — 请先安装后再安装 dsh。"
            self.after(0, lambda: self._env_lbl.configure(text=text))
        threading.Thread(target=worker, daemon=True).start()

    def _browse_dir(self):
        from tkinter import filedialog
        start = self._dir.get().strip() or os.path.expanduser("~")
        chosen = filedialog.askdirectory(title="选择 dsh 安装目录", initialdir=start,
                                         parent=self)
        if chosen:
            self._dir.set(chosen)

    def _start(self):
        url = self._url.get().strip()
        target = self._dir.get().strip()
        if not url:
            messagebox.showerror("缺少仓库地址", "请填写 dsh 的 git 仓库地址。", parent=self)
            return
        # target 默认: 用户主目录/dsh
        target = target or os.path.join(os.path.expanduser("~"), "dsh")
        self.result = (url, target)
        self.destroy()
class EnvDialog(tk.Toplevel):
    # 独立"环境检查"窗口: 展示 git/node/npm/pnpm 版本与推荐基准,
    # 提供 更新/安装/卸载 操作(点击确认后执行)。

    TOOLS = [
        ("git",  "git",  ["git", "--version"]),
        ("node", "node", ["node", "--version"]),
        ("npm",  "npm",  ["npm.cmd", "--version"]),
        ("pnpm", "pnpm", ["pnpm.cmd", "--version"]),
    ]
    # 推荐基准版本(作者开发机实测可跑 dsh 的版本)
    RECOMMENDED = {
        "git":  "2.53",
        "node": "v24.19",
        "npm":  "11.17",
        "pnpm": "11.7",
    }
    # 每个工具的操作定义:
    #   install/uninstall: 安装/卸载引导
    #   update: 更新操作(可多条)
    #   每条: (类型, 内容, 描述)
    #   类型: cmd=执行命令 / browser=打开网页 / hint=仅提示
    OPS = {
        "git": dict(
            name="Git",
            install=[("browser", "https://git-scm.com/download/win", "打开官网下载 Git 安装包")],
            update=[("cmd", ["git", "update-git-for-windows"], "运行 Git 自带升级器 (git update-git-for-windows)")],
            uninstall=[("page", "ms-settings:appsfeatures", "打开 Windows 设置 - 应用 - 安装的应用，找到 Git 卸载")],
        ),
        "node": dict(
            name="Node.js",
            install=[("browser", "https://nodejs.org/zh-cn/download", "打开官网下载 Node.js LTS 安装包")],
            update=[("hint", "Node.js 无官方自升级命令。\n建议用 nvm-windows 管理版本, 或到官网 https://nodejs.org 下载新版安装包。")],
            uninstall=[("page", "ms-settings:appsfeatures", "打开 Windows 设置 - 应用 - 安装的应用，找到 Node.js 卸载")],
        ),
        "npm": dict(
            name="npm",
            install=[("hint", "npm 随 Node.js 一起安装, 装好 Node.js 即自带 npm。")],
            update=[("cmd", ["npm.cmd", "install", "-g", "npm@latest"], "npm install -g npm@latest")],
            uninstall=[("cmd", ["npm.cmd", "uninstall", "-g", "npm"], "npm uninstall -g npm（移除 npm 自身，Node.js 保留）")],
        ),
        "pnpm": dict(
            name="pnpm",
            install=[("cmd", ["npm.cmd", "install", "-g", "pnpm"], "npm install -g pnpm")],
            update=[("cmd", ["pnpm.cmd", "self-update"], "pnpm self-update（官方推荐的 pnpm 更新方式）")],
            uninstall=[("cmd", ["npm.cmd", "uninstall", "-g", "pnpm"], "npm uninstall -g pnpm（卸载全局 pnpm 包）")],
        ),
    }

    def __init__(self, master):
        # master 可以是 Dashboard 实例(推荐) 或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("环境检查")
        self.configure(padx=15, pady=12)
        self._rows = {}
        self._build()
        self.transient(tk_master)
        self.grab_set()
        self._refresh()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="开发环境检查（git / node / npm / pnpm）",
                  font=F_BOLD).pack(anchor="w", pady=(0, 6))
        table = ttk.Frame(wrap)
        table.pack(fill="x")
        for j, t in enumerate(("工具", "当前版本", "推荐基准", "状态", "操作")):
            ttk.Label(table, text=t, font=F_BOLD, width=11, anchor="w").grid(row=0, column=j, padx=2)
        for i, (key, name, _cmd) in enumerate(self.TOOLS):
            r = i + 1
            ttk.Label(table, text=name, width=11, anchor="w").grid(row=r, column=0, sticky="w", pady=2)
            ver = ttk.Label(table, text="...", width=11, anchor="w")
            ver.grid(row=r, column=1, sticky="w", padx=2)
            ttk.Label(table, text=self.RECOMMENDED.get(key, ""), width=14, anchor="w").grid(
                row=r, column=2, sticky="w", padx=2)
            status = ttk.Label(table, text="", width=8, anchor="w")
            status.grid(row=r, column=3, sticky="w", padx=2)
            ops = ttk.Frame(table)
            ops.grid(row=r, column=4, sticky="w", padx=2)
            ttk.Button(ops, text="更新", width=5,
                       command=lambda k=key: self._do_action(k, "update", "更新")).pack(side="left", padx=1)
            ttk.Button(ops, text="安装", width=5,
                       command=lambda k=key: self._do_action(k, "install", "安装")).pack(side="left", padx=1)
            ttk.Button(ops, text="卸载", width=5,
                       command=lambda k=key: self._do_action(k, "uninstall", "卸载")).pack(side="left", padx=1)
            self._rows[key] = (ver, status)
        ttk.Label(wrap, text="点“更新/安装/卸载”会先说明将执行什么, 确认后才执行。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(12, 0))
        ttk.Button(wrap, text="关闭", command=self.destroy).pack(anchor="e", pady=(12, 0))

    def _get_version(self, cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
            return (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else None
        except Exception:
            return None

    def _refresh(self):
        def worker():
            res = {}
            for key, _name, cmd in self.TOOLS:
                res[key] = self._get_version(cmd)
            try:
                self.after(0, lambda: self._apply(res))
            except tk.TclError:
                pass   # 窗口已关闭, 忽略
        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, res):
        for key, (ver_lbl, st_lbl) in self._rows.items():
            v = res.get(key)
            if v is None:
                ver_lbl.configure(text="未安装", foreground="#c33")
                st_lbl.configure(text="缺失", foreground="#c33")
            else:
                ver_lbl.configure(text=v, foreground="#000")
                st_lbl.configure(text="OK", foreground="#3c3")

    def _do_action(self, key, kind, label):
        ops = self.OPS.get(key)
        if ops is None:
            return
        name = ops["name"]
        plan = ops.get(kind) or []
        if not plan:
            return
        for typ, payload, desc in plan:
            ok = messagebox.askyesno(
                label + " " + name,
                "将执行：\n" + desc + "\n\n是否继续？",
                parent=self)
            if not ok:
                return
            if typ == "cmd":
                self._run_cmd(payload, desc)
            elif typ == "browser":
                self._open_url(payload)
            elif typ == "page":
                self._open_apps_page()
            elif typ == "hint":
                messagebox.showinfo(label + " " + name, payload, parent=self)

    def _run_cmd(self, cmd, desc):
        # 后台线程执行, 输出流式打到主界面日志区(复用 Dashboard._stream_cmd), 完成弹结果框。
        def worker():
            m = self._master
            use_stream = hasattr(m, "_stream_cmd") and hasattr(m, "log")
            if use_stream:
                m.log("[环境] " + desc + " 开始执行...", "warn")
                try:
                    env = None
                    if cmd and str(cmd[0]).lower().startswith("pnpm"):
                        # pnpm 要求全局 bin 目录在 PATH 中, 自动注入避免报错
                        env = dict(os.environ)
                        pnpm_bin = os.path.join(os.environ.get("LOCALAPPDATA", ""), "pnpm", "bin")
                        if pnpm_bin and pnpm_bin not in env.get("PATH", ""):
                            env["PATH"] = env.get("PATH", "") + os.pathsep + pnpm_bin
                    ok = m._stream_cmd(cmd, env=env)
                except Exception as e:
                    ok = False
                    m.log("  [环境] 执行异常: " + str(e), "err")
                try:
                    self.after(0, lambda: messagebox.showinfo(
                        "结果: " + desc, "已" + ("完成" if ok else "失败") + "（详见主界面日志区）", parent=self))
                except tk.TclError:
                    pass
            else:
                # 容错回退: 无主界面时用 subprocess 捕获
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                       timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
                    tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-600:]
                    head = "完成" if r.returncode == 0 else "失败 (code=%s)" % r.returncode
                    body = head + "\n\n" + tail
                    try:
                        self.after(0, lambda: messagebox.showinfo("结果: " + desc, body, parent=self))
                    except tk.TclError:
                        pass
                except Exception as e:
                    try:
                        self.after(0, lambda: messagebox.showerror("执行出错", str(e), parent=self))
                    except tk.TclError:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _open_url(self, url):
        try:
            os.startfile(url)
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)

    def _open_apps_page(self):
        try:
            os.startfile("ms-settings:appsfeatures")
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)
class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("dsh 控制台 · 隧道与健康监控  v" + APP_VERSION)
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
        self.DASH_REPO = DASH_REPO   # 供插件管理等页面取 dsh 仓库目录(cwd)
        self._build_ui()
        self._start_monitor()
        self.root.after(800, self._maybe_first_run)   # 首次启动引导(未配置时)

    # ── 首次启动引导 ──────────────────────────
    def _maybe_first_run(self):
        # 未配置(ssh_server 为空或占位符)时, 引导用户打开配置向导; 可跳过
        try:
            ssh_server = str(CONFIG.get("ssh_server") or "")
            unconfigured = (not ssh_server) or ssh_server.startswith("YOUR_")
            if not unconfigured:
                return
            ok = messagebox.askyesno(
                "欢迎使用 dsh-console-aio",
                "检测到尚未完成基础配置（服务器地址等）。\n\n"
                "是否现在打开【配置向导】？\n（也可以跳过，之后随时点顶部【配置】按钮）",
                parent=self.root)
            if ok:
                self._open_config()
        except Exception:
            pass   # 引导失败不影响主界面

    # ── UI ────────────────────────────────
    def _build_ui(self):
        pad = 10
        # ── 顶部栏: 标题 + 部署选择器 + 动作按钮 ──
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=pad, pady=(pad, 4))
        ttk.Label(top, text="dsh 控制台", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, text="  v" + APP_VERSION, font=F_SMALL, foreground="#888").pack(side="left")
        ttk.Label(top, text="   部署:").pack(side="left")
        self.deploy_var = tk.StringVar(value="本机")
        self.deploy_combo = ttk.Combobox(top, textvariable=self.deploy_var,
                                         state="readonly", width=14, font=F_SMALL)
        self.deploy_combo.pack(side="left", padx=(2, 8))
        self.deploy_combo.bind("<<ComboboxSelected>>", self._on_deploy_changed)
        ttk.Label(top, text=f"轮询 {POLL_SECONDS}s·{REMOTE_POLL_SECONDS}s",
                  font=F_SMALL, foreground="#666").pack(side="left")
        # 右侧按钮
        ttk.Button(top, text="立即刷新", command=self._force_refresh).pack(side="right")
        ttk.Button(top, text="配置", command=self._open_config).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="安装 dsh", command=self._open_install).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="环境", command=self._open_env).pack(side="right", padx=(0, 6))

        # ── 主体: 左导航 + 中栏页面 + 右状态 ──
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=pad, pady=4)
        navf = ttk.Frame(body)
        navf.pack(side="left", fill="y")
        self.nav_list = tk.Listbox(navf, width=13, font=F_SMALL, relief="flat",
                                   highlightthickness=1, activestyle="none")
        self.nav_list.pack(fill="both", expand=True)
        for _label, _key in NAV_ITEMS:
            self.nav_list.insert("end", _label)
        self.nav_list.bind("<<ListboxSelect>>", self._on_nav)
        # 中栏页面容器
        center = ttk.Frame(body)
        center.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.page_host = ttk.Frame(center)
        self.page_host.pack(fill="both", expand=True)
        # 右状态栏
        right = ttk.LabelFrame(body, text="状态", padding=6)
        right.pack(side="left", fill="y", padx=(6, 0))
        self.mon_widgets = {}
        ttk.Label(right, text="本机端口", font=F_BOLD, foreground="#555").pack(anchor="w")
        r1 = ttk.Frame(right)
        r1.pack(fill="x", pady=(2, 8))
        for port, label, note in LOCAL_PORTS:
            self._add_mon_cell(r1, "L" + str(port), label, "端口 " + str(port), note)
        ttk.Label(right, text="公网服务器 反向隧道", font=F_BOLD, foreground="#555").pack(anchor="w")
        r2 = ttk.Frame(right)
        r2.pack(fill="x", pady=(2, 4))
        for port, label, note in REMOTE_TUNNELS:
            self._add_mon_cell(r2, "R" + str(port), label, "端口 " + str(port), note)
        f = ttk.Frame(r2)
        f.pack(side="left", expand=True, fill="both", padx=4)
        d = tk.Label(f, text="●", font=("Segoe UI", 12), fg=COLOR_OFF)
        d.pack()
        ttk.Label(f, text="公网服务器 SSH", font=F_BOLD).pack()
        det = ttk.Label(f, text="--", font=F_SMALL, foreground="#888")
        det.pack()
        self.mon_widgets["公网服务器"] = (d, det)

        # ── 底部: 控制台输出 ──
        logf = ttk.LabelFrame(self.root, text="控制台输出", padding=4)
        logf.pack(fill="both", expand=True, padx=pad, pady=(4, 0))
        self.log_text = tk.Text(logf, height=7, wrap="word", font=F_MONO,
                                state="disabled", bg="#1e1e1e", fg="#e6e6e6")
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log_text.tag_configure("ok", foreground="#7ecb6a")
        self.log_text.tag_configure("err", foreground=COLOR_RED)
        self.log_text.tag_configure("warn", foreground=COLOR_WARN)

        self.status = ttk.Label(self.root, text="就绪", anchor="w",
                                font=F_SMALL, relief="sunken")
        self.status.pack(fill="x", side="bottom")

        # ── 部署列表 + 默认页 ──
        self._current_deploy = None
        self._current_page_key = None
        self._refresh_deploy_list()
        self._show_page("overview")


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

    # ── 导航与页面 ──────────────────────────
    def _on_nav(self, _evt=None):
        sel = self.nav_list.curselection()
        if not sel:
            return
        self._show_page(NAV_ITEMS[sel[0]][1])

    def _show_page(self, key):
        # 切换中栏页面: 销毁旧页面并构建新页面(总览内置, 其余动态加载 mgmt 模块 Page)
        for w in self.page_host.winfo_children():
            w.destroy()
        self._current_page_key = key
        if key == "overview":
            self._build_overview_page(self.page_host)
            return
        mod_name, cls_name = PAGE_MODULES.get(key, (None, None))
        if not mod_name:
            self.log("未知页面: " + str(key), "err")
            return
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            if key == "version":
                page = cls(self.page_host, self, APP_VERSION)
            else:
                page = cls(self.page_host, self)
            page.pack(fill="both", expand=True)
        except Exception as e:
            self.log("打开页面 " + str(key) + " 失败: " + str(e), "err")

    def _build_overview_page(self, parent):
        # 总览页: 隧道操控卡片 + 部署状态总览(健康状态在右侧栏)
        cards = ttk.LabelFrame(parent, text="操控", padding=8)
        cards.pack(fill="x", pady=(0, 6))
        self.cards = {}
        for i, cfg_item in enumerate(ITEMS):
            cards.columnconfigure(i, weight=1)
            self.cards[cfg_item["key"]] = self._build_card(cards, cfg_item, i)
        # 部署状态总览卡片
        depf = ttk.LabelFrame(parent, text="部署状态", padding=8)
        depf.pack(fill="x", pady=(0, 6))
        self.dep_status_lbl = ttk.Label(depf, text="加载中…", font=F_SMALL, foreground="#888")
        self.dep_status_lbl.pack(anchor="w")
        ttk.Button(depf, text="刷新部署状态", command=self._refresh_dep_status).pack(anchor="e")
        self._refresh_dep_status()
        ttk.Label(parent, text="隧道/健康状态见右侧状态栏；更多管理功能见左侧导航。",
                  font=F_SMALL, foreground="#888").pack(anchor="w")

    def _refresh_dep_status(self):
        # 后台线程汇总所有部署快照(本机 + deployments), 结果回主线程显示
        depls = [{"name": "本机", "host": ""}] + dsh_data.load_deployments()
        def worker():
            rows = []
            for d in depls:
                try:
                    snap = dsh_data.deployment_snapshot(dsh_data.DshRemote(d if d.get("host") else None))
                except Exception as e:
                    snap = {"ok": False, "error": str(e), "name": d.get("name")}
                rows.append(snap)
            try:
                self.root.after(0, lambda: self._dep_status_done(rows))
            except tk.TclError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _dep_status_done(self, rows):
        # 主线程更新部署状态标签
        try:
            parts = []
            for s in rows:
                name = s.get("name") or "?"
                if not s.get("ok"):
                    parts.append(name + ":离线")
                    continue
                parts.append("%s:v%s 会话%d 插件%d" % (
                    name, s.get("version") or "?",
                    s.get("sessions") or 0, s.get("plugins") or 0))
            self.dep_status_lbl.configure(text="   |  ".join(parts))
        except tk.TclError:
            pass   # 页面已切换

    # ── 部署选择器 ──────────────────────────
    def _refresh_deploy_list(self):
        self._deployments = [{"name": "本机", "host": ""}] + dsh_data.load_deployments()
        self.deploy_combo["values"] = [d.get("name") or "?" for d in self._deployments]
        self.deploy_var.set("本机")
        self._current_deploy = None

    def _on_deploy_changed(self, _evt=None):
        name = self.deploy_var.get()
        dep = None
        for d in self._deployments:
            if d.get("name") == name and d.get("host"):
                dep = d
                break
        self._current_deploy = dep
        self.log("切换部署: " + name + (" (" + dep.get("host") + ")" if dep else ""), "warn")
        if self._current_page_key:
            self._show_page(self._current_page_key)

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
                                 f"{path}\n不存在。请确认脚本与 dsh-console-aio.py 放在同一目录。")
            return
        self.log(f"[{cfg_item['key']}] 模式: {mode}", "warn")
        self.set_status(f"正在执行 {mode} → {os.path.basename(path)} ...")
        threading.Thread(target=self._run_ps1, args=(cfg_item, path, mode), daemon=True).start()

    # ── 本机 dsh ───────────────────────────
    def _run_dsh(self, mode):
        if mode == "start":
            self._dsh_start()
        elif mode == "restart":
            self._dsh_stop()
            self.log("  停止完成, 重新启动…", "warn")
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

    def _open_env(self):
        EnvDialog(self)
    # ── 安装 dsh ──────────────────────────
    def _open_install(self):
        dlg = InstallDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            url, target = dlg.result
            self.log(f"[安装 dsh] 目标: {target}  源: {url}", "warn")
            self.set_status("正在安装 dsh(clone+依赖+构建, 较久请耐心)...")
            threading.Thread(target=self._run_install, args=(url, target), daemon=True).start()

    def _run_install(self, url, target):
        import shutil
        # 0) 环境预检
        need = [t for t in ("git", "node", "npm", "pnpm") if not shutil.which(t)]
        if need:
            self.log(f"[安装] 缺少依赖: {', '.join(need)}", "err")
            self.log("  请先安装 Node.js(含 npm) 和 git; 然后 npm install -g pnpm", "warn")
            self.set_status("安装中止: 缺少依赖 " + ", ".join(need))
            return
        # 1) clone(完整克隆, 便于后续 update 的 git pull)
        if os.path.isdir(target) and os.listdir(target):
            self.log(f"[安装] 目录已存在且有内容, 跳过 clone: {target}", "warn")
        else:
            self.log("[安装] 步骤1/3: git clone ...", "warn")
            if not self._stream_cmd(["git", "clone", url, target]):
                self.set_status("安装失败: git clone")
                return
        # 2) install
        self.log("[安装] 步骤2/3: pnpm install", "warn")
        if not self._stream_cmd(["pnpm.cmd", "install"], cwd=target):
            self.set_status("安装失败: pnpm install")
            return
        # 3) build
        self.log("[安装] 步骤3/3: pnpm run build", "warn")
        if not self._stream_cmd(["pnpm.cmd", "run", "build"], cwd=target):
            self.set_status("安装失败: pnpm run build")
            return
        # 4) 写 config.dash_repo
        self.log(f"[安装] 完成! 目标目录: {target}", "ok")
        try:
            cfg = load_config()
            cfg["dash_repo"] = target
            if save_config(cfg):
                self.log("[安装] 已把 dash_repo 写入 config.json, 重启后生效。", "ok")
            else:
                self.log("[安装] 无法写 config.json(权限?), 请在配置向导里手动设置 dash_repo。", "warn")
        except Exception as e:
            self.log(f"[安装] 写 config 失败: {e}", "warn")
        self.set_status("dsh 安装完成 ✓ 重启后生效")

    def _stream_cmd(self, cmd, cwd=None, env=None):
        """流式运行命令, 输出逐行打进日志。返回 True/False。"""
        self.log("  $ " + " ".join(cmd))
        try:
            p = subprocess.Popen(
                cmd, cwd=cwd, env=env,
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
            # 在家正向: 本机 8090/8022/8091 -> 公网服务器 同端口
            forwards = [(p, "127.0.0.1", p) for p in FORWARD_PORTS]
            host, user, mode = SSH_SERVER, SSH_USER, "forward"
            watch = FORWARD_PORTS[0] if FORWARD_PORTS else None
        elif key == "connect-lab-dsh":
            # 实验室直连: 本机 3090 -> 实验室dsh 的 3090 (局域网, 不经 公网服务器)
            forwards = [(LAB_PORT, "127.0.0.1", LAB_PORT)]
            host, user, mode = LAB_SERVER, LAB_USER, "forward"
            watch = LAB_PORT
        elif key == "dsh-tunnel-reverse":
            # 本机 -> 公网服务器 反向: 公网服务器 的 reverse_port -> 本机 dsh
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
        results["公网服务器"] = tcp_ok(SSH_SERVER, 22)
        ssh_count = ssh_proc_count()
        # 后台线程预计算隧道状态(端口探测/读PID), 主线程 apply 只做 UI 更新(防阻塞)
        py_state = {}
        cards = getattr(self, "cards", {}) or {}
        for key, card in cards.items():
            cfg_item = card.get("cfg") or {}
            port = cfg_item.get("port")
            if port is None or port < 0:
                py_state[key] = False
            elif cfg_item.get("backend") == "python":
                try:
                    t = self._build_tunnel(cfg_item)
                    py_state[key] = t.is_running()
                except Exception:
                    py_state[key] = False
        self._render(results, ssh_count, py_state)

    def _remote_tick(self):
        state = probe_remote_tunnels()
        self.remote_state = state
        self._render_remote(state)

    def _render(self, results, ssh_count, py_state=None):
        # 本机端口健康（不含 公网服务器 公网连通, 概念分开）
        local_ok = [port for port, (ok, _) in results.items()
                    if port != "公网服务器" and ok]
        local_total = len(LOCAL_PORTS)
        ssh_ok = results.get("公网服务器", (False, -1))[0]
        ssh_txt = "公网服务器 在线" if ssh_ok else "公网服务器 不可达"
        summary = (f"本机端口 {len(local_ok)}/{local_total} · {ssh_txt}"
                   f" · ssh.exe {ssh_count if ssh_count >= 0 else '?'}")
        def apply():
            try:
                self._render_apply(results, ssh_count, py_state, summary)
            except tk.TclError:
                pass   # 页面已切换/窗口关闭, 卡片销毁, 忽略
        self.root.after(0, apply)

    def _render_apply(self, results, ssh_count, py_state, summary):
        # 主线程 UI 更新(无 IO): 监控点 + 卡片 + 状态栏
        for port, (ok, dt) in results.items():
            if port == "公网服务器":
                dot, det = self.mon_widgets["公网服务器"]
                dot.configure(fg=COLOR_ON if ok else COLOR_RED)
                det.configure(text="在线" if ok else "不可达")
                continue
            key = "L" + str(port)
            if key not in self.mon_widgets:
                continue
            dot, det = self.mon_widgets[key]
            dot.configure(fg=COLOR_ON if ok else COLOR_RED)
            det.configure(text=str(dt) + "ms" if ok else "未就绪")
        cards = getattr(self, "cards", {}) or {}
        for key, card in cards.items():
            cfg_item = card.get("cfg") or {}
            port = cfg_item.get("port")
            if port is None or port < 0:
                card["st"].configure(text="○ 空闲", fg=COLOR_OFF)
                continue
            if cfg_item.get("backend") == "python":
                on = bool((py_state or {}).get(key))
            elif port:
                on = port in results and results[port][0]
            else:
                on = ssh_count > 0
            card["st"].configure(text="● 运行中" if on else "○ 停止",
                                 fg=COLOR_ON if on else COLOR_OFF)
        self.status.configure(text=summary)

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
