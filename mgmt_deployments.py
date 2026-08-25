# -*- coding: utf-8 -*-
# mgmt_deployments.py — 部署管理: v0.4 多部署管理。
# 提供 DeploymentPage(ttk.Frame 内嵌页面) 与 DeploymentDialog(Toplevel 兼容包装)。
# 部署清单只存本地 config.json(gitignored); 远程操作为只读(cat/ls/du/echo),
# 写操作(安装/升级/配置)留待后续版本。
# 数据层接口: dsh_data.load_deployments() / save_deployments() / DshRemote / deployment_snapshot()。

import threading
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 风格常量与主程序 dsh-console-aio.py 顶部保持一致(文件含连字符无法常规 import)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

_LOCAL_NAME = "本机"


def _human_size(n):
    # 字节数人性化: B / KB / MB / GB(会话大小展示用)
    n = int(n or 0)
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    if n < 1024 * 1024 * 1024:
        return "%.1f MB" % (n / 1024.0 / 1024.0)
    return "%.1f GB" % (n / 1024.0 / 1024.0 / 1024.0)


class _AddDeployDialog(tk.Toplevel):
    # 添加部署的小对话框: 名称/主机/user/端口(默认22)/dsh_home(默认~/.dsh)
    def __init__(self, parent):
        super().__init__(parent)
        self.title("添加部署")
        self.geometry("420x280")
        self.resizable(False, False)
        self.configure(padx=14, pady=12)
        self._parent = parent
        self.result = None
        self._name_var = tk.StringVar()
        self._host_var = tk.StringVar()
        self._user_var = tk.StringVar()
        self._port_var = tk.StringVar(value="22")
        self._home_var = tk.StringVar(value="~/.dsh")
        self._build()
        self.transient(parent)
        self.grab_set()
        self._name_entry.focus_set()

    def _build(self):
        ttk.Label(self, text="添加远程部署", font=F_BOLD).pack(anchor="w")
        ttk.Label(self, text="部署信息只写本地 config.json（自动备份 .bak），不会连接远程。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(2, 8))
        form = ttk.Frame(self)
        form.pack(fill="x")
        fields = (
            ("name", "名称", self._name_var),
            ("host", "主机", self._host_var),
            ("user", "user", self._user_var),
            ("port", "端口", self._port_var),
            ("dsh_home", "dsh_home", self._home_var),
        )
        for i, (_key, label, var) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ent = ttk.Entry(form, textvariable=var, width=32)
            ent.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=3)
            if _key == "name":
                self._name_entry = ent
        form.columnconfigure(1, weight=1)
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="保存", command=self._confirm).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _confirm(self):
        # 校验并组装部署 dict; 通过后写入 result 并关窗(父窗口负责保存)
        name = self._name_var.get().strip()
        host = self._host_var.get().strip()
        user = self._user_var.get().strip()
        port_s = self._port_var.get().strip() or "22"
        home = self._home_var.get().strip() or "~/.dsh"
        if not name:
            messagebox.showerror("缺少名称", "请填写部署名称。", parent=self)
            return
        if not host:
            messagebox.showerror("缺少主机", "请填写主机地址(IP 或域名)。", parent=self)
            return
        if not user:
            messagebox.showerror("缺少用户", "请填写 SSH 用户名。", parent=self)
            return
        try:
            port = int(port_s)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("端口无效", "端口必须是 1-65535 的整数。", parent=self)
            return
        # 同主机同用户重复添加会让人混淆, 直接拦截
        for d in self._parent._deployments:
            if d.get("host") == host and d.get("user") == user and int(d.get("port") or 22) == port:
                messagebox.showerror("主机已存在", "已存在同主机/同用户/同端口的部署「%s」。" % d.get("name"),
                                     parent=self)
                return
        self.result = {"name": name, "host": host, "user": user,
                       "port": port, "dsh_home": home}
        self.destroy()


