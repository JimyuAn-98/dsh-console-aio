# -*- coding: utf-8 -*-
# mgmt_ops.py — 备份与运维管理(页面化): OpsPage 嵌入主界面, OpsDialog 兼容包装
# 备份 ~/.dsh 到 zip(数据层自动排除凭据/密钥/sessions/node_modules)、
# 查看 dsh web 日志(目录/尾部)、凭据文件只提示存在性与时间(不明文展示)。

import os
import time
import threading
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import dsh_data

# 风格常量与主程序 dsh-console-aio.py 顶部保持一致(文件含连字符无法常规 import)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 9)

TAIL_BYTES = 16384   # 查看日志尾部最多读取的字节数


def _fmt_size(n):
    # 字节数转人类可读文本(B/KB/MB/GB)
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, unit)
        n /= 1024.0


class OpsPage(ttk.Frame):
    # 备份/日志/凭据三个运维分区, 均不触碰密钥明文。
    # parent=容器 Frame, app=Dashboard 实例(可为 None); 页面高度随容器自适应, 不设窗口尺寸。
    def __init__(self, parent, app):
        super().__init__(parent, padding=(15, 12))
        self._app = app
        # dsh web 日志目录固定为 %TEMP%/dsh-dash
        self._log_dir = os.path.join(os.environ.get("TEMP") or tempfile.gettempdir(), "dsh-dash")
        self._build()
        self._refresh_logs()
        self._refresh_cred()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)

        bak = ttk.LabelFrame(wrap, text="备份", padding=8)
        bak.pack(fill="x", pady=(0, 6))
        ttk.Label(bak, text="一键备份 ~/.dsh 到 zip。自动排除：凭据/密钥文件、sessions、node_modules。",
                  font=F_SMALL, foreground="#888").pack(anchor="w")
        row = ttk.Frame(bak)
        row.pack(fill="x", pady=(6, 0))
        self._backup_btn = ttk.Button(row, text="备份 ~/.dsh…", command=self._do_backup)
        self._backup_btn.pack(side="left")
        self._backup_lbl = ttk.Label(row, text="", font=F_SMALL)
        self._backup_lbl.pack(side="left", padx=(10, 0))

        logs = ttk.LabelFrame(wrap, text="dsh web 日志", padding=8)
        logs.pack(fill="both", expand=True, pady=(0, 6))
        cols = ("file", "size", "mtime")
        self._tree = ttk.Treeview(logs, columns=cols, show="headings", height=6)
        self._tree.heading("file", text="文件")
        self._tree.heading("size", text="大小")
        self._tree.heading("mtime", text="最后修改")
        self._tree.column("file", width=300, anchor="w")
        self._tree.column("size", width=90, anchor="e")
        self._tree.column("mtime", width=150, anchor="w")
        sb = ttk.Scrollbar(logs, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ops = ttk.Frame(logs)
        ops.pack(fill="x", pady=(6, 0))
        ttk.Button(ops, text="刷新", command=self._refresh_logs).pack(side="left", padx=(0, 4))
        ttk.Button(ops, text="打开目录", command=self._open_log_dir).pack(side="left", padx=4)
        ttk.Button(ops, text="查看尾部", command=self._view_tail).pack(side="left", padx=4)

        cred = ttk.LabelFrame(wrap, text="凭据（只提示存在性，不明文展示）", padding=8)
        cred.pack(fill="x")
        self._cred_lbl = ttk.Label(cred, text="", font=F_SMALL, justify="left")
        self._cred_lbl.pack(anchor="w")
        ttk.Label(cred,
                  text="安全说明：.credentials.yaml 与 apiKeyEnv 引用的密钥只保存在系统环境变量中，\n"
                       "控制台不读取、不写入、不展示密钥明文。",
                  font=F_SMALL, foreground="#888", justify="left").pack(anchor="w", pady=(6, 0))

        # 页面无"关闭"按钮: 页面随容器销毁, 关闭是外层 Toplevel 的事

    def _refresh_logs(self):
        # 列出 %TEMP%/dsh-dash/*.log 的文件名/大小/修改时间
        for i in self._tree.get_children():
            self._tree.delete(i)
        if not os.path.isdir(self._log_dir):
            return
        try:
            names = sorted(os.listdir(self._log_dir))
        except OSError:
            return
        for fn in names:
            if not fn.lower().endswith(".log"):
                continue
            fp = os.path.join(self._log_dir, fn)
            if not os.path.isfile(fp):
                continue
            try:
                st = os.stat(fp)
            except OSError:
                continue
            mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
            self._tree.insert("", "end", values=(fn, _fmt_size(st.st_size), mtime))

    def _open_log_dir(self):
        # 用资源管理器打开日志目录
        if not os.path.isdir(self._log_dir):
            messagebox.showinfo("提示", "日志目录不存在：\n%s" % self._log_dir, parent=self)
            return
        try:
            os.startfile(self._log_dir)
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)

    def _view_tail(self):
        # 弹出只读窗口显示所选日志的尾部内容
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一个日志文件。", parent=self)
            return
        fn = self._tree.item(sel[0], "values")[0]
        path = os.path.join(self._log_dir, fn)
        try:
            body = self._read_tail(path)
        except OSError as e:
            body = "读取失败：%s" % e
        dlg = tk.Toplevel(self)
        dlg.title("日志尾部 - %s" % fn)
        dlg.geometry("680x380")
        txt = tk.Text(dlg, wrap="none", font=F_MONO, bg="#1e1e1e", fg="#e6e6e6",
                      state="disabled", padx=6, pady=6)
        sb = ttk.Scrollbar(dlg, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        txt.configure(state="normal")
        txt.insert("1.0", body)
        txt.configure(state="disabled")
        ttk.Button(dlg, text="关闭", command=dlg.destroy).pack(anchor="e", padx=8, pady=6)

    def _read_tail(self, path, limit=TAIL_BYTES):
        # 从文件尾部读最多 limit 字节, 避免大文件整读; 截断时丢弃首行残余半行
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - limit)
            fh.seek(start)
            data = fh.read()
        text = data.decode("utf-8", errors="replace")
        # 统一换行符, 避免 Windows 日志的 \r 残留显示
        text = text.replace("\r\n", "\n")
        if start > 0:
            nl = text.find("\n")
            if nl >= 0:
                text = text[nl + 1:]
        return text

    def _do_backup(self):
        # 选 zip 路径 -> 确认 -> 后台线程备份, 完成后回主线程提示文件数与大小
        default_name = "dsh-backup-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        path = filedialog.asksaveasfilename(
            parent=self, title="选择备份文件", defaultextension=".zip",
            initialfile=default_name, filetypes=[("Zip 压缩包", "*.zip")])
        if not path:
            return
        if not messagebox.askyesno(
                "确认备份",
                "将把 ~/.dsh 备份到：\n%s\n\n自动排除：凭据/密钥文件、sessions、node_modules。\n是否继续？" % path,
                parent=self):
            return
        self._backup_btn.configure(state="disabled")
        self._backup_lbl.configure(text="备份中…", foreground="#888")

        def worker():
            try:
                count = dsh_data.backup_dsh_home(path)
                size = os.path.getsize(path)
            except Exception as e:
                err = str(e)

                def fail():
                    # 页面可能已随容器销毁, TclError 忽略
                    try:
                        self._backup_btn.configure(state="normal")
                        self._backup_lbl.configure(text="备份失败", foreground="#c33")
                        messagebox.showerror("备份失败", err, parent=self)
                    except tk.TclError:
                        pass

                try:
                    self.after(0, fail)
                except tk.TclError:
                    pass
                return

            def done():
                try:
                    self._backup_btn.configure(state="normal")
                    self._backup_lbl.configure(text="完成：%d 个文件，%s" % (count, _fmt_size(size)),
                                               foreground="#3c3")
                    messagebox.showinfo("备份完成",
                                        "已备份 %d 个文件，大小 %s。\n%s"
                                        % (count, _fmt_size(size), path),
                                        parent=self)
                except tk.TclError:
                    pass

            try:
                self.after(0, done)
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_cred(self):
        # 凭据文件只显示存在性与最后修改时间, 不明文展示内容
        home = dsh_data.dsh_home()
        lines = []
        p1 = os.path.join(home, ".credentials.yaml")
        if os.path.isfile(p1):
            try:
                t1 = time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.localtime(os.path.getmtime(p1)))
            except OSError:
                t1 = "?"
            lines.append(".credentials.yaml：存在（最后修改 %s，内容不明文展示）" % t1)
        else:
            lines.append(".credentials.yaml：不存在")
        p2 = os.path.join(home, ".anonymous-user-id")
        if os.path.isfile(p2):
            lines.append(".anonymous-user-id：存在")
        else:
            lines.append(".anonymous-user-id：不存在")
        self._cred_lbl.configure(text="\n".join(lines))


class OpsDialog(tk.Toplevel):
    # 兼容包装: 内容由 OpsPage 提供, 保留原 Toplevel 的窗口行为(标题/尺寸/transient/grab_set)
    def __init__(self, master):
        # master 兼容 Dashboard 实例(推荐)或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self._master = app
        self.title("备份与运维")
        self.geometry("640x500")
        self.minsize(600, 460)
        self._page = OpsPage(self, app)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
