# -*- coding: utf-8 -*-
# mgmt_sessions.py — 会话与工作区管理(SessionPage 页面 + SessionDialog 兼容包装)。
# 只读 dsh_data.read_workspace()/list_sessions(); 写 workspace.json 前先 .bak 备份。
# 删除分组用 shutil.rmtree, 必须二次确认; 本模块不执行任何子进程命令。

import os
import io
import json
import datetime
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 风格常量优先复用主程序顶部定义, 独立运行时用等价回退, 保证 UI 观感一致
try:
    import importlib
    _console = importlib.import_module("dsh-console-aio")
    F_BOLD = _console.F_BOLD
    F_SMALL = _console.F_SMALL
except Exception:
    # 主程序不可导入时回退到相近字体, 不影响本模块功能
    F_BOLD = ("Segoe UI", 10, "bold")
    F_SMALL = ("Segoe UI", 9)


def _human_size(n):
    # 字节数人性化: B / KB / MB / GB
    n = int(n or 0)
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    if n < 1024 * 1024 * 1024:
        return "%.1f MB" % (n / 1024.0 / 1024.0)
    return "%.1f GB" % (n / 1024.0 / 1024.0 / 1024.0)


def _fmt_time(ts):
    # 时间戳 -> 本地时间字符串, 异常返回占位符
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "-"


def _workspace_path():
    # workspace.json 固定位于 ~/.dsh/storages/ 下
    return os.path.join(dsh_data.dsh_home(), "storages", "workspace.json")


def _write_workspace_archived(session_ids):
    # 读改写 workspace.json 的 global.archivedSessionIds, 保留其他字段; 写前备份
    p = _workspace_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    dsh_data.backup_file(p)
    try:
        with io.open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    g = raw.setdefault("global", {})
    if not isinstance(g, dict):
        g = {}
        raw["global"] = g
    g["archivedSessionIds"] = list(session_ids)
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, p)