class DeploymentPage(ttk.Frame):
    # 部署管理内嵌页面: 上半区部署列表(本机 + config.json deployments),
    # 下半区选中部署的只读快照详情。parent=容器 Frame, app=Dashboard 实例。
    # CRUD/快照刷新逻辑与原 DeploymentDialog 完全一致;
    # 窗口级职责(标题/geometry/transient/grab_set)交给外层 Toplevel。

    # 详情区字段: (快照键, 界面名)
    _FIELDS = (
        ("name", "名称"),
        ("host", "主机"),
        ("version", "版本"),
        ("sessions", "会话数"),
        ("size", "会话大小"),
        ("plugins", "插件数"),
        ("profiles", "profile 数"),
        ("presets", "agent 预设数"),
        ("error", "错误信息"),
    )

    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app
        self._master = app   # 兼容原 self._master 用法(页面内按需访问)
        self._deployments = []
        self._rows = []          # [{"iid", "deployment", "snap", "dep_index", "gen"}], 与 Treeview 行一一对应
        self._gen = 0            # 列表重建代数, 用于丢弃过期快照回调
        self._pending = 0        # 刷新总览的进行中线程数
        self._tree = None
        self._del_btn = None
        self._test_btn = None
        self._refresh_btn = None
        self._status_lbl = None
        self._detail_lbls = {}
        self._build()
        self._load()

    # ── UI 构建 ──────────────────────────────
    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        wrap = ttk.Frame(self)
        wrap.grid(row=0, column=0, sticky="nsew")

        ttk.Label(wrap, text="部署管理（多部署只读总览）", font=F_BOLD).pack(anchor="w")
        ttk.Label(wrap, text="部署信息只存本地 config.json；远程只读操作，写操作后续版本提供。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(2, 6))

        # ── 上半区: 部署列表 ──
        top = ttk.LabelFrame(wrap, text="部署列表", padding=6)
        top.pack(fill="both", expand=True, pady=(0, 6))
        cols = ("name", "host", "status")
        self._tree = ttk.Treeview(top, columns=cols, show="headings", height=8, selectmode="browse")
        for col, title, width, anchor in (("name", "名称", 220, "w"),
                                          ("host", "主机", 240, "w"),
                                          ("status", "状态", 100, "center")):
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, anchor=anchor)
        self._tree.tag_configure("ok", foreground="#1a7f37")
        self._tree.tag_configure("err", foreground="#c33")
        self._tree.tag_configure("none", foreground="#888")
        sb = ttk.Scrollbar(top, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="添加部署", command=self._add_deployment).pack(side="left", padx=(0, 4))
        self._del_btn = ttk.Button(btns, text="删除部署", command=self._delete_deployment, state="disabled")
        self._del_btn.pack(side="left", padx=4)
        self._test_btn = ttk.Button(btns, text="测试连接", command=self._test_connection, state="disabled")
        self._test_btn.pack(side="left", padx=4)
        self._refresh_btn = ttk.Button(btns, text="刷新总览", command=self._refresh_all)
        self._refresh_btn.pack(side="left", padx=4)
        ttk.Label(btns, text="本机不可删除；状态来自 deployment_snapshot(在线/离线/未测试)",
                  font=F_SMALL, foreground="#888").pack(side="left", padx=10)

        # ── 下半区: 选中部署详情 ──
        detail = ttk.LabelFrame(wrap, text="部署详情（只读）", padding=8)
        detail.pack(fill="x")
        grid = ttk.Frame(detail)
        grid.pack(fill="x")
        for i, (_key, label) in enumerate(self._FIELDS):
            ttk.Label(grid, text=label, font=F_BOLD).grid(row=i, column=0, sticky="nw", pady=1)
            val = ttk.Label(grid, text="-", wraplength=420, justify="left")
            val.grid(row=i, column=1, sticky="w", padx=(10, 0), pady=1)
            self._detail_lbls[_key] = val

        # ── 底部状态行 ──
        self._status_lbl = ttk.Label(wrap, text="", font=F_SMALL, foreground="#888")
        self._status_lbl.pack(fill="x", pady=(8, 0))

    # ── 数据加载与列表渲染 ──────────────────────
    def _load(self):
        # 读 config.json 的 deployments; "本机"始终作为第一行(DshRemote(None))
        try:
            self._deployments = dsh_data.load_deployments() or []
        except Exception:
            self._deployments = []
        self._render_rows()

    def _render_rows(self):
        # 重建 Treeview: 第 0 行本机, 其后为 config 里的每个部署
        if self._tree is None:
            return
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._gen += 1
        self._pending = 0   # 列表重建后旧刷新线程的过期回调不再计数
        if self._refresh_btn is not None:
            self._refresh_btn.configure(state="normal")
        self._rows = []
        rows = [(None, _LOCAL_NAME, "本地")] + [
            (d, d.get("name") or d.get("host") or "-", d.get("host") or "-")
            for d in self._deployments
        ]
        for idx, (dep, name, host) in enumerate(rows):
            iid = "local" if idx == 0 else "dep_%d" % (idx - 1)
            row = {"iid": iid, "deployment": dep, "snap": None,
                   "dep_index": idx - 1, "gen": self._gen}
            self._tree.insert("", "end", iid=iid, values=(name, host, "未测试"), tags=("none",))
            self._rows.append(row)
        self._fill_detail(None)

    def _selected_row(self):
        # 当前选中行对应的 row dict; 未选中返回 None
        sel = self._tree.selection()
        if not sel:
            return None
        for row in self._rows:
            if row["iid"] == sel[0]:
                return row
        return None

    # ── 选择与详情 ─────────────────────────────
    def _on_select(self, _event=None):
        row = self._selected_row()
        self._fill_detail(row)
        is_local = row is not None and row["deployment"] is None
        if self._del_btn is not None:
            self._del_btn.configure(state="disabled" if (row is None or is_local) else "normal")
        if self._test_btn is not None:
            self._test_btn.configure(state="disabled" if (row is None or is_local) else "normal")

    def _fill_detail(self, row):
        # 只读展示快照字段; 未选中或未测过时用占位符
        if row is None:
            for key in self._detail_lbls:
                self._detail_lbls[key].configure(text="-")
            return
        dep = row["deployment"]
        snap = row["snap"]
        local = dep is None
        name = _LOCAL_NAME if local else (dep.get("name") or dep.get("host") or "-")
        host = "本地" if local else (dep.get("host") or "-")
        if snap is None:
            vals = {"name": name, "host": host,
                    "version": "-", "sessions": "-", "size": "-",
                    "plugins": "-", "profiles": "-", "presets": "-",
                    "error": "未测试（点“刷新总览”获取）"}
        else:
            vals = {
                "name": name,
                "host": host,
                "version": snap.get("version") or "-",
                "sessions": str(snap.get("sessions") or 0),
                "size": _human_size(snap.get("session_bytes")),
                "plugins": str(snap.get("plugins") or 0),
                "profiles": str(snap.get("profiles") or 0),
                "presets": str(snap.get("presets") or 0),
                "error": "无" if snap.get("ok") else (snap.get("error") or "未知错误"),
            }
        for key, text in vals.items():
            if key in self._detail_lbls:
                self._detail_lbls[key].configure(text=text)

    # ── 添加 / 删除 ────────────────────────────
    def _add_deployment(self):
        # 小对话框收集字段 -> save_deployments(数据层自动备份)
        dlg = _AddDeployDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        self._deployments = list(self._deployments) + [dlg.result]
        self._save_and_reload("已添加部署「%s」" % dlg.result.get("name"))

    def _delete_deployment(self):
        # 删除 config.json 里的部署记录(本机不可删); 远程数据不受影响
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        ok = messagebox.askyesno(
            "删除部署",
            "将删除部署「%s」（主机 %s）的本地记录。\n"
            "仅删除本地 config.json 中的记录，不会改动远程任何数据。\n\n"
            "是否继续？"
            % (dep.get("name") or "-", dep.get("host") or "-"),
            parent=self)
        if not ok:
            return
        idx = row["dep_index"]
        if 0 <= idx < len(self._deployments):
            del self._deployments[idx]
        self._save_and_reload("已删除部署记录")

    def _save_and_reload(self, msg):
        # 写回 config.json(数据层自动 .bak 备份)并重建列表
        try:
            dsh_data.save_deployments(self._deployments)
        except Exception as e:
            messagebox.showerror("保存失败", "写入 config.json 失败：\n%s" % e, parent=self)
            return
        self._load()
        self._set_status(msg, "#1a7f37")

    # ── 测试连接 ───────────────────────────────
    def _test_connection(self):
        # 对选中远程部署 ssh 执行 "echo ok"(DshRemote.exec); 本机行不可测(按钮已禁用)
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        host = dep.get("host") or "-"
        self._set_status("正在测试 %s ..." % host)

        def worker():
            remote = dsh_data.DshRemote(dep)
            try:
                # 远程 exec 收字符串命令; 本机 exec 收命令列表(但本机行不会走到这里)
                remote.exec("echo ok")
                msg = "连接正常：%s 返回 ok" % host
                color = "#1a7f37"
            except Exception as e:
                msg = "连接失败：%s 不可达（%s）" % (host, e)
                color = "#c33"
            try:
                self.after(0, lambda m=msg, c=color: self._set_status(m, c))
            except tk.TclError:
                pass   # 窗口已关闭, 忽略

        threading.Thread(target=worker, daemon=True).start()

    # ── 刷新总览 ───────────────────────────────
    def _refresh_all(self):
        # 对每个部署(含本机)后台线程跑 deployment_snapshot, 结果更新状态列与详情
        if self._pending > 0:
            return
        self._pending = len(self._rows)
        self._refresh_btn.configure(state="disabled")
        self._set_status("正在刷新 %d 个部署 ..." % self._pending)
        for row in self._rows:
            dep = row["deployment"]
            threading.Thread(target=self._snap_worker, args=(row, dep), daemon=True).start()

    def _snap_worker(self, row, dep):
        # 后台跑快照; 结果经 after(0,...) 回主线程, 窗口关闭后忽略 TclError
        try:
            snap = dsh_data.deployment_snapshot(dsh_data.DshRemote(dep))
            if not isinstance(snap, dict):
                snap = {"ok": False, "error": "快照返回格式错误"}
        except Exception as e:
            snap = {"ok": False, "error": str(e)}
        try:
            self.after(0, lambda r=row, s=snap: self._apply_snapshot(r, s))
        except tk.TclError:
            pass   # 窗口已关闭, 忽略

    def _apply_snapshot(self, row, snap):
        # 主线程应用快照: 更新状态列; 若该行正被选中则同步刷新详情
        try:
            if row.get("gen") != self._gen:
                return   # 列表已重建, 丢弃过期回调
            row["snap"] = snap
            ok = bool(snap.get("ok"))
            status, tag = ("在线", "ok") if ok else ("离线", "err")
            self._tree.item(row["iid"], values=(
                self._tree.item(row["iid"], "values")[0],
                self._tree.item(row["iid"], "values")[1],
                status), tags=(tag,))
            sel = self._tree.selection()
            if sel and sel[0] == row["iid"]:
                self._fill_detail(row)
            self._pending -= 1
            if self._pending <= 0:
                self._pending = 0
                self._refresh_btn.configure(state="normal")
                self._set_status("总览刷新完成", "#1a7f37")
        except tk.TclError:
            pass   # 窗口已关闭, 忽略

    # ── 状态行 ─────────────────────────────────
    def _set_status(self, text, color="#888"):
        if self._status_lbl is not None:
            self._status_lbl.configure(text=text, foreground=color)


class DeploymentDialog(tk.Toplevel):
    # 兼容包装: 保持原 Toplevel 入口(master 兼容 Dashboard 实例或 Tk 根窗口),
    # 内部内嵌 DeploymentPage。窗口级职责(标题/geometry/transient/grab_set)只在这里。
    def __init__(self, master):
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
            app = master
        else:
            tk_master = master
            self._master = None
            app = None
        super().__init__(tk_master)
        self.title("部署管理")
        self.geometry("720x540")
        self.minsize(680, 480)
        self.configure(padx=12, pady=10)
        self._page = DeploymentPage(self, app)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
