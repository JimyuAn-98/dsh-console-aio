# -*- coding: utf-8 -*-
# mgmt_taskboard.py — 任务看板管理窗口(只读): 展示 task-board 的 ledger 与 scheduler。
# 设计: 纯只读展示 + 刷新, 不提供任何写操作; 定时任务编辑属高级操作, 请使用 dsh web。
# 风格跟随 dsh-console-aio.py 的 EnvDialog: Toplevel 子类 + ttk + F_BOLD/F_SMALL。

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 与 dsh-console-aio.py 顶部一致的风格常量(独立文件, 不复用主程序避免循环导入)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

# 任务表格固定列: (数据字段, 表头)
TASK_COLS = (
    ("id", "任务 ID"),
    ("title", "标题"),
    ("status", "状态"),
    ("createdAt", "创建时间"),
)


def _fmt_ts(v):
    # 时间戳(毫秒)转本地时间字符串; 缺失/非法返回"（无数据）"
    try:
        ms = int(v)
        if ms <= 0:
            return "（无数据）"
        return datetime.datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "（无数据）"


class TaskboardDialog(tk.Toplevel):
    # 只读"任务看板"窗口: 任务列表 + 调度器信息 + 最近请求数量

    def __init__(self, master):
        # master 可以是 Dashboard(推荐) 或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("任务看板")
        self.configure(padx=12, pady=10)
        self.geometry("680x500")
        self.minsize(620, 420)
        self._build()
        self.transient(tk_master)
        self.grab_set()
        self._refresh()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="任务看板", font=F_BOLD).pack(anchor="w", pady=(0, 6))

        # 调度器信息(单行三格: 时区 / 最近心跳 / ledgerId)
        info = ttk.Frame(wrap)
        info.pack(fill="x", pady=(0, 2))
        self._sch_labels = {}
        for i, (key, caption) in enumerate((("timeZone", "时区"), ("lastTickAt", "最近心跳"), ("ledgerId", "ledgerId"))):
            lbl = ttk.Label(info, text=caption + ": --", font=F_SMALL, foreground="#444")
            lbl.grid(row=0, column=i, sticky="w", padx=(0, 20))
            self._sch_labels[key] = lbl

        # 最近请求数量
        self._recent_lbl = ttk.Label(wrap, text="最近请求: --", font=F_SMALL, foreground="#444")
        self._recent_lbl.pack(anchor="w", pady=(0, 6))

        # 任务列表表格
        box = ttk.LabelFrame(wrap, text="任务列表", padding=6)
        box.pack(fill="both", expand=True)
        cols = [c[0] for c in TASK_COLS]
        self._tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
        for c, (key, title) in zip(cols, TASK_COLS):
            width = 150 if key in ("title", "id") else 110
            self._tree.heading(key, text=title)
            self._tree.column(key, width=width, anchor="w", stretch=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 底部说明与按钮
        ttk.Label(wrap, text="定时任务编辑属高级操作，请使用 dsh web。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(8, 0))
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(8, 0))
        self._refresh_btn = ttk.Button(btns, text="刷新", command=self._refresh)
        self._refresh_btn.pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="left")

    def _refresh(self):
        # 读取 task-board(两个小 json, 本地读取足够快, 无需后台线程)
        try:
            data = dsh_data.read_taskboard()
        except Exception as e:
            messagebox.showerror("读取失败", "任务看板读取失败:\n" + str(e), parent=self)
            return
        ledger = data.get("ledger") if isinstance(data.get("ledger"), dict) else {}
        tasks = ledger.get("tasks")
        if not isinstance(tasks, list):
            tasks = []

        # 调度器: ledger.scheduler 与 scheduler-v2.json 合并, 后者 lastTickAt 更新时覆盖
        sch = {}
        s1 = ledger.get("scheduler")
        if isinstance(s1, dict):
            sch.update(s1)
        s2 = data.get("scheduler")
        if isinstance(s2, dict):
            sch.update(s2)

        # 调度器信息
        for key, caption in (("timeZone", "时区"), ("lastTickAt", "最近心跳"), ("ledgerId", "ledgerId")):
            v = sch.get(key)
            text = _fmt_ts(v) if key == "lastTickAt" else (str(v) if v not in (None, "") else "（无数据）")
            self._sch_labels[key].configure(text=caption + ": " + text)

        # 最近请求数量
        recent = ledger.get("recentRequests")
        n = len(recent) if isinstance(recent, list) else 0
        self._recent_lbl.configure(text="最近请求: %d 条" % n)

        # 任务列表
        for item in self._tree.get_children():
            self._tree.delete(item)
        if not tasks:
            self._tree.insert("", "end", values=("（无数据）", "（暂无任务）", "（无数据）", "（无数据）"))
            return
        for i, t in enumerate(tasks):
            if not isinstance(t, dict):
                t = {}
            row = []
            for key, _title in TASK_COLS:
                v = t.get(key)
                if key == "createdAt":
                    row.append(_fmt_ts(v))
                elif v in (None, ""):
                    row.append("（无数据）")
                else:
                    row.append(str(v))
            self._tree.insert("", "end", iid=str(i), values=row)
