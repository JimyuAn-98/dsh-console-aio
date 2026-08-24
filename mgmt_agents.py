# -*- coding: utf-8 -*-
# mgmt_agents.py — Agent 模式管理对话框: 只读浏览 .agent-presets 各模式并展示 preset.yml。
# 数据全部来自 dsh_data.list_agent_presets() / dsh_data.read_yaml(), 不做任何写入。

import os
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 与 dsh-tunnel-console.py 顶部的风格常量保持一致(该模块名带连字符, 无法直接 import)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 9)


def _fmt_scalar(v):
    # 把解析后的标量转成展示文本
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


def _fmt_yaml(data, indent=0):
    # 把 read_yaml 解析结果渲染成易读的 YAML 风格文本(只读展示用)
    pad = "  " * indent
    lines = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(pad + str(k) + ":")
                lines.extend(_fmt_yaml(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(pad + str(k) + ": []")
                    continue
                lines.append(pad + str(k) + ":")
                for item in v:
                    if isinstance(item, dict):
                        items = list(item.items())
                        if not items:
                            lines.append(pad + "  - {}")
                            continue
                        k0, v0 = items[0]
                        if isinstance(v0, (dict, list)):
                            lines.append(pad + "  - " + str(k0) + ":")
                            lines.extend(_fmt_yaml(v0, indent + 2))
                        else:
                            lines.append(pad + "  - " + str(k0) + ": " + _fmt_scalar(v0))
                        for kk, vv in items[1:]:
                            if isinstance(vv, (dict, list)):
                                lines.append(pad + "    " + str(kk) + ":")
                                lines.extend(_fmt_yaml(vv, indent + 2))
                            else:
                                lines.append(pad + "    " + str(kk) + ": " + _fmt_scalar(vv))
                    else:
                        lines.append(pad + "  - " + _fmt_scalar(item))
            else:
                lines.append(pad + str(k) + ": " + _fmt_scalar(v))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                items = list(item.items())
                if not items:
                    lines.append(pad + "- {}")
                    continue
                k0, v0 = items[0]
                if isinstance(v0, (dict, list)):
                    lines.append(pad + "- " + str(k0) + ":")
                    lines.extend(_fmt_yaml(v0, indent + 1))
                else:
                    lines.append(pad + "- " + str(k0) + ": " + _fmt_scalar(v0))
                for kk, vv in items[1:]:
                    if isinstance(vv, (dict, list)):
                        lines.append(pad + "  " + str(kk) + ":")
                        lines.extend(_fmt_yaml(vv, indent + 1))
                    else:
                        lines.append(pad + "  " + str(kk) + ": " + _fmt_scalar(vv))
            else:
                lines.append(pad + "- " + _fmt_scalar(item))
    else:
        lines.append(pad + _fmt_scalar(data))
    return lines


class AgentDialog(tk.Toplevel):
    # Agent 模式管理: 浏览 .agent-presets 下各模式, 只读展示 preset.yml。
    # Agent 模式是会话级选择(session 记录 agent-preset/selected), 控制台不做修改。

    def __init__(self, master):
        # master 可以是 Dashboard 实例(推荐) 或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("Agent 模式管理")
        self.configure(padx=15, pady=12)
        self.geometry("860x520")
        self.minsize(700, 420)
        self._presets = []
        self._build()
        self.transient(tk_master)
        self.grab_set()
        self._refresh()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Agent 模式管理", font=F_BOLD).pack(anchor="w", pady=(0, 6))
        ttk.Label(wrap, text="Agent 模式是会话级选择（session 记录 agent-preset/selected），"
                             "控制台仅做浏览与说明。",
                  font=F_SMALL, foreground="#888", wraplength=820,
                  justify="left").pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(wrap)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        # 左侧: 模式列表
        left = ttk.LabelFrame(body, text="现有模式", padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tree = ttk.Treeview(left, columns=("name", "desc", "files"),
                            show="headings", height=16)
        tree.heading("name", text="名称")
        tree.heading("desc", text="描述")
        tree.heading("files", text="文件数")
        tree.column("name", width=150, anchor="w")
        tree.column("desc", width=210, anchor="w")
        tree.column("files", width=60, anchor="center")
        sb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree = tree
        # 右侧: preset.yml 只读详情
        right = ttk.LabelFrame(body, text="preset.yml（只读）", padding=6)
        right.grid(row=0, column=1, sticky="nsew")
        self._info = ttk.Label(right, text="请在左侧选择一个模式", font=F_SMALL, foreground="#888")
        self._info.pack(anchor="w", pady=(0, 4))
        txt = tk.Text(right, font=F_MONO, wrap="none", state="disabled", height=16)
        tsb = ttk.Scrollbar(right, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=tsb.set)
        txt.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self._detail = txt
        # 底部按钮
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="打开 .agent-presets 目录", command=self._open_dir).pack(side="left", padx=4)
        ttk.Button(btns, text="刷新", command=self._refresh).pack(side="left", padx=4)
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=4)

    def _refresh(self):
        self._presets = dsh_data.list_agent_presets()
        self._tree.delete(*self._tree.get_children())
        for p in self._presets:
            self._tree.insert("", "end", iid=p["name"],
                              values=(p["name"], p["desc"], p["files"]))
        self._set_detail("请在左侧选择一个模式")

    def _on_select(self, _evt=None):
        sel = self._tree.selection()
        if not sel:
            return
        name = sel[0]
        preset = None
        for p in self._presets:
            if p["name"] == name:
                preset = p
                break
        if preset is None:
            return
        pp = os.path.join(dsh_data.dsh_home(), ".agent-presets", name, "preset.yml")
        data = dsh_data.read_yaml(pp)
        if data is None:
            text = "(preset.yml 不存在或为空)"
        else:
            text = "\n".join(_fmt_yaml(data))
        self._info.configure(text="模式: %s   ·   描述: %s   ·   文件数: %d"
                                  % (name, preset["desc"] or "—", preset["files"]))
        self._set_detail(text)

    def _set_detail(self, text):
        # 只读填充详情文本框
        self._detail.configure(state="normal")
        self._detail.delete("1.0", "end")
        self._detail.insert("1.0", text)
        self._detail.configure(state="disabled")

    def _open_dir(self):
        base = os.path.join(dsh_data.dsh_home(), ".agent-presets")
        if not os.path.isdir(base):
            messagebox.showinfo("目录不存在", "尚未创建任何 Agent 模式（%s）" % base, parent=self)
            return
        try:
            os.startfile(base)
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)