class SessionPage(ttk.Frame):
    # 会话与工作区管理页面: 挂载到容器 Frame, app 为 Dashboard 实例(可 None)。
    # 页面不设窗口标题/transient/grab_set, 也不自行 destroy; 生命周期由容器管理。

    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app
        # master 兼容: 无 Dashboard(裸 Tk 根窗口)时日志转发静默
        self._master = app
        self._group_map = {}
        self._archived = set()
        self._sel_group = None
        self._last_op_msg = None
        self._build()
        self._refresh()

    # ── UI 构建 ──────────────────────────────
    def _build(self):
        # 根网格: 第 0 行内容区(可伸缩), 第 1 行状态栏; 高度随容器自适应
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        wrap = ttk.Frame(self)
        wrap.grid(row=0, column=0, sticky="nsew")

        ttk.Label(wrap, text="会话与工作区管理", font=F_BOLD).pack(anchor="w")
        ttk.Label(wrap, text="会话数据存放在 ~/.dsh/sessions；归档只写 workspace.json，不移动数据。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(0, 6))

        # ── 上半区: 工作区统计 ──
        wsf = ttk.LabelFrame(wrap, text="工作区", padding=8)
        wsf.pack(fill="x", pady=(0, 6))
        self._ws_lbl = ttk.Label(wsf, text="工作区数量: 0 个    已归档会话: 0 个", font=F_SMALL)
        self._ws_lbl.pack(anchor="w")

        # ── 中部: 分组列表 + 会话详情 ──
        mid = ttk.Frame(wrap)
        mid.pack(fill="both", expand=True, pady=(0, 6))
        left = ttk.LabelFrame(mid, text="会话分组", padding=6)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.LabelFrame(mid, text="会话详情（选择分组查看）", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        # 分组树: 工作目录 / 会话数 / 总大小
        self._group_tree = ttk.Treeview(left, columns=("dir", "count", "size"),
                                        show="headings", selectmode="browse")
        for col, text, width, anchor in (
                ("dir", "工作目录", 210, "w"),
                ("count", "会话数", 60, "center"),
                ("size", "总大小", 90, "e")):
            self._group_tree.heading(col, text=text)
            self._group_tree.column(col, width=width, anchor=anchor, stretch=(col == "dir"))
        gsb = ttk.Scrollbar(left, orient="vertical", command=self._group_tree.yview)
        self._group_tree.configure(yscrollcommand=gsb.set)
        self._group_tree.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self._group_tree.bind("<<TreeviewSelect>>", self._on_group_select)

        # 详情树: 会话 / 大小 / 修改时间 / 状态
        self._detail_tree = ttk.Treeview(right, columns=("name", "size", "mtime", "state"),
                                         show="headings", selectmode="browse")
        for col, text, width, anchor in (
                ("name", "会话", 130, "w"),
                ("size", "大小", 70, "e"),
                ("mtime", "修改时间", 120, "w"),
                ("state", "状态", 55, "center")):
            self._detail_tree.heading(col, text=text)
            self._detail_tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))
        dsd = ttk.Scrollbar(right, orient="vertical", command=self._detail_tree.yview)
        self._detail_tree.configure(yscrollcommand=dsd.set)
        self._detail_tree.pack(side="left", fill="both", expand=True)
        dsd.pack(side="right", fill="y")
        self._detail_tree.tag_configure("archived", foreground="#888")

        # ── 操作按钮(关闭按钮由 Dialog 包装层提供, 页面随容器销毁) ──
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(0, 4))
        self._btn_refresh = ttk.Button(btns, text="刷新", command=self._refresh)
        self._btn_refresh.pack(side="left", padx=4)
        self._btn_archive = ttk.Button(btns, text="归档/恢复", command=self._toggle_archive)
        self._btn_archive.pack(side="left", padx=4)
        self._btn_delete = ttk.Button(btns, text="删除分组", command=self._delete_group)
        self._btn_delete.pack(side="left", padx=4)

        # ── 底部状态栏 ──
        self._status_lbl = ttk.Label(self, text="就绪", anchor="w", font=F_SMALL, relief="sunken")
        self._status_lbl.grid(row=1, column=0, sticky="ew", pady=(0, 2))

    # ── 数据刷新 ──────────────────────────────
    def _refresh(self):
        # 后台线程读 dsh_data, 避免大 sessions 目录扫描卡住界面
        self._set_status("正在读取会话数据…")
        self._btn_refresh.configure(state="disabled")
        self._btn_archive.configure(state="disabled")
        self._btn_delete.configure(state="disabled")

        def worker():
            err = None
            try:
                ws = dsh_data.read_workspace()
                groups = dsh_data.list_sessions()
            except Exception as e:
                ws, groups, err = {}, [], str(e)
            try:
                self.after(0, lambda: self._apply_data(ws, groups, err))
            except (tk.TclError, RuntimeError):
                pass  # 窗口已关闭或未运行 mainloop 时丢弃 UI 更新

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, ws, groups, err):
        # 主线程回调: 用最新数据重绘工作区统计与分组树
        try:
            self._apply_data_do(ws, groups, err)
        except tk.TclError:
            pass  # 页面已随容器销毁(导航切换/对话框关闭), 丢弃重绘

    def _apply_data_do(self, ws, groups, err):
        # 重绘主体, 只在 widget 存活时执行
        self._btn_refresh.configure(state="normal")
        self._btn_archive.configure(state="normal")
        self._btn_delete.configure(state="normal")
        ws_ids = ws.get("workspaceIds") or []
        arch_ids = ws.get("archivedSessionIds") or []
        if not isinstance(ws_ids, list):
            ws_ids = []
        if not isinstance(arch_ids, list):
            arch_ids = []
        self._archived = set(str(x) for x in arch_ids)
        self._ws_lbl.configure(text="工作区数量: %d 个    已归档会话: %d 个"
                                    % (len(ws_ids), len(self._archived)))
        self._group_tree.delete(*self._group_tree.get_children())
        self._group_map = {}
        total = 0
        for g in groups:
            total += g["count"]
            self._group_map[g["workdir"]] = g
            self._group_tree.insert("", "end", iid=g["workdir"],
                                    values=(g["workdir"], g["count"], _human_size(g["bytes"])))
        self._detail_tree.delete(*self._detail_tree.get_children())
        if self._sel_group in self._group_map:
            self._group_tree.selection_set(self._sel_group)
            self._show_group_details(self._sel_group)
        if err:
            self._set_status("读取失败: " + err, "#c33")
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("已刷新: %d 个分组, %d 个会话" % (len(groups), total))

    def _on_group_select(self, _event=None):
        # 选中分组 -> 在右侧详情树显示该组会话
        sel = self._group_tree.selection()
        if not sel:
            return
        workdir = sel[0]
        self._sel_group = workdir
        self._show_group_details(workdir)

    def _show_group_details(self, workdir):
        # 填充详情树; 已归档会话(目录名在 archivedSessionIds 中)置灰标注
        self._detail_tree.delete(*self._detail_tree.get_children())
        g = self._group_map.get(workdir)
        if not g:
            return
        for s in g["sessions"]:
            name = s["name"]
            archived = name in self._archived
            self._detail_tree.insert("", "end", iid=name,
                                     values=(name, _human_size(s["bytes"]),
                                             _fmt_time(s["mtime"]),
                                             "已归档" if archived else ""),
                                     tags=("archived",) if archived else ())

    # ── 归档 / 恢复 ───────────────────────────
    def _toggle_archive(self):
        # 把选中会话的目录名加入/移出 workspace.json 的 archivedSessionIds
        sel = self._detail_tree.selection()
        if not sel:
            self._set_status("请先在右侧选择要归档/恢复的会话", "#c33")
            return
        name = sel[0]
        was_archived = name in self._archived
        if was_archived:
            act = "恢复"
            msg = "确定将已归档会话“%s”恢复为正常？\n（从 workspace.json 的 archivedSessionIds 移除）" % name
        else:
            act = "归档"
            msg = "确定归档会话“%s”？\n（写入 workspace.json 的 archivedSessionIds，会话数据保留）" % name
        if not messagebox.askyesno(act + "会话", msg, parent=self):
            return
        self._btn_archive.configure(state="disabled")
        self._btn_delete.configure(state="disabled")

        def worker():
            err = None
            try:
                new_arch = set(self._archived)
                if was_archived:
                    new_arch.discard(name)
                else:
                    new_arch.add(name)
                _write_workspace_archived(sorted(new_arch))
            except Exception as e:
                err = str(e)
            msg_done = ("已恢复会话: %s" % name) if was_archived else ("已归档会话: %s" % name)
            try:
                self.after(0, lambda: self._after_write(msg_done, err))
            except (tk.TclError, RuntimeError):
                pass  # 窗口已关闭或未运行 mainloop 时丢弃 UI 更新

        threading.Thread(target=worker, daemon=True).start()

    # ── 删除分组 ──────────────────────────────
    def _delete_group(self):
        # 删除 sessions/<分组> 整个目录; 二次确认 + 路径安全校验
        sel = self._group_tree.selection()
        if not sel:
            self._set_status("请先选择要删除的会话分组", "#c33")
            return
        workdir = sel[0]
        g = self._group_map.get(workdir)
        n = g["count"] if g else 0
        base = os.path.normpath(dsh_data.sessions_dir())
        target = os.path.normpath(os.path.join(base, workdir))
        # 安全校验: target 必须在 sessions 根目录内且确实存在, 防止误删其他目录
        try:
            inside = os.path.commonpath([base, target]) == base
        except ValueError:
            inside = False
        if not inside or target == base or not os.path.isdir(target):
            messagebox.showerror("无法删除", "分组目录不存在或路径异常，已取消删除。", parent=self)
            return
        if not messagebox.askyesno("删除分组", "确定删除整个会话分组“%s”？" % workdir, parent=self):
            return
        if not messagebox.askyesno("二次确认", "将删除 %d 个会话，不可恢复！\n是否继续？" % n, parent=self):
            return
        self._btn_archive.configure(state="disabled")
        self._btn_delete.configure(state="disabled")

        def worker():
            err = None
            try:
                shutil.rmtree(target)
            except Exception as e:
                err = str(e)
            try:
                self.after(0, lambda: self._after_write("已删除分组: %s" % workdir, err))
            except (tk.TclError, RuntimeError):
                pass  # 窗口已关闭或未运行 mainloop 时丢弃 UI 更新

        threading.Thread(target=worker, daemon=True).start()

    # ── 公共回调 ──────────────────────────────
    def _after_write(self, msg, err=None):
        # 写操作收尾: 失败置红提示并恢复按钮; 成功提示后自动刷新
        try:
            self._after_write_do(msg, err)
        except tk.TclError:
            pass  # 页面已随容器销毁, 丢弃收尾

    def _after_write_do(self, msg, err=None):
        # 收尾主体, 只在 widget 存活时执行
        self._btn_refresh.configure(state="normal")
        self._btn_archive.configure(state="normal")
        self._btn_delete.configure(state="normal")
        if err:
            self._set_status("操作失败: " + err, "#c33")
            return
        self._log(msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh()

    def _set_status(self, text, color="#333"):
        try:
            self._status_lbl.configure(text=text, foreground=color)
        except tk.TclError:
            pass  # 窗口已关闭, 忽略

    def _log(self, msg, tag=""):
        # 若有主界面日志区则转发, 无则静默(状态栏已提示)
        m = self._master
        if m is None or not hasattr(m, "log"):
            return
        try:
            m.log("[会话管理] " + msg, tag)
        except Exception:
            pass  # 日志转发失败不影响对话框本身


class SessionDialog(tk.Toplevel):
    # 兼容包装: 主程序菜单仍以独立窗口打开, 实际 UI 是内嵌的 SessionPage。
    # master 兼容 Dashboard 实例或 Tk 根窗口(hasattr(master, "root") 判断)。

    def __init__(self, master):
        # 兼容两种 master: Dashboard(有 .root) 或裸 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self.title("会话与工作区管理")
        self.geometry("720x520")
        self.minsize(640, 440)
        self.configure(padx=12, pady=10)
        self._master = app  # 兼容旧代码访问
        self._page = SessionPage(self, app)
        self._page.pack(fill="both", expand=True)
        # 关闭按钮由包装层提供(页面内不负责销毁)
        ttk.Button(self, text="关闭", command=self.destroy).pack(anchor="e", padx=12, pady=(0, 10))
        self.transient(tk_master)
        self.grab_set()
