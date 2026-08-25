# -*- coding: utf-8 -*-
# mgmt_version.py — 版本管理: 当前版本/检查更新/更新日志/一键自动更新。
# 提供 VersionPage(ttk.Frame 内嵌页面) 与 VersionDialog(Toplevel 兼容包装)。
import os
import sys
import json
import time
import io
import urllib.request
import threading
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, messagebox

# 与主程序一致的风格常量(独立模块自带)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

GITHUB_RAW = "https://raw.githubusercontent.com/JimyuAn-98/dsh-console-aio/main/"
GITHUB_ZIP = "https://codeload.github.com/JimyuAn-98/dsh-console-aio/zip/refs/heads/main"
VERSION_URL = GITHUB_RAW + "version.json"
RELEASE_URL = GITHUB_RAW + "RELEASE_NOTES.md"

# 更新时保留的本地文件(用户数据/配置, 不替换)
KEEP_FILES = {"config.json", "dsh使用指南.txt", "tunnel-pids.json"}


def _cmp_ver(a, b):
    # 版本号 "x.y.z" 比较, 返回 -1/0/1
    def t(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except ValueError:
            return (0,)
    x, y = t(a), t(b)
    return (x > y) - (x < y)


def _fetch(url, timeout=15):
    # 下载文本(utf-8), 失败抛异常
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _base_dir():
    # 程序所在目录: 打包(exe)后为 exe 目录, 源码模式为脚本目录
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    # 打包资源目录: onefile 下资源在 _MEIPASS(临时解压), 源码模式为脚本目录
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class VersionPage(ttk.Frame):
    # 版本管理内嵌页面: parent=容器 Frame, app=Dashboard 实例, version=当前 APP_VERSION。
    # 检查更新/更新日志/一键更新逻辑与原 VersionDialog 完全一致;
    # 窗口级职责(标题/transient/grab_set)交给外层 Toplevel。

    def __init__(self, parent, app, version):
        super().__init__(parent)
        self._app = app
        self._master = app   # 兼容原 self._master 用法(页面内按需访问)
        self._version = version
        self._latest = None       # 最新版本号或 None
        self._latest_notes = ""
        self._build()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="dsh-console-aio · 版本管理", font=F_BOLD).pack(anchor="w", pady=(0, 6))
        # 版本信息
        info = ttk.Frame(wrap)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, text="当前版本:", width=10).grid(row=0, column=0, sticky="w")
        self._cur_lbl = ttk.Label(info, text="v" + self._version, font=F_BOLD)
        self._cur_lbl.grid(row=0, column=1, sticky="w")
        ttk.Label(info, text="最新版本:", width=10).grid(row=1, column=0, sticky="w")
        self._latest_lbl = ttk.Label(info, text="(未检查)", foreground="#888")
        self._latest_lbl.grid(row=1, column=1, sticky="w")
        ttk.Label(info, text="状态:", width=10).grid(row=2, column=0, sticky="w")
        self._status_lbl = ttk.Label(info, text="", foreground="#3c3")
        self._status_lbl.grid(row=2, column=1, sticky="w")
        # 按钮
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="检查更新", command=self._check).pack(side="left", padx=2)
        self._update_btn = ttk.Button(btns, text="一键更新", command=self._update, state="disabled")
        self._update_btn.pack(side="left", padx=2)
        ttk.Button(btns, text="打开 GitHub", command=self._open_github).pack(side="left", padx=2)
        # 更新日志
        ttk.Label(wrap, text="更新日志:", font=F_BOLD).pack(anchor="w")
        log_frame = ttk.Frame(wrap)
        log_frame.pack(fill="both", expand=True)
        self._log_text = tk.Text(log_frame, height=14, wrap="none",
                                 font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._load_local_log()

    def _load_local_log(self):
        # 本地 RELEASE_NOTES.md 展示(离线可用)
        base = _resource_dir()
        p = os.path.join(base, "RELEASE_NOTES.md")
        try:
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = "(未找到 RELEASE_NOTES.md)"
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("1.0", text)
        self._log_text.configure(state="disabled")

    def _set_status(self, text, color="#888"):
        self._status_lbl.configure(text=text, foreground=color)

    def _check(self):
        # 后台线程拉远程 version.json
        self._set_status("正在检查…")
        self._check_btn = None
        def worker():
            try:
                data = json.loads(_fetch(VERSION_URL))
                latest = str(data.get("version") or "")
                notes = str(data.get("notes") or "")
                self.after(0, lambda: self._check_done(latest, notes))
            except Exception as e:
                self.after(0, lambda: self._check_fail(str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _check_done(self, latest, notes):
        self._latest = latest
        self._latest_notes = notes
        self._latest_lbl.configure(text="v" + latest, foreground="#000")
        cmpv = _cmp_ver(latest, self._version)
        if cmpv > 0:
            self._set_status("发现新版本 v" + latest + "!", "#c60")
            self._update_btn.configure(state="normal")
        elif cmpv == 0:
            self._set_status("已是最新版本", "#3c3")
            self._update_btn.configure(state="disabled")
        else:
            self._set_status("当前版本高于远程(可能为开发版)", "#888")
            self._update_btn.configure(state="disabled")

    def _check_fail(self, err):
        self._set_status("检查失败: " + err, "#c33")

    def _update(self):
        if not self._latest:
            return
        if getattr(sys, "frozen", False):
            # 打包(exe)版: 更新 = 下载并运行新安装包(MSI/exe, 天然支持升级安装)
            ok = messagebox.askyesno(
                "检查到新版本 v" + self._latest,
                "当前为安装版。\n将打开 GitHub Releases 页面下载新安装包，\n下载后运行安装器即可完成升级(配置与数据保留)。\n\n是否打开下载页？",
                parent=self)
            if ok:
                self._open_releases()
            return
        ok = messagebox.askyesno(
            "一键更新",
            "将执行：\n1. 下载 v" + self._latest + " 更新包(GitHub)\n"
            "2. 解压并替换程序文件(自动备份旧文件, config.json 等本地配置保留)\n"
            "3. 重启 dsh-console-aio\n\n是否继续？",
            parent=self)
        if not ok:
            return
        self._update_btn.configure(state="disabled")
        self._set_status("正在下载更新…")
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        # 下载 zip -> 解压 -> 备份 -> 替换 -> 重启
        base = _base_dir()
        tmp = os.path.join(os.environ.get("TEMP", "."), "dsh-aio-update")
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp, exist_ok=True)
            zip_path = os.path.join(tmp, "update.zip")
            self.after(0, lambda: self._set_status("下载中(约几百 KB~几 MB)…"))
            urllib.request.urlretrieve(GITHUB_ZIP, zip_path)
            self.after(0, lambda: self._set_status("解压中…"))
            extract = os.path.join(tmp, "x")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extract)
            # zip 顶层目录: dsh-console-aio-main/
            roots = [d for d in os.listdir(extract)
                     if os.path.isdir(os.path.join(extract, d))]
            src = os.path.join(extract, roots[0]) if roots else extract
            # 备份旧文件 + 替换
            bak = os.path.join(tmp, "backup")
            os.makedirs(bak, exist_ok=True)
            replaced = 0
            for fn in os.listdir(src):
                if fn in KEEP_FILES or fn == ".git":
                    continue
                s = os.path.join(src, fn)
                d = os.path.join(base, fn)
                if os.path.isfile(s):
                    if os.path.exists(d):
                        shutil.copy2(d, os.path.join(bak, fn))
                    shutil.copy2(s, d)
                    replaced += 1
            self.after(0, lambda: self._update_done(replaced, bak))
        except Exception as e:
            self.after(0, lambda: self._update_fail(str(e)))

    def _update_done(self, replaced, bak):
        self._set_status("更新完成(" + str(replaced) + " 个文件), 正在重启…", "#3c3")
        messagebox.showinfo("更新完成",
                            "已更新 " + str(replaced) + " 个文件。\n"
                            "旧文件备份在: " + bak + "\n\n将自动重启程序。", parent=self)
        self._restart()

    def _update_fail(self, err):
        self._set_status("更新失败: " + err, "#c33")
        self._update_btn.configure(state="normal")
        messagebox.showerror("更新失败", "更新未完成，程序未改动。\n错误: " + err, parent=self)

    def _restart(self):
        # 重启程序: 打包(exe)后直接重启 exe; 源码模式用解释器重启脚本。
        # 页面本身不销毁, 关闭的是承载它的外层 Toplevel。
        base = _base_dir()
        try:
            subprocess = __import__("subprocess")
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable], cwd=base,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                main = os.path.join(base, "dsh-console-aio.py")
                subprocess.Popen([sys.executable, main], cwd=base,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
        try:
            self.winfo_toplevel().destroy()
        except tk.TclError:
            pass

    def _open_releases(self):
        try:
            os.startfile("https://github.com/JimyuAn-98/dsh-console-aio/releases")
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)

    def _open_github(self):
        try:
            os.startfile("https://github.com/JimyuAn-98/dsh-console-aio")
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)


class VersionDialog(tk.Toplevel):
    # 兼容包装: 保持原 Toplevel 入口(master 兼容 Dashboard / Tk root), 内部内嵌 VersionPage。
    # 窗口级职责(标题/transient/grab_set)只在这里, 页面不含。
    def __init__(self, master, version):
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
            app = master
        else:
            tk_master = master
            self._master = None
            app = None
        super().__init__(tk_master)
        self.title("关于与更新")
        self.configure(padx=15, pady=12)
        self._page = VersionPage(self, app, version)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
