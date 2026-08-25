# -*- coding: utf-8 -*-
# mgmt_profiles.py — Profile 管理(ProfilePage 页面 + ProfileDialog 兼容包装):
# 浏览/复制/删除 ~/.dsh/profiles。
# 复制排除 node_modules; web 是默认 Profile 不可删除。dsh web 等价 dsh --profile web。

import os
import json
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import dsh_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 与 dsh-console-aio.py 顶部的风格常量保持一致
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)


def _load_dash_cmd():
    # 读取控制台 config.json 的 dash_cmd, 用于判断当前是否以 web Profile 启动
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        cmd = cfg.get("dash_cmd")
        return cmd if isinstance(cmd, list) else []
    except (OSError, ValueError):
        return []


class ProfilePage(ttk.Frame):
    # Profile 管理页面: 浏览/复制/删除 ~/.dsh/profiles。
    # 挂载到容器 Frame, app 为 Dashboard 实例(可 None); 页面不负责窗口级行为。

    def __init__(self, parent, app, dash_cmd=None):
        super().__init__(parent)
        self._app = app
        # master 兼容: 无 Dashboard(裸 Tk 根窗口)时相关转发静默
        self._master = app
        # 部署联动: 当前部署(host 非空)构造 DshRemote, 读操作走远程; None=本机
        remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            remote = dsh_data.DshRemote(_dep)
        self._remote = remote
        if dash_cmd is None:
            dash_cmd = _load_dash_cmd()
        self._is_web_current = "web" in dash_cmd
        self._build()
        self._refresh()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Profile 管理", font=F_BOLD).pack(anchor="w", pady=(0, 6))
        ttk.Label(wrap, text="dsh 用 dsh --profile <名> 启动；dsh web 等价 dsh --profile web。"
                             "web 是默认 Profile，不可删除。",
                  font=F_SMALL, foreground="#888", wraplength=600,
                  justify="left").pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(wrap, columns=("name", "cordis", "patch", "pkg", "cur"),
                            show="headings", height=14)
        tree.heading("name", text="名称")
        tree.heading("cordis", text="cordis.yml")
        tree.heading("patch", text="patch")
        tree.heading("pkg", text="package.json")
        tree.heading("cur", text="当前")
        tree.column("name", width=150, anchor="w")
        tree.column("cordis", width=80, anchor="center")
        tree.column("patch", width=80, anchor="center")
        tree.column("pkg", width=110, anchor="center")
        tree.column("cur", width=60, anchor="center")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._tree = tree
        # 底部按钮(关闭按钮由 Dialog 包装层提供, 页面随容器销毁)
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="复制 Profile", command=self._copy_profile).pack(side="left", padx=4)
        ttk.Button(btns, text="删除 Profile", command=self._delete_profile).pack(side="left", padx=4)
        ttk.Button(btns, text="打开目录", command=self._open_dir).pack(side="left", padx=4)
        ttk.Button(btns, text="刷新", command=self._refresh).pack(side="left", padx=4)

    def _refresh(self):
        self._tree.delete(*self._tree.get_children())
        try:
            profiles = dsh_data.list_profiles(remote=self._remote)
        except Exception as e:
            messagebox.showerror("读取失败", "Profile 列表读取失败：%s" % e, parent=self)
            return
        for p in profiles:
            cur = "✓" if (self._is_web_current and p["name"] == "web") else ""
            self._tree.insert("", "end", iid=p["name"], values=(
                p["name"],
                "✓" if p["cordis"] else "—",
                "✓" if p["patch"] else "—",
                "✓" if p["pkg"] else "—",
                cur,
            ))

    def _selected(self):
        sel = self._tree.selection()
        return sel[0] if sel else None

    def _copy_profile(self):
        base = dsh_data.profiles_dir()
        if not os.path.isdir(base):
            messagebox.showinfo("目录不存在", "尚未创建任何 Profile。", parent=self)
            return
        src = self._selected()
        if not src:
            messagebox.showinfo("请先选择", "请先在列表中选择要复制的 Profile。", parent=self)
            return
        new = simpledialog.askstring("复制 Profile", "输入新 Profile 名称：", parent=self)
        if not new:
            return
        new = new.strip()
        if not new:
            messagebox.showwarning("名称无效", "Profile 名称不能为空。", parent=self)
            return
        if any(ch in new for ch in '\\/:*?"<>|'):
            messagebox.showwarning("名称无效", '名称不能包含 \\ / : * ? " < > | 等字符。', parent=self)
            return
        if new == src:
            messagebox.showwarning("名称无效", "新名称不能与源 Profile 相同。", parent=self)
            return
        if os.path.isdir(os.path.join(base, new)):
            messagebox.showwarning("已存在", "名为 %s 的 Profile 已存在。" % new, parent=self)
            return
        ok = messagebox.askyesno("复制 Profile",
                                 "将复制 '%s' 到 '%s'（排除 node_modules）。\n是否继续？"
                                 % (src, new), parent=self)
        if not ok:
            return

        def worker():
            try:
                shutil.copytree(os.path.join(base, src), os.path.join(base, new),
                                ignore=shutil.ignore_patterns("node_modules"))
                msg, err = "已复制 %s → %s" % (src, new), None
            except Exception as e:
                msg, err = "复制失败", str(e)
            try:
                self.after(0, lambda: self._copy_done(msg, err))
            except tk.TclError:
                pass  # 窗口已关闭, 忽略
        threading.Thread(target=worker, daemon=True).start()

    def _copy_done(self, msg, err):
        try:
            self._copy_done_do(msg, err)
        except tk.TclError:
            pass  # 页面已随容器销毁, 丢弃收尾

    def _copy_done_do(self, msg, err):
        self._refresh()
        if err:
            messagebox.showerror("复制 Profile", "%s：%s" % (msg, err), parent=self)
        else:
            messagebox.showinfo("复制 Profile", msg, parent=self)

    def _delete_profile(self):
        base = dsh_data.profiles_dir()
        name = self._selected()
        if not name:
            messagebox.showinfo("请先选择", "请先在列表中选择要删除的 Profile。", parent=self)
            return
        if name == "web":
            messagebox.showwarning("不能删除", "web 是默认 Profile，请勿删除。", parent=self)
            return
        if not os.path.isdir(os.path.join(base, name)):
            messagebox.showwarning("目录不存在", "Profile 目录不存在，可能已被删除。", parent=self)
            return
        ok = messagebox.askyesno("删除 Profile",
                                 "将永久删除 '%s' 目录及其全部内容。\n是否继续？" % name,
                                 parent=self)
        if not ok:
            return

        def worker():
            try:
                shutil.rmtree(os.path.join(base, name))
                msg, err = "已删除 %s" % name, None
            except Exception as e:
                msg, err = "删除失败", str(e)
            try:
                self.after(0, lambda: self._delete_done(msg, err))
            except tk.TclError:
                pass  # 窗口已关闭, 忽略
        threading.Thread(target=worker, daemon=True).start()

    def _delete_done(self, msg, err):
        try:
            self._delete_done_do(msg, err)
        except tk.TclError:
            pass  # 页面已随容器销毁, 丢弃收尾

    def _delete_done_do(self, msg, err):
        self._refresh()
        if err:
            messagebox.showerror("删除 Profile", "%s：%s" % (msg, err), parent=self)
        else:
            messagebox.showinfo("删除 Profile", msg, parent=self)

    def _open_dir(self):
        base = dsh_data.profiles_dir()
        name = self._selected()
        if name and os.path.isdir(os.path.join(base, name)):
            target = os.path.join(base, name)
        else:
            target = base
        if not os.path.isdir(target):
            messagebox.showinfo("目录不存在", "尚未创建任何 Profile（%s）" % base, parent=self)
            return
        try:
            os.startfile(target)
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)


class ProfileDialog(tk.Toplevel):
    # 兼容包装: 主程序菜单仍以独立窗口打开, 实际 UI 是内嵌的 ProfilePage。
    # master 兼容 Dashboard 实例或 Tk 根窗口(hasattr(master, "root") 判断);
    # dash_cmd 允许上层注入, 缺省读 config.json。

    def __init__(self, master, dash_cmd=None):
        # master 可以是 Dashboard 实例(推荐) 或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self.title("Profile 管理")
        self.configure(padx=15, pady=12)
        self.geometry("640x480")
        self.minsize(560, 400)
        self._master = app  # 兼容旧代码访问
        self._page = ProfilePage(self, app, dash_cmd=dash_cmd)
        self._page.pack(fill="both", expand=True)
        # 关闭按钮由包装层提供(页面内不负责销毁)
        ttk.Button(self, text="关闭", command=self.destroy).pack(anchor="e", padx=15, pady=(0, 12))
        self.transient(tk_master)
        self.grab_set()
